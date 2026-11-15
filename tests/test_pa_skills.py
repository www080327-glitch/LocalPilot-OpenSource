"""Reviewed on-demand Skills through the actual registry and persistence identity."""
import json
from pathlib import Path
import tempfile
import unittest

from agent.engine_v5 import EngineV5Policy
from agent.persistence import configuration
from agent.registry import create_default_registry
from agent.session import AgentSession
from localpilot_plugins.adapter import configure_session
from localpilot_plugins.skills import SkillRegistry
from tests.test_runtime_api import Backend, answer, call


class SelectedSkillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.work = self.root / "work"
        self.work.mkdir()
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        self.skills = SkillRegistry(self.root / "skills", self.work)
        self.runtimes = []

    def tearDown(self):
        for runtime in self.runtimes:
            runtime.close()
        self.tmp.cleanup()

    def install(self, name, text, *, dependencies=None, replace=False):
        manifest = {"id": name, "version": "1.0.0", "description": "Summarize public activity records",
                    "requires_localpilot": ">=5.0.0b1,<6", "dependencies": dependencies or {},
                    "tools": ["read_file"], "inputs": {"type": "object"}, "outputs": {"type": "object"}}
        (self.bundle / "skill.json").write_text(json.dumps(manifest))
        (self.bundle / "SKILL.md").write_text(text)
        installed = self.skills.install(self.bundle, replace=replace)
        self.skills.enable(name, "user", reviewed_sha256=installed["bundle_sha256"])

    def runtime(self, selected):
        backend = Backend(answer(None, call("load_skill", {"skill": "activity:user"})), answer("Read the selected guide."))
        runtime = AgentSession(create_default_registry(self.work, permission_mode="full-permission"),
                               backend=backend, policy="cloud-only", engine_policy=EngineV5Policy())
        self.runtimes.append(runtime)
        configure_session(runtime, self.root / "plugins", skill_home=self.skills.user, skills=selected)
        return runtime, backend

    def test_model_sees_catalog_then_loads_reviewed_body_without_second_approval(self):
        self.install("activity", "BODY_ONLY_ON_DEMAND: cite observed source IDs.")
        runtime, backend = self.runtime([{"id": "activity", "scope": "user"}])
        schema = next(s for s in runtime.registry.schemas() if s["function"]["name"] == "load_skill")
        self.assertIn("Summarize public activity records", schema["function"]["description"])
        self.assertNotIn("BODY_ONLY_ON_DEMAND", json.dumps(runtime._schemas()))
        self.assertNotIn("BODY_ONLY_ON_DEMAND", runtime.messages[0].content)
        result = runtime.run_turn("Use the activity guide.")
        self.assertEqual(result.status, "completed")
        self.assertIsNone(runtime.pending_approval)
        tool = next(m for m in backend.requests[-1]["messages"] if m.role == "tool")
        self.assertIn("BODY_ONLY_ON_DEMAND", tool.content)

    def test_reviewed_content_change_changes_configuration_and_rejects_stale_loader(self):
        self.install("activity", "Old guide")
        runtime, _ = self.runtime([{"id": "activity", "scope": "user"}])
        old = configuration(runtime)
        self.install("activity", "Updated guide", replace=True)
        with self.assertRaisesRegex(ValueError, "changed"):
            runtime.registry.call("load_skill", {"skill": "activity:user"})
        new, _ = self.runtime([{"id": "activity", "scope": "user"}])
        self.assertNotEqual(configuration(new), old)

    def test_dependency_change_invalidates_selected_catalog_and_disabled_skill_stops_loading(self):
        self.install("base", "Base guide")
        self.install("activity", "Activity guide", dependencies={"base": ">=1"})
        runtime, _ = self.runtime([{"id": "activity", "scope": "user"}])
        loaded = runtime.registry.call("load_skill", {"skill": "activity:user"})
        self.assertEqual([s["id"] for s in loaded["skills"]], ["base", "activity"])
        self.skills.enable("base", "user", enabled=False)
        with self.assertRaises(ValueError):
            runtime.registry.call("load_skill", {"skill": "activity:user"})

    def test_catalog_order_is_stable(self):
        for name in ("activity", "notes"):
            self.install(name, name + " guide")
        selected = [{"id": name, "scope": "user"} for name in ("activity", "notes")]
        first, _ = self.runtime(selected)
        second, _ = self.runtime(list(reversed(selected)))
        self.assertEqual(first.registry.schemas(), second.registry.schemas())


if __name__ == "__main__":
    unittest.main()
