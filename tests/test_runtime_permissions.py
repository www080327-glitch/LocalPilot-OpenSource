import tempfile
import unittest
from pathlib import Path

from agent.permissions import PermissionMode, RiskAssessment, ToolRiskMetadata
from agent.registry import ToolRegistry, create_default_registry
from agent.safety import CapabilityPolicy


def judge_allow(operation, risk, reasons, resource):
    return RiskAssessment(risk.upper(), "Local assessment", "Workspace impact", "allow")


class RuntimePermissionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / "note.txt").write_text("one", encoding="utf-8")
        self.capabilities = CapabilityPolicy(execute=True)

    def tearDown(self):
        self.directory.cleanup()

    def registry(self, mode, **kwargs):
        return create_default_registry(self.root, permission_mode=mode,
                                       capabilities=self.capabilities, **kwargs)

    def patch(self, registry, **kwargs):
        return registry.call("apply_patch", {"changes": [{"path": "new.txt", "operation": "create",
                                                          "content": "created"}]}, **kwargs)

    def test_five_new_modes_apply_distinct_thresholds(self):
        expected = {
            PermissionMode.APPROVE_ALL: ("approval_required", "approval_required", "approval_required"),
            PermissionMode.APPROVE_MUTATIONS: ("allowed", "approval_required", "approval_required"),
            PermissionMode.LOCAL_JUDGE_CONSERVATIVE: ("allowed", "approval_required", "approval_required"),
            PermissionMode.LOCAL_JUDGE_PERMISSIVE: ("allowed", "allowed", "approval_required"),
            PermissionMode.FULL_PERMISSION: ("allowed", "allowed", "allowed"),
        }
        for mode, statuses in expected.items():
            with self.subTest(mode=mode):
                gateway = self.registry(mode, judge=judge_allow).gateway
                actual = tuple(gateway.decide(operation, risk, [], {"kind": "test"})["status"]
                               for operation, risk in (("read_file", "low"),
                                                       ("apply_patch", "medium"),
                                                       ("apply_patch", "high")))
                self.assertEqual(actual, statuses)

    def test_unavailable_invalid_or_failing_judge_requires_approval(self):
        for judge in (None, lambda *_: None, lambda *_: 1 / 0):
            with self.subTest(judge=judge):
                registry = self.registry(PermissionMode.LOCAL_JUDGE_PERMISSIVE, judge=judge)
                self.assertEqual(registry.call("read_file", {"path": "note.txt"}), "one")
                self.assertEqual(self.patch(registry)["status"], "approval_required")

    def test_local_judge_non_deleting_patch_uses_assessed_risk(self):
        for level, expected in (("LOW", "ok"), ("MEDIUM", "approval_required")):
            with self.subTest(level=level):
                (self.root / "new.txt").unlink(missing_ok=True)
                judge = lambda *_: RiskAssessment(level, "patch", "workspace file", "allow")
                registry = self.registry(PermissionMode.LOCAL_JUDGE_CONSERVATIVE, judge=judge)
                self.assertEqual(self.patch(registry)["status"], expected)
                self.assertEqual((self.root / "new.txt").exists(), expected == "ok")
        (self.root / "new.txt").unlink(missing_ok=True)
        medium_judge = lambda *_: RiskAssessment("MEDIUM", "patch", "workspace file", "allow")
        permissive = self.registry(PermissionMode.LOCAL_JUDGE_PERMISSIVE, judge=medium_judge)
        self.assertEqual(self.patch(permissive)["status"], "ok")

    def test_judge_cannot_lower_gateway_risk_or_override_path_rule(self):
        low_judge = lambda *_: RiskAssessment("LOW", "low", "none", "allow")
        registry = self.registry(PermissionMode.LOCAL_JUDGE_PERMISSIVE, judge=low_judge)
        self.assertEqual(registry.gateway.decide("apply_patch", "high", [], {})["status"],
                         "approval_required")
        with self.assertRaises(ValueError):
            registry.call("read_file", {"path": "../outside"}, approved=True)

    def test_host_approval_is_scoped_and_cannot_override_hard_denials(self):
        registry = self.registry(PermissionMode.APPROVE_ALL)
        self.assertEqual(registry.call("read_file", {"path": "note.txt"}, approved=True), "one")
        self.assertEqual(registry.call("read_file", {"path": "note.txt"})["status"],
                         "approval_required")
        with self.assertRaises(ValueError):
            registry.call("read_file", {"path": "note.txt", "approved": True})
        self.assertEqual(registry.call("execute", {"argv": ["sudo", "true"]}, approved=True)["status"],
                         "denied")
        no_execute = create_default_registry(self.root, permission_mode=PermissionMode.FULL_PERMISSION,
                                             capabilities=CapabilityPolicy(execute=False))
        self.assertEqual(no_execute.call("execute", {"argv": ["cat", "note.txt"]},
                                         approved=True)["status"], "denied")

    def test_read_only_plan_and_capability_deny_mutations_after_approval(self):
        for options in ({"plan_read_only": True},
                        {"capabilities": CapabilityPolicy(execute=True, read_only=True)}):
            with self.subTest(options=options):
                registry = create_default_registry(self.root, permission_mode=PermissionMode.FULL_PERMISSION,
                    capabilities=options.get("capabilities", self.capabilities),
                    plan_read_only=options.get("plan_read_only", False))
                self.assertEqual(registry.call("read_file", {"path": "note.txt"}), "one")
                self.assertEqual(self.patch(registry, approved=True)["status"], "denied")
                self.assertEqual(registry.call("execute", {"argv": ["cat", "note.txt"]},
                                               approved=True)["status"], "denied")
                self.assertFalse((self.root / "new.txt").exists())

    def test_declared_read_only_extension_and_unknown_default(self):
        registry = ToolRegistry(self.root, permission_mode=PermissionMode.APPROVE_MUTATIONS)
        registry.register("inspect", lambda workspace_root: "ok",
                          metadata=ToolRiskMetadata(read_only=True, mutating=False))
        registry.register("unknown", lambda workspace_root: "ran")
        registry.register("hazard", lambda workspace_root: "unsafe",
                          metadata=ToolRiskMetadata(read_only=True, mutating=False,
                                                    external_side_effect=True))
        self.assertTrue(registry.metadata("inspect").read_only)
        self.assertTrue(registry.metadata("unknown").mutating)
        self.assertEqual(registry.call("inspect", {}), "ok")
        self.assertEqual(registry.call("unknown", {})["status"], "approval_required")
        self.assertEqual(registry.call("hazard", {})["status"], "approval_required")
        self.assertEqual(registry.call("unknown", {}, approved=True), "ran")
        builtin = self.registry(PermissionMode.FULL_PERMISSION)
        self.assertTrue(builtin.metadata("execute").potentially_destructive)
        self.assertTrue(builtin.metadata("execute").external_side_effect)
        self.assertTrue(builtin.metadata("execute").network_access)


if __name__ == "__main__":
    unittest.main()
