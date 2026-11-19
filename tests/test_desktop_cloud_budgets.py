import tempfile
from pathlib import Path
import unittest

from agent.backends import Message
from agent.hybrid import CloudEgressDenied, CloudEgressPolicy, HybridPolicy
from agent.persistence import configuration, snapshot_runtime, restore_runtime
from agent.registry import create_default_registry
from agent.session import AgentSession, SessionBudgets
from localpilot_service.desktop_sessions import apply_options
from tests.test_runtime_session import ScriptBackend, response


class DesktopCloudBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.sessions = []

    def tearDown(self):
        for session in self.sessions:
            session.close()
        self.temp.cleanup()

    def runtime(self):
        backend = ScriptBackend(response('done'))
        runtime = AgentSession(create_default_registry(self.work), backend=backend,
            policy='cloud-only', budgets=SessionBudgets(max_steps=100, max_token_units=2000000),
            hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED')),
            hybrid_backends={'cloud': backend}, hybrid_primary='cloud')
        self.sessions.append(runtime)
        return runtime

    def options(self, runtime, mode='full', budget='standard'):
        options = {'permission_mode': mode, 'agent_profile': 'standard', 'scope_revision': 3}
        if budget is not None:
            options['execution_budget'] = budget
        apply_options(runtime, options)

    def test_new_full_session_uses_declared_budget_for_large_and_many_cloud_requests(self):
        runtime = self.runtime()
        self.options(runtime)
        egress = runtime.hybrid.authorize([Message('user', 'x' * 160000)], [])
        self.assertGreater(egress['bytes'], 131072)
        for _ in range(100):
            attempt = runtime.hybrid.begin_attempt(1, egress)
            runtime.hybrid.end_attempt(attempt, response('ok'))
        with self.assertRaisesRegex(CloudEgressDenied, 'budget exhausted'):
            runtime.hybrid.begin_attempt(1, egress)

    def test_extended_and_permission_downgrade_recompute_from_host_limits(self):
        runtime = self.runtime()
        self.options(runtime, budget='extended')
        self.assertEqual(runtime.hybrid.policy.egress.max_request_bytes, 64 * 1024 * 1024)
        self.assertEqual(runtime.hybrid.policy.max_cloud_requests_per_turn, 2048)
        self.options(runtime, mode='workspace')
        self.assertEqual(runtime.hybrid.policy.egress.max_request_bytes, 131072)
        self.assertEqual(runtime.hybrid.policy.max_cloud_requests_per_turn, 32)

    def test_historical_full_session_without_budget_field_retains_its_identity(self):
        runtime = self.runtime()
        self.options(runtime, budget=None)
        self.assertEqual(runtime.hybrid.policy.egress.max_request_bytes, 131072)
        self.assertEqual(runtime.hybrid.policy.max_cloud_requests_per_turn, 32)
        saved = snapshot_runtime(runtime)
        restored = self.runtime()
        self.options(restored, budget=None)
        restore_runtime(restored, saved)
        self.assertEqual(configuration(restored), configuration(runtime))

    def test_new_full_contract_restores_without_an_extra_cloud_grant(self):
        runtime = self.runtime()
        self.options(runtime)
        saved = snapshot_runtime(runtime)
        restored = self.runtime()
        self.options(restored)
        restore_runtime(restored, saved)
        result = restored.hybrid.authorize([Message('user', 'y' * 160000)], [])
        self.assertGreater(result['bytes'], 131072)


if __name__ == '__main__':
    unittest.main()
