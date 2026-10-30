"""Real loopback HTTP/SSE over real AgentSession/Gateway; scripted model/AX only."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import shutil
import subprocess
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agent.backends import BackendCapabilities, BackendChunk, BackendResponse, Message, ModelInfo, ToolCall
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets
from computer.runtime import ComputerRuntime
from localpilot_api.client import Client
from localpilot_api.server import APIServer
from localpilot_api.service import APIError, TaskRequest, TaskService
from tests.test_computer_runtime import APP, MemoryAX, condition


def answer(text="done", *calls):
    return BackendResponse(Message("assistant", text, list(calls)), {"prompt_tokens": 7, "completion_tokens": 3}, "script-provider", "tool_calls" if calls else "stop")


def call(name, args, id="call"):
    return ToolCall(id, name, json.dumps(args))


class Backend:
    is_local = False
    capabilities = BackendCapabilities(supports_tool_calling=True)
    model_info = ModelInfo("script-provider", "scripted", 131072)
    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []
    def request(self, messages, **kwargs):
        self.requests.append({"messages": deepcopy(messages), **kwargs})
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(messages) if callable(step) else step


class StreamBackend(Backend):
    capabilities = BackendCapabilities(supports_tool_calling=True, supports_streaming=True)
    def __init__(self):
        super().__init__()
        self.first = threading.Event()
        self.release = threading.Event()
    def stream(self, messages, **kwargs):
        self.requests.append({"messages": deepcopy(messages), **kwargs})
        yield BackendChunk("text", "hello ")
        self.first.set()
        self.release.wait(3)
        yield BackendChunk("text", "世界")
        yield BackendChunk("response", response=answer("hello 世界"))


class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "note.txt").write_text("fact")
        self.backend = Backend(answer())
        self.mode = "approve-mutations"
        self.budgets = SessionBudgets(max_steps=12)
        self.computer = None
        self.sessions = []
        def factory(callback):
            registry = create_default_registry(self.root, permission_mode=self.mode)
            session = AgentSession(registry, backend=self.backend, policy="cloud-only", event_callback=callback,
                computer_runtime=self.computer, budgets=self.budgets,
                retry_policy=RetryPolicy(max_attempts=1))
            self.sessions.append(session)
            return session
        self.service = TaskService({"localpilot": factory, "alternate": factory})
        self.server = APIServer(("127.0.0.1", 0), self.service, api_key="test-key", control_token="host-key")
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.client = Client(self.url, api_key="test-key", control_token="host-key", timeout=5)

    def tearDown(self):
        self.service.shutdown()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.tmp.cleanup()

    def responses(self, input="hi", **kwargs):
        return self.client.request("/v1/responses", {"model": "localpilot", "input": input, **kwargs})

    def task(self, response):
        return self.service.wait(response["id"])

    def host_action(self, task, action="approve", **kwargs):
        return self.client.request(f'/localpilot/v1/tasks/{task["id"]}/{action}',
            {"action_id": task["required_action"]["id"], **kwargs}, control=True)

    def assert_http(self, status, path, body, **kwargs):
        with self.assertRaises(HTTPError) as error:
            self.client.request(path, body, **kwargs)
        self.assertEqual(error.exception.code, status)
        with error.exception:
            return json.load(error.exception)

    def test_normal_response_model_identity_and_real_usage(self):
        result = self.responses()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["output"][0]["content"][0]["text"], "done")
        self.assertEqual(result["model"], "localpilot")
        self.assertEqual(result["usage"]["total_tokens"], 10)
        self.assertIsNone(result["usage"]["output_tokens_details"]["reasoning_tokens"])
        self.assertEqual(result["localpilot"]["engineering_status"], "unverified")
        models = self.client.request("/v1/models")
        self.assertEqual([m["id"] for m in models["data"]], ["alternate", "localpilot"])

    def test_persistent_previous_response_keeps_context_and_old_snapshot(self):
        self.backend = Backend(answer("first"), answer("second"), answer("third"))
        first = self.responses("remember pear", instructions="Reply briefly")
        second = self.responses("what fruit?", previous_response_id=first["id"])
        self.assertEqual(second["conversation"], first["conversation"])
        context = [m.content for m in self.backend.requests[1]["messages"]]
        self.assertIn("remember pear", context)
        self.assertIn("first", context)
        self.assertNotIn("Reply briefly", self.backend.requests[1]["messages"][0].content)
        snapshot = self.client.request('/v1/responses/' + first["id"])
        self.assertEqual(snapshot, first)
        self.assert_http(409, "/v1/responses", {"input": "stale", "previous_response_id": first["id"]})
        third = self.responses("one more", conversation=first["conversation"])
        self.assertEqual(third["status"], "completed")

    def test_native_session_task_and_reconnect_events(self):
        session = self.client.request("/localpilot/v1/sessions", {"model": "localpilot"})
        task = self.client.request("/localpilot/v1/tasks", {"session_id": session["id"], "input": "native task"})
        done = self.task(task)
        self.assertEqual(done["status"], "completed")
        frames = list(self.client.stream(f'/localpilot/v1/tasks/{task["id"]}/events'))
        sequences = [frame["data"]["sequence"] for frame in frames]
        self.assertEqual(sequences, sorted(set(sequences)))
        resumed = list(self.client.stream(f'/localpilot/v1/tasks/{task["id"]}/events', last_event_id=sequences[-2]))
        self.assertEqual([f["data"]["sequence"] for f in resumed], sequences[-1:])
        closed = self.client.request("/localpilot/v1/sessions/" + session["id"], method="DELETE")
        self.assertEqual(closed["state"], "closed")
        self.assert_http(409, "/localpilot/v1/tasks", {"session_id": session["id"], "input": "closed"})

    def test_responses_sse_is_incremental_before_backend_finishes(self):
        self.backend = StreamBackend()
        frames = self.client.stream("/v1/responses", {"model": "localpilot", "input": "stream", "stream": True})
        collected = []
        for frame in frames:
            collected.append(frame)
            if frame["event"] == "response.output_text.delta":
                self.assertEqual(frame["data"]["delta"], "hello ")
                self.assertFalse(self.backend.release.is_set())
                self.backend.release.set()
                break
        collected.extend(frames)
        types = [f["event"] for f in collected]
        self.assertEqual(types[:2], ["response.created", "response.in_progress"])
        self.assertEqual(types[-1], "response.completed")
        self.assertEqual("".join(f["data"]["delta"] for f in collected if f["event"] == "response.output_text.delta"), "hello 世界")
        self.assertEqual(collected[-1]["data"]["response"]["output"][0]["id"],
                         next(f["data"]["item"]["id"] for f in collected if f["event"] == "response.output_item.added"))

    def test_chat_stateless_history_and_persistent_stream(self):
        self.backend = Backend(answer("first"), answer("second"))
        first = self.client.request("/v1/chat/completions", {"messages": [
            {"role": "system", "content": "brief"}, {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old reply"}, {"role": "user", "content": "new"}]})
        self.assertEqual(first["choices"][0]["message"]["content"], "first")
        self.assertEqual(first["choices"][0]["finish_reason"], "stop")
        self.assertIn("old reply", [m.content for m in self.backend.requests[0]["messages"]])
        frames = list(self.client.stream("/v1/chat/completions", {"messages": [{"role": "user", "content": "again"}],
            "localpilot": {"session_id": first["localpilot"]["session_id"]}, "stream": True}))
        self.assertEqual("".join(f["data"]["choices"][0]["delta"].get("content", "") for f in frames), "second")
        self.assertEqual(frames[-1]["data"]["choices"][0]["finish_reason"], "stop")
        self.assert_http(400, "/v1/chat/completions", {"messages": [{"role": "assistant", "content": "replay"}, {"role": "user", "content": "again"}],
            "localpilot": {"session_id": first["localpilot"]["session_id"]}})

    def test_tool_use_and_goals_through_same_registry(self):
        self.backend = Backend(answer(None, call("manage_goal", {"action": "create", "description": "Inspect fact"}, "goal")),
            answer(None, call("read_file", {"path": "note.txt"}, "read")), answer("fact checked"))
        result = self.responses("inspect")
        self.assertEqual(result["status"], "completed")
        self.assertEqual([t["name"] for t in result["localpilot"]["tools"]], ["manage_goal", "read_file"])
        self.assertEqual(len(result["localpilot"]["goals"]), 1)
        self.assertTrue(result["localpilot"]["tools"][-1]["payload"]["ok"])
        self.assertEqual(len(self.sessions), 1)
        self.assertIn("fact", self.backend.requests[-1]["messages"][-1].content)

    def patch_backend(self):
        self.backend = Backend(answer(None, call("apply_patch", {"changes": [{"path": "new.txt", "operation": "create", "content": "new"}]}, "write")), answer("written"))

    def test_approval_is_explicit_authenticated_and_executes_once(self):
        self.patch_backend()
        result = self.responses("write")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["localpilot"]["status"], "requires_approval")
        self.assertFalse((self.root / "new.txt").exists())
        task = self.task(result)
        self.assert_http(403, f'/localpilot/v1/tasks/{task["id"]}/approve', {"action_id": task["required_action"]["id"]})
        self.assert_http(409, f'/localpilot/v1/tasks/{task["id"]}/approve', {"action_id": "stale"}, control=True)
        self.assert_http(409, "/v1/responses", {"input": "new turn", "previous_response_id": result["id"]})
        self.host_action(task)
        done = self.task(result)
        self.assertEqual(done["status"], "completed")
        self.assertEqual((self.root / "new.txt").read_text(), "new")
        self.assertEqual(len([e for e in self.sessions[0].registry.gateway.audit if e.get("status") == "applied"]), 1)
        self.assert_http(409, f'/localpilot/v1/tasks/{task["id"]}/approve', {"action_id": task["required_action"]["id"]}, control=True)

    def test_streaming_tool_arguments_are_actual_and_approval_has_no_completed_event(self):
        self.patch_backend()
        frames = list(self.client.stream("/v1/responses", {"input": "write", "stream": True}))
        kinds = [f["event"] for f in frames]
        self.assertIn("localpilot.requires_approval", kinds)
        self.assertEqual(kinds[-1], "response.incomplete")
        self.assertNotIn("response.completed", kinds)
        arguments = next(f["data"]["arguments"] for f in frames if f["event"] == "response.function_call_arguments.done")
        self.assertEqual(json.loads(arguments)["changes"][0]["content"], "new")
        streamed = next(f["data"]["item"] for f in frames if f["event"] == "response.output_item.done")
        final = frames[-1]["data"]["response"]["output"][0]
        self.assertEqual(streamed, final)

    def test_chat_approval_returns_pending_tool_call(self):
        self.patch_backend()
        result = self.client.request("/v1/chat/completions", {"messages": [{"role": "user", "content": "write"}]})
        choice = result["choices"][0]
        self.assertEqual(choice["finish_reason"], "tool_calls")
        self.assertEqual(choice["message"]["tool_calls"][0]["function"]["name"], "apply_patch")
        self.assertEqual(result["localpilot"]["status"], "requires_approval")

    def test_reject_never_executes_patch(self):
        self.patch_backend()
        task = self.task(self.responses("write"))
        self.host_action(task, "reject", reason="No write")
        done = self.task(task)
        self.assertEqual(done["status"], "completed")
        self.assertFalse((self.root / "new.txt").exists())
        self.assertFalse(done["tools"][0]["payload"]["ok"])

    def computer_backend(self):
        self.ax = MemoryAX()
        self.computer = ComputerRuntime(self.ax, allowed_apps=[APP], verification_timeout=0)
        def dynamic(messages):
            tree = json.loads(next(m.content for m in reversed(messages) if m.role == "tool"))["result"]
            return answer(None, call("set_value", {"app": APP, "element": "input", "observation": tree["observation"],
                "value": "new", "postcondition": condition()}, "write"))
        self.backend = Backend(answer(None, call("inspect_tree", {"app": APP}, "observe")), dynamic, answer("done"))

    def test_computer_approval_takeover_and_resume_invalidates_old_write(self):
        self.computer_backend()
        task = self.task(self.responses("edit AX"))
        self.assertEqual(task["status"], "requires_approval")
        self.assertEqual(self.ax.sent, 0)
        paused = self.client.request(f'/localpilot/v1/tasks/{task["id"]}/computer/takeover', {}, control=True)
        self.assertEqual(paused["status"], "requires_human")
        self.assertTrue(paused["quiescent"])
        self.ax.nodes[0]["value"] = "human"
        self.assert_http(409, f'/localpilot/v1/tasks/{task["id"]}/approve', {"action_id": task["required_action"]["id"]}, control=True)
        self.host_action(paused, "computer/resume")
        done = self.task(task)
        self.assertEqual(done["status"], "incomplete")
        self.assertEqual(self.ax.sent, 0)
        self.assertIn("human_handoff_invalidated", json.dumps(done["tools"]))

    def test_reused_call_id_in_new_turn_cannot_rebind_old_failed_intent(self):
        self.computer_backend()
        self.mode = 'full-permission'
        self.backend.steps = [answer(None, call('set_value', {'app': APP, 'element': 'input',
            'observation': 'stale', 'value': 'original', 'postcondition': condition(value='original')}, 'same-id')), answer()]
        task = self.task(self.responses('write original'))
        self.assertEqual(task['status'], 'requires_human')
        def unrelated(messages):
            token = self.computer.observations[APP]['token']
            return answer(None, call('set_value', {'app': APP, 'element': 'input', 'observation': token,
                'value': 'unrelated', 'postcondition': condition(value='unrelated')}, 'same-id'))
        self.backend.steps = [unrelated, answer()]
        self.host_action(task, 'computer/resume')
        done = self.task(task)
        self.assertEqual(done['status'], 'requires_human')
        self.assertEqual(self.ax.nodes[0]['value'], 'unrelated')
        writes = [r for r in done['tools'] if r['name'] == 'set_value']
        self.assertEqual([r['turn_id'] for r in writes], [1, 2])
        self.assertEqual([json.loads(r['arguments'])['value'] for r in writes], ['original', 'unrelated'])

    def test_unstructured_mutation_failure_cannot_be_completed_by_model(self):
        self.computer_backend()
        self.mode = 'full-permission'
        self.backend.steps = [answer(None, call('set_value', {'bad': 'arguments'}, 'bad-write')), answer()]
        task = self.task(self.responses('write'))
        self.assertEqual(task['status'], 'requires_human')
        self.assertEqual(self.ax.sent, 0)

    def test_shutdown_waits_for_inflight_receipt_and_closes_session(self):
        self.computer_backend()
        self.mode = 'full-permission'
        entered, release = threading.Event(), threading.Event()
        action = self.ax.action
        def blocked(*args, **kwargs):
            entered.set()
            release.wait(3)
            return action(*args, **kwargs)
        self.ax.action = blocked
        task = self.responses('write', background=True)
        self.assertTrue(entered.wait(2))
        result = self.service.shutdown(timeout=0)
        self.assertFalse(result['quiescent'])
        self.assertEqual(self.service.task_snapshot(task['id'])['status'], 'cancelling')
        finished = threading.Event()
        shutdown_results = []
        def drain():
            shutdown_results.append(self.service.shutdown())
            finished.set()
        worker = threading.Thread(target=drain)
        worker.start()
        self.assertFalse(finished.wait(.05))
        release.set()
        worker.join(3)
        self.assertTrue(finished.is_set())
        self.assertTrue(shutdown_results[0]['quiescent'])
        done = self.task(task)
        self.assertEqual(done['status'], 'cancelled')
        self.assertTrue(done['tools'][-1]['payload']['result']['action_sent'])
        self.assertTrue(self.service.sessions[done['session_id']].closed)

    def test_handoff_replanned_write_has_new_approval_and_verified_completion(self):
        self.computer_backend()
        def fresh(messages):
            tree = json.loads(next(m.content for m in reversed(messages) if m.role == "tool"))["result"]
            return answer(None, call("set_value", {"app": APP, "element": "input", "observation": tree["observation"],
                "value": "new", "postcondition": condition()}, "fresh-write"))
        self.backend.steps[-1:] = [answer(None, call("inspect_tree", {"app": APP}, "reobserve")), fresh, answer("verified done")]
        initial = self.task(self.responses("edit AX"))
        paused = self.client.request(f'/localpilot/v1/tasks/{initial["id"]}/computer/takeover', {}, control=True)
        self.ax.nodes[0]["value"] = "human change"
        self.host_action(paused, "computer/resume")
        replanned = self.task(initial)
        self.assertEqual(replanned["status"], "requires_approval")
        self.assertNotEqual(replanned["required_action"]["id"], initial["required_action"]["id"])
        self.assertEqual(self.ax.sent, 0)
        self.host_action(replanned, "approve")
        done = self.task(initial)
        self.assertEqual(done["status"], "completed")
        self.assertEqual(self.ax.sent, 1)
        self.assertTrue(done["tools"][-1]["payload"]["result"]["verified"])

    def test_repeated_handoff_can_complete_one_verified_write_without_budget_reset(self):
        self.computer_backend()
        self.budgets = SessionBudgets(max_steps=16, max_token_units=1048576)
        self.backend.model_info = ModelInfo("script-provider", "scripted", 65536)
        def write(id):
            def step(messages):
                result = json.loads(next(m.content for m in reversed(messages) if m.role == "tool"))["result"]
                return answer(None, call("set_value", {"app": APP, "element": "input", "observation": result["observation"],
                    "value": "new", "postcondition": condition()}, id))
            return step
        reads = [answer("Read explanation. " * 600, call("inspect_tree", {"app": APP}, "read-" + str(i))) for i in range(2)]
        self.backend.steps[-1:] = [reads[0], write("new-1"), reads[1], write("new-2"), answer("verified done")]
        task = self.task(self.responses("Edit fixture. " + "Known task context. " * 35))
        tickets = []
        attempts = self.sessions[0]._attempts
        for _ in range(2):
            tickets.append(task["required_action"]["id"])
            paused = self.client.request(f'/localpilot/v1/tasks/{task["id"]}/computer/takeover', {}, control=True)
            self.ax.nodes[0]["value"] = "human change"
            self.host_action(paused, "computer/resume")
            task = self.task(task)
            self.assertEqual(task["status"], "requires_approval")
            self.assertGreater(self.sessions[0]._attempts, attempts)
            attempts = self.sessions[0]._attempts
            self.assertEqual(self.ax.sent, 0)
        for ticket in tickets:
            self.assert_http(409, f'/localpilot/v1/tasks/{task["id"]}/approve', {"action_id": ticket}, control=True)
        self.host_action(task, "approve")
        done = self.task(task)
        self.assertEqual(done["status"], "completed")
        self.assertEqual(self.ax.sent, 1)
        self.assertTrue(done["tools"][-1]["payload"]["result"]["verified"])
        self.assertEqual(self.sessions[0].budgets, self.budgets)

    def test_computer_interference_preserves_partial_receipt_and_sse_human_state(self):
        self.computer_backend()
        self.mode = "full-permission"
        self.ax.fault = "focus"
        frames = list(self.client.stream("/v1/responses", {"input": "edit AX", "stream": True}))
        self.assertNotIn("response.completed", [f["event"] for f in frames])
        result = frames[-1]["data"]["response"]
        self.assertEqual(result["localpilot"]["status"], "requires_human")
        receipt = result["localpilot"]["tools"][-1]
        self.assertEqual(receipt["side_effect_status"], "partial")
        self.assertTrue(receipt["payload"]["result"]["action_sent"])
        self.assertIsNone(receipt["payload"]["result"]["verified"])
        self.host_action(self.task(result), "computer/resume")
        self.assertEqual(self.task(result)["status"], "requires_human")
        self.assertEqual(self.ax.sent, 1)
        self.backend.steps[:] = [answer(None, call("verify", {"app": APP, "postcondition": condition()}, "verify-after-resume")), answer("verified done")]
        self.host_action(self.task(result), "computer/resume")
        self.assertEqual(self.task(result)["status"], "completed")
        self.assertEqual(self.ax.sent, 1)

    def test_computer_locked_and_failed_resume_stay_human(self):
        self.computer_backend()
        self.mode = "full-permission"
        self.ax.env["locked"] = True
        task = self.task(self.responses("inspect AX"))
        self.assertEqual(task["status"], "requires_human")
        self.host_action(task, "computer/resume")
        paused = self.task(task)
        self.assertEqual(paused["status"], "requires_human")
        self.assertEqual(self.ax.sent, 0)

    def test_takeover_reports_human_state_while_model_is_still_inflight(self):
        self.computer_backend()
        entered, release = threading.Event(), threading.Event()
        def blocked(messages):
            entered.set()
            release.wait(3)
            return answer("model says done")
        self.backend = Backend(blocked, answer("human restored"))
        initial = self.responses("inspect", background=True)
        self.assertTrue(entered.wait(2))
        paused = self.client.request(f'/localpilot/v1/tasks/{initial["id"]}/computer/takeover', {}, control=True)
        self.assertEqual(paused["status"], "requires_human")
        self.assertFalse(paused["quiescent"])
        self.assertEqual(paused["computer"]["state"], "human_controlling")
        self.assert_http(409, f'/localpilot/v1/tasks/{initial["id"]}/computer/resume', {"action_id": paused["required_action"]["id"]}, control=True)
        release.set()
        ready = self.task(initial)
        self.assertEqual(ready["status"], "requires_human")
        self.host_action(ready, "computer/resume")
        self.assertEqual(self.task(initial)["status"], "completed")

    def test_computer_fallback_does_not_accept_model_completion_as_success(self):
        self.computer_backend()
        self.mode = "full-permission"
        self.computer.background_safe_apps = frozenset()
        result = self.responses("edit AX")
        task = self.task(result)
        self.assertEqual(task["status"], "requires_human")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(self.ax.sent, 0)
        self.backend.steps.append(answer("human completed task"))
        self.host_action(task, "computer/resume")
        self.assertEqual(self.task(result)["status"], "requires_human")
        resumed = self.client.request("/v1/responses/" + result["id"])
        self.assertEqual(resumed["usage"]["total_tokens"], 40)

    def test_unresolved_stale_ax_write_cannot_be_completed_by_model(self):
        self.computer_backend()
        self.computer.observation_ttl = 0
        self.mode = "full-permission"
        result = self.responses("edit stale AX")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["localpilot"]["status"], "requires_human")
        self.assertEqual(result["localpilot"]["required_action"]["reason"]["error"], "stale_observation")
        self.assertEqual(self.ax.sent, 0)

    def test_verified_retry_of_same_ax_postcondition_resolves_error(self):
        self.computer_backend()
        self.mode = "full-permission"
        def write(messages, stale=False):
            tree = json.loads(next(m.content for m in reversed(messages) if m.role == "tool"))["result"]
            return answer(None, call("set_value", {"app": APP, "element": "input", "observation": "stale" if stale else tree["observation"],
                "value": "new", "postcondition": condition()}, "stale" if stale else "fresh"))
        self.backend = Backend(answer(None, call("inspect_tree", {"app": APP}, "observe1")),
            lambda messages: write(messages, True), answer(None, call("inspect_tree", {"app": APP}, "observe2")),
            write, answer("verified done"))
        result = self.responses("retry with fresh AX")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.ax.sent, 1)
        self.assertTrue(result["localpilot"]["tools"][-1]["payload"]["result"]["verified"])

    def test_false_verify_after_explicit_ax_rejection_is_expected(self):
        self.computer_backend()
        self.backend.steps[-1:] = [answer(None, call("verify", {"app": APP, "postcondition": condition()}, "verify-rejected")),
                                  answer("write was rejected; value is unchanged")]
        task = self.task(self.responses("reject AX"))
        self.host_action(task, "reject")
        done = self.task(task)
        self.assertEqual(done["status"], "completed")
        self.assertEqual(self.ax.sent, 0)
        self.assertFalse(done["tools"][-1]["payload"]["result"]["verified"])

    def test_runtime_error_and_stream_error_are_failed(self):
        self.backend = Backend(ValueError("script failure"), ValueError("stream failure"))
        first = self.responses("fail")
        self.assertEqual(first["status"], "failed")
        self.assertEqual(first["error"]["code"], "runtime_error")
        frames = list(self.client.stream("/v1/responses", {"input": "fail", "stream": True}))
        self.assertEqual(frames[-1]["event"], "response.failed")
        self.assertNotIn("response.completed", [f["event"] for f in frames])

    def test_runtime_finalization_with_incomplete_deliverable_is_not_completed(self):
        class StagnatingBackend(Backend):
            def request(self, messages, **kwargs):
                if not kwargs.get("tools"):
                    return answer("Unfinished work at the finalization boundary")
                return answer(None, call("read_file", {"path": "note.txt"}, str(len(messages))))
        self.backend = StagnatingBackend()
        result = self.responses("read repeatedly")
        self.assertEqual(result["localpilot"]["status"], "incomplete")
        self.assertEqual(result["status"], "incomplete")
        task = self.task(result)
        self.assertEqual(task["result"]["runtime_status"], "completed")
        self.assertEqual(task["result"]["deliverable_status"], "incomplete")
        self.assertEqual(task["result"]["runtime_metrics"]["finalization_reason"], "stagnation")

    def test_cancel_is_cooperative_no_next_tool_and_closes_session(self):
        entered, release = threading.Event(), threading.Event()
        def blocked(messages):
            entered.set()
            release.wait(3)
            return answer(None, call("apply_patch", {"changes": [{"path": "cancelled.txt", "operation": "create", "content": "bad"}]}))
        self.mode = "full-permission"
        self.backend = Backend(blocked)
        task = self.responses("cancel", background=True)
        self.assertTrue(entered.wait(2))
        cancelling = self.client.request(f'/v1/responses/{task["id"]}/cancel', {})
        self.assertEqual(cancelling["localpilot"]["status"], "cancelling")
        self.assertFalse(cancelling["localpilot"]["quiescent"])
        release.set()
        done = self.task(task)
        self.assertEqual(done["status"], "cancelled")
        self.assertTrue(done["quiescent"])
        self.assertFalse((self.root / "cancelled.txt").exists())
        self.assertEqual(len(self.backend.requests), 1)
        self.assert_http(409, "/v1/responses", {"input": "continue", "previous_response_id": task["id"]})
        self.assertEqual(self.client.request(f'/v1/responses/{task["id"]}/cancel', {})["status"], "cancelled")

    def test_cancel_pending_approval(self):
        self.patch_backend()
        task = self.task(self.responses("write"))
        self.client.request(f'/localpilot/v1/tasks/{task["id"]}/cancel', {})
        self.assertEqual(self.task(task)["status"], "cancelled")
        self.assertFalse((self.root / "new.txt").exists())
        self.assertEqual(len(self.backend.requests), 1)

    def test_cancel_after_inflight_tool_keeps_receipt(self):
        entered, release = threading.Event(), threading.Event()
        self.mode = "full-permission"
        self.backend = Backend(answer(None, call("read_file", {"path": "note.txt"})), answer("should not request"))
        session = self.client.request("/localpilot/v1/sessions", {})
        registry = self.sessions[0].registry
        original = registry._tools["read_file"]
        def blocked(*, workspace_root, path, **kwargs):
            entered.set()
            release.wait(3)
            return original(workspace_root=workspace_root, path=path, **kwargs)
        registry._tools["read_file"] = blocked
        task = self.client.request("/localpilot/v1/tasks", {"session_id": session["id"], "input": "inspect"})
        self.assertTrue(entered.wait(2))
        self.client.request(f'/localpilot/v1/tasks/{task["id"]}/cancel', {})
        release.set()
        done = self.task(task)
        self.assertEqual(done["status"], "cancelled")
        self.assertEqual(len(done["tools"]), 1)
        self.assertEqual(len(self.backend.requests), 1)

    def test_deadline_includes_waiting_for_approval(self):
        self.patch_backend()
        result = self.responses("write", localpilot={"timeout_seconds": 0.1})
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            task = self.service.task_snapshot(result["id"])
            if task["status"] == "timed_out" and task["quiescent"]:
                break
            time.sleep(0.01)
        self.assertEqual(task["status"], "timed_out")
        self.assertFalse((self.root / "new.txt").exists())

    def test_stream_timeout_stops_future_chunks(self):
        self.backend = StreamBackend()
        task = self.responses("slow", background=True, localpilot={"timeout_seconds": 0.05})
        self.assertTrue(self.backend.first.wait(2))
        time.sleep(0.08)
        self.assertEqual(self.service.task_snapshot(task["id"])["status"], "cancelling")
        self.backend.release.set()
        self.assertEqual(self.task(task)["status"], "timed_out")
        events, _ = self.service.events(task["id"], wait_seconds=0)
        text = [e["data"]["data"]["text"] for e in events if e["type"] == "runtime.event" and e["data"]["type"] == "TextDelta"]
        self.assertEqual(text, ["hello "])

    def test_session_busy_route_conflict_and_unknown_route(self):
        self.patch_backend()
        task = self.task(self.responses("write"))
        self.assert_http(409, "/localpilot/v1/tasks", {"session_id": task["session_id"], "input": "concurrent"})
        self.assert_http(409, "/localpilot/v1/tasks", {"model": "alternate", "session_id": task["session_id"], "input": "route"})
        self.assert_http(404, "/v1/responses", {"model": "backend-provider-name", "input": "hi"})

    def test_input_validation_and_no_host_policy_injection(self):
        for body in ({"input": ""}, {"input": "hi", "stream": "yes"}, {"input": "hi", "tools": []},
                     {"input": [{"type": "function_call_output", "call_id": "fake", "output": "approve"}]},
                     {"input": "hi", "localpilot": {"permission_mode": "full-permission"}},
                     {"input": "hi", "localpilot": {"timeout_seconds": True}}, {"input": "hi", "max_output_tokens": 99999},
                     {"input": "hi", "store": False}):
            self.assert_http(400, "/v1/responses", body)
        self.assertEqual(self.backend.requests, [])

    def test_auth_origin_and_bad_json(self):
        for headers, status in (({}, 401), ({"Authorization": "Bearer test-key", "Origin": "http://evil.test"}, 403)):
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(self.url + "/v1/models", headers=headers), timeout=2)
            self.assertEqual(error.exception.code, status)
            error.exception.close()
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.url + "/v1/responses", data=b'{invalid', headers={"Authorization": "Bearer test-key", "Content-Type": "application/json"}), timeout=2)
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_usage_unknown_remains_null(self):
        self.backend = Backend(BackendResponse(Message("assistant", "unknown usage")))
        self.assertIsNone(self.responses()["usage"])

    def test_partial_stream_failure_reports_failed_and_never_executes_tools(self):
        class BrokenStream(Backend):
            capabilities = StreamBackend.capabilities
            def stream(self, messages, **kwargs):
                yield BackendChunk("text", "partial")
                raise ValueError("broken stream")
        self.backend = BrokenStream()
        frames = list(self.client.stream("/v1/responses", {"input": "partial", "stream": True}))
        self.assertEqual(frames[-1]["event"], "response.failed")
        self.assertEqual([f["data"]["delta"] for f in frames if f["event"] == "response.output_text.delta"], ["partial"])
        self.assertEqual(frames[-1]["data"]["response"]["localpilot"]["tools"], [])
        partial = frames[-1]["data"]["response"]["output"][0]
        self.assertEqual(partial["status"], "incomplete")
        self.assertEqual(partial["content"][0]["text"], "partial")
        self.assertEqual(partial, next(f["data"]["item"] for f in frames if f["event"] == "response.output_item.done"))

    def test_two_independent_sessions_can_run_without_global_runtime_lock(self):
        entered, release = threading.Event(), threading.Event()
        def blocked(messages):
            entered.set()
            release.wait(3)
            return answer("first")
        self.backend = Backend(blocked, answer("second"))
        first = self.responses("first", background=True)
        self.assertTrue(entered.wait(2))
        try:
            second = self.responses("second")
            self.assertEqual(second["status"], "completed")
            self.assertNotEqual(first["conversation"], second["conversation"])
        finally:
            release.set()
        self.assertEqual(self.task(first)["status"], "completed")

    def test_output_cap_is_kept_across_approval_resume(self):
        self.patch_backend()
        task = self.task(self.responses("write", max_output_tokens=100))
        self.host_action(task)
        self.task(task)
        self.assertEqual([r["max_tokens"] for r in self.backend.requests], [100, 100])

    def test_cancel_propagates_to_existing_runtime_worker(self):
        entered, release = threading.Event(), threading.Event()
        def worker(messages):
            entered.set()
            release.wait(3)
            return answer(None, call("read_file", {"path": "note.txt"}, "worker-read"))
        self.backend = Backend(answer(None, call("delegate", {"backend_preference": "cloud", "task": "inspect", "read_only": True}, "worker")), worker, answer("must not request"))
        task = self.task(self.responses("delegate"))
        self.assertEqual(task["status"], "requires_approval")
        self.host_action(task)
        self.assertTrue(entered.wait(2))
        self.client.request(f'/localpilot/v1/tasks/{task["id"]}/cancel', {})
        release.set()
        done = self.task(task)
        self.assertEqual(done["status"], "cancelled")
        self.assertEqual(len(self.backend.requests), 2)
        events, _ = self.service.events(task["id"], wait_seconds=0)
        self.assertFalse(any(e["type"] == "runtime.event" and e["data"]["type"] == "SubagentEvent"
            and e["data"]["data"]["event"]["type"] == "ToolCallStarted" for e in events))

    def test_retention_gap_and_capacity_fail_explicitly(self):
        self.service.max_events = 3
        result = self.responses()
        self.assert_http(409, f'/localpilot/v1/tasks/{result["id"]}/events?after=0', None)
        self.service.max_tasks = 1
        self.assert_http(429, "/v1/responses", {"input": "capacity"})

    @unittest.skipUnless(shutil.which("curl"), "curl not installed")
    def test_curl_json_and_sse_examples_over_http(self):
        self.backend = Backend(answer("curl response"), answer("curl stream"))
        args = ["curl", "--fail", "--silent", "--show-error", "--max-time", "3", self.url + "/v1/responses",
            "-H", "Authorization: Bearer test-key", "-H", "Content-Type: application/json", "-d"]
        normal = subprocess.run(args + ['{"model":"localpilot","input":"curl"}'], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(normal.stdout)["output"][0]["content"][0]["text"], "curl response")
        stream = subprocess.run(args + ['{"model":"localpilot","input":"curl","stream":true}', "-N"], check=True, capture_output=True, text=True)
        self.assertIn("event: response.output_text.delta", stream.stdout)
        self.assertIn("event: response.completed", stream.stdout)


if __name__ == "__main__":
    unittest.main()
