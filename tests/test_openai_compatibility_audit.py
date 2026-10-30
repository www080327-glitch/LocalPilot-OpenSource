"""Independent protocol oracles on the existing real HTTP/Runtime fixture.

Passing tests include explicit observations of known compatibility gaps. They
are scripted controls, never a claim of full OpenAI or real-model compatibility.
Run as a module with --output NEW.json to save response/event observations.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from queue import Queue
import threading
import unittest

try:
    import httpx
    import openai
    from openai import OpenAI, APIResponseValidationError, APIStatusError, APITimeoutError
    from openai.types.responses import Response
    from pydantic import ValidationError
except ImportError:
    OpenAI = None

from agent.backends import BackendChunk, BackendResponse, Message
from tests import test_runtime_api as fixtures


@unittest.skipIf(OpenAI is None, "optional official SDK is not installed")
class CompatibilityAudit(unittest.TestCase):
    observations = []
    task = fixtures.APITests.task
    patch_backend = fixtures.APITests.patch_backend
    computer_backend = fixtures.APITests.computer_backend

    def setUp(self):
        fixtures.APITests.setUp(self)
        self.releases = []
        self.sdk = OpenAI(base_url=self.url + "/v1", api_key="test-key", max_retries=0,
                          timeout=5, http_client=httpx.Client(trust_env=False))

    def tearDown(self):
        for release in self.releases:
            release.set()
        self.sdk.close()
        fixtures.APITests.tearDown(self)

    def record(self, classification, **data):
        self.observations.append({"case": self._testMethodName, "classification": classification, **data})

    def create(self, **kwargs):
        return self.sdk.responses.create(model="localpilot", input="audit", **kwargs)

    def chat(self, **kwargs):
        return self.sdk.chat.completions.create(model="localpilot", messages=[{"role": "user", "content": "audit"}], **kwargs)

    def reject(self, path, body, status=400):
        response = self.sdk._client.post(self.url + path, json=body,
            headers={"Authorization": "Bearer test-key"})
        self.assertEqual(response.status_code, status, response.text)
        error = response.json()["error"]
        self.assertTrue(error["message"])
        self.assertIn("param", error)
        return error

    def test_sdk_text_and_usage(self):
        self.backend = fixtures.Backend(fixtures.answer("你好"), fixtures.answer("chat"))
        response, chat = self.create(), self.chat()
        self.assertEqual(response.output_text, "你好")
        self.assertEqual(chat.choices[0].finish_reason, "stop")
        self.assertEqual(response.usage.total_tokens, 10)
        self.assertEqual(chat.usage.total_tokens, 10)
        self.record("partial", response=response.model_dump(mode="json", exclude_unset=True, warnings=False), chat=chat.model_dump(mode="json", exclude_unset=True, warnings=False))

    def test_strict_sdk_response_schema_gap(self):
        self.backend = fixtures.Backend(fixtures.answer(), fixtures.answer())
        with OpenAI(base_url=self.url + "/v1", api_key="test-key", max_retries=0,
                http_client=httpx.Client(trust_env=False), _strict_response_validation=True) as strict:
            with self.assertRaises(APIResponseValidationError):
                strict.responses.create(model="localpilot", input="strict")
        response = self.create().model_dump(mode="json", exclude_unset=True, warnings=False)
        with self.assertRaises(ValidationError) as error:
            Response.model_validate(response)
        locations = [list(item["loc"]) for item in error.exception.errors()]
        self.assertIn(["tools"], locations)
        self.record("partial", missing_or_invalid=locations)

    def test_response_sse_order_and_item_identity(self):
        frames = list(self.client.stream("/v1/responses", {"model": "localpilot", "input": "audit", "stream": True}))
        data = [frame["data"] for frame in frames]
        standard = [e for e in data if not e["type"].startswith("localpilot.")]
        self.assertEqual([e["sequence_number"] for e in data], list(range(1, len(data) + 1)))
        self.assertEqual([e["type"] for e in standard], ["response.created", "response.in_progress",
            "response.output_item.added", "response.content_part.added", "response.output_text.delta",
            "response.output_text.done", "response.content_part.done", "response.output_item.done", "response.completed"])
        self.assertEqual(standard[-2]["item"], standard[-1]["response"]["output"][0])
        self.record("partial", frames=frames)

    def test_response_sdk_accumulator_and_internal_tool_rounds(self):
        self.backend = fixtures.Backend(fixtures.answer(None, fixtures.call("read_file", {"path": "note.txt"}, "r")), fixtures.answer("fact"))
        with self.sdk.responses.stream(model="localpilot", input="audit") as stream:
            events = list(stream)
            final = stream.get_final_response()
        self.assertEqual([i.type for i in final.output], ["function_call", "message"])
        self.assertEqual(final.output_text, "fact")
        self.assertTrue(final.localpilot["tools"][0]["payload"]["ok"])
        done = [e.item.id for e in events if e.type == "response.output_item.done"]
        self.assertEqual(done, [i.id for i in final.output])
        self.assertEqual(final.usage.total_tokens, 20)
        self.record("extension", events=[e.model_dump(mode="json", exclude_unset=True, warnings=False) for e in events])

    def test_chat_usage_opt_in_wire_contract(self):
        self.backend = fixtures.Backend(*(fixtures.answer("text") for _ in range(3)))
        observed = []
        for options in ({}, {"stream_options": {"include_usage": False}}, {"stream_options": {"include_usage": True}}):
            frames = list(self.client.stream("/v1/chat/completions", {"model": "localpilot",
                "messages": [{"role": "user", "content": "audit"}], "stream": True, **options}))
            observed.append({"options": options, "frames": frames})
        self.record("fully_compatible_subset", streams=observed)
        for stream in observed[:2]:
            self.assertTrue(all(f["data"].get("usage") is None for f in stream["frames"]))
        data = [f["data"] for f in observed[2]["frames"]]
        self.assertEqual(data[-1]["choices"], [])
        self.assertEqual(data[-1]["usage"]["total_tokens"], 10)
        self.assertEqual(data[-2]["choices"][0]["finish_reason"], "stop")
        self.assertTrue(all("usage" in c and c["usage"] is None for c in data[:-1]))

    def test_chat_sdk_accumulator_includes_usage(self):
        with self.sdk.chat.completions.stream(model="localpilot", messages=[{"role": "user", "content": "audit"}],
                stream_options={"include_usage": True}) as stream:
            events = list(stream)
            final = stream.get_final_completion()
        self.assertEqual(final.choices[0].message.content, "done")
        self.assertEqual(final.choices[0].finish_reason, "stop")
        self.assertEqual(final.usage.total_tokens, 10)
        self.record("fully_compatible_subset", event_types=[e.type for e in events])

    def test_unknown_usage_is_null(self):
        self.backend = fixtures.Backend(BackendResponse(Message("assistant", "unknown")))
        response = self.create()
        self.assertIsNone(response.usage)
        self.record("partial", response=response.model_dump(mode="json", exclude_unset=True, warnings=False))

    def test_chat_raw_sse_done_exactly_once_and_last(self):
        response = self.sdk._client.post(self.url + "/v1/chat/completions",
            headers={"Authorization": "Bearer test-key"}, json={"model": "localpilot",
                "messages": [{"role": "user", "content": "audit"}], "stream": True,
                "stream_options": {"include_usage": True}})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(response.text.count("data: [DONE]"), 1)
        self.assertTrue(response.text.endswith("data: [DONE]\n\n"))
        self.record("fully_compatible_subset", wire=response.text)

    def test_backend_length_maps_failed_and_not_openai_length(self):
        self.backend = fixtures.Backend(BackendResponse(Message("assistant", "truncated"),
            {"prompt_tokens": 7, "completion_tokens": 3}, "script-provider", "length"))
        response = self.create()
        self.assertEqual(response.status, "failed")
        self.assertEqual(response.error.code, "runtime_error")
        self.assertEqual(response.localpilot["tools"], [])
        self.record("partial", response=response.model_dump(mode="json", exclude_unset=True, warnings=False), provider_finish_reason="length")

    def test_unsupported_fields_rejected_before_backend(self):
        rows = []
        fields = {"temperature": 0, "top_p": 1, "tools": [], "tool_choice": "auto", "parallel_tool_calls": False,
                  "reasoning": {"effort": "low"}, "text": {"format": {"type": "json_object"}},
                  "truncation": "auto", "metadata": {"key": "value"}, "store": False}
        for field, value in fields.items():
            with self.subTest(field=field):
                rows.append({"field": field, "error": self.reject("/v1/responses", {"input": "audit", field: value})})
        for field, value in {"max_completion_tokens": 10, "response_format": {"type": "json_object"},
                             "n": 2, "logprobs": True, "tools": []}.items():
            rows.append({"field": field, "error": self.reject("/v1/chat/completions",
                {"messages": [{"role": "user", "content": "audit"}], field: value})})
        self.assertEqual(self.backend.requests, [])
        self.record("unsupported", fields=rows)

    def test_malformed_requests_and_json(self):
        bodies = [{}, {"input": ""}, {"input": None}, {"input": 4}, {"input": []}, {"input": "a", "stream": "true"},
                  {"input": "a", "instructions": []}, {"input": "a", "max_output_tokens": True},
                  {"input": "a", "max_output_tokens": -1}, {"input": "a", "localpilot": {"timeout_seconds": True}},
                  {"input": [{"role": [], "content": "a"}]}, {"input": "a", "localpilot": {"permission_mode": "full-permission"}}]
        rows = []
        for body in bodies:
            with self.subTest(body=body):
                rows.append({"body": body, "error": self.reject("/v1/responses", body)})
        for raw in (b'{invalid', b'[]', b'{"input":NaN}', b'{"input":"\xff"}'):
            response = self.sdk._client.post(self.url + "/v1/responses", content=raw,
                headers={"Authorization": "Bearer test-key", "Content-Type": "application/json"})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.backend.requests, [])
        self.record("partial", requests=rows)

    def test_http_errors_sdk_exceptions(self):
        rows = []
        for request, status in (({"model": "missing"}, 404), ({"temperature": 0}, 400)):
            with self.assertRaises(APIStatusError) as error:
                self.sdk.responses.create(input="audit", **request)
            self.assertEqual(error.exception.status_code, status)
            rows.append({"status": status, "exception": type(error.exception).__name__, "body": error.exception.body})
        with self.assertRaises(APIStatusError) as error:
            self.sdk.with_options(api_key="wrong").models.list()
        self.assertEqual(error.exception.status_code, 401)
        self.service.max_tasks = 1
        self.create()
        with self.assertRaises(APIStatusError) as error:
            self.create()
        self.assertEqual(error.exception.status_code, 429)
        self.record("partial", errors=rows, auth_status=401, capacity_status=429)

    def test_multiturn_head_and_instruction_reset(self):
        self.backend = fixtures.Backend(fixtures.answer("first"), fixtures.answer("second"), fixtures.answer("third"))
        first = self.sdk.responses.create(input="remember pear", instructions="audit-instruction")
        second = self.sdk.responses.create(input="recall", previous_response_id=first.id)
        self.assertEqual(first.conversation.id, second.conversation.id)
        self.assertIn("remember pear", [m.content for m in self.backend.requests[1]["messages"]])
        self.assertNotIn("audit-instruction", self.backend.requests[1]["messages"][0].content)
        self.assertEqual(self.sdk.responses.retrieve(first.id).output_text, "first")
        self.reject("/v1/responses", {"input": "fork", "previous_response_id": first.id}, 409)
        third = self.sdk.responses.create(input="third", conversation={"id": first.conversation.id})
        self.assertEqual(third.conversation.id, first.conversation.id)
        self.record("partial", responses=[first.model_dump(mode="json", exclude_unset=True, warnings=False), second.model_dump(mode="json", exclude_unset=True, warnings=False), third.model_dump(mode="json", exclude_unset=True, warnings=False)], fork_status=409)

    def test_tool_approval_is_host_extension(self):
        self.patch_backend()
        with self.sdk.responses.stream(model="localpilot", input="write") as stream:
            events = list(stream)
            with self.assertRaises(RuntimeError):
                stream.get_final_response()
        waiting = events[-1].response
        self.assertEqual(waiting.status, "incomplete")
        self.assertEqual(waiting.incomplete_details.reason, "requires_approval")
        self.assertFalse((self.root / "new.txt").exists())
        self.reject("/v1/responses", {"input": [{"type": "function_call_output", "call_id": "call", "output": "approved"}]})
        task = self.task({"id": waiting.id})
        self.client.request(f'/localpilot/v1/tasks/{waiting.id}/approve', {"action_id": task["required_action"]["id"]}, control=True)
        self.task({"id": waiting.id})
        final = self.sdk.responses.retrieve(waiting.id)
        self.assertEqual((self.root / "new.txt").read_text(), "new")
        self.assertEqual(final.status, "completed")
        self.assertEqual(final.usage.total_tokens, 20)
        self.record("extension", waiting=waiting.model_dump(mode="json", exclude_unset=True, warnings=False), final=final.model_dump(mode="json", exclude_unset=True, warnings=False))

    def test_chat_tool_return_cannot_accept_client_result(self):
        self.patch_backend()
        waiting = self.chat()
        self.assertEqual(waiting.choices[0].finish_reason, "tool_calls")
        tool = waiting.choices[0].message.tool_calls[0]
        error = self.reject("/v1/chat/completions", {"messages": [{"role": "tool", "content": "ok", "tool_call_id": tool.id}]})
        self.assertFalse((self.root / "new.txt").exists())
        self.record("extension", completion=waiting.model_dump(mode="json", exclude_unset=True, warnings=False), client_result_error=error)

    def test_human_status_is_not_standard_chat_finish(self):
        self.computer_backend()
        self.mode = "full-permission"
        self.ax.fault = "focus"
        chat = self.chat()
        self.assertIsNone(chat.choices[0].finish_reason)
        self.assertEqual(chat.localpilot["status"], "requires_human")
        self.assertIsNone(chat.localpilot["tools"][-1]["payload"]["result"]["verified"])
        self.record("extension", completion=chat.model_dump(mode="json", exclude_unset=True, warnings=False))

    def test_midstream_failure_preserves_partial_never_completed(self):
        class Broken(fixtures.Backend):
            capabilities = fixtures.StreamBackend.capabilities
            def stream(self, messages, **kwargs):
                yield BackendChunk("text", "partial")
                raise ValueError("audit broken backend")
        self.backend = Broken()
        with self.create(stream=True) as stream:
            events = list(stream)
        final = events[-1].response
        self.assertEqual(events[-1].type, "response.failed")
        self.assertEqual(final.output_text, "partial")
        self.assertEqual(final.output[0].status, "incomplete")
        self.assertEqual(final.localpilot["tools"], [])
        self.assertNotIn("response.completed", [e.type for e in events])
        self.record("partial", events=[e.model_dump(mode="json", exclude_unset=True, warnings=False) for e in events])

    def test_chat_stream_failure_raises_sdk_error(self):
        self.backend = fixtures.Backend(ValueError("audit failed backend"))
        with self.assertRaises(openai.APIError) as error:
            with self.chat(stream=True) as stream:
                list(stream)
        self.record("partial", exception=type(error.exception).__name__, body=error.exception.body)

    def test_cancel_stream_uses_nonstandard_terminal_event(self):
        self.backend = fixtures.StreamBackend()
        self.releases.append(self.backend.release)
        with self.create(stream=True) as stream:
            events = []
            for event in stream:
                events.append(event)
                if event.type == "response.created":
                    task_id = event.response.id
                if event.type == "response.output_text.delta":
                    cancelling = self.sdk.responses.cancel(task_id)
                    self.assertEqual(cancelling.status, "in_progress")
                    self.assertFalse(cancelling.localpilot["quiescent"])
                    self.backend.release.set()
                    break
            events.extend(stream)
        self.assertEqual(events[-1].type, "response.cancelled")
        # Unknown event discriminators are permissively parsed by SDK 2.29;
        # nested response remains a dict, unlike official typed events.
        self.assertIsInstance(events[-1].response, dict)
        self.assertEqual(events[-1].response["status"], "cancelled")
        self.assertNotIn("response.completed", [e.type for e in events])
        self.record("extension", events=[e.model_dump(mode="json", exclude_unset=True, warnings=False) for e in events])

    def test_deadline_is_cooperative_and_uses_extension_reason(self):
        self.backend = fixtures.StreamBackend()
        self.releases.append(self.backend.release)
        initial = self.create(background=True, extra_body={"localpilot": {"timeout_seconds": 0.05}})
        self.assertTrue(self.backend.first.wait(2))
        with self.service.condition:
            self.assertTrue(self.service.condition.wait_for(lambda: self.service.task_snapshot(initial.id)["status"] == "cancelling", 2))
        self.assertFalse(self.sdk.responses.retrieve(initial.id).localpilot["quiescent"])
        self.backend.release.set()
        self.task({"id": initial.id})
        final = self.sdk.responses.retrieve(initial.id)
        self.assertEqual(final.status, "incomplete")
        self.assertEqual(final.incomplete_details.reason, "timed_out")
        self.assertEqual(final.output_text, "hello ")
        self.record("extension", final=final.model_dump(mode="json", exclude_unset=True, warnings=False))

    def test_client_timeout_detaches_without_retry_or_server_cancel(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        def block(messages):
            entered.set()
            release.wait(3)
            return fixtures.answer("late")
        self.backend = fixtures.Backend(block)
        with self.assertRaises(APITimeoutError):
            self.sdk.with_options(timeout=0.05).responses.create(input="timeout")
        self.assertTrue(entered.wait(2))
        task_id = next(iter(self.service.tasks))
        self.assertEqual(self.service.task_snapshot(task_id)["status"], "running")
        release.set()
        self.task({"id": task_id})
        self.assertEqual(len(self.backend.requests), 1)
        self.record("extension", final=self.sdk.responses.retrieve(task_id).model_dump(mode="json", exclude_unset=True, warnings=False), task_id_obtained="host fixture, not SDK timeout response")

    def test_disconnect_retrieve_native_reconnect_and_openai_replay_gap(self):
        self.backend = fixtures.StreamBackend()
        self.releases.append(self.backend.release)
        with self.create(stream=True) as stream:
            for event in stream:
                if event.type == "response.created":
                    task_id = event.response.id
                if event.type == "response.output_text.delta":
                    break
        self.assertEqual(self.sdk.responses.retrieve(task_id).status, "in_progress")
        self.backend.release.set()
        self.task({"id": task_id})
        final = self.sdk.responses.retrieve(task_id)
        self.assertEqual(final.output_text, "hello 世界")
        frames = list(self.client.stream(f'/localpilot/v1/tasks/{task_id}/events'))
        cursor = frames[-2]["data"]["sequence"]
        replay = list(self.client.stream(f'/localpilot/v1/tasks/{task_id}/events', last_event_id=cursor))
        self.assertEqual([f["data"]["sequence"] for f in replay], [frames[-1]["data"]["sequence"]])
        wire = self.sdk._client.get(self.url + f'/v1/responses/{task_id}?stream=true&starting_after=1', headers={"Authorization": "Bearer test-key"})
        self.assertTrue(wire.headers["content-type"].startswith("application/json"))
        self.assertEqual(len(self.backend.requests), 1)
        self.record("partial", final=final.model_dump(mode="json", exclude_unset=True, warnings=False), native_replay=replay, openai_replay_content_type=wire.headers["content-type"])

    def test_retention_gap_stream_error_shape(self):
        self.service.max_events = 1
        frames = list(self.client.stream("/v1/responses", {"input": "audit", "stream": True}))
        self.assertEqual(frames[-1]["event"], "error")
        error = frames[-1]["data"]
        self.assertEqual(error["error"]["code"], "event_history_expired")
        self.assertNotIn("type", error)
        self.assertNotIn("response.completed", [f["event"] for f in frames])
        self.record("partial", frames=frames)

    def test_independent_sessions_and_same_session_busy(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        def block(messages):
            entered.set()
            release.wait(3)
            return fixtures.answer("first")
        self.backend = fixtures.Backend(block, fixtures.answer("second"))
        first = self.sdk.responses.create(input="private-first", background=True)
        self.assertTrue(entered.wait(2))
        self.reject("/v1/responses", {"input": "busy", "previous_response_id": first.id}, 409)
        with ThreadPoolExecutor(max_workers=1) as pool:
            second = pool.submit(self.sdk.responses.create, input="private-second").result(timeout=2)
        self.assertEqual(second.status, "completed")
        self.assertNotEqual(first.conversation.id, second.conversation.id)
        self.assertNotIn("private-first", [m.content for m in self.backend.requests[1]["messages"]])
        release.set()
        self.task({"id": first.id})
        self.record("partial", sessions=[first.conversation.id, second.conversation.id], same_session_status=409)

    def test_eight_concurrent_sessions_preserve_private_context(self):
        barrier = threading.Barrier(8, timeout=3)
        entered = Queue()
        class Concurrent(fixtures.Backend):
            def request(self, messages, **kwargs):
                user = [m.content for m in messages if m.role == "user"]
                self.requests.append(user)
                entered.put(user[-1])
                barrier.wait()
                return fixtures.answer(user[-1])
        self.backend = Concurrent()
        markers = [f"private-session-{i}" for i in range(8)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            pending = []
            # Confirm each TCP request has entered Runtime before adding the
            # next. All eight model requests still overlap at the barrier.
            # This oracle measures session isolation, not accept-backlog load.
            for marker in markers:
                pending.append(pool.submit(self.sdk.responses.create, input=marker))
                self.assertEqual(entered.get(timeout=2), marker)
            responses = [future.result(timeout=5) for future in pending]
        self.assertEqual([r.output_text for r in responses], markers)
        self.assertEqual(len({r.conversation.id for r in responses}), 8)
        # Runtime legitimately injects its own working-state user message.
        # Check marker isolation across the full view, not a one-message shape.
        observed = sorted(sorted(marker for marker in markers if marker in "\n".join(context))
                          for context in self.backend.requests)
        self.assertEqual(observed, [[marker] for marker in markers])
        self.record("fully_compatible_subset", markers=markers, sessions=[r.conversation.id for r in responses])

    def test_idempotency_key_does_not_deduplicate(self):
        self.backend = fixtures.Backend(fixtures.answer(), fixtures.answer())
        first = self.create(extra_headers={"Idempotency-Key": "audit-same"})
        second = self.create(extra_headers={"Idempotency-Key": "audit-same"})
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(self.backend.requests), 2)
        self.record("unsupported", ids=[first.id, second.id], note="Do not auto-retry mutating tasks after ambiguous transport failures")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="New evidence JSON; refuses overwrite")
    args = parser.parse_args()
    if args.output and Path(args.output).exists():
        parser.error("output already exists")
    CompatibilityAudit.observations = []
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CompatibilityAudit))
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        report = {"evidence_kind": "scripted-tested", "sdk_version": openai.__version__ if OpenAI else None,
            "tests_run": result.testsRun, "skipped": len(result.skipped),
            "failures": [(test.id(), detail) for test, detail in result.failures + result.errors],
            "observations": CompatibilityAudit.observations,
            "limits": "Passing gap observations are not compatibility passes. No real model or native AX was run."}
        with target.open("x") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
