"""Inference Backend V1: unit and scripted sockets, never model inference."""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.__main__ import main
from agent.backends import Message
from agent.backend_verification import verify_backend, render_report, write_report
from agent.cli import command
from agent.local_http import LocalHTTPBackend, LocalBackendError
from agent.policy import DataPolicy
from agent.registry import create_default_registry
from agent.retry import is_transient_error, RetryPolicy
from agent.session import AgentSession
from tests.test_local_http_backend import MockServer, completion, tool_call, sse, CloudSpy


def probe_call(payload):
    token = re.search(r"token ([a-f0-9]+)", payload["messages"][-1]["content"]).group(1)
    if not payload["stream"]:
        return completion(calls=[tool_call("probe_echo", {"token": token})])
    return sse({"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "probe",
        "function": {"name": "probe_", "arguments": '{"token":'}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0,
        "function": {"name": "echo", "arguments": json.dumps(token) + "}"}}]}, "finish_reason": "tool_calls"}]})


def probe_continuation(payload):
    result = payload["messages"][-1]
    assert result["role"] == "tool" and result["tool_call_id"]
    token = json.loads(result["content"])["token"]
    if not payload["stream"]:
        return completion(token)
    return sse({"choices": [{"index": 0, "delta": {"content": token}, "finish_reason": "stop"}]})


def successful_smoke(server):
    server.add(completion("READY"))
    server.add(sse({"choices": [{"index": 0, "delta": {"content": "READY"}, "finish_reason": "stop"}]}), content_type="text/event-stream")
    server.add(probe_call, content_type="text/event-stream")
    server.add(probe_continuation, content_type="text/event-stream")
    reason = completion("56")
    reason["choices"][0]["message"]["reasoning_content"] = "7 times 8 is 56"
    server.add(reason)


class InferenceBackendTests(unittest.TestCase):
    def setUp(self):
        self.server = MockServer()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.backend = self.make_backend()

    def tearDown(self):
        self.server.close()
        self.tmp.cleanup()

    def make_backend(self, **kwargs):
        return LocalHTTPBackend(base_url=self.server.base_url, model="mock-local", timeout=1, **kwargs)

    def session(self, backend=None, streaming=False, cloud=None):
        return AgentSession(create_default_registry(self.root), local_backend=backend or self.backend,
            policy="local-first" if cloud else "local-only", cloud_backend=cloud, streaming=streaming,
            retry_policy=RetryPolicy(max_attempts=2, base_delay=0, jitter=0))

    def cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status = main(list(args))
        return status, output.getvalue()

    def test_profile_claims_are_not_verified_capabilities(self):
        profile = self.make_backend(engine="omlx", engine_version="UNKNOWN", hardware="operator-reported M1", device="Metal").profile.snapshot()
        self.assertEqual(profile["engine"], "omlx")
        self.assertEqual(profile["model_revision"], "UNKNOWN")
        self.assertEqual(profile["capabilities"]["streaming"]["status"], "configured")
        self.assertEqual(profile["capabilities"]["reasoning"]["status"], "unknown")
        self.assertEqual(profile["verification_state"], "not_run")
        self.backend.status()
        self.assertEqual(self.backend.profile.snapshot()["capabilities"]["basic_chat"]["status"], "unknown")
        self.assertFalse(self.server.requests)

    def test_optional_authorization_all_routes_and_secret_redaction(self):
        backend = self.make_backend(api_key="private-test-token")
        backend.status()
        self.server.add(completion("ok"))
        backend.request([Message("user", "hi")])
        self.server.add(sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}), content_type="text/event-stream")
        list(backend.stream([Message("user", "hi")]))
        self.assertTrue(all(header == "Bearer private-test-token" for _, header in self.server.headers))
        self.assertNotIn("private-test-token", json.dumps(backend.profile.snapshot()))
        self.server.add({"error": "private-test-token"}, status=401)
        with self.assertRaises(LocalBackendError) as caught:
            backend.request([Message("user", "hi")])
        self.assertNotIn("private-test-token", str(caught.exception))
        self.assertFalse(is_transient_error(caught.exception))

    def test_auth_default_and_header_injection_validation(self):
        self.backend.status()
        self.assertIsNone(self.server.headers[0][1])
        for key in ("", "x\nInjected: value", 123):
            with self.assertRaises(ValueError):
                self.make_backend(api_key=key)

    def test_authorization_never_follows_redirect(self):
        target = MockServer()
        try:
            self.server.redirect_url = target.base_url + "/models"
            self.server.add({}, status=302)
            backend = self.make_backend(api_key="secret")
            with self.assertRaisesRegex(LocalBackendError, "redirect refused"):
                backend.request([Message("user", "hi")])
            self.assertFalse(target.headers)
            self.assertFalse(target.requests)
        finally:
            target.close()

    def test_unknown_usage_stays_null_and_explicit_zero_survives(self):
        for usage in (None, {}, {"completion_tokens": 0}, {"completion_tokens": None}):
            data = completion("ok")
            data["usage"] = usage
            self.assertEqual(LocalHTTPBackend._choice(data).usage, usage)
        data.pop("usage")
        self.assertIsNone(LocalHTTPBackend._choice(data).usage)
        self.server.add(sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}), content_type="text/event-stream")
        self.assertIsNone(list(self.backend.stream([Message("user", "hi")]))[-1].response.usage)

    def test_finish_reasons_are_preserved_in_buffered_and_stream_responses(self):
        for reason in ("stop", "length", "content_filter", "vendor_limit"):
            self.server.add(completion("partial", finish=reason))
            response = self.backend.request([Message("user", "hi")])
            self.assertEqual(response.finish_reason, reason)
            self.server.add(sse({"choices": [{"delta": {"content": "partial"}, "finish_reason": reason}]}), content_type="text/event-stream")
            response = list(self.backend.stream([Message("user", "hi")]))[-1].response
            self.assertEqual(response.finish_reason, reason)
            self.assertEqual(response.message.content, "partial")

    def test_truncated_tools_never_execute_or_fallback_or_generate_plan(self):
        change = tool_call("apply_patch", {"changes": [{"path": "new.txt", "operation": "create", "content": "bad"}]})
        for streaming in (False, True):
            cloud = CloudSpy()
            if streaming:
                self.server.add(sse({"choices": [{"delta": {"tool_calls": [{"index": 0, **change}], "content": "partial"}, "finish_reason": "length"}]}), content_type="text/event-stream")
            else:
                self.server.add(completion("partial", calls=[change], finish="length"))
            session = self.session(streaming=streaming, cloud=cloud)
            session.set_plan_mode(True)
            result = session.run_turn("create")
            self.assertEqual(result.status, "error")
            self.assertEqual(result.model_calls[0].finish_reason, "length")
            self.assertIn("partial", result.text)
            self.assertIn("finish_reason=length", result.text)
            self.assertFalse((self.root / "new.txt").exists())
            self.assertFalse(session.tool_history)
            self.assertFalse(session.pending_approval)
            self.assertIsNone(session.active_plan)
            self.assertFalse(cloud.calls)

    def test_session_missing_usage_is_unknown(self):
        data = completion("ok")
        data.pop("usage")
        self.server.add(data)
        result = self.session().run_turn("hi")
        self.assertEqual(result.status, "completed")
        self.assertIsNone(result.model_calls[0].input_tokens)
        self.assertIsNone(result.model_calls[0].output_tokens)
        self.assertEqual(result.usage_summary()["cache"]["status"], "unavailable")

    def test_reasoning_preserved_and_replay_opt_in(self):
        message = Message("assistant", None, reasoning_content="previous reasoning")
        self.assertNotIn("reasoning_content", self.backend._payload([message], None, 10)["messages"][0])
        backend = self.make_backend(reasoning_replay=True)
        self.assertEqual(backend._payload([message], None, 10)["messages"][0]["reasoning_content"], "previous reasoning")
        self.server.add(sse({"choices": [{"delta": {"reasoning_content": "step "}}]},
            {"choices": [{"delta": {"reasoning_content": "two", "content": "answer"}, "finish_reason": "stop"}]}), content_type="text/event-stream")
        chunks = list(backend.stream([Message("user", "hi")]))
        self.assertEqual([c.text for c in chunks if c.kind == "reasoning"], ["step ", "two"])
        self.assertEqual(chunks[-1].response.message.reasoning_content, "step two")
        self.server.add(completion("next"))
        backend.request([chunks[-1].response.message, Message("user", "again")])
        self.assertEqual(self.server.requests[-1]["messages"][0]["reasoning_content"], "step two")

    def test_reasoning_tool_result_continuation_uses_gateway(self):
        (self.root / "note.txt").write_text("fact")
        backend = self.make_backend(reasoning_replay=True)
        data = completion(calls=[tool_call("read_file", {"path": "note.txt"})])
        data["choices"][0]["message"]["reasoning_content"] = "need evidence"
        self.server.add(data)
        self.server.add(completion("fact found"))
        session = self.session(backend)
        self.assertEqual(session.run_turn("read").status, "completed")
        self.assertEqual(session.tool_history[0]["name"], "read_file")
        messages = self.server.requests[-1]["messages"]
        self.assertEqual(messages[-2]["reasoning_content"], "need evidence")
        self.assertEqual(messages[-1]["tool_call_id"], "c1")

    def test_interrupted_reasoning_and_tool_fragments_are_not_replayed(self):
        for delta in ({"reasoning_content": "thinking"}, {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "apply_patch", "arguments": "{"}}]}):
            body = ("data: " + json.dumps({"choices": [{"delta": delta}]}) + "\n\n").encode()
            self.server.add(body, content_type="text/event-stream")
            before = len(self.server.requests)
            cloud = CloudSpy()
            session = self.session(streaming=True, cloud=cloud)
            self.assertEqual(session.run_turn("write").status, "error")
            self.assertEqual(len(self.server.requests), before + 1)
            self.assertFalse(cloud.calls)
            self.assertFalse(session.tool_history)

    def test_reasoning_mapping_requires_operator_native_values(self):
        with self.assertRaises(ValueError):
            self.backend._payload([Message("user", "hi")], None, 10, thinking="high")
        backend = self.make_backend(supports_reasoning=True, reasoning_efforts=["medium"])
        self.assertEqual(backend._payload([Message("user", "hi")], None, 10, thinking="medium")["reasoning_effort"], "medium")
        self.assertIn("not_verified", backend.thinking_mapping("medium")["reason"])
        with self.assertRaises(ValueError):
            self.make_backend(reasoning_efforts=["high"])

    def test_full_scripted_verification_and_reports(self):
        backend = self.make_backend(supports_reasoning=True, reasoning_replay=True)
        successful_smoke(self.server)
        report = verify_backend(backend, evidence_kind="scripted-tested")
        self.assertTrue(report["passed"])
        self.assertTrue(all(c["status"] == "verified" for c in report["checks"].values()))
        self.assertEqual(len(self.server.requests), 5)
        self.assertTrue(all(p["max_tokens"] == 96 for p in self.server.requests))
        profile = backend.profile.snapshot()
        self.assertEqual(profile["capabilities"]["context"]["status"], "configured")
        self.assertEqual(profile["capabilities"]["parallel_tool_calls"]["status"], "unknown")
        self.assertEqual(profile["verification_state"], "matched_historical")
        modified = json.loads(json.dumps(report))
        modified["checks"]["context"] = {"status": "verified", "outcome": "passed"}
        with self.assertRaises(ValueError):
            backend.profile.attach_verification(modified)
        paths = write_report(report, self.root / "probe")
        self.assertEqual(json.loads(paths[0].read_text()), report)
        self.assertIn("scripted-tested", paths[1].read_text())
        with self.assertRaises(FileExistsError):
            write_report(report, self.root / "probe")
        self.assertIn("no context", render_report(report))

    def test_verification_is_independent_of_product_eligibility(self):
        backend = self.make_backend(size_class="4B", effective_context=512)
        self.server.add(completion("READY"))
        report = verify_backend(backend, ["basic_chat"])
        self.assertTrue(report["passed"])
        self.assertEqual(backend.model_info.effective_context, 512)
        self.assertEqual(backend.profile.snapshot()["capabilities"]["context"]["status"], "configured")

    def test_verification_disabled_unknown_and_failed_are_distinct(self):
        backend = self.make_backend(supports_streaming=False, supports_tool_calling=False)
        self.server.add(completion("READY"))
        report = verify_backend(backend)
        self.assertEqual(report["checks"]["streaming"]["status"], "unsupported")
        self.assertEqual(report["checks"]["streaming"]["source"], "operator_disabled")
        self.assertEqual(report["checks"]["reasoning"]["status"], "unknown")
        self.assertEqual(len(self.server.requests), 1)
        self.server.add(completion("partial", finish="length"))
        report = verify_backend(backend, ["basic_chat"])
        self.assertFalse(report["passed"])
        check = report["checks"]["basic_chat"]
        self.assertEqual(check["status"], "unknown")
        self.assertEqual(check["observations"][0]["finish_reason"], "length")

    def test_health_failure_does_not_send_generation_requests(self):
        self.server.models = []
        report = verify_backend(self.backend)
        self.assertFalse(report["passed"])
        self.assertEqual(report["checks"]["basic_chat"]["outcome"], "skipped")
        self.assertFalse(self.server.requests)

    def test_transient_verification_failure_is_not_unsupported_or_retried(self):
        self.server.add({"error": "busy"}, status=503)
        report = verify_backend(self.backend, ["basic_chat"])
        check = report["checks"]["basic_chat"]
        self.assertEqual(check["status"], "unknown")
        self.assertEqual(check["status_code"], 503)
        self.assertEqual(len(self.server.requests), 1)

    def test_reasoning_absence_is_unknown_not_verified_or_unsupported(self):
        backend = self.make_backend(supports_reasoning=True)
        self.server.add(completion("56"))
        report = verify_backend(backend, ["reasoning"])
        self.assertEqual(report["checks"]["reasoning"]["status"], "unknown")
        self.assertEqual(report["checks"]["reasoning"]["outcome"], "failed")

    def test_mismatched_and_stale_verification_cannot_verify_new_config(self):
        report = verify_backend(self.backend, ["health_models"], evidence_kind="scripted-tested")
        for kwargs in ({"engine_version": "new"}, {"model_revision": "new"}, {"reasoning_replay": True}, {"hardware": "new"}, {"size_class": "4B"}):
            with self.assertRaises(ValueError):
                self.make_backend(**kwargs).profile.attach_verification(report)
        self.backend.profile.model_revision = "new"
        snapshot = self.backend.profile.snapshot()
        self.assertEqual(snapshot["verification_state"], "stale")
        self.assertEqual(snapshot["capabilities"]["health_models"]["status"], "unknown")

    def test_cli_profile_and_historical_report_are_offline(self):
        report = verify_backend(self.backend, ["health_models"], evidence_kind="scripted-tested")
        report_path = self.root / "verification.json"
        report_path.write_text(json.dumps(report))
        with patch.object(LocalHTTPBackend, "_open", side_effect=AssertionError("network")):
            status, output = self.cli("--local-base-url", self.server.base_url, "--local-model", "mock-local",
                                      "--local-timeout", "1", "--backend-status", "--backend-verification", str(report_path))
        self.assertEqual(status, 0, output)
        self.assertEqual(json.loads(output)["verification_state"], "matched_historical")
        self.assertFalse(self.server.requests)

    def test_cli_profile_flags_override_and_key_env_is_not_exported(self):
        config = {"base_url": self.server.base_url, "model": "old", "configured_context": 512,
                  "engine": "llama.cpp", "capabilities": {"tool_calling": False}, "api_key_env": "TEST_SERVING_KEY"}
        path = self.root / "profile.json"
        path.write_text(json.dumps(config))
        with patch.dict("os.environ", {"TEST_SERVING_KEY": "secret"}):
            status, output = self.cli("--serving-profile", str(path), "--local-model", "mock-local", "--local-context", "1024", "--backend-status")
        self.assertEqual(status, 0, output)
        profile = json.loads(output)
        self.assertEqual(profile["model"], "mock-local")
        self.assertEqual(profile["configured_context"], 1024)
        self.assertEqual(profile["engine"], "llama.cpp")
        self.assertFalse(profile["configured_capabilities"]["tool_calling"])
        self.assertNotIn("secret", output)
        self.assertFalse(self.server.requests)

    def test_cli_verification_has_no_cloud_or_workspace_dependency(self):
        self.server.add(completion("READY"))
        with patch("agent.__main__.DeepSeekBackend", side_effect=AssertionError("cloud")), patch("agent.__main__.configure_workers", side_effect=AssertionError("workers")):
            status, output = self.cli("--workspace", "/nonexistent/smoke", "--local-base-url", self.server.base_url,
                "--local-model", "mock-local", "--backend-verify", "--backend-checks", "basic_chat",
                "--backend-report", str(self.root / "cli"), "--verification-evidence", "scripted-tested")
        self.assertEqual(status, 0, output)
        self.assertTrue((self.root / "cli.json").exists())
        self.assertTrue((self.root / "cli.md").exists())
        self.assertIn("scripted-tested", output)

    def test_interactive_backend_snapshot_does_not_call_service(self):
        session = self.session()
        before = len(self.server.headers)
        state = json.loads(command(session, "/backend"))
        self.assertEqual(state["backend"], "LocalHTTPBackend")
        self.assertEqual(state["profile"]["verification_state"], "not_run")
        self.assertEqual(len(self.server.headers), before)

    def test_profile_rejects_false_verified_claims_and_malformed_config(self):
        for config in ({"capabilities": {"streaming": "verified"}}, {"api_key": "secret"}, {"verification": {"status": "verified"}}, {"reasoning_replay": "false"}):
            config.update(base_url=self.server.base_url, model="mock-local")
            path = self.root / "bad.json"
            path.write_text(json.dumps(config))
            status, output = self.cli("--serving-profile", str(path), "--backend-status")
            self.assertEqual(status, 1, output)
        self.assertFalse(self.server.headers)

    def test_local_only_rejects_declared_remote_tunnel_before_network(self):
        backend = self.make_backend(service_location="remote")
        with self.assertRaises(PermissionError):
            self.session(backend)
        with self.assertRaises(PermissionError):
            DataPolicy(local_only=True).check_backend(backend)
        self.assertFalse(self.server.headers)

    def test_local_only_policy_change_rejects_remote_tunnel(self):
        session = self.session(self.make_backend(service_location="remote"), cloud=CloudSpy())
        with self.assertRaises(PermissionError):
            session.set_policy("local-only")
        self.assertEqual(session.routing_policy.value, "local-first")

    def test_malformed_stream_usage_and_tool_index_fail_closed(self):
        for data in ({"choices": [], "usage": 0}, {"choices": [{"delta": {"tool_calls": [
                {"index": "0", "id": "c1", "function": {"name": "read_file", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]}):
            self.server.add(sse(data), content_type="text/event-stream")
            with self.assertRaises(LocalBackendError) as caught:
                list(self.backend.stream([Message("user", "hi")]))
            self.assertFalse(is_transient_error(caught.exception))

    def test_buffered_tool_smoke_rejects_invalid_arguments(self):
        backend = self.make_backend(supports_streaming=False)
        call = tool_call("probe_echo", {})
        call["function"]["arguments"] = "{bad-json"
        self.server.add(completion(calls=[call]))
        report = verify_backend(backend, ["tool_calling"])
        self.assertFalse(report["passed"])
        self.assertEqual(report["checks"]["tool_calling"]["status"], "unknown")
        self.assertEqual(len(self.server.requests), 1)

    def test_buffered_tool_smoke_continuation(self):
        backend = self.make_backend(supports_streaming=False)
        self.server.add(probe_call)
        self.server.add(probe_continuation)
        report = verify_backend(backend, ["tool_calling"])
        self.assertTrue(report["passed"])
        self.assertEqual(report["checks"]["tool_calling"]["status"], "verified")
        self.assertEqual(len(self.server.requests), 2)

    def test_unknown_check_rejected_before_network(self):
        with self.assertRaises(ValueError):
            verify_backend(self.backend, ["context"])
        self.assertFalse(self.server.headers)


if __name__ == "__main__":
    unittest.main()
