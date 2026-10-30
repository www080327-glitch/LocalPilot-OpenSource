"""Official SDK over real HTTP/Session/Gateway; scripted backend and AX.

Install requirements-validation.txt in a separate environment to run these.
No cloud credentials, native UI or downloaded models are required.
"""
import json
import threading
import unittest
from urllib.error import HTTPError

try:
    import httpx
    from openai import OpenAI, APIStatusError
except ImportError:
    OpenAI = None

from tests import test_runtime_api as fixtures
from tests.test_runtime_api import Backend, StreamBackend, answer, call
from agent.backends import BackendChunk


@unittest.skipIf(OpenAI is None, "optional official OpenAI SDK is not installed")
class SDKTests(unittest.TestCase):
    # Reuse the same HTTP/AgentSession fixture without inheriting its tests.
    task = fixtures.APITests.task
    patch_backend = fixtures.APITests.patch_backend
    computer_backend = fixtures.APITests.computer_backend

    def setUp(self):
        fixtures.APITests.setUp(self)
        self.sdk = OpenAI(base_url=self.url + "/v1", api_key="test-key", max_retries=0,
                          timeout=5, http_client=httpx.Client(trust_env=False))
        self.releases = []

    def tearDown(self):
        for release in self.releases:
            release.set()
        self.sdk.close()
        fixtures.APITests.tearDown(self)

    def create(self, **kwargs):
        return self.sdk.responses.create(model="localpilot", input="validate", **kwargs)

    def host_action(self, task, action="approve", **kwargs):
        return self.client.request(f'/localpilot/v1/tasks/{task["id"]}/{action}',
            {"action_id": task["required_action"]["id"], **kwargs}, control=True)

    def test_responses_objects_retrieve_and_models(self):
        result = self.create()
        self.assertEqual(result.output_text, "done")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.usage.total_tokens, 10)
        self.assertEqual(self.sdk.responses.retrieve(result.id).model_dump(), result.model_dump())
        self.assertEqual([m.id for m in self.sdk.models.list()], ["alternate", "localpilot"])

    def test_persistent_previous_and_conversation_and_stale_head(self):
        self.backend = Backend(answer("first"), answer("second"), answer("third"))
        first = self.sdk.responses.create(model="localpilot", input="remember kiwi")
        second = self.sdk.responses.create(model="localpilot", input="recall", previous_response_id=first.id)
        third = self.sdk.responses.create(model="localpilot", input="again", conversation=first.conversation.id)
        self.assertEqual(first.conversation.id, second.conversation.id)
        self.assertEqual(second.conversation.id, third.conversation.id)
        self.assertIn("remember kiwi", [m.content for m in self.backend.requests[2]["messages"]])
        self.assertEqual(self.sdk.responses.retrieve(first.id).output_text, "first")
        with self.assertRaises(APIStatusError) as error:
            self.create(previous_response_id=first.id)
        self.assertEqual(error.exception.status_code, 409)

    def test_responses_create_stream_is_incremental(self):
        self.backend = StreamBackend()
        self.releases.append(self.backend.release)
        kinds, parts = [], []
        with self.create(stream=True) as stream:
            for event in stream:
                kinds.append(event.type)
                if event.type == "response.output_text.delta":
                    parts.append(event.delta)
                    if len(parts) == 1:
                        self.assertFalse(self.backend.release.is_set())
                        self.backend.release.set()
        self.assertEqual("".join(parts), "hello 世界")
        self.assertEqual(kinds[-1], "response.completed")

    def test_responses_stream_helper_aggregates(self):
        self.backend = Backend(answer("hello"))
        with self.sdk.responses.stream(model="localpilot", input="validate") as stream:
            events = list(stream)
            result = stream.get_final_response()
        self.assertEqual(result.output_text, "hello")
        self.assertEqual(result.status, "completed")
        self.assertIn("response.output_text.delta", [e.type for e in events])

    def test_stream_helper_tool_items_and_server_execution(self):
        self.backend = Backend(answer(None, call("read_file", {"path": "note.txt"}, "read")), answer("fact"))
        with self.sdk.responses.stream(model="localpilot", input="read note") as stream:
            list(stream)
            result = stream.get_final_response()
        self.assertEqual([i.type for i in result.output], ["function_call", "message"])
        self.assertEqual(json.loads(result.output[0].arguments), {"path": "note.txt"})
        self.assertEqual(result.output_text, "fact")
        self.assertTrue(result.localpilot["tools"][0]["payload"]["ok"])

    def test_chat_objects_stream_and_persistent_extension(self):
        self.backend = Backend(answer("first"), answer("second"))
        first = self.sdk.chat.completions.create(model="localpilot", messages=[{"role": "user", "content": "first"}])
        self.assertEqual(first.choices[0].message.content, "first")
        with self.sdk.chat.completions.create(model="localpilot", messages=[{"role": "user", "content": "second"}],
                stream=True, stream_options={"include_usage": True},
                extra_body={"localpilot": {"session_id": first.localpilot["session_id"]}}) as stream:
            chunks = list(stream)
        self.assertEqual("".join(c.choices[0].delta.content or "" for c in chunks if c.choices), "second")
        self.assertEqual(chunks[-2].choices[0].finish_reason, "stop")
        self.assertEqual(chunks[-1].choices, [])
        self.assertEqual(chunks[-1].usage.total_tokens, 10)
        self.assertEqual(chunks[-2].localpilot["session_id"], first.localpilot["session_id"])

    def test_approval_stream_waiting_auth_stale_and_once(self):
        self.patch_backend()
        with self.sdk.responses.stream(model="localpilot", input="write") as stream:
            events = list(stream)
            # SDK 2.29's accumulator only finalizes completed events. Preserve
            # incomplete/waiting honestly and use its typed terminal event.
            with self.assertRaises(RuntimeError):
                stream.get_final_response()
            waiting = events[-1].response
        self.assertEqual(waiting.status, "incomplete")
        self.assertEqual(waiting.localpilot["status"], "requires_approval")
        self.assertNotIn("response.completed", [e.type for e in events])
        self.assertFalse((self.root / "new.txt").exists())
        task = self.task({"id": waiting.id})
        with self.assertRaises(HTTPError) as error:
            self.client.request(f'/localpilot/v1/tasks/{waiting.id}/approve', {"action_id": task["required_action"]["id"]})
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        self.host_action(task)
        self.task(task)
        final = self.sdk.responses.retrieve(waiting.id)
        self.assertEqual(final.status, "completed")
        self.assertEqual(final.conversation.id, waiting.conversation.id)
        self.assertEqual((self.root / "new.txt").read_text(), "new")
        with self.assertRaises(HTTPError) as error:
            self.host_action(task)
        self.assertEqual(error.exception.code, 409)
        error.exception.close()
        self.assertEqual(len([e for e in self.sessions[0].registry.gateway.audit if e.get("status") == "applied"]), 1)

    def test_reject_has_no_mutation(self):
        self.patch_backend()
        waiting = self.create()
        self.host_action(self.task({"id": waiting.id}), "reject", reason="validation rejection")
        self.task({"id": waiting.id})
        self.assertEqual(self.sdk.responses.retrieve(waiting.id).status, "completed")
        self.assertFalse((self.root / "new.txt").exists())

    def test_human_takeover_resume_same_session_no_old_dispatch(self):
        self.computer_backend()
        waiting = self.create()
        paused = self.client.request(f'/localpilot/v1/tasks/{waiting.id}/computer/takeover', {}, control=True)
        self.assertEqual(paused["status"], "requires_human")
        self.ax.nodes[0]["value"] = "human edit"
        self.host_action(paused, "computer/resume")
        self.task({"id": waiting.id})
        result = self.sdk.responses.retrieve(waiting.id)
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.conversation.id, waiting.conversation.id)
        self.assertEqual(self.ax.sent, 0)
        self.assertIn("human_handoff_invalidated", json.dumps(result.localpilot["tools"]))

    def test_cancel_inflight_sdk_retrieve_closes_session(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        def blocked(messages):
            entered.set()
            release.wait(4)
            return answer(None, call("read_file", {"path": "note.txt"}))
        self.backend = Backend(blocked)
        initial = self.create(background=True)
        self.assertTrue(entered.wait(2))
        cancelling = self.sdk.responses.cancel(initial.id)
        self.assertEqual(cancelling.localpilot["status"], "cancelling")
        self.assertFalse(cancelling.localpilot["quiescent"])
        release.set()
        self.task({"id": initial.id})
        final = self.sdk.responses.retrieve(initial.id)
        self.assertEqual(final.status, "cancelled")
        self.assertEqual(final.localpilot["tools"], [])
        self.assertEqual(self.client.request('/localpilot/v1/sessions/' + initial.conversation.id)["state"], "closed")

    def test_deadline_waiting_approval_never_completed(self):
        self.patch_backend()
        waiting = self.create(extra_body={"localpilot": {"timeout_seconds": 0.1}})
        # wait() returns approval as well; wait for the terminal deadline signal.
        with self.service.condition:
            self.assertTrue(self.service.condition.wait_for(
                lambda: self.service.task_snapshot(waiting.id)["status"] == "timed_out", 2))
        self.task({"id": waiting.id})
        final = self.sdk.responses.retrieve(waiting.id)
        self.assertEqual(final.status, "incomplete")
        self.assertEqual(final.localpilot["status"], "timed_out")
        self.assertFalse((self.root / "new.txt").exists())

    def test_client_disconnect_detaches_and_reconnects(self):
        self.backend = StreamBackend()
        self.releases.append(self.backend.release)
        with self.create(stream=True) as stream:
            for event in stream:
                if event.type == "response.created":
                    task_id = event.response.id
                if event.type == "response.output_text.delta":
                    break
        active = self.sdk.responses.retrieve(task_id)
        self.assertEqual(active.status, "in_progress")
        self.assertFalse(active.localpilot["quiescent"])
        self.backend.release.set()
        self.task({"id": task_id})
        final = self.sdk.responses.retrieve(task_id)
        self.assertEqual(final.status, "completed")
        self.assertEqual(final.output_text, "hello 世界")
        self.assertEqual(len(self.backend.requests), 1)

    def test_backend_failure_stream_no_completed(self):
        self.backend = Backend(ValueError("injected backend failure"))
        with self.create(stream=True) as stream:
            events = list(stream)
        self.assertEqual(events[-1].type, "response.failed")
        self.assertEqual(events[-1].response.status, "failed")
        self.assertNotIn("response.completed", [e.type for e in events])

    def test_ax_failure_stream_no_completed(self):
        self.computer_backend()
        self.mode = "full-permission"
        self.ax.fault = "focus"
        with self.create(stream=True) as stream:
            events = list(stream)
        result = events[-1].response
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.localpilot["status"], "requires_human")
        self.assertIsNone(result.localpilot["tools"][-1]["payload"]["result"]["verified"])
        self.assertNotIn("response.completed", [e.type for e in events])

    def test_backend_partial_stream_failure_preserves_text(self):
        class BrokenStream(Backend):
            capabilities = StreamBackend.capabilities
            def stream(self, messages, **kwargs):
                yield BackendChunk("text", "partial evidence")
                raise ValueError("injected mid-stream failure")
        self.backend = BrokenStream()
        with self.create(stream=True) as stream:
            events = list(stream)
        final = events[-1].response
        self.assertEqual(events[-1].type, "response.failed")
        self.assertEqual(final.status, "failed")
        self.assertEqual(final.output_text, "partial evidence")
        self.assertEqual(final.output[0].status, "incomplete")
        self.assertEqual(final.localpilot["tools"], [])
        self.assertNotIn("response.completed", [e.type for e in events])

    def test_chat_ax_failure_has_null_finish_and_human_extension(self):
        self.computer_backend()
        self.mode = "full-permission"
        self.ax.fault = "focus"
        result = self.sdk.chat.completions.create(model="localpilot", messages=[{"role": "user", "content": "edit"}])
        self.assertIsNone(result.choices[0].finish_reason)
        self.assertEqual(result.localpilot["status"], "requires_human")


if __name__ == "__main__":
    unittest.main()
