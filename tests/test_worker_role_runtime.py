"""Real delegation, permissions and persistence with scripted model responses."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from agent.adaptive import AdaptivePolicy, TaskTraits
from agent.backends import Message, ModelInfo
from agent.context_v5 import host_state
from agent.engine_v5 import EngineV5Policy
from agent.hybrid import CloudEgressPolicy, HybridPolicy
from agent.persistence import backend_identity, configuration, restore_runtime, snapshot_runtime
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets
from tests.test_runtime_api import Backend, answer, call


class WorkerRoleRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'fact.txt').write_text('OBSERVED-7319')
        self.runtimes = []

    def tearDown(self):
        for runtime in reversed(self.runtimes):
            runtime.close()
        self.temp.cleanup()

    def make(self, parent, worker, *, roles=None, tiers=None, thinking=None, adaptive_policy=None, registry=None):
        parent.model_info = ModelInfo('coordinator', 'scripted', 131072)
        worker.model_info = ModelInfo('reviewer', 'scripted', 131072)
        catalog = {'selected': parent, 'route:review': worker}
        profiles = {'version': 1, 'models': {alias: {'identity': backend_identity(backend), 'available': True}
                    for alias, backend in catalog.items()}} if adaptive_policy else None
        runtime = AgentSession(registry or create_default_registry(self.root, permission_mode='full-permission'),
            cloud_backend=parent, cloud_worker_backends=tiers, policy='cloud-only', streaming=False,
            thinking=thinking, hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED', ('fact.txt',))),
            hybrid_backends=catalog, hybrid_primary='selected',
            engine_policy=EngineV5Policy(), worker_roles=roles,
            adaptive_policy=adaptive_policy, capability_profiles=profiles,
            task_traits=TaskTraits() if adaptive_policy else None,
            budgets=SessionBudgets(max_steps=32, max_tool_calls=48, max_token_units=8000000,
                max_worker_steps=8, max_worker_tool_calls=8, max_worker_token_units=1000000),
            retry_policy=RetryPolicy(max_attempts=1))
        self.runtimes.append(runtime)
        return runtime

    @staticmethod
    def delegate(**changes):
        return call('delegate', {'task': 'Read fact.txt and report evidence.',
            'backend_preference': 'cloud', **changes}, 'delegate-once')

    @staticmethod
    def properties(runtime):
        return next(schema['function']['parameters']['properties'] for schema in runtime._schemas()
                    if schema['function']['name'] == 'delegate')

    def test_unconfigured_tier_is_not_advertised_or_dispatched(self):
        parent = Backend(answer(None, self.delegate(tier='LIGHT')), answer('Unavailable tier rejected.'))
        worker = Backend(answer('must not run'))
        runtime = self.make(parent, worker)
        self.assertNotIn('tier', self.properties(runtime))
        runtime.run_turn('Use the configured worker.')
        receipt = runtime.tool_history[0]
        self.assertEqual(receipt['payload']['error']['type'], 'schema_validation')
        self.assertEqual(receipt['payload']['result']['stage'], 'not_dispatched')
        self.assertFalse(receipt['payload']['result']['action_sent'])
        self.assertEqual(runtime.subagents, [])
        self.assertEqual(worker.requests, [])

    def test_only_registered_configured_tier_is_advertised_and_executes(self):
        parent = Backend(answer(None, self.delegate(tier='LIGHT')), answer('Collected.'))
        worker = Backend(answer('Reviewed.'))
        runtime = self.make(parent, worker, tiers={'LIGHT': worker, 'STRONG': Backend(answer('not registered'))})
        self.assertEqual(self.properties(runtime)['tier']['enum'], ['LIGHT'])
        result = runtime.run_turn('Use the registered worker.')
        self.assertEqual(result.status, 'completed')
        self.assertEqual(len(worker.requests), 1)
        self.assertEqual(runtime.subagents[0]['backend_id'], 'route:review')

    def test_role_reads_actual_file_and_keeps_parent_and_worker_models_fixed(self):
        parent = Backend(answer(None, self.delegate(role='review')), answer('Collected OBSERVED-7319.'))
        worker = Backend(answer(None, call('read_file', {'path': 'fact.txt'}, 'read-once')), answer('OBSERVED-7319'))
        runtime = self.make(parent, worker, roles={'review': 'route:review'})
        result = runtime.run_turn('Review the actual file.')
        self.assertEqual(result.status, 'completed')
        self.assertEqual(runtime.hybrid.state['backend_id'], 'selected')
        record = runtime.subagents[0]
        self.assertEqual(record['role'], 'review')
        self.assertTrue(record['read_only'])
        self.assertEqual(record['receipts'][0]['payload']['result'], 'OBSERVED-7319')
        child = runtime._children[record['id']]
        self.assertEqual(set(child.hybrid.catalog), {'route:review'})
        self.assertFalse(child.registry.gateway.capabilities.write)
        self.assertFalse(child.registry.gateway.capabilities.execute)
        tools = {tool['function']['name'] for tool in worker.requests[0]['tools']}
        self.assertNotIn('apply_patch', tools)
        self.assertNotIn('shell', tools)
        self.assertNotIn('request_model_switch', tools)
        state = host_state(runtime, {}, runtime._schemas())
        self.assertEqual(state['worker_roles']['review']['backend_id'], 'route:review')
        self.assertEqual(state['worker_roles']['review']['model'], 'reviewer')
        self.assertTrue(state['worker_roles']['review']['read_only'])
        projected = runtime.hybrid.project_messages([Message('assistant', None, [self.delegate(role='review')])])
        self.assertEqual(json.loads(projected[0].tool_calls[0].arguments)['role'], 'review')
        self.assertIn('Preserve supplied interpreter paths', state['work_contract'])

    def test_role_conflicts_are_rejected_before_child_creation(self):
        for changes in ({'read_only': False}, {'backend_id': 'selected'}, {'model': 'coordinator'},
                        {'backend_preference': 'local'}, {'tier': 'LIGHT'}):
            with self.subTest(changes=changes):
                parent = Backend(answer(None, self.delegate(role='review', **changes)), answer('Rejected conflict.'))
                worker = Backend(answer('must not run'))
                runtime = self.make(parent, worker, roles={'review': 'route:review'}, tiers={'LIGHT': worker})
                runtime.run_turn('Review without changing files.')
                receipt = runtime.tool_history[0]
                self.assertEqual(receipt['payload']['error']['type'], 'schema_validation')
                self.assertEqual(receipt['payload']['result']['stage'], 'not_dispatched')
                self.assertFalse(receipt['payload']['result']['action_sent'])
                self.assertEqual(runtime.subagents, [])
                self.assertEqual(worker.requests, [])

    def test_full_host_shell_is_hidden_from_role_but_available_to_mutating_worker(self):
        from agent.host_tools import register
        from agent.scope_permissions import configure

        for readonly in (True, False):
            with self.subTest(readonly=readonly):
                selection = {'role': 'review'} if readonly else {'backend_id': 'route:review', 'read_only': False}
                operation = call('read_file', {'path': 'fact.txt'}, 'observe') if readonly else call(
                    'shell', {'command': 'printf executed > worker-command.txt'}, 'execute')
                parent = Backend(answer(None, self.delegate(**selection)), answer('Collected.'))
                worker = Backend(answer(None, operation), answer('Checked.'))
                registry = create_default_registry(self.root, permission_mode='full-permission')
                configure(registry, 'full', (), revision=3)
                register(registry, 'full', ())
                runtime = self.make(parent, worker, roles={'review': 'route:review'}, registry=registry)
                self.assertIn('shell', {tool['function']['name'] for tool in runtime._schemas()})
                self.assertEqual(runtime.run_turn('Run the configured worker.').status, 'completed')
                tools = {tool['function']['name'] for tool in worker.requests[0]['tools']}
                self.assertEqual('shell' in tools, not readonly)
                record = runtime.subagents[0]
                self.assertEqual(record['status'], 'completed')
                if readonly:
                    self.assertEqual(record['receipts'][0]['payload']['result'], 'OBSERVED-7319')
                else:
                    self.assertEqual(record['receipts'][0]['payload']['result']['exit_code'], 0)
                    self.assertEqual((self.root / 'worker-command.txt').read_text(), 'executed')

    def test_shadow_lock_does_not_block_fixed_role_and_survives_restore(self):
        parent = Backend(answer(None, self.delegate(role='review')), answer('Collected.'))
        worker = Backend(answer('Reviewed.'))
        policy = AdaptivePolicy(mode='shadow', model_lock='selected')
        runtime = self.make(parent, worker, roles={'review': 'route:review'}, adaptive_policy=policy)
        self.assertEqual(runtime.run_turn('Review.').status, 'completed')
        self.assertEqual(len(worker.requests), 1)
        self.assertEqual(runtime.adaptive.policy.model_lock, 'selected')
        child = runtime._children['1.1']
        self.assertEqual(child.adaptive.policy.model_lock, 'route:review')
        self.assertEqual(set(child.adaptive.profiles['models']), {'route:review'})
        snapshot = snapshot_runtime(runtime)
        restored = self.make(parent, worker, roles={'review': 'route:review'}, adaptive_policy=policy)
        restore_runtime(restored, snapshot)
        self.assertEqual(snapshot_runtime(restored)['children'], snapshot['children'])
        self.assertEqual(restored._children['1.1'].adaptive.policy.model_lock, 'route:review')
        self.assertEqual(len(worker.requests), 1)

    def test_normal_shadow_worker_keeps_catalog_and_automatic_lock_still_blocks_role(self):
        for mode, role in (('shadow', None), ('automatic', 'review')):
            with self.subTest(mode=mode):
                selection = {'role': role} if role else {'backend_id': 'route:review'}
                parent = Backend(answer(None, self.delegate(**selection)), answer('Collected.'))
                worker = Backend(answer('Reviewed.'))
                policy = AdaptivePolicy(mode=mode, model_lock='selected', allowed_categories=('file',),
                                        max_cloud_cost_usd=100)
                runtime = self.make(parent, worker, roles={'review': 'route:review'}, adaptive_policy=policy)
                runtime.run_turn('Review.')
                if role:
                    self.assertEqual(worker.requests, [])
                    self.assertEqual(runtime.subagents, [])
                    receipt = runtime.tool_history[0]['payload']['result']
                    self.assertEqual(receipt['status'], 'denied')
                    self.assertEqual(receipt['reason'], 'proposal_conflicts_with_host_model_lock')
                else:
                    self.assertEqual(len(worker.requests), 1)
                    child = runtime._children['1.1']
                    self.assertEqual(set(child.hybrid.catalog), {'selected', 'route:review'})
                    self.assertEqual(child.adaptive.policy, policy)

    def test_configured_partner_effort_wins_but_unconfigured_worker_inherits(self):
        for configured, provider_default, supported, expected in (
                ('medium', 'medium', ('high', 'medium'), 'medium'),
                (None, 'medium', ('high', 'medium'), 'high'),
                (None, 'low', ('low',), 'low')):
            with self.subTest(configured=configured, supported=supported):
                parent = Backend(answer(None, self.delegate(backend_id='route:review')), answer('Collected.'))
                parent.capabilities = replace(parent.capabilities, supports_reasoning_effort=True,
                                              supported_thinking_efforts=('high', 'medium'))
                worker = Backend(answer('Reviewed.'))
                worker.capabilities = replace(worker.capabilities, supports_reasoning_effort=True,
                    supported_thinking_efforts=supported, default_thinking_effort=provider_default)
                if configured is not None:
                    worker.service_contract = {'default_thinking': configured}
                runtime = self.make(parent, worker, thinking='high')
                self.assertEqual(runtime.run_turn('Delegate review.').status, 'completed')
                self.assertEqual(parent.requests[0]['thinking'], 'high')
                self.assertEqual(worker.requests[0]['thinking'], expected)
                self.assertEqual(parent.requests[-1]['thinking'], 'high')

    def test_role_catalog_and_effort_survive_restore_without_calls(self):
        parent = Backend(answer(None, self.delegate(role='review')), answer('Collected.'))
        parent.capabilities = replace(parent.capabilities, supports_reasoning_effort=True,
                                      supported_thinking_efforts=('high', 'medium'))
        worker = Backend(answer('Reviewed.'))
        worker.capabilities = replace(worker.capabilities, supports_reasoning_effort=True,
                                      supported_thinking_efforts=('high', 'medium'), default_thinking_effort='medium')
        worker.service_contract = {'default_thinking': 'medium'}
        runtime = self.make(parent, worker, roles={'review': 'route:review'}, thinking='high')
        self.assertEqual(runtime.run_turn('Review.').status, 'completed')
        snapshot = snapshot_runtime(runtime)
        counts = len(parent.requests), len(worker.requests)
        restored = self.make(parent, worker, roles={'review': 'route:review'}, thinking='high')
        restore_runtime(restored, snapshot)
        child = restored._children['1.1']
        self.assertEqual(set(child.hybrid.catalog), {'route:review'})
        self.assertEqual(child.thinking_mode, 'medium')
        self.assertTrue(restored.subagents[0]['read_only'])
        self.assertEqual(restored.subagents[0]['role'], 'review')
        self.assertEqual(snapshot_runtime(restored)['children'], snapshot['children'])
        self.assertEqual((len(parent.requests), len(worker.requests)), counts)

    def test_empty_roles_preserve_default_configuration_and_invalid_roles_fail_at_entry(self):
        parent, worker = Backend(), Backend()
        unset = self.make(parent, worker)
        empty = self.make(parent, worker, roles={})
        self.assertEqual(configuration(unset), configuration(empty))
        self.assertNotIn('worker_roles', configuration(unset))
        self.assertNotIn('role', self.properties(unset))
        configured = self.make(parent, worker, roles={'search': 'route:review', 'review': 'route:review'})
        self.assertEqual(configuration(configured)['worker_roles'],
                         {'search': 'route:review', 'review': 'route:review'})
        for roles in ([], {'search': 'missing'}, {'unknown': 'route:review'}):
            with self.subTest(roles=roles), self.assertRaises(ValueError):
                self.make(parent, worker, roles=roles)


if __name__ == '__main__':
    unittest.main()
