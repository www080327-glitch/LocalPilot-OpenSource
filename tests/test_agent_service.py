"""Real loopback HTTP and SQLite, scripted model. No local model inference."""
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError

from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession
from localpilot_api.service import TaskService
from localpilot_service.security import AccessPolicy, Principal
from localpilot_service.server import ServiceServer
from localpilot_service.sdk import Client
from localpilot_service.adapter import mcp
from localpilot_service.routing import select_route
from localpilot_service.model_manager import ControlledModelManager, ResourceGrant, ManagerError
from tests.test_runtime_api import Backend, answer, call


class AgentServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"; self.workspace.mkdir()
        self.backend = Backend(answer("hello"), answer("again"))
        self.verifier = None
        self.principals = [Principal("codex", "c"*32), Principal("dsh", "d"*32),
            Principal("operator", "o"*32, scopes=frozenset({"read", "control", "cancel"}), operator=True, approval_for=("codex",)),
            Principal("reader", "r"*32, scopes=frozenset({"read"}))]
        self.services = []
        self.start()

    def factory(self, callback):
        return AgentSession(create_default_registry(self.workspace, permission_mode="approve-mutations"),
            backend=self.backend, policy="cloud-only", event_callback=callback,
            verification_callback=self.verifier, retry_policy=RetryPolicy(max_attempts=1))

    def start(self):
        self.service = TaskService({"localpilot": self.factory}, persistence=self.root / "runtime.db")
        self.services.append(self.service)
        self.access = AccessPolicy(self.principals, audit_path=self.root/"audit.jsonl")
        self.server = ServiceServer(("127.0.0.1", 0), self.service, access=self.access)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True); self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        self.codex = Client(self.url, token="c"*32); self.dsh = Client(self.url, token="d"*32)
        self.operator = Client(self.url, token="o"*32)

    def stop(self):
        self.server.shutdown(); self.thread.join(2); self.server.server_close(); self.access.close()

    def tearDown(self):
        self.stop()
        for service in self.services:
            if service.store.connection:
                service.shutdown()
        self.temp.cleanup()

    def denied(self, code, function):
        with self.assertRaises(HTTPError) as caught:
            function()
        self.assertEqual(caught.exception.code, code)
        caught.exception.close()

    def done(self, task):
        self.service.wait(task["id"])
        return self.codex.status(task["id"])

    def test_client_isolation_and_operator_binding(self):
        task = self.done(self.codex.submit("hi", idempotency_key="same"))
        self.denied(404, lambda: self.dsh.status(task["id"]))
        self.denied(404, lambda: self.dsh.cancel(task["id"]))
        self.denied(404, lambda: self.dsh.submit("hijack", session_id=task["session_id"], idempotency_key="hijack"))
        self.assertEqual(self.operator.status(task["id"])["id"], task["id"])
        other = self.dsh.submit("dsh", idempotency_key="same"); self.service.wait(other["id"])
        self.denied(404, lambda: self.operator.status(other["id"]))
        self.assertNotEqual(task["id"], other["id"])

    def test_restart_ownership_request_id_and_durable_idempotency(self):
        task = self.done(self.codex.submit("hi", idempotency_key="restart"))
        request_id = task["service"]["request_id"]
        self.stop(); self.service.suspend(); self.start()
        retry = self.codex.submit("hi", idempotency_key="restart")
        self.assertEqual(retry["id"], task["id"])
        self.assertEqual(retry["service"]["request_id"], request_id)
        self.denied(404, lambda: self.dsh.status(task["id"]))
        self.assertEqual(len(self.backend.requests), 1)
        self.denied(409, lambda: self.codex.submit("changed", idempotency_key="restart"))

    def test_multi_turn_sse_and_openai_protocol(self):
        first = self.codex.request("/v1/responses", {"input": "remember pear"}, key="first")
        second = self.codex.request("/v1/chat/completions", {"messages": [{"role": "user", "content": "again"}],
            "localpilot": {"session_id": first["localpilot"]["session_id"]}}, key="second")
        self.assertEqual(second["localpilot"]["status"], "completed")
        self.assertIn("remember pear", [m.content for m in self.backend.requests[-1]["messages"]])
        events = list(self.codex.events(first["id"]))
        seq = [e["data"]["sequence"] for e in events]
        self.assertEqual(seq, sorted(set(seq)))
        self.assertEqual(list(self.codex.events(first["id"], after=seq[-2]))[-1]["data"]["sequence"], seq[-1])
        self.denied(404, lambda: self.dsh.request("/v1/responses", {"input": "stolen", "previous_response_id": first["id"]}, key="steal"))

    def test_session_retains_nondefault_route_when_model_is_omitted(self):
        self.service.routes["alternate"] = self.factory
        p = self.access.principals["codex"]
        self.access.principals["codex"] = replace(p, routes={"localpilot":"localpilot", "alternate":"alternate"})
        first = self.done(self.codex.submit("first", model="alternate", idempotency_key="alternate-first"))
        second = self.done(self.codex.submit("second", session_id=first["session_id"], idempotency_key="alternate-second"))
        self.assertEqual(second["model"], "alternate")
        self.assertEqual(second["service"]["route_decision"]["selection"], "session_affinity")
        self.denied(409, lambda: self.codex.submit("switch", model="localpilot", session_id=first["session_id"], idempotency_key="switch"))

    def test_approval_server_control_only_current_ticket(self):
        self.backend = Backend(answer(None, call("apply_patch", {"changes": [{"path": "out.txt", "operation": "create", "content": "approved"}]}, "write")), answer("done"))
        task = self.done(self.codex.submit("write", idempotency_key="write"))
        self.assertEqual(task["status"], "requires_approval"); self.assertFalse((self.workspace/"out.txt").exists())
        self.denied(403, lambda: self.codex.continue_task(task["id"], task["required_action"]["id"], action="approve"))
        self.stop(); self.service.suspend(); self.start()
        restored = self.codex.status(task["id"])
        self.denied(409, lambda: self.operator.continue_task(task["id"], task["required_action"]["id"], action="approve"))
        self.operator.continue_task(task["id"], restored["required_action"]["id"], action="approve")
        done = self.done(task)
        self.assertEqual(done["status"], "completed"); self.assertEqual((self.workspace/"out.txt").read_text(), "approved")
        self.assertEqual(done["receipt_summary"]["count"], 1)
        self.denied(409, lambda: self.operator.continue_task(task["id"], restored["required_action"]["id"], action="approve"))

    def test_cancel_waiting_approval_does_not_execute(self):
        self.backend = Backend(answer(None, call("apply_patch", {"changes": [{"path": "never.txt", "operation": "create", "content": "x"}]}, "write")))
        task = self.done(self.codex.submit("write", idempotency_key="cancel")); self.codex.cancel(task["id"])
        self.assertEqual(self.done(task)["status"], "cancelled"); self.assertFalse((self.workspace/"never.txt").exists())

    def test_unknown_mutation_is_quarantined_after_restart(self):
        self.backend = Backend(answer(None, call("apply_patch", {"changes": [{"path": "uncertain.txt", "operation": "create", "content": "effect"}]}, "write")), answer("done"))
        sid = self.codex.request("/localpilot/v1/sessions", {})["id"]
        registry = self.service.sessions[sid].runtime.registry
        original = registry._tools["apply_patch"]
        def lost(**kwargs):
            result = original(**kwargs)
            if (self.workspace/"uncertain.txt").exists():
                raise TimeoutError("receipt lost")
            return result
        registry._tools["apply_patch"] = lost
        task = self.done(self.codex.submit("write", session_id=sid, idempotency_key="unknown"))
        self.operator.continue_task(task["id"], task["required_action"]["id"], action="approve"); task = self.done(task)
        self.assertEqual(task["status"], "requires_human"); self.assertEqual(task["receipt_summary"]["unknown_effects"], 1)
        self.stop(); self.service.suspend(); self.start(); restored = self.codex.status(task["id"])
        self.assertEqual(restored["recovery"]["class"], "UNKNOWN_BLOCKED")
        self.denied(409, lambda: self.operator.continue_task(task["id"], restored["required_action"]["id"]))
        self.assertEqual(self.codex.submit("write", session_id=sid, idempotency_key="unknown")["id"], task["id"])
        self.assertEqual((self.workspace/"uncertain.txt").read_text(), "effect")

    def test_denied_missing_token_scope_origin_and_key(self):
        self.denied(401, lambda: Client(self.url, token="wrong").request("/healthz"))
        self.denied(403, lambda: Client(self.url, token="r"*32).submit("hi", idempotency_key="read"))
        self.denied(400, lambda: self.codex.request("/v1/responses", {"input": "hi"}))
        request = self.codex._request("/healthz"); request.add_header("Origin", "http://example.com")
        self.denied(403, lambda: self.codex.opener.open(request))
        self.assertEqual(len(self.backend.requests), 0)

    def test_rate_and_active_limits(self):
        p = self.access.principals["codex"]
        self.access.principals["codex"] = replace(p, requests_per_minute=1)
        self.codex.request("/healthz"); self.denied(429, lambda: self.codex.request("/healthz"))
        self.access.principals["codex"] = replace(p, max_active_tasks=1)
        self.access.times["codex"].clear()
        self.backend = Backend(answer(None, call("apply_patch", {"changes": [{"path": "x", "operation": "create", "content": "x"}]}, "write")))
        task = self.done(self.codex.submit("write", idempotency_key="one"))
        self.denied(429, lambda: self.codex.submit("another", idempotency_key="two"))
        self.assertEqual(self.codex.submit("write", idempotency_key="one")["id"], task["id"])

    def test_mcp_stdio_executes_service_not_http_example(self):
        requests = [
            {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}},
            {"jsonrpc":"2.0","id":2,"method":"tools/list"},
            {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"localpilot_submit","arguments":{"input":"real HTTP","idempotency_key":"mcp"}}}]
        out = io.StringIO(); mcp(self.codex, io.StringIO("\n".join(json.dumps(r) for r in requests)), out)
        replies = [json.loads(s) for s in out.getvalue().splitlines()]
        task = json.loads(replies[-1]["result"]["content"][0]["text"])
        self.assertEqual(self.done(task)["status"], "completed"); self.assertEqual(len(self.backend.requests), 1)
        self.assertEqual(len(replies[1]["result"]["tools"]), 7)

    def test_backend_failure_never_reports_completed(self):
        self.backend = Backend(ConnectionError("provider unreachable"))
        task = self.done(self.codex.submit("failure", idempotency_key="failed"))
        self.assertEqual(task["status"], "failed")
        self.assertEqual(self.codex.submit("failure", idempotency_key="failed")["id"], task["id"])

    def test_unknown_or_failed_host_verification_never_becomes_completed(self):
        from agent.stabilization import HostVerification
        for status in ("unknown", "failed", "blocked"):
            self.backend = Backend(answer("model says done"))
            self.verifier = lambda root, result, s=status: HostVerification(s, "fixture-contract", {}, False, True, True)
            task = self.done(self.codex.submit("verify", idempotency_key=status))
            self.assertEqual(task["status"], "incomplete")
            self.assertEqual(task["result"]["runtime_status"], "completed")
            facade = self.codex.request("/v1/responses/"+task["id"])
            self.assertEqual(facade["status"], "incomplete")
            self.assertEqual(facade['localpilot']['task_outcome'], status)
            request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                'params': {'name': 'localpilot_result', 'arguments': {'task_id': task['id']}}}
            out = io.StringIO()
            mcp(self.codex, io.StringIO(json.dumps(request)), out)
            snapshot = json.loads(json.loads(out.getvalue())['result']['content'][0]['text'])
            self.assertEqual(snapshot['result']['task_outcome'], status)
            self.assertFalse(snapshot['result']['task_succeeded'])

    def test_audit_contains_no_token_or_input(self):
        self.done(self.codex.submit("private prompt sentinel", idempotency_key="audit"))
        text = (self.root/"audit.jsonl").read_text()
        self.assertNotIn("private prompt sentinel", text); self.assertNotIn("c"*32, text)
        self.assertIn('"subject": "codex"', text)


class ContractTests(unittest.TestCase):
    def test_route_modes_and_unavailability_are_distinct(self):
        routes = {"local":"a", "cloud":"b", "down":"c", "offline":"d"}
        catalog = {"a":{"deployment_status":"not_deployed"}, "b":{"capabilities":["tool_calling"]},
                   "c":{"deployment_status":"loading"}, "d":{"deployment_status":"unavailable"}}
        model, decision = select_route(routes, catalog, preferences=["local","cloud"], required=["tool_calling"])
        self.assertEqual(model, "cloud"); self.assertEqual(decision["selection"], "preference")
        self.assertFalse(decision["backend_fallback"])
        from localpilot_api.service import APIError
        for model, reason in [("local","model_not_deployed"),("offline","model_unavailable"),("cloud","model_capability_insufficient")]:
            with self.assertRaises(APIError) as exc:
                select_route(routes, catalog, explicit=model, required=["reasoning"])
            self.assertEqual(exc.exception.code, reason)
        self.assertEqual(select_route({"cloud":"b"}, catalog)[1]["selection"], "automatic")
        self.assertEqual(select_route({"cloud":"b"}, catalog, explicit="cloud")[1]["selection"], "explicit")

    def test_model_manager_authorization_resource_and_idempotency(self):
        for values in ({"allow_download":"false"},{"disk_bytes":float("nan")},{"memory_bytes":-1},{"hardware":None}):
            with self.assertRaises(ValueError): ResourceGrant(**values)
        with self.assertRaises(ValueError): Principal("ordinary", "s"*32, operator="false")
        registry = {"approved":{"source":"trusted", "revision":"sha123", "license":"Apache-2.0", "hardware":"cpu-test", "trust_remote_code":False,
            "resource_estimate":{"memory_bytes":100,"disk_bytes":50}, "downloaded":False, "deployment_status":"not_deployed"}}
        manager = ControlledModelManager(registry)
        grant = ResourceGrant(("approved",), False, 50, 100, 200, "cpu-test", ("Apache-2.0",), ("trusted",))
        job = manager.ensure("approved", grant=grant, idempotency_key="denied")
        self.assertEqual(job["failure_reason"], "download_not_authorized")
        grant = replace(grant, allow_download=True)
        job = manager.ensure("approved", grant=grant, idempotency_key="allowed")
        self.assertEqual(manager.ensure("approved", grant=grant, idempotency_key="allowed")["id"], job["id"])
        while job["status"] != "completed": job = manager.advance(job["id"])
        self.assertEqual(manager.model("approved")["deployment_status"], "ready")
        with self.assertRaises(ManagerError): manager.ensure("arbitrary/repo", grant=grant, idempotency_key="arbitrary")
        with self.assertRaises(ManagerError): manager.ensure("approved", grant=grant, idempotency_key="allowed", operation="unload")
        for field, value, reason in [("source","evil","source_revision_not_approved"),("license","unknown","license_not_approved"),("hardware","gpu","hardware_incompatible_or_unknown"),("trust_remote_code",True,"untrusted_code_forbidden")]:
            bad = json.loads(json.dumps(registry)); bad["approved"][field] = value
            self.assertEqual(ControlledModelManager(bad).ensure("approved", grant=grant, idempotency_key=field)["failure_reason"], reason)


if __name__ == "__main__":
    unittest.main()
