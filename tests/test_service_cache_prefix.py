"""Cache layout controls with scripted models; zero provider API calls."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from copy import deepcopy
from dataclasses import replace

from agent.backends import Message
from agent.context import transfer_context
from agent.hybrid import CloudEgressPolicy, HybridPolicy
from agent.persistence import configuration, snapshot_runtime, restore_runtime, PersistenceError
from agent.policy import DataPolicy
from agent.registry import create_default_registry
from agent.session import AgentSession
from localpilot_service.deployment import build
from localpilot_api.service import TaskService, TaskRequest
from tests.test_runtime_api import Backend, answer
from tests.test_runtime_api import call
from tests import test_agent_service as agent_service_tests


class ServiceCachePrefixTests(unittest.TestCase):
    def runtime(self, root, backend, *, in_history=False):
        backend.service_cache_stable_prefix = True
        backend.supports_in_history_system_prompt = in_history
        return AgentSession(create_default_registry(root, data_policy=DataPolicy(local_only=False)),
            backend=backend, policy="cloud-only", data_policy=DataPolicy(local_only=False),
            hybrid_policy=HybridPolicy(CloudEgressPolicy("CLOUD_ALLOWED")),
            hybrid_backends={"cloud":backend}, hybrid_primary="cloud")

    def test_opt_in_appends_current_state_after_stable_history(self):
        with tempfile.TemporaryDirectory() as root:
            backend = Backend(answer("one"), answer("two"))
            backend.service_cache_stable_prefix = True
            runtime = AgentSession(create_default_registry(root, data_policy=DataPolicy(local_only=False)),
                backend=backend, policy="cloud-only", data_policy=DataPolicy(local_only=False),
                hybrid_policy=HybridPolicy(CloudEgressPolicy("CLOUD_ALLOWED")),
                hybrid_backends={"cloud":backend}, hybrid_primary="cloud")
            runtime.run_turn("public question one")
            runtime.run_turn("public question two")
            first = [m.to_dict() for m in backend.requests[0]["messages"]]
            second = [m.to_dict() for m in backend.requests[1]["messages"]]
            self.assertEqual(first, second[:len(first)])
            self.assertIn("Host working state", first[-1]["content"])
            self.assertIn("Host working state", second[-1]["content"])
            self.assertIn("public question two", json.dumps(second[-1]))
            self.assertIsNone(runtime.harness_policy)

    def test_supported_system_update_appends_without_changing_old_prefix(self):
        with tempfile.TemporaryDirectory() as root:
            backend=Backend(answer("one"),answer("two"))
            runtime=self.runtime(root,backend,in_history=True)
            runtime.run_turn("public one")
            first=[m.to_dict() for m in backend.requests[0]["messages"]]
            runtime.set_plan_mode(True)
            runtime.run_turn("public two")
            second=[m.to_dict() for m in backend.requests[1]["messages"]]
            self.assertEqual(first,second[:len(first)])
            systems=[m for m in second if m["role"]=="system"]
            self.assertEqual(len(systems),2)
            self.assertIn("Plan Mode ON",systems[-1]["content"])
            self.assertTrue(runtime.registry.gateway.plan_read_only)
            self.assertEqual(second[-1]["role"],"user")
            runtime.close()

    def test_unsupported_route_consolidates_effective_prompt(self):
        with tempfile.TemporaryDirectory() as root:
            backend=Backend(answer("one"),answer("two"))
            runtime=self.runtime(root,backend)
            runtime.run_turn("one");runtime.set_plan_mode(True);runtime.run_turn("two")
            systems=[m for m in backend.requests[1]["messages"] if m.role=="system"]
            self.assertEqual(len(systems),1)
            self.assertIn("Plan Mode ON",systems[0].content)
            runtime.close()

    def test_public_cloud_history_survives_actual_sqlite_style_snapshot_restore(self):
        with tempfile.TemporaryDirectory() as root:
            backend=Backend(answer("one"),answer("two"))
            runtime=self.runtime(root,backend,in_history=True);runtime.run_turn("one")
            snapshot=snapshot_runtime(runtime)
            first=[m.to_dict() for m in backend.requests[0]["messages"]]
            restored=self.runtime(root,backend,in_history=True)
            restore_runtime(restored,snapshot);restored.run_turn("two")
            second=[m.to_dict() for m in backend.requests[1]["messages"]]
            self.assertEqual(first,second[:len(first)])
            self.assertTrue(any(m.get("content")=="one" and m["role"]=="assistant" for m in second))
            runtime.close();restored.close()

    def test_local_or_unproven_assistant_text_is_still_withheld(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=self.runtime(root,Backend(answer("public")))
            messages=[Message("assistant","LOCAL_PRIVATE_CANARY")]
            self.assertNotIn("LOCAL_PRIVATE_CANARY",json.dumps([m.to_dict() for m in runtime.hybrid.project_messages(messages)]))
            runtime.close()

    def test_egress_scope_change_invalidates_cloud_history_provenance(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=self.runtime(root,Backend(answer("known cloud text")))
            runtime.run_turn("one")
            self.assertIn("known cloud text",json.dumps([m.to_dict() for m in runtime.hybrid.project_messages(runtime.messages)]))
            runtime.hybrid.policy=replace(runtime.hybrid.policy,egress=CloudEgressPolicy("LOCAL_ONLY"))
            self.assertNotIn("known cloud text",json.dumps([m.to_dict() for m in runtime.hybrid.project_messages(runtime.messages)]))
            runtime.close()

    def test_compaction_uses_current_system_and_preserves_raw_history(self):
        messages=[Message("system","old control"),Message("user","x"*12000),
                  Message("system","current control"),Message("user","new question")]
        before=deepcopy(messages)
        result,info=transfer_context(messages,[],3000,500,working_state={"unknown":"UNKNOWN_BLOCKED","approval":"pending"},stable_history_prefix=True)
        self.assertTrue(info)
        self.assertEqual([m.content for m in result if m.role=="system"],["current control"])
        self.assertIn("UNKNOWN_BLOCKED",result[-1].content)
        self.assertEqual(messages,before)

    def test_tool_schema_order_does_not_depend_on_registration_order(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=self.runtime(root,Backend(answer("one")))
            schemas=runtime.registry.schemas()
            with patch.object(runtime.registry,"schemas",return_value=list(reversed(schemas))):
                reversed_view=runtime._schemas()
            self.assertEqual(runtime._schemas(),reversed_view)
            runtime.close()

    def test_unknown_cache_usage_stays_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=self.runtime(root,Backend(answer("one")))
            runtime.run_turn("one")
            metrics=runtime.hybrid.summary()["by_backend"]["cloud"]
            self.assertIsNone(metrics["cache_hit_ratio"])
            self.assertIsNone(metrics["prompt_cache_miss_tokens"])
            runtime.close()

    def test_sqlite_restart_preserves_complete_cached_request_prefix(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);workspace=root/"workspace";workspace.mkdir()
            backend=Backend(answer("one"),answer("two"))
            factory=lambda callback:self.runtime(workspace,backend,in_history=True)
            service=TaskService({"localpilot":factory},persistence=root/"runtime.sqlite3")
            first=service.create_task(TaskRequest("public first",idempotency_key="one"))
            service.wait(first["id"])
            first_view=[m.to_dict() for m in backend.requests[0]["messages"]]
            service.suspend()
            service=TaskService({"localpilot":factory},persistence=root/"runtime.sqlite3")
            try:
                second=service.create_task(TaskRequest("public second",session_id=first["session_id"],idempotency_key="two"))
                service.wait(second["id"])
                second_view=[m.to_dict() for m in backend.requests[1]["messages"]]
                self.assertEqual(first_view,second_view[:len(first_view)])
            finally:
                service.shutdown()

    def configured(self, root, option):
        config = {"schema_version":1,"port":0,"data_dir":str(root/"data"),
            "clients":[{"subject":"companion","token_env":"SERVICE_CACHE_TEST_TOKEN"}],
            "routes":{"localpilot":{"workspace":str(root/"workspace"),
                "backend":{"kind":"local-openai","model":"fixture","base_url":"http://127.0.0.1:1/v1"},
                "cache_stable_prefix":option}}}
        path = root/"service.json"; path.write_text(json.dumps(config)); path.chmod(0o600)
        return path

    def test_option_is_host_only_and_changes_recovery_fingerprint(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,SERVICE_CACHE_TEST_TOKEN="c"*32):
            root=Path(folder);(root/"workspace").mkdir()
            enabled=build(self.configured(root,True))
            try:
                runtime=enabled.service.routes["localpilot"](lambda event:None)
                self.assertTrue(runtime.current_backend.service_cache_stable_prefix)
                conf=configuration(runtime)
                self.assertIn('"cache_stable_prefix": true',json.dumps(conf))
                self.assertIsNone(runtime.harness_policy)
                self.assertTrue(enabled.catalog["localpilot"]["cache_stable_prefix"])
            finally:
                enabled.service.suspend();enabled.server_close();enabled.access.close()
            disabled=build(self.configured(root,False))
            try:
                runtime=disabled.service.routes["localpilot"](lambda event:None)
                self.assertFalse(getattr(runtime.current_backend,"service_cache_stable_prefix",False))
                self.assertNotIn('"cache_stable_prefix"',json.dumps(configuration(runtime)))
            finally:
                disabled.service.suspend();disabled.server_close();disabled.access.close()

    def test_truthy_strings_never_enable_host_policy(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,SERVICE_CACHE_TEST_TOKEN="c"*32):
            root=Path(folder);(root/"workspace").mkdir()
            with self.assertRaisesRegex(ValueError,"host boolean"):
                build(self.configured(root,"false"))

    def test_minimal_reasoning_route_has_no_tools_or_agent_state_prompt(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,SERVICE_CACHE_TEST_TOKEN="c"*32):
            root=Path(folder);(root/"workspace").mkdir()
            path=self.configured(root,True);config=json.loads(path.read_text())
            route=config["routes"]["localpilot"]
            route.update(prompt_profile="minimal_0",tool_profile="compact",reasoning_only=True,
                         capabilities={"read":False,"write":False,"execute":False})
            route["backend"]={"kind":"deepseek","model":"deepseek-flash","api_key_env":"SERVICE_CACHE_TEST_TOKEN"}
            route["cloud_egress"]="CLOUD_ALLOWED"
            path.write_text(json.dumps(config));server=build(path)
            try:
                runtime=server.service.routes["localpilot"](lambda event:None)
                self.assertEqual(runtime.registry.schemas(),[])
                self.assertEqual(runtime._schemas(),[])
                self.assertEqual(runtime.base_prompt,"")
                self.assertFalse(runtime.runtime_tools)
                self.assertTrue(server.catalog["localpilot"]["reasoning_only"])
                # Keep all Gateway/Task state outside model input in this profile.
                runtime.streaming=False
                captured=[]
                def reply(messages,**options):
                    captured.append((messages,options));return answer("plain answer")
                with patch.object(runtime.current_backend,"request",side_effect=reply):
                    runtime.run_turn("synthetic question")
                text=json.dumps([m.to_dict() for m in captured[0][0]])
                self.assertNotIn("Host working state",text)
                self.assertNotIn("COORDINATOR",text)
                self.assertIsNone(captured[0][1]["tools"])
                with patch.object(runtime.current_backend,"request",return_value=answer(None,call("apply_patch",{"changes":[{"path":"forbidden.txt","operation":"create","content":"bad"}]}))):
                    rejected=runtime.run_turn("malicious proposal")
                    self.assertEqual(rejected.status,"error")
                    self.assertIn("tools despite disabled",rejected.text)
                self.assertFalse((root/"workspace/forbidden.txt").exists())
                self.assertEqual(runtime.tool_history,[])
                runtime.close()
            finally:
                server.service.suspend();server.server_close();server.access.close()

    def test_reasoning_profile_rejects_tool_grants(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,SERVICE_CACHE_TEST_TOKEN="c"*32):
            root=Path(folder);(root/"workspace").mkdir()
            path=self.configured(root,True);config=json.loads(path.read_text())
            config["routes"]["localpilot"].update(reasoning_only=True,capabilities={"read":True,"write":False,"execute":False})
            path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError,"cannot grant"):
                build(path)


class CachedAgentServiceTests(agent_service_tests.AgentServiceTests):
    """Run existing ownership/approval/UNKNOWN controls with cache enabled."""
    def factory(self, callback):
        self.backend.service_cache_stable_prefix=True
        return super().factory(callback)

class CompanionProfileSplitTests(unittest.TestCase):
    def test_generated_companion_routes_split_minimal_reasoning_and_standard_agent(self):
        import contextlib,io
        from localpilot_service.configure import main
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);workspace=root/'workspace';workspace.mkdir()
            private=root/'service'
            with contextlib.redirect_stdout(io.StringIO()):
                main(['--workspace',str(workspace),'--directory',str(private),'--model','scripted-model'])
            config=json.loads((private/'service.json').read_text())
            reasoning=config['routes']['companion-reasoning'];execution=config['routes']['companion-execution']
            self.assertEqual(reasoning['prompt_profile'],'minimal_0')
            self.assertTrue(reasoning['reasoning_only'])
            self.assertFalse(any(reasoning['capabilities'].values()))
            self.assertEqual(execution['prompt_profile'],'standard')
            self.assertEqual(execution['tool_profile'],'full')
            self.assertFalse(execution.get('reasoning_only',False))
            self.assertTrue(reasoning['cache_stable_prefix']);self.assertTrue(execution['cache_stable_prefix'])
