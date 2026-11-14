"""Real Session routing with scripted model proposals; no capability score."""
from pathlib import Path
import tempfile
import unittest

from agent.policy import DataPolicy
from agent.registry import create_default_registry
from agent.session import AgentSession
from tests.test_hybrid_runtime import Local
from tests.test_runtime_api import Backend, answer, call


def switch(target):
    return call("request_model_switch", {"target": target, "reason": "Bounded routing fixture",
                "task_complexity": "simple", "scope": "session"})


class FullPermissionRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtimes = []

    def tearDown(self):
        for runtime in self.runtimes:
            runtime.close()
        self.tmp.cleanup()

    def runtime(self, local, cloud, *, mode="full-permission", policy="balanced", local_only=False):
        registry = create_default_registry(self.root, permission_mode=mode,
                                           data_policy=DataPolicy(local_only=local_only))
        runtime = AgentSession(registry, local_backend=local, cloud_backend=cloud,
                               policy=policy, streaming=False)
        self.runtimes.append(runtime)
        return runtime

    def test_nonhybrid_full_permission_local_switch_reuses_authorization(self):
        local = Local(answer("Local result"))
        cloud = Backend(answer(None, switch("local")))
        runtime = self.runtime(local, cloud)
        result = runtime.run_turn("Complete the simple task locally.")
        self.assertEqual(result.status, "completed")
        self.assertEqual(runtime.primary, "local")
        self.assertEqual(len(local.requests), 1)
        self.assertIsNone(runtime.pending_approval)
        requests = [e for e in runtime.events.events if e.type == "ModelSwitchRequested"]
        self.assertFalse(requests[0].data["requires_user_confirmation"])

    def test_approval_mode_still_asks_before_local_switch(self):
        local = Local(answer("Local result"))
        cloud = Backend(answer(None, switch("local")))
        runtime = self.runtime(local, cloud, mode="approve-mutations")
        self.assertEqual(runtime.run_turn("Simple task").status, "approval_required")
        self.assertEqual(runtime.pending_approval["kind"], "switch")
        self.assertEqual(local.requests, [])

    def test_full_permission_does_not_create_cloud_egress_authorization(self):
        local = Local(answer(None, switch("cloud")))
        cloud = Backend(answer("Cloud result"))
        runtime = self.runtime(local, cloud, policy="local-first")
        self.assertEqual(runtime.run_turn("Task requiring cloud").status, "approval_required")
        self.assertEqual(cloud.requests, [])
        self.assertTrue(runtime.pending_approval["request"]["requires_user_confirmation"])
        self.assertEqual(runtime.approve().status, "completed")
        self.assertEqual(len(cloud.requests), 1)

    def test_nonhybrid_cloud_delegate_still_needs_explicit_authorization(self):
        local = Local(answer(None, call("delegate", {"task": "Read-only investigation",
                             "backend_preference": "cloud", "read_only": True})))
        cloud = Backend(answer("Worker result"))
        runtime = self.runtime(local, cloud, policy="local-first")
        self.assertEqual(runtime.run_turn("Investigate").status, "approval_required")
        self.assertEqual(runtime.pending_approval["kind"], "delegate")
        self.assertEqual(cloud.requests, [])

    def test_full_permission_retains_explicit_local_only_boundary(self):
        local = Local(answer(None, switch("cloud")), answer("Cloud is unavailable under local-only policy."))
        cloud = Backend(answer("Must not be requested"))
        runtime = self.runtime(local, cloud, policy="local-first", local_only=True)
        result = runtime.run_turn("Attempt the task within its data boundary.")
        self.assertEqual(result.status, "completed")
        self.assertEqual(runtime.primary, "local")
        self.assertEqual(cloud.requests, [])
        self.assertIsNone(runtime.pending_approval)


if __name__ == "__main__":
    unittest.main()
