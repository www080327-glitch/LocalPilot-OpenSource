"""Portable routing/path tests; native Seatbelt qualification is separate."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

from agent.backends import Message, ModelInfo
from agent.context_budget import request_budget, context_tokens
from agent.context import transfer_context
from agent.context_v5 import transfer as v5_transfer
from agent.backends import ToolCall
from agent.cooperative import CooperativePolicy, decide
from agent.host_tools import shell, register, SHELL_MAX_TIMEOUT
from agent.registry import create_default_registry
from agent.routing import local_main_eligible, EligibilityConfig
from agent.scope_permissions import configure, proposal, workspace_arguments


class RoutingAdmissionTests(unittest.TestCase):
    def decide(self, mode='balanced', **changes):
        args = dict(current='local', local_requests=0, tool_errors=0, stagnation=0,
                    context_tokens=100, local_context=32768, bucket='simple', profile={})
        args.update(changes)
        return decide(CooperativePolicy(mode=mode), **args)

    def test_short_request_fits_32k(self):
        budget = request_budget([Message('user', '你好')], [], 2048)
        self.assertLess(budget['total_tokens'], 32768)
        self.assertEqual(self.decide(context_tokens=budget['total_tokens'])['target'], 'local')
        self.assertFalse(budget['measured'])

    def test_context_projection_uses_tokens_and_keeps_complete_tool_groups(self):
        history = [Message('system', 'You are a helpful agent.'),
                   Message('user', '你好'),
                   Message('assistant', tool_calls=[ToolCall('receipt', 'read_file', '{"path":"a.txt"}')]),
                   Message('tool', 'observed result', tool_call_id='receipt')]
        view, notice = transfer_context(history, [], 32768, 2048)
        self.assertIsNone(notice)
        self.assertEqual(view, history)
        self.assertLess(context_tokens(view, []) + 2048 + 64, 32768)

    def test_v5_small_local_window_admits_short_chinese_request(self):
        history = [Message('system', '系统提示'), Message('user', '你好')]
        view, notice = v5_transfer(history, [], 32768, 2048 + 655,
                                   working_state={'original_task': '你好', 'pending_obligations': []})
        self.assertIsNone(notice)
        self.assertEqual(view[1], history[1])
        self.assertLess(context_tokens(view, []), 32768 - 2048 - 655)

    def test_tool_schema_is_counted(self):
        messages = [Message('user', 'hello')]
        small = request_budget(messages, [], 2048)
        large = request_budget(messages, [{'description': 'tool ' * 2000}], 2048)
        self.assertGreater(large['input_tokens'], small['input_tokens'])

    def test_output_reserve_uses_tokens_once(self):
        messages = [Message('user', 'hello')]
        a, b = (request_budget(messages, [], n) for n in (100, 200))
        self.assertEqual(b['total_tokens'] - a['total_tokens'], 100)

    def test_chat_template_count_is_identified(self):
        class Template:
            def apply_chat_template(self, messages, **kwargs):
                self.kwargs = kwargs
                return [1, 2, 3, 4]
        tokenizer = Template()
        budget = request_budget([Message('user', 'hi')], [{'type':'function'}], 10,
                                tokenizer=tokenizer)
        self.assertEqual(budget['input_tokens'], 4)
        self.assertTrue(budget['measured'])
        self.assertIn('tools', tokenizer.kwargs)
        self.assertTrue(tokenizer.kwargs['add_generation_prompt'])

    def test_unusable_template_has_explicit_fallback(self):
        class Template:
            def apply_chat_template(self, *args, **kwargs):
                raise ValueError('unsupported tools')
        budget = request_budget([Message('user', 'hello')], [], 20, tokenizer=Template())
        self.assertEqual(budget['estimator'], 'mixed_text_estimate_v1')
        self.assertFalse(budget['measured'])

    def test_balanced_unseen_simple_task_gets_local_trial(self):
        result = self.decide()
        self.assertEqual(result['target'], 'local')
        self.assertEqual(result['quality_evidence'], 'UNKNOWN')
        self.assertEqual(result['reason'], 'bounded_local_trial')

    def test_balanced_complex_still_prefers_cloud(self):
        self.assertEqual(self.decide(bucket='complex')['target'], 'cloud')

    def test_local_first_trials_complex_tasks(self):
        self.assertEqual(self.decide('local-first', bucket='complex')['target'], 'local')

    def test_cloud_first_remains_cloud_priority(self):
        self.assertEqual(self.decide('cloud-first')['target'], 'cloud')

    def test_only_modes_remain_hard_boundaries(self):
        self.assertEqual(self.decide('local-only', context_tokens=999999, tool_errors=20)['target'], 'local')
        self.assertEqual(self.decide('cloud-only')['target'], 'cloud')

    def test_closed_egress_cannot_be_overridden(self):
        self.assertEqual(self.decide('local-first', cloud_allowed=False, tool_errors=3)['target'], 'local')

    def test_trial_is_bounded(self):
        self.assertEqual(self.decide(local_requests=7)['target'], 'local')
        self.assertEqual(self.decide(local_requests=8)['reason'], 'local_trial_budget_exhausted')

    def test_failures_and_no_progress_escalate(self):
        self.assertEqual(self.decide(tool_errors=1)['reason'], 'tool_error')
        self.assertEqual(self.decide(stagnation=2)['reason'], 'no_progress')
        self.assertEqual(self.decide(verification_failed=True)['reason'], 'verification_failed')

    def test_hysteresis_does_not_ping_pong(self):
        self.assertEqual(self.decide(escalated=True)['target'], 'cloud')

    def test_calibration_can_still_be_requested_explicitly(self):
        policy = CooperativePolicy(use_calibration=True)
        result = decide(policy, current='local', local_requests=0, tool_errors=0,
                        stagnation=0, context_tokens=100, local_context=32768,
                        bucket='simple', profile={})
        self.assertEqual(result['target'], 'cloud')

    def test_small_models_are_not_excluded_by_name(self):
        for size in ('4B', '9B', 'unknown'):
            backend = SimpleNamespace(is_local=True, health_check=lambda: True,
                                      model_info=ModelInfo('fixture', size, 32768))
            self.assertTrue(local_main_eligible(backend))
        self.assertEqual(EligibilityConfig().excluded_size_classes, ())

    def test_unhealthy_or_tiny_context_is_not_admitted(self):
        backend = SimpleNamespace(is_local=True, health_check=lambda: True,
                                  model_info=ModelInfo('fixture', '4B', 512))
        self.assertFalse(local_main_eligible(backend))
        backend.health_check = lambda: False
        backend.model_info = ModelInfo('fixture', '4B', 32768)
        self.assertFalse(local_main_eligible(backend))


class CanonicalScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.work = self.root / 'work'; self.work.mkdir()
        self.out = self.root / 'outside'; self.out.mkdir()
        (self.out / 'fact.txt').write_text('verified data')
        self.alias = self.root / 'alias'; self.alias.symlink_to(self.out, target_is_directory=True)
        self.registry = create_default_registry(self.work, permission_mode='full-permission', file_operations=True)
        configure(self.registry, 'full', revision=3)

    def tearDown(self):
        self.temp.cleanup()

    def test_external_directory_alias_resolves_to_real_target(self):
        request = proposal(self.registry, 'read_file', {'path':str(self.alias / 'fact.txt')})
        self.assertEqual(request['targets'], [str(self.out / 'fact.txt')])

    def test_alias_reads_execute_and_return_real_bytes(self):
        result = self.registry.call('read_file', {'path':str(self.alias / 'fact.txt')})
        self.assertIn('verified data', str(result))

    def test_directory_link_itself_can_be_listed(self):
        request = proposal(self.registry, 'list_directory', {'path':str(self.alias)})
        self.assertEqual(request['targets'], [str(self.out)])

    def test_internal_link_escaping_workspace_stays_external(self):
        link = self.work / 'elsewhere'; link.symlink_to(self.out, target_is_directory=True)
        args = workspace_arguments(self.registry, 'read_file', {'path':'elsewhere/fact.txt'})
        self.assertEqual(args['path'], str(self.out / 'fact.txt'))
        self.assertIsNotNone(proposal(self.registry, 'read_file', args))

    def test_alias_into_workspace_becomes_workspace_relative(self):
        link = self.root / 'work-alias'; link.symlink_to(self.work, target_is_directory=True)
        args = workspace_arguments(self.registry, 'read_file', {'path':str(link / 'a.txt')})
        self.assertEqual(args['path'], 'a.txt')

    def test_directory_alias_allows_new_file_target(self):
        request = proposal(self.registry, 'apply_patch', {'changes':[
            {'operation':'create', 'path':str(self.alias / 'new.txt'), 'content':'new'}]})
        self.assertEqual(request['targets'], [str(self.out / 'new.txt')])

    def test_final_mutation_link_is_not_silently_followed(self):
        link = self.out / 'leaf'; link.symlink_to(self.out / 'fact.txt')
        with self.assertRaises(PermissionError):
            proposal(self.registry, 'apply_patch', {'changes':[
                {'operation':'update', 'path':str(link), 'old_text':'data', 'new_text':'changed'}]})
        self.assertEqual((self.out / 'fact.txt').read_text(), 'verified data')

    def test_legacy_symlink_contract_is_unchanged(self):
        configure(self.registry, 'request', revision=2)
        with self.assertRaises(PermissionError):
            proposal(self.registry, 'read_file', {'path':str(self.alias / 'fact.txt')})

    def test_changed_alias_invalidates_original_proposal(self):
        original = proposal(self.registry, 'read_file', {'path':str(self.alias / 'fact.txt')})
        other = self.root / 'other'; other.mkdir(); (other / 'fact.txt').write_text('other')
        self.alias.unlink(); self.alias.symlink_to(other, target_is_directory=True)
        changed = proposal(self.registry, 'read_file', {'path':str(self.alias / 'fact.txt')})
        self.assertNotEqual(original['binding'], changed['binding'])


class ShellBudgetTests(unittest.TestCase):
    def test_long_timeout_configuration_runs_real_bash(self):
        with TemporaryDirectory() as tmp, patch('agent.host_tools.sys.platform', 'darwin'):
            result = shell(tmp, 'printf ready > output.txt; cat output.txt', timeout=90, mode='full')
            self.assertEqual(result['stdout'], 'ready')
            self.assertTrue(result['process_completed'])
            self.assertEqual(Path(tmp, 'output.txt').read_text(), 'ready')

    def test_timeout_keeps_unknown_effect_and_never_claims_replay(self):
        with TemporaryDirectory() as tmp, patch('agent.host_tools.sys.platform', 'darwin'):
            result = shell(tmp, 'printf done > output.txt; sleep 1', timeout=.1, mode='full')
            self.assertEqual(result['status'], 'timeout')
            self.assertTrue(result['action_may_have_applied'])
            self.assertFalse(result['replay_allowed'])
            self.assertEqual(Path(tmp, 'output.txt').read_text(), 'done')

    def test_nonzero_exit_is_observed_not_lost(self):
        with TemporaryDirectory() as tmp, patch('agent.host_tools.sys.platform', 'darwin'):
            result = shell(tmp, 'exit 3', mode='full')
            self.assertEqual(result['exit_code'], 3)
            self.assertTrue(result['process_completed'])
            self.assertFalse(result['action_may_have_applied'])

    def test_invalid_timeout_does_not_dispatch(self):
        with TemporaryDirectory() as tmp, patch('agent.host_tools.sys.platform', 'darwin'):
            for value in (True, 0, -1, float('inf'), float('nan'), SHELL_MAX_TIMEOUT + 1):
                with self.assertRaises(ValueError):
                    shell(tmp, 'touch should-not-exist', timeout=value, mode='full')
            self.assertFalse(Path(tmp, 'should-not-exist').exists())

    def test_reregistration_updates_schema_once(self):
        with TemporaryDirectory() as tmp:
            registry = create_default_registry(tmp)
            configure(registry, 'request', revision=3)
            register(registry, 'request', ())
            register(registry, 'full', ())
            schemas = [s for s in registry._extension_schemas if s['function']['name'] == 'shell']
            self.assertEqual(len(schemas), 1)
            self.assertEqual(schemas[0]['function']['parameters']['properties']['timeout']['maximum'], 3600)
            self.assertNotIn('confine writes and network', schemas[0]['function']['description'])


if __name__ == '__main__':
    unittest.main()
