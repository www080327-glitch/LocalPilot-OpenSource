"""Regression checks for the V0 release's evidence and hard-policy boundaries."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.deepseek import DeepSeekBackend
from agent.loop import Agent
from agent.policy import DataPolicy
from agent.profiles import PROMPT_PROFILES, TOOL_PROFILES
from agent.registry import create_default_registry
from agent.safety import CapabilityPolicy
from benchmarks.summarize_mlx import summarize
from tests.test_agent_loop import FakeBackend, assistant_message, tool_call


class ConvergenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'note.txt').write_text('real evidence')

    def tearDown(self):
        self.temp.cleanup()

    def test_prompt_ablation_sends_identical_tool_schemas(self):
        for tool_profile in TOOL_PROFILES:
            schemas = []
            for prompt_profile in PROMPT_PROFILES:
                backend = FakeBackend(assistant_message('done'))
                registry = create_default_registry(self.root, tool_profile=tool_profile)
                result = Agent(backend, registry, prompt_profile=prompt_profile).run('task')
                schemas.append(backend.calls[0]['tools'])
                system = [m for m in backend.calls[0]['messages'] if m['role'] == 'system']
                self.assertEqual(len(system), 0 if prompt_profile == 'minimal_0' else 1)
                if system:
                    self.assertEqual(system[0]['content'], PROMPT_PROFILES[prompt_profile])
                self.assertEqual(result.prompt_profile, prompt_profile)
            self.assertEqual(schemas[0], schemas[1])
            self.assertEqual(schemas[1], schemas[2])

    def test_compact_schema_changes_only_descriptions(self):
        full = create_default_registry(self.root).schemas()
        compact = create_default_registry(self.root, tool_profile='compact').schemas()
        def strip(value):
            if isinstance(value, dict):
                return {k: strip(v) for k, v in value.items() if k != 'description'}
            if isinstance(value, list):
                return [strip(v) for v in value]
            return value
        self.assertEqual(strip(full), compact)
        self.assertLess(len(json.dumps(compact)), len(json.dumps(full)))
        self.assertEqual(len(full), 6)

    def test_profiles_and_permission_modes_cannot_expand_capabilities(self):
        for prompt in PROMPT_PROFILES:
            for tool in TOOL_PROFILES:
                for mode in ('all_confirm', 'cautious', 'permissive', 'full'):
                    with self.subTest(prompt=prompt, tool=tool, mode=mode):
                        registry = create_default_registry(self.root, tool_profile=tool, permission_mode=mode,
                            capabilities=CapabilityPolicy(write=False, execute=False))
                        calls = [tool_call('write', 'apply_patch', json.dumps({'changes': [
                            {'path': 'new.txt', 'operation': 'create', 'content': 'bad'}]})),
                            tool_call('exec', 'execute', json.dumps({'argv': ['true']}))]
                        backend = FakeBackend(assistant_message(tool_calls=calls), assistant_message('done'))
                        with patch('agent.commands.subprocess.Popen') as spawn:
                            result = Agent(backend, registry, prompt_profile=prompt).run('try')
                            spawn.assert_not_called()
                        payloads = [json.loads(m['content']) for m in result.messages if m['role'] == 'tool']
                        self.assertTrue(all(p['result']['status'] == 'denied' for p in payloads))
                        self.assertFalse((self.root / 'new.txt').exists())

    def test_execute_is_disabled_by_default_even_for_full_permission_mode(self):
        registry = create_default_registry(self.root, permission_mode='full')
        self.assertEqual(registry.call('execute', {'argv': ['true']})['status'], 'denied')

    def test_disabled_patch_cannot_read_content_through_preflight_preview(self):
        registry = create_default_registry(self.root, permission_mode='full',
                                           capabilities=CapabilityPolicy(read=False, write=False))
        with patch('agent.patches._read_bytes', side_effect=AssertionError('must not read')):
            result = registry.call('apply_patch', {'changes': [
                {'path': 'note.txt', 'operation': 'update', 'old_text': 'real', 'new_text': 'fake'}]})
        self.assertEqual(result['status'], 'denied')
        self.assertNotIn('changes', result)

    def test_local_only_cloud_send_point_blocks_before_http(self):
        backend = DeepSeekBackend(api_key='test-placeholder')
        backend.data_policy = DataPolicy(local_only=True)
        with patch('agent.deepseek.urlopen') as send:
            with self.assertRaises(PermissionError):
                backend.chat([{'role': 'user', 'content': 'synthetic workspace secret'}])
            send.assert_not_called()
        with self.assertRaises(PermissionError):
            DeepSeekBackend(api_key='test-placeholder', data_policy=DataPolicy(local_only=True))

    def test_agent_enforces_strictest_egress_policy_before_backend(self):
        for source in ('agent', 'registry', 'backend'):
            backend = FakeBackend(assistant_message('should not run'))
            backend.is_local = False
            backend.data_policy = DataPolicy(local_only=source == 'backend')
            registry = create_default_registry(self.root, data_policy=DataPolicy(local_only=source == 'registry'))
            agent = Agent(backend, registry, data_policy=DataPolicy(local_only=source == 'agent'))
            with self.assertRaises(PermissionError):
                agent.run('secret')
            self.assertEqual(backend.calls, [])

    def test_local_only_also_disables_unsandboxed_network_capable_host_programs(self):
        backend = FakeBackend(assistant_message('done')); backend.is_local = True
        registry = create_default_registry(self.root, permission_mode='full', capabilities=CapabilityPolicy(execute=True))
        Agent(backend, registry, data_policy=DataPolicy(local_only=True))
        with patch('agent.commands.subprocess.Popen') as spawn:
            self.assertEqual(registry.call('execute', {'argv': ['true']})['status'], 'denied')
            spawn.assert_not_called()

    def test_data_and_capability_policy_are_immutable_values(self):
        with self.assertRaises(FrozenInstanceError):
            DataPolicy(local_only=True).local_only = False
        with self.assertRaises(FrozenInstanceError):
            CapabilityPolicy().execute = True

    def test_tool_budget_refuses_whole_over_limit_batch_before_side_effects(self):
        registry = create_default_registry(self.root, permission_mode='full')
        proposal = tool_call('write', 'apply_patch', json.dumps({'changes': [
            {'path': 'new.txt', 'operation': 'create', 'content': 'bad'}]}))
        backend = FakeBackend(assistant_message(tool_calls=[proposal, proposal]))
        result = Agent(backend, registry, max_tool_calls=1).run('too many')
        self.assertEqual(result.status, 'tool_budget_exceeded')
        self.assertFalse((self.root / 'new.txt').exists())
        self.assertEqual(registry.gateway.audit, [])

    def test_credential_paths_and_aliases_do_not_leak_through_read_or_search(self):
        (self.root / '.env').write_text('SYNTHETIC_SECRET=do-not-send')
        (self.root / 'alias').symlink_to(self.root / '.env')
        registry = create_default_registry(self.root)
        for path in ('.env', 'alias'):
            with self.assertRaises(ValueError):
                registry.call('read_file', {'path': path})
        self.assertEqual(registry.call('search_text', {'query': 'SYNTHETIC_SECRET'}), [])

    def test_total_patch_bytes_are_bounded(self):
        registry = create_default_registry(self.root, permission_mode='full')
        with self.assertRaisesRegex(ValueError, 'total byte budget'):
            registry.call('apply_patch', {'changes': [
                {'path': f'{i}.txt', 'operation': 'create', 'content': 'x' * 800000} for i in range(3)]})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['note.txt'])


class ProvenanceTests(unittest.TestCase):
    def row(self):
        return {'status': 'ok', 'model_id': 'fixture', 'repo_id': 'synthetic/model',
            'model_revision': 'revision-a', 'quantization': '4-bit', 'backend': 'mlx-vlm',
            'software': {'python': '3.x', 'packages': {'mlx-vlm': 'version-a', 'mlx': 'version-a'}},
            'host': {'os': 'macOS', 'arch': 'arm64', 'chip': 'synthetic', 'memory_gb': 64},
            'context_k': 32, 'actual_input_tokens': 32768, 'max_new_tokens': 16,
            'cache_mode': 'fresh_process', 'prompt_protocol': 'synthetic-v1',
            'rendered_prompt_sha256': 'synthetic-hash', 'generation': {'temperature': 0.0},
            'benchmark_conditions': 'isolated', 'power_state_at_start': {'source': 'AC'},
            'peak_process_rss_gb': 3, 'mlx_peak_memory_gb': 20, 'ttft_seconds': 2}

    def summarize_rows(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'raw.jsonl', Path(tmp) / 'summary.json'
            source.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            original = source.read_bytes()
            result = summarize(source, target)
            self.assertEqual(source.read_bytes(), original)
            return result

    def test_different_conditions_do_not_silently_aggregate(self):
        base = self.row()
        variants = []
        for field in ('model_revision', 'backend', 'quantization', 'actual_input_tokens', 'max_new_tokens', 'cache_mode', 'context_k'):
            changed = deepcopy(base); changed[field] = 'different'; variants.append(changed)
        changed = deepcopy(base); changed['software']['packages']['mlx-vlm'] = 'version-b'; variants.append(changed)
        changed = deepcopy(base); changed['host']['chip'] = 'another-chip'; variants.append(changed)
        result = self.summarize_rows([base, *variants])
        self.assertEqual(len(result['measurements']), 1 + len(variants))
        self.assertTrue(all(item['repeats'] == 1 for item in result['measurements']))

    def test_known_identical_identity_can_aggregate_and_retains_provenance(self):
        result = self.summarize_rows([self.row(), self.row()])
        self.assertEqual(len(result['measurements']), 1)
        point = result['measurements'][0]
        self.assertEqual(point['repeats'], 2)
        self.assertEqual(point['metric_provenance']['memory'], 'measured')
        self.assertEqual(point['metric_provenance']['capability_quality'], 'unknown')
        self.assertIsNone(point['metrics']['swap_delta_bytes'])

    def test_unknown_revision_does_not_get_filled_from_catalog_or_merge(self):
        row = self.row(); row.pop('model_revision')
        result = self.summarize_rows([row, row])
        self.assertEqual(len(result['measurements']), 2)
        self.assertIsNone(result['measurements'][0]['identity']['model_revision'])

    def test_failures_are_retained_without_manufactured_measurements(self):
        row = self.row(); row['status'] = 'failed'
        result = self.summarize_rows([row])
        self.assertEqual(result['measurements'], [])
        self.assertEqual(len(result['failures']), 1)

    def test_failed_worker_retains_error_and_allocator_without_becoming_success(self):
        row = self.row(); row['status'] = 'failed'
        row.pop('mlx_peak_memory_gb'); row.pop('peak_process_rss_gb')
        row['worker'] = {'error_type': 'RuntimeError', 'error': 'synthetic Metal OOM',
                         'mlx_peak_memory_gb': 51.16, 'peak_process_rss_gb': 16.356}
        result = self.summarize_rows([row])
        self.assertEqual(result['measurements'], [])
        failure = result['failures'][0]
        self.assertEqual(failure['error_type'], 'RuntimeError')
        self.assertEqual(failure['failure_reason'], 'synthetic Metal OOM')
        self.assertEqual(failure['memory_metrics']['mlx_peak_memory_gb'], 51.16)
