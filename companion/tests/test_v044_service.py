"""Real V4.9.1 HTTP/SQLite + scripted backend; model evidence is MOCK_ONLY."""
from dataclasses import replace
from datetime import datetime
from email.message import Message
import io
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

from companion.config import Config
from companion.escalation.service_v491 import LocalPilotProvider
from companion.escalation.localpilot import task_view
from companion.escalation.egress import cloud_context
from companion.escalation.provider import EscalationRequest
from companion.runtime.power import LowPowerPolicy
from companion.runtime.service import Companion

# Monorepo tests must use their owning checkout, never a sibling historical tree.
_checkout = Path(__file__).resolve().parents[2]
LP = Path(os.environ.get("LOCALPILOT_SOURCE", str(_checkout if (_checkout/'localpilot_service').is_dir() else _checkout.parent/'LocalPilot')))
sys.path.insert(0, str(LP))


def request(text="Explain this public synthetic question", classification="LOCAL_ONLY"):
    return EscalationRequest(text, "manual", "explicit_user_request", [], [], [],
                             {"local_only":classification == "LOCAL_ONLY", "classification":classification}, "")


class ServiceContractTests(unittest.TestCase):
    def setUp(self):
        global create_default_registry, RetryPolicy, AgentSession, TaskService, ServiceServer, AccessPolicy, Principal, Client, Backend, answer, call
        from agent.registry import create_default_registry
        from agent.retry import RetryPolicy
        from agent.session import AgentSession
        from localpilot_api.service import TaskService
        from localpilot_service.server import ServiceServer
        from localpilot_service.security import AccessPolicy, Principal
        from localpilot_service.sdk import Client
        from tests.test_runtime_api import Backend, answer, call
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.workspace = self.root/"workspace"
        self.workspace.mkdir()
        self.backend = Backend(answer("Synthetic answer"), answer("Next answer"))
        self.token = secrets.token_urlsafe(32)
        self.other_token = secrets.token_urlsafe(32)
        self.env = patch.dict(os.environ, LOCALPILOT_COMPANION_TOKEN=self.token)
        self.env.start()
        self.services = []
        self.start()

    def factory(self, callback):
        return AgentSession(create_default_registry(self.workspace, permission_mode="approve-all"),
                            backend=self.backend, policy="cloud-only", event_callback=callback,
                            retry_policy=RetryPolicy(max_attempts=1))

    def start(self):
        self.service = TaskService({"localpilot":self.factory}, persistence=self.root/"runtime.sqlite3")
        self.services.append(self.service)
        self.access = AccessPolicy([Principal("companion", self.token), Principal("other", self.other_token)])
        self.server = ServiceServer(("127.0.0.1", 0), self.service, access=self.access,
            catalog={"localpilot":{"adapter":"local-openai", "cloud_egress":"LOCAL_ONLY", "model":"script-provider", "deployment_status":"ready", "prompt_profile":"standard", "reasoning_only":False}})
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval":.02}, daemon=True)
        self.thread.start()
        self.config = Config(data_dir=str(self.root/"host"), backend="disabled", low_power_policy="off",
                             localpilot_endpoint=f"http://127.0.0.1:{self.server.server_port}",
                             localpilot_host_local_only=True)
        self.provider = LocalPilotProvider(self.config)

    def stop(self):
        self.server.shutdown()
        self.thread.join(2)
        self.server.server_close()
        self.access.close()

    def tearDown(self):
        self.stop()
        for service in self.services:
            if service.store.connection:
                service.shutdown()
        self.env.stop()
        self.tmp.cleanup()

    def submit(self, key="stable-key", **kwargs):
        return self.provider.submit(request(), approved=True, submission_id=key, **kwargs)

    def done(self, view):
        self.service.wait(view["task_id"])
        return self.provider.status(view["task_id"])

    def host(self):
        app = Companion(self.config)
        app.controls._test_bypass=True
        app.monitor_task = Mock()  # Deterministic tests inspect real snapshots explicitly.
        self.addCleanup(app.lock.close)
        self.addCleanup(app.store.close)
        self.addCleanup(app.channel.stop)
        return app

    def test_cloud_question_never_reuses_local_context_session(self):
        from dataclasses import replace as dc_replace
        self.server.catalog["localpilot"].update(reasoning_only=True,prompt_profile="minimal_0")
        p=self.access.principals["companion"]
        self.access.principals["companion"]=dc_replace(p,routes={"localpilot":"localpilot","companion-cloud-reasoning":"localpilot"})
        app=self.host();app.config.localpilot_analysis_route="localpilot"
        app.localpilot=LocalPilotProvider(app.config)
        local=app.prepare_escalation(request("local question"),mode="reasoning")
        one=app.command({"command":"submit_escalation","approved":True,"expected_digest":local["review_digest"]})
        self.service.wait(one["task_id"])
        self.server.catalog["localpilot"].update(adapter="deepseek",cloud_egress="REQUIRES_APPROVAL")
        cloud=app.prepare_escalation(request("public cloud question"),mode="reasoning")
        two=app.command({"command":"submit_escalation","approved":True,"provider_kind":"cloud","cloud_approved":True,"expected_digest":cloud["review_digest"]})
        self.assertNotEqual(one["session_id"],two["session_id"])
        self.assertNotIn("Client instructions:",self.service._session(two["session_id"]).runtime.base_prompt)
        self.assertTrue(two["task_id"])
        self.assertIn("local-user.reasoning.cloud",app.store.get("localpilot_conversations"))
        self.service.wait(two["task_id"])
        third=app.prepare_escalation(request("another public question"),mode="reasoning")
        three=app.command({"command":"submit_escalation","approved":True,"provider_kind":"cloud","cloud_approved":True,"expected_digest":third["review_digest"]})
        self.assertTrue(three.get("task_id"),three)
        self.assertNotEqual(two["session_id"],three["session_id"])

    def test_authenticated_health_checks_subject_and_persistence(self):
        value = self.provider.health()
        self.assertEqual(value["service"]["client_subject"], "companion")
        self.assertTrue(value["identity_verified"])
        self.assertEqual(value["service"]["model_health"], "NOT_PROBED")
        self.assertEqual(self.backend.requests, [])

    def test_wrong_expired_or_missing_token_is_auth_failure(self):
        for token in ("invalid", ""):
            with patch.dict(os.environ, LOCALPILOT_COMPANION_TOKEN=token):
                provider = LocalPilotProvider(self.config)
                self.assertNotEqual(provider.health()["status"], "available")
        self.assertEqual(self.backend.requests, [])

    def test_other_subject_cannot_be_used_as_companion(self):
        with patch.dict(os.environ, LOCALPILOT_COMPANION_TOKEN=self.other_token):
            self.assertEqual(self.submit()["error"]["code"], "service_identity_mismatch")
        self.assertEqual(len(self.service.tasks), 0)

    def test_native_submit_result_not_claimed_verified(self):
        view = self.done(self.submit())
        self.assertEqual(view["status"], "completed")
        self.assertEqual(view["verification_status"], "not_run")
        self.assertFalse(view["goal_verified"])
        self.assertEqual(view["semantic_status"], "UNVERIFIED")

    def test_namespace_isolation_and_control_denial(self):
        view = self.done(self.submit())
        other = Client(self.config.localpilot_endpoint, token=self.other_token)
        from urllib.error import HTTPError
        for action in (lambda:other.status(view["task_id"]),
                       lambda:other.cancel(view["task_id"])):
            with self.assertRaises(HTTPError) as caught:
                action()
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()
        client = Client(self.config.localpilot_endpoint, token=self.token)
        with self.assertRaises(HTTPError) as caught:
            client.continue_task(view["task_id"], "forged", action="approve")
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_durable_idempotency_survives_actual_service_replacement(self):
        first = self.done(self.submit())
        self.stop()
        self.service.suspend()
        self.start()
        repeated = self.submit()
        self.assertEqual(first["task_id"], repeated["task_id"])
        self.assertEqual(first["session_id"], repeated["session_id"])
        self.assertEqual(len(self.backend.requests), 1)

    def test_changed_request_same_key_conflicts(self):
        self.done(self.submit())
        result = self.provider.submit(request("changed"), approved=True, submission_id="stable-key")
        self.assertEqual(result["error"]["http_status"], 409)
        self.assertEqual(len(self.backend.requests), 1)

    def test_real_sse_cursor_replay_and_snapshot(self):
        view = self.done(self.submit())
        frames = list(self.provider.stream(view["task_id"]))
        events = [f for f in frames if f["status"] == "event"]
        self.assertTrue(events)
        cursor = events[0]["last_event_id"]
        replay = list(self.provider.stream(view["task_id"], after=cursor))
        self.assertEqual([f["last_event_id"] for f in replay], [f["last_event_id"] for f in events[1:]])
        self.assertEqual(self.provider.status(view["task_id"])["task_id"], view["task_id"])

    def test_invalid_cursor_does_not_resubmit(self):
        view = self.done(self.submit())
        frames = list(self.provider.stream(view["task_id"], after=999999))
        self.assertEqual(frames[-1]["error"]["http_status"], 409)
        self.assertEqual(self.provider.status(view["task_id"])["status"], "completed")
        self.assertEqual(len(self.backend.requests), 1)

    def test_waiting_approval_and_cancel_are_service_owned(self):
        self.backend.steps[:] = [answer("", call("read_file", {"path":"public.txt"}))]
        (self.workspace/"public.txt").write_text("public fixture")
        waiting = self.done(self.submit())
        self.assertEqual(waiting["status"], "requires_approval")
        self.assertTrue(waiting["required_action"]["id"])
        self.assertEqual(self.provider.approve(waiting["task_id"])["status"], "host_control_required")
        cancelled = self.provider.cancel(waiting["task_id"], approved=True)
        self.service.wait(waiting["task_id"])
        cancelled = self.provider.status(waiting["task_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertFalse(cancelled["goal_verified"])

    def test_host_intent_and_conversation_session_persist_across_host_restart(self):
        app = self.host()
        app.prepare_escalation(request())
        digest = app.review_digest(app.store.get("pending_escalation"))
        view = app.command({"command":"submit_escalation", "approved":True, "expected_digest":digest})
        self.assertIn("task_id", view)
        self.service.wait(view["task_id"])
        app.channel.stop(); app.store.close(); app.lock.close()
        # Cancel registered cleanups for the closed first host.
        self._cleanups = self._cleanups[:-3]
        app = self.host()
        mapping = app.store.get("localpilot_conversations")["local-user"]
        self.assertEqual(mapping["session_id"], view["session_id"])
        self.assertEqual(mapping["last_task_id"], view["task_id"])
        self.assertIn(view["task_id"], app.store.get("localpilot_tasks"))
        restored = app.command({"command":"task_status", "task_id":view["task_id"]})
        self.assertEqual(restored["task_id"], view["task_id"])
        self.assertEqual(len(self.backend.requests), 1)

    def test_disconnect_retains_running_snapshot(self):
        app = self.host()
        app.store.set("localpilot_tasks", {"resp_saved":{"endpoint":self.config.localpilot_endpoint,
            "last_status":{"status":"running", "task_id":"resp_saved", "quiescent":False}}})
        app.receive_task_update("resp_saved", {"status":"unavailable", "task_id":"resp_saved", "error":{"code":"connection_unavailable"}})
        saved = app.store.get("localpilot_tasks")["resp_saved"]
        self.assertEqual(saved["last_status"]["status"], "running")
        self.assertIn("connection_error", saved)

    def test_result_written_to_real_sqlite_with_unverified_identity(self):
        app = self.host()
        view = self.done(self.submit())
        app.store_task_result(view)
        rows = app.observation_memory.records(limit=10)
        self.assertTrue(any(r["source"] == "localpilot" for r in rows))
        self.assertFalse(app.store.records(10, ["user_fact"]))
        self.assertEqual(app.store.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_cloud_context_rejected_before_any_network_call(self):
        provider = LocalPilotProvider(replace(self.config, localpilot_host_local_only=False, localpilot_allow_cloud=True))
        result = provider.submit(request(), approved=True, cloud_approved=True)
        self.assertEqual(result["error"]["code"], "cloud_approval_required")
        self.assertEqual(provider.network_calls, 0)

    def test_lost_submit_response_reuses_persisted_key_after_host_restart(self):
        from companion.escalation.localpilot import TransportFailure
        app = self.host()
        app.prepare_escalation(request())
        digest = app.review_digest(app.store.get("pending_escalation"))
        original = app.localpilot._request
        def lose_response(path, body=None, **kwargs):
            value = original(path, body, **kwargs)
            if path == "/localpilot/v1/tasks":
                raise TransportFailure("incomplete_response")
            return value
        with patch.object(app.localpilot, "_request", side_effect=lose_response):
            uncertain = app.command({"command":"submit_escalation", "approved":True, "expected_digest":digest})
        self.assertEqual(uncertain["status"], "submission_unknown")
        intent = app.store.get("pending_localpilot_submission")
        self.service.wait(next(iter(self.service.tasks)))
        app.channel.stop(); app.store.close(); app.lock.close(); self._cleanups = self._cleanups[:-3]
        app = self.host()
        restored = app.command({"command":"submit_escalation", "approved":True, "expected_digest":digest, "retry":True})
        self.assertEqual(restored["submission_id"], intent["submission_id"])
        self.assertEqual(len(self.service.tasks), 1)
        self.assertEqual(len(self.backend.requests), 1)

    def test_crash_between_id_record_and_mapping_projection_repairs_locally(self):
        app = self.host()
        view = self.done(self.submit())
        app.store.set("pending_localpilot_submission", {"endpoint":self.config.localpilot_endpoint,
            "result":app.task_summary(view), "transport":{"subject":"companion"}, "conversation_id":"repair"})
        calls = self.provider.network_calls
        app.recover_submission_journal()
        self.assertIn(view["task_id"], app.store.get("localpilot_tasks"))
        self.assertEqual(app.store.get("localpilot_conversations")["repair"]["session_id"], view["session_id"])
        self.assertIsNone(app.store.get("pending_localpilot_submission"))
        self.assertEqual(self.provider.network_calls, calls)

    def test_second_conversation_cannot_reuse_first_session(self):
        app = self.host()
        first = self.done(self.submit())
        app.store.set("localpilot_conversations", {"one":{"session_id":first["session_id"],
            "endpoint":self.config.localpilot_endpoint,"subject":"companion"}})
        app.prepare_escalation(request())
        digest = app.review_digest(app.store.get("pending_escalation"))
        result = app.command({"command":"submit_escalation", "approved":True, "expected_digest":digest,
                              "conversation_id":"two", "session_id":first["session_id"]})
        self.assertEqual(result["status"], "denied")
        self.assertEqual(len(self.backend.requests), 1)

    def test_connection_failure_opens_circuit_without_submission_replay(self):
        from urllib.error import URLError
        self.provider.opener = Mock()
        self.provider.opener.open.side_effect = URLError("connection refused")
        for _ in range(8):
            self.provider.health()
        self.assertEqual(self.provider.opener.open.call_count, 1)
        self.assertEqual(self.provider.connection_state()["status"], "LOCALPILOT_UNAVAILABLE")
        self.assertEqual(len(self.service.tasks), 0)

    def test_reasoning_requires_explicit_separate_host_route(self):
        provider=LocalPilotProvider(replace(self.config,localpilot_analysis_route=""))
        result = provider.submit(request(), approved=True, mode="reasoning")
        self.assertEqual(result["error"]["code"], "analysis_route_unconfigured")
        self.assertEqual(self.provider.network_calls, 0)

    def test_429_prevents_immediate_reconnect_storm(self):
        from urllib.error import HTTPError
        headers = Message(); headers["Retry-After"] = "120"
        self.provider.opener = Mock()
        self.provider.opener.open.side_effect = HTTPError("redacted", 429, "limited", headers, io.BytesIO(b'{}'))
        first = self.provider.health()
        self.assertGreater(first["retry_after_seconds"], 119)
        for _ in range(10):
            self.provider.health()
        self.assertEqual(self.provider.opener.open.call_count, 1)

    def test_openapi_status_enum_matches_client(self):
        from companion.escalation.localpilot import STATUSES
        schema = json.loads((LP/"localpilot_service/openapi.json").read_text())
        task = schema["components"]["schemas"]["Task"]
        self.assertEqual(set(task["properties"]["status"]["enum"]), STATUSES)
        for path in ("/healthz", "/localpilot/v1/tasks", "/localpilot/v1/tasks/{task_id}/events"):
            self.assertIn(path, set(schema["paths"]))


class PowerPrivacyTests(unittest.TestCase):
    def test_default_is_always_low_power(self):
        self.assertTrue(LowPowerPolicy(Config()).active())

    def test_explicit_09_and_21_local_time(self):
        for limit in ("09:00", "21:00"):
            policy = LowPowerPolicy(Config(low_power_policy="until", low_power_until=limit))
            hour = int(limit[:2])
            self.assertTrue(policy.active(datetime(2026,10,18,hour-1,59)))
            self.assertFalse(policy.active(datetime(2026,10,18,hour,0)))

    def test_ambiguous_time_and_invalid_schedule_rejected(self):
        for value in ("9", "9:00", "25:00", "21:90"):
            with self.assertRaises(ValueError):
                LowPowerPolicy(Config(low_power_until=value))

    def test_local_context_labels_and_derived_summaries_cannot_bypass(self):
        value = request(classification="USER_APPROVED_CLOUD")
        value.relevant_memories = [{"id":"private", "summary":"PRIVATE_CANARY", "classification":"PUBLIC"}]
        value.recent_events = [{"summary":"DERIVED_CANARY", "metadata":{"cloud_approved":True}}]
        value.relevant_files = ["PRIVATE_PATH"]
        result = cloud_context(value, True)
        self.assertNotIn("CANARY", json.dumps(result))
        self.assertNotIn("PRIVATE_PATH", json.dumps(result))
        self.assertEqual(result["privacy_scope"]["omitted_local_records"], 3)

    def test_public_still_requires_per_request_grant(self):
        with self.assertRaises(PermissionError):
            cloud_context(request(classification="PUBLIC"), False)

    def test_unknown_mutation_cannot_be_verified_by_model_text(self):
        task = {"object":"localpilot.task", "id":"resp_x", "session_id":"sess_x", "status":"completed", "quiescent":True,
                "result":{"text":"All done and verified", "verification_status":"passed"}, "recovery":{"class":"UNKNOWN_BLOCKED"}}
        self.assertEqual(task_view(task)["semantic_status"], "UNKNOWN")
        self.assertFalse(task_view(task)["goal_verified"])

    def test_backend_failure_or_unverified_engineering_never_means_goal_success(self):
        for state, verification, engineering in (("failed","not_run","unverified"),
                ("completed","passed","unverified"), ("completed","not_run","unverified")):
            task = {"object":"localpilot.task", "id":"resp_x", "session_id":"sess_x", "status":state,
                "quiescent":True, "result":{"text":"Success!", "verification_status":verification,"engineering_status":engineering}}
            self.assertFalse(task_view(task)["goal_verified"])

    def test_low_power_does_not_summarize_document_with_local_model(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root).resolve(); docs = root/"docs"; docs.mkdir()
            file = docs/"public.txt"; file.write_text("A synthetic source.")
            app = Companion(Config(data_dir=str(root/"state"), watch_dirs=(str(docs),), backend="disabled", summarize_documents=True))
            try:
                app.process_file(str(file), "modified")
                self.assertEqual(app.model.inferences, 0)
                self.assertTrue(app.store.records(10, ["document"]))
            finally:
                app.channel.stop(); app.store.close(); app.lock.close()

    def test_low_power_no_background_calls_or_large_manager(self):
        with tempfile.TemporaryDirectory() as root:
            app = Companion(Config(data_dir=str(Path(root).resolve()/"state"), backend="disabled", tier2_model_path="/synthetic/4B"))
            try:
                for index in range(50):
                    app.consider_event({"kind":"edits", "project":str(index), "count":20})
                app.greet("startup")
                self.assertIsNone(app.secondary_model)
                self.assertEqual(app.model.inferences, 0)
                self.assertEqual(app.localpilot.network_calls, 0)
                self.assertEqual(app.ask("你好")["status"], "ok")
            finally:
                app.channel.stop(); app.store.close(); app.lock.close()

    def test_small_model_idle_does_not_load_without_on_demand(self):
        from companion.model.backend import ModelManager
        model = ModelManager(Config(model_path="/nonexistent/lightweight", lightweight_on_demand=False))
        self.assertEqual(model.complete([{"role":"user", "content":"hello"}])["error_stage"], "power_policy")
        self.assertIsNone(model.child)

    def test_large_weight_budget_rejected_before_loading(self):
        from companion.model.backend import ModelManager
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"model.safetensors"
            with path.open("wb") as stream:
                stream.truncate(1500000001)
            model = ModelManager(Config(model_path=root, lightweight_on_demand=True))
            self.assertEqual(model.complete([])["error_stage"], "power_policy")
            self.assertIsNone(model.child)
