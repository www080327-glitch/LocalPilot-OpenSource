"""Reviewed on-demand Skills through the actual registry and persistence identity."""
import json
from pathlib import Path
import tempfile
import unittest

from agent.engine_v5 import EngineV5Policy
from agent.hybrid import CloudEgressPolicy, HybridPolicy
from agent.persistence import configuration, snapshot_runtime, restore_runtime
from agent.registry import create_default_registry
from agent.session import AgentSession, SessionBudgets
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

    def runtime(self, selected, *, profile="standard"):
        backend = Backend(answer(None, call("load_skill", {"skill": "activity:user"})), answer("Read the selected guide."))
        runtime = AgentSession(create_default_registry(self.work, profile=profile, permission_mode="full-permission"),
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

    def test_compact_model_sees_skill_catalog_without_changing_stored_contract(self):
        self.install("activity", "BODY_ONLY_ON_DEMAND: cite observed source IDs.")
        selected = [{"id": "activity", "scope": "user"}]
        runtime, backend = self.runtime(selected, profile="minimal")
        saved = snapshot_runtime(runtime)
        contract = configuration(runtime)
        schema = next(s for s in contract["schemas"] if s["function"]["name"] == "load_skill")
        self.assertNotIn("description", schema["function"])
        self.assertEqual(runtime.run_turn("Use the activity guide.").status, "completed")
        tools = backend.requests[0]["tools"]
        model_schema = next(s for s in tools if s["function"]["name"] == "load_skill")
        self.assertIn("Summarize public activity records", model_schema["function"]["description"])
        self.assertNotIn("BODY_ONLY_ON_DEMAND", json.dumps(tools))
        self.assertNotIn("BODY_ONLY_ON_DEMAND", runtime.messages[0].content)
        tool = next(m for m in backend.requests[-1]["messages"] if m.role == "tool")
        self.assertIn("BODY_ONLY_ON_DEMAND", tool.content)
        self.assertEqual(configuration(runtime), contract)
        restored, restored_backend = self.runtime(selected, profile="minimal")
        restore_runtime(restored, saved)
        self.assertEqual(configuration(restored), contract)
        self.assertEqual(restored_backend.requests, [])

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

    def test_worker_loads_same_reviewed_skill_and_restores_its_tool_contract(self):
        self.install('activity', 'WORKER_GUIDE: read the source and cite the observation.')
        (self.work/'source.txt').write_text('Public source fact')
        backend = Backend(answer(None, call('delegate', {
            'backend_preference':'cloud', 'task':'Read the public source with the activity guide.',
            'read_only':True}, 'delegate-once')),
            answer(None, call('load_skill', {'skill':'activity:user'}, 'load-once')),
            answer(None, call('read_file', {'path':'source.txt'}, 'read-once')),
            answer('Public source fact'), answer('Collected the evidence.'))

        def configured():
            runtime = AgentSession(create_default_registry(self.work, permission_mode='full-permission'),
                backend=backend, policy='cloud-only', engine_policy=EngineV5Policy(),
                hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED')),
                hybrid_backends={'cloud':backend}, hybrid_primary='cloud',
                budgets=SessionBudgets(max_steps=20, max_token_units=2000000,
                    max_worker_steps=8, max_worker_token_units=500000))
            self.runtimes.append(runtime)
            configure_session(runtime, self.root/'plugins', skill_home=self.skills.user,
                              skills=[{'id':'activity','scope':'user'}])
            return runtime

        runtime = configured()
        result = runtime.run_turn('Delegate a read-only source check.')
        self.assertEqual(result.status, 'completed')
        child = runtime._children['1.1']
        self.assertIn('load_skill', child.registry._tools)
        self.assertTrue(child.registry.gateway.capabilities.read_only)
        self.assertFalse(child.registry.gateway.capabilities.write)
        self.assertEqual([r['name'] for r in child.tool_history], ['load_skill','read_file'])
        self.assertNotIn('apply_patch', [s['function']['name'] for s in backend.requests[1]['tools']])
        saved = snapshot_runtime(runtime)
        count = len(backend.requests)
        restored = configured()
        restore_runtime(restored, saved)
        self.assertEqual(snapshot_runtime(restored)['children'], saved['children'])
        self.assertEqual(len(backend.requests), count)


if __name__ == "__main__":
    unittest.main()
