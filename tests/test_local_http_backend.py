"""Real loopback HTTP/SSE transport tests; the server is scripted, not a model."""

import contextlib
import io
import json
import ssl
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from agent.backends import BackendCapabilities, BackendResponse, Message
from agent.local_http import LocalBackendError, LocalHTTPBackend
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.retry import is_transient_error
from agent.session import AgentSession


def completion(text=None, calls=None, finish=None):
    message = {"role": "assistant", "content": text}
    if calls:
        message["tool_calls"] = calls
    return {"model": "mock-local", "choices": [{"message": message,
             "finish_reason": finish or ("tool_calls" if calls else "stop")}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2}}


def tool_call(name, arguments, call_id="c1"):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}


def sse(*events):
    return "".join("data: " + json.dumps(item) + "\n\n" for item in events).encode() + b"data: [DONE]\n\n"


class MockServer:
    def __init__(self):
        self.responses = []
        self.requests = []
        self.headers = []
        self.models = ["mock-local"]
        self.model_status = 200
        self.redirect_url = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                outer.headers.append((self.path, self.headers.get("Authorization")))
                self.send_response(outer.model_status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"data": [{"id": x} for x in outer.models]}).encode())

            def do_POST(self):
                outer.headers.append((self.path, self.headers.get("Authorization")))
                length = int(self.headers["Content-Length"])
                outer.requests.append(json.loads(self.rfile.read(length)))
                status, body, content_type = outer.responses.pop(0)
                if callable(body):
                    body = body(outer.requests[-1])
                self.send_response(status)
                if outer.redirect_url and 300 <= status < 400:
                    self.send_header("Location", outer.redirect_url)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                if isinstance(body, list):
                    for fragment in body:
                        self.wfile.write(fragment)
                        self.wfile.flush()
                else:
                    self.wfile.write(body if isinstance(body, bytes) else json.dumps(body).encode())

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.http.server_port}/v1"

    def add(self, body, status=200, content_type="application/json"):
        self.responses.append((status, body, content_type))

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()


class CloudSpy:
    capabilities = BackendCapabilities(supports_tool_calling=True)
    is_local = False

    def __init__(self):
        self.calls = []

    def request(self, messages, **kwargs):
        self.calls.append([m.to_dict() for m in messages])
        return BackendResponse(Message("assistant", "cloud answer"))


class LocalHTTPTests(unittest.TestCase):
    def setUp(self):
        self.server = MockServer()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "note.txt").write_text("fact")
        self.local = LocalHTTPBackend(base_url=self.server.base_url, model="mock-local",
                                      effective_context=131072, size_class="27B", timeout=1)
        self.cloud = CloudSpy()

    def tearDown(self):
        self.server.close()
        self.tmp.cleanup()

    def session(self, policy="local-only", *, permission_mode="approve-mutations", streaming=False, cloud=None):
        registry = create_default_registry(self.root, permission_mode=permission_mode)
        return AgentSession(registry, cloud_backend=cloud, local_backend=self.local,
                            policy=policy, streaming=streaming,
                            retry_policy=RetryPolicy(max_attempts=2, base_delay=0, jitter=0))

    def test_health_and_model_identity(self):
        state = self.local.status()
        self.assertTrue(state["service_running"])
        self.assertTrue(state["model_available"])
        self.assertEqual(state["model"], "mock-local")
        self.assertEqual(state["effective_context"], 131072)
        self.assertEqual(state["effective_context_source"], "configured_estimate")
        self.assertTrue(state["capabilities"]["supports_tool_calling"])

    def test_successful_completion_and_message_payload(self):
        self.server.add(completion("hello"))
        answer = self.local.request([Message("user", "hi")], max_tokens=20)
        self.assertEqual(answer.message.content, "hello")
        self.assertEqual(self.server.requests[0]["messages"], [{"role": "user", "content": "hi"}])
        self.assertEqual(self.server.requests[0]["max_tokens"], 20)

    def test_optional_chat_template_kwargs_for_local_server(self):
        local = LocalHTTPBackend(base_url=self.server.base_url, model="mock-local",
                                 chat_template_kwargs={"enable_thinking": False})
        self.server.add(completion("READY"))
        self.assertEqual(local.request([Message("user", "hi")]).message.content, "READY")
        self.assertEqual(self.server.requests[0]["chat_template_kwargs"],
                         {"enable_thinking": False})
        self.assertNotIn("chat_template_kwargs", self.local._payload([Message("user", "hi")], None, 10))

    def test_optional_stream_usage_request(self):
        local = LocalHTTPBackend(base_url=self.server.base_url, model="mock-local",
                                 include_stream_usage=True)
        self.server.add(sse({"choices": [{"index": 0, "delta": {"content": "ok"},
                                          "finish_reason": "stop"}]},
                            {"choices": [], "usage": {"completion_tokens": 1}}),
                        content_type="text/event-stream")
        chunks = list(local.stream([Message("user", "hi")]))
        self.assertEqual(chunks[-1].response.usage["completion_tokens"], 1)
        self.assertEqual(self.server.requests[0]["stream_options"], {"include_usage": True})
        self.assertNotIn("stream_options", self.local._payload([Message("user", "hi")], None, 10, True))

    def test_streaming_and_fragmented_sse(self):
        body = sse({"choices": [{"index": 0, "delta": {"content": "Hel"}}]},
                   {"choices": [{"index": 0, "delta": {"content": "lo"}, "finish_reason": "stop"}]},
                   {"choices": [], "usage": {"completion_tokens": 2}})
        self.server.add([body[:3], body[3:17], body[17:48], body[48:]], content_type="text/event-stream")
        chunks = list(self.local.stream([Message("user", "hi")]))
        self.assertEqual([c.text for c in chunks if c.kind == "text"], ["Hel", "lo"])
        self.assertEqual(chunks[-1].response.message.content, "Hello")
        self.assertEqual(chunks[-1].response.usage["completion_tokens"], 2)

    def test_fragmented_tool_call_and_result_continuation(self):
        first = sse({"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0,
            "id": "c1", "function": {"name": "read_", "arguments": '{"pa'}}]}}]},
            {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0,
            "function": {"name": "file", "arguments": 'th":"note.txt"}'}}]},
            "finish_reason": "tool_calls"}]})
        self.server.add([first[:8], first[8:60], first[60:]], content_type="text/event-stream")
        second = sse({"choices": [{"index": 0, "delta": {"content": "fact found"},
                                    "finish_reason": "stop"}]})
        self.server.add(second, content_type="text/event-stream")
        session = self.session(streaming=True)
        result = session.run_turn("read note")
        self.assertEqual(result.text, "fact found")
        self.assertEqual(len(self.server.requests), 2)
        self.assertTrue(self.server.requests[0]["tools"])
        sent = self.server.requests[1]["messages"]
        self.assertEqual(sent[-1]["role"], "tool")
        self.assertEqual(sent[-1]["tool_call_id"], "c1")
        self.assertIn("fact", sent[-1]["content"])
        self.assertEqual(session.tool_history[0]["name"], "read_file")

    def test_local_only_never_calls_cloud_and_persistent_context(self):
        self.server.add(completion("first"))
        self.server.add(completion("second"))
        session = self.session(cloud=self.cloud)
        self.assertEqual(session.run_turn("secret").text, "first")
        self.assertEqual(session.run_turn("follow up").text, "second")
        sent = self.server.requests[1]["messages"]
        self.assertIn({"role": "user", "content": "secret"}, sent)
        self.assertIn({"role": "assistant", "content": "first"}, sent)
        self.assertEqual(self.cloud.calls, [])

    def test_local_first_fallback_after_retry_exhaustion(self):
        self.server.add({"error": "busy"}, status=503)
        self.server.add({"error": "busy"}, status=503)
        session = self.session("local-first", cloud=self.cloud)
        self.assertEqual(session.run_turn("question").text, "cloud answer")
        self.assertEqual(len(self.server.requests), 2)
        self.assertEqual(len(self.cloud.calls), 1)
        self.assertIn({"role": "user", "content": "question"}, self.cloud.calls[0])

    def test_local_only_retry_exhaustion(self):
        self.server.add({"error": "busy"}, status=503)
        self.server.add({"error": "busy"}, status=503)
        result = self.session(cloud=self.cloud).run_turn("secret")
        self.assertEqual(result.status, "error")
        self.assertEqual(len(self.server.requests), 2)
        self.assertEqual(self.cloud.calls, [])

    def test_model_unavailable_and_service_unavailable(self):
        self.server.models = []
        status = self.local.status()
        self.assertTrue(status["service_running"])
        self.assertFalse(status["model_available"])
        self.assertIn("install or load", status["error"])
        self.assertEqual(self.session().run_turn("hi").status, "error")
        self.server.model_status = 503
        self.assertFalse(self.local.status()["service_running"])

    def test_malformed_response_never_executes_tool(self):
        self.server.add({"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "tool_calls": []}}]})
        session = self.session()
        self.assertEqual(session.run_turn("change").status, "error")
        self.assertFalse(session.tool_history)

    def test_permission_enforcement_and_no_duplicate_mutation(self):
        change = tool_call("apply_patch", {"changes": [{"path": "new.txt", "operation": "create", "content": "new"}]})
        self.server.add(completion(calls=[change]))
        self.server.add(completion("done"))
        session = self.session()
        self.assertEqual(session.run_turn("create").status, "approval_required")
        self.assertFalse((self.root / "new.txt").exists())
        self.assertEqual(session.approve().text, "done")
        self.assertEqual((self.root / "new.txt").read_text(), "new")
        self.assertEqual(len([x for x in session.registry.gateway.audit if x.get("status") == "applied"]), 1)
        self.assertEqual(len(self.server.requests), 2)

    def test_repeated_tool_call_id_uses_original_receipt(self):
        change = tool_call("apply_patch", {"changes": [{"path": "new.txt", "operation": "create", "content": "new"}]})
        self.server.add(completion(calls=[change]))
        self.server.add(completion(calls=[change]))
        self.server.add(completion("done"))
        session = self.session(permission_mode="full-permission")
        self.assertEqual(session.run_turn("create once").text, "done")
        self.assertEqual((self.root / "new.txt").read_text(), "new")
        self.assertEqual(len([x for x in session.registry.gateway.audit if x.get("status") == "applied"]), 1)
        self.assertEqual(len(self.server.requests), 3)

    def test_local_model_switch_preserves_context_and_requires_approval(self):
        switch = tool_call("request_model_switch", {"target": "cloud", "reason": "complex",
                                                   "task_complexity": "complex"})
        self.server.add(completion(calls=[switch]))
        session = self.session("local-first", cloud=self.cloud)
        self.assertEqual(session.run_turn("remember this").status, "approval_required")
        self.assertEqual(self.cloud.calls, [])
        self.assertEqual(session.approve().text, "cloud answer")
        self.assertIn({"role": "user", "content": "remember this"}, self.cloud.calls[0])

    def test_malformed_sse_never_executes_tool(self):
        self.server.add(b"data: {bad json}\n\ndata: [DONE]\n\n", content_type="text/event-stream")
        session = self.session(streaming=True)
        self.assertEqual(session.run_turn("write").status, "error")
        self.assertFalse(session.tool_history)

    def test_one_shot_agent_regression_uses_same_session(self):
        from agent.loop import Agent
        self.server.add(completion("one shot"))
        registry = create_default_registry(self.root)
        agent = Agent(self.local, registry, max_steps=2)
        self.assertEqual(agent.run("hi").text, "one shot")

    def test_cli_one_shot_with_configured_local_server(self):
        from agent.__main__ import main
        self.server.add(completion("local CLI answer"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status = main(["--workspace", str(self.root), "--local-only",
                           "--local-base-url", self.server.base_url,
                           "--local-model", "mock-local", "--no-stream", "hello"])
        self.assertEqual(status, 0, output.getvalue())
        self.assertIn("local CLI answer", output.getvalue())
        self.assertEqual(len(self.server.requests), 1)

    def test_loopback_default_and_redirect_rejection(self):
        for url in ("http://example.com/v1", "http://localhost:1234/v1", "http://127.0.0.2.evil/v1"):
            with self.assertRaises(ValueError):
                LocalHTTPBackend(base_url=url, model="x")
        self.server.add(b"", status=302)
        with self.assertRaises(LocalBackendError):
            self.local.request([Message("user", "hi")])

    def test_certificate_failure_is_not_transient(self):
        with patch.object(self.local._opener, "open", side_effect=URLError(ssl.SSLCertVerificationError("invalid"))):
            with self.assertRaises(LocalBackendError) as caught:
                self.local.request([Message("user", "hi")])
        self.assertFalse(is_transient_error(caught.exception))

    def test_remote_override_cannot_be_local_only(self):
        remote = LocalHTTPBackend(base_url="https://example.com/v1", model="x", allow_remote=True)
        with self.assertRaises(PermissionError):
            AgentSession(create_default_registry(self.root), local_backend=remote, policy="local-only")


if __name__ == "__main__":
    unittest.main()
