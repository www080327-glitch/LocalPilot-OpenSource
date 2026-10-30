"""Offline behavior tests for runtime state, side effects and policy boundaries."""
import io
import json
import ssl
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from agent.backends import BackendCapabilities, BackendChunk, BackendResponse, Message, ModelInfo, ToolCall
from agent.context import transfer_context
from agent.deepseek import DeepSeekBackend
from agent.events import EventStream
from agent.judge import LocalSafetyJudge
from agent.permissions import RiskAssessment
from agent.policy import DataPolicy
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.safety import CapabilityPolicy
from agent.session import AgentSession, SessionBudgets, SessionState


def call(name, args, id="call-1"):
    return ToolCall(id, name, json.dumps(args))


def response(text=None, *calls):
    return BackendResponse(Message("assistant", text, list(calls)))


class ScriptBackend:
    capabilities = BackendCapabilities(supports_tool_calling=True,
        supported_thinking_efforts=("none", "low", "high", "max"), default_thinking_effort="high")

    def __init__(self, *responses, local=False, size="27B", context=131072):
        self.responses = list(responses)
        self.calls = []
        self.is_local = local
        self.is_loopback = local
        self.model_info = ModelInfo("local" if local else "cloud", size, context)

    def health_check(self):
        return True

    def request(self, messages, tools=None, thinking=None, max_tokens=None):
        self.calls.append({"messages": deepcopy(messages), "tools": tools, "thinking": thinking})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class RuntimeSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "note.txt").write_text("fact")
        self.events = []

    def tearDown(self):
        self.temp.cleanup()

    def session(self, cloud=None, local=None, **kwargs):
        mode = kwargs.pop("permission_mode", "approve-mutations")
        registry = create_default_registry(self.root, permission_mode=mode,
                                           capabilities=kwargs.pop("capabilities", None))
        return AgentSession(registry, cloud_backend=cloud, local_backend=local,
            event_callback=self.events.append, retry_policy=RetryPolicy(base_delay=0, jitter=0), **kwargs)

    def test_two_turns_retain_context_and_final_does_not_close(self):
        cloud = ScriptBackend(response("first answer"), response("second answer"))
        session = self.session(cloud)
        self.assertEqual(session.run_turn("first question").text, "first answer")
        self.assertEqual(session.state, SessionState.TURN_FINISHED)
        session.run_turn("followup")
        self.assertIn("first question", [m.content for m in cloud.calls[1]["messages"]])
        self.assertIn("first answer", [m.content for m in cloud.calls[1]["messages"]])
        session.close()
        self.assertEqual(session.state, SessionState.SESSION_FINISHED)
        with self.assertRaises(ValueError):
            session.run_turn("cannot reopen")

    def test_updates_apply_to_subsequent_request(self):
        cloud = ScriptBackend(response("ok"))
        session = self.session(cloud)
        session.set_policy("cloud-only")
        session.set_thinking("high")
        session.set_permissions("approve-all")
        self.assertEqual(session.run_turn("hi").status, "completed")
        self.assertEqual(cloud.calls[0]["thinking"], "high")
        self.assertEqual(session.registry.gateway.mode, "approve-all")

    def test_provider_native_thinking_rejects_unsupported_value(self):
        cloud = ScriptBackend(response("ok"))
        session = self.session(cloud)
        self.assertEqual(session.settings()["supported_thinking_efforts"], ["none", "low", "high", "max"])
        self.assertEqual(session.settings()["thinking"], "high")
        for unsupported in ("medium", "off", "deep"):
            with self.assertRaisesRegex(ValueError, "does not support"):
                session.set_thinking(unsupported)
        session.set_thinking("none")
        session.run_turn("hi")
        self.assertEqual(cloud.calls[0]["thinking"], "none")

    def test_local_only_cannot_send_cloud_even_when_unavailable(self):
        cloud = ScriptBackend(response("should never run"))
        session = self.session(cloud, policy="local-only")
        self.assertEqual(session.run_turn("secret").status, "error")
        self.assertFalse(cloud.calls)

    def test_local_first_selects_eligible_local_and_cloud_policies_default_cloud(self):
        for policy in ("local-first", "balanced", "cloud-first", "cloud-only"):
            with self.subTest(policy=policy):
                cloud, local = ScriptBackend(response("cloud")), ScriptBackend(response("local"), local=True)
                session = self.session(cloud, local, policy=policy)
                expected = "local" if policy == "local-first" else "cloud"
                self.assertEqual(session.run_turn("hi").text, expected)

    def test_ineligible_models_never_primary(self):
        for size, context in (("4B", 131072), ("9B", 131072), ("27B", 32768)):
            with self.subTest(size=size, context=context):
                local = ScriptBackend(response("bad"), local=True, size=size, context=context)
                session = self.session(ScriptBackend(response("cloud")), local, policy="local-only")
                self.assertEqual(session.run_turn("hi").status, "error")
                self.assertFalse(local.calls)

    def test_local_retry_exhaustion_fallback_is_visible(self):
        local = ScriptBackend(*[TimeoutError("transient") for _ in range(4)], local=True)
        cloud = ScriptBackend(response("cloud reply"))
        session = self.session(cloud, local, policy="local-first")
        self.assertEqual(session.run_turn("hi").text, "cloud reply")
        self.assertEqual(len(local.calls), 4)
        event = next(e for e in self.events if e.type == "BackendFallback")
        self.assertEqual(event.data["reason"], "local_backend_failure")
        self.assertIn("conversation", event.data["data_categories"])

    def test_local_only_retry_exhaustion_never_falls_back(self):
        local = ScriptBackend(*[TimeoutError("transient") for _ in range(4)], local=True)
        cloud = ScriptBackend(response("never"))
        session = self.session(cloud, local, policy="local-only")
        self.assertEqual(session.run_turn("hi").status, "error")
        self.assertEqual(len(local.calls), 4)
        self.assertFalse(cloud.calls)

    def test_switch_confirmation_context_and_guard(self):
        switch = call("request_model_switch", {"target": "local", "reason": "simple", "task_complexity": "simple"})
        reverse = call("request_model_switch", {"target": "cloud", "reason": "changed mind", "task_complexity": "complex"}, "switch-back")
        cloud = ScriptBackend(response(None, switch))
        local = ScriptBackend(response(None, reverse), response("done"), local=True)
        session = self.session(cloud, local)
        self.assertEqual(session.run_turn("Remember this context").status, "approval_required")
        self.assertFalse(local.calls)
        self.assertEqual(session.state, SessionState.MODEL_SWITCH_AWAITING_APPROVAL)
        self.assertEqual(session.approve().status, "completed")
        self.assertIn("Remember this context", [m.content for m in local.calls[0]["messages"]])
        self.assertEqual(session.primary, "local")
        self.assertEqual(session._switches, 1)
        self.assertIn("denied", local.calls[1]["messages"][-1].content)
        self.assertIn("ModelSwitched", [e.type for e in self.events])

    def test_local_to_cloud_switch_categories_and_rejection(self):
        switch = call("request_model_switch", {"target": "cloud", "reason": "complex", "task_complexity": "complex"})
        local = ScriptBackend(response(None, call("read_file", {"path": "note.txt"}, "read")),
                              response(None, switch), response("local answer"), local=True)
        cloud = ScriptBackend(response("never"))
        session = self.session(cloud, local, policy="local-first")
        session.run_turn("inspect")
        self.assertIn("workspace_snippets", session.pending_approval["request"]["data_boundary_change"])
        self.assertEqual(session.reject().text, "local answer")
        self.assertFalse(cloud.calls)

    def test_cloud_first_requires_very_simple_and_cloud_only_blocks_local(self):
        for policy, complexity, permitted in (("cloud-first", "simple", False),
                                               ("cloud-first", "very_simple", True),
                                               ("cloud-only", "very_simple", False)):
            cloud = ScriptBackend(response(None, call("request_model_switch", {
                "target": "local", "reason": "small", "task_complexity": complexity})), response("cloud"))
            session = self.session(cloud, ScriptBackend(response("local"), local=True), policy=policy)
            result = session.run_turn("hi")
            self.assertEqual(result.status, "approval_required" if permitted else "completed")

    def test_approval_resume_executes_once_and_continues_remaining_batch(self):
        change = call("apply_patch", {"changes": [{"path": "new.txt", "operation": "create", "content": "new"}]})
        cloud = ScriptBackend(response(None, change, call("read_file", {"path": "new.txt"}, "read")), response("done"))
        session = self.session(cloud)
        self.assertEqual(session.run_turn("create").status, "approval_required")
        self.assertFalse((self.root / "new.txt").exists())
        self.assertEqual(len(cloud.calls), 1)
        result = session.approve()
        self.assertEqual(result.status, "completed")
        self.assertEqual((self.root / "new.txt").read_text(), "new")
        self.assertEqual(len(cloud.calls), 2)
        self.assertEqual(len([r for r in session.registry.gateway.audit if r.get("status") == "applied"]), 1)
        with self.assertRaises(ValueError):
            session.approve()

    def test_retry_and_duplicate_id_do_not_reexecute_mutation(self):
        change = call("apply_patch", {"changes": [{"path": "note.txt", "operation": "update", "old_text": "fact", "new_text": "facts"}]})
        cloud = ScriptBackend(response(None, change), ssl.SSLEOFError("eof"), response(None, change), response("done"))
        session = self.session(cloud, permission_mode="full-permission")
        self.assertEqual(session.run_turn("modify").status, "completed")
        self.assertEqual((self.root / "note.txt").read_text(), "facts")
        self.assertEqual(len([r for r in session.registry.gateway.audit if r.get("status") == "applied"]), 1)
        self.assertEqual(cloud.calls[1]["messages"], cloud.calls[2]["messages"])

    def test_changed_approval_target_invalidates_ticket(self):
        change = call("apply_patch", {"changes": [{"path": "note.txt", "operation": "update", "old_text": "fact", "new_text": "new"}]})
        cloud = ScriptBackend(response(None, change), response("conflict"))
        session = self.session(cloud)
        session.run_turn("change")
        (self.root / "note.txt").write_text("fact changed externally")
        session.approve()
        self.assertEqual((self.root / "note.txt").read_text(), "fact changed externally")
        self.assertIn("Approval expired", cloud.calls[-1]["messages"][-1].content)

    def test_plan_read_only_then_plan_approval_does_not_approve_patch(self):
        change = call("apply_patch", {"changes": [{"path": "new", "operation": "create", "content": "new"}]})
        cloud = ScriptBackend(response(None, change), response("Plan: create new"),
                              response(None, call("apply_patch", json.loads(change.arguments), "execute-patch")), response("done"))
        session = self.session(cloud, plan_mode=True)
        self.assertEqual(session.run_turn("create new").status, "approval_required")
        self.assertEqual(session.state, SessionState.PLAN_AWAITING_APPROVAL)
        self.assertFalse((self.root / "new").exists())
        self.assertEqual(session.approve().status, "approval_required")
        self.assertEqual(session.state, SessionState.TOOL_AWAITING_APPROVAL)
        self.assertFalse((self.root / "new").exists())
        self.assertEqual(session.approve().status, "completed")
        self.assertTrue((self.root / "new").exists())

    def test_plan_revisions_and_rejection(self):
        cloud = ScriptBackend(response("first plan"), response("revised plan"))
        session = self.session(cloud, plan_mode=True)
        session.run_turn("task")
        session.revise_plan("use one file")
        self.assertEqual(session.active_plan["text"], "revised plan")
        self.assertEqual(session.reject().status, "rejected")
        self.assertEqual(session.state, SessionState.TURN_FINISHED)

    def test_plan_can_create_goals_and_only_read_only_worker_until_approval(self):
        cloud = ScriptBackend(
            response(None, call("manage_goal", {"action": "create", "description": "Implement", "subgoals": ["Explore", "Patch"]}, "goal")),
            response(None, call("delegate", {"task": "Inspect safely", "backend_preference": "local"}, "worker")),
            response("Plan: inspect then patch"), response("Approved execution continues"))
        local = ScriptBackend(response(None, call("apply_patch", {"changes": [
            {"path": "blocked.txt", "operation": "create", "content": "bad"}]})), response("Cannot patch"), local=True)
        session = self.session(cloud, local, plan_mode=True, permission_mode="full-permission")
        self.assertEqual(session.run_turn("plan task").status, "approval_required")
        self.assertEqual(len(session.goals.list()), 3)
        self.assertFalse((self.root / "blocked.txt").exists())
        self.assertTrue(session.subagents[0]["read_only"])
        self.assertTrue(session.active_goal_lines())
        self.assertEqual(session.approve().status, "incomplete")
        self.assertEqual(session.subagents[0]["obligation_status"], "unresolved")
        self.assertEqual(session.subagents[0]["unfinished_calls"][0]["payload"]["result"]["status"], "denied")
        self.assertEqual(len(session.goals.list()), 3)
        self.assertFalse(session.registry.gateway.plan_read_only)

    def test_full_permission_preserves_hard_boundaries(self):
        for name, args in (("read_file", {"path": "../secret"}), ("read_file", {"path": ".env"}),
                           ("execute", {"argv": ["rm", "note.txt"]})):
            cloud = ScriptBackend(response(None, call(name, args)), response("denied"))
            session = self.session(cloud, permission_mode="full-permission", capabilities=CapabilityPolicy(execute=True))
            session.run_turn("try")
            self.assertFalse(session.tool_history[0]["payload"]["ok"])
        self.assertTrue((self.root / "note.txt").exists())

    def test_hard_data_policy_cannot_be_changed(self):
        session = self.session(data_policy=DataPolicy(local_only=True), policy="local-only")
        with self.assertRaises(PermissionError):
            session.set_policy("cloud-only")

    def test_bounded_worker_returns_structured_result_to_main(self):
        delegation = call("delegate", {"task": "summarize this independent task", "backend_preference": "local", "budget": {"steps": 2, "tools": 1, "tokens": 20000}})
        cloud = ScriptBackend(response(None, delegation), response("integrated"))
        local = ScriptBackend(response("worker finding"), local=True, size="4B")
        session = self.session(cloud, local)
        result = session.run_turn("MAIN SECRET")
        self.assertEqual(result.status, "completed")
        self.assertIn("worker finding", cloud.calls[-1]["messages"][-1].content)
        self.assertNotIn("MAIN SECRET", str(local.calls))
        self.assertEqual(session.subagents[0]["depth"], 1)

    def test_delegate_rejects_unsupported_worker_thinking_without_remap(self):
        delegation = call("delegate", {"task": "inspect", "backend_preference": "local"})
        cloud = ScriptBackend(response(None, delegation), response("handled"))
        local = ScriptBackend(response("unused"), local=True)
        local.capabilities = BackendCapabilities(supports_tool_calling=True,
            supported_thinking_efforts=("none",), default_thinking_effort="none")
        session = self.session(cloud, local, thinking="max")
        self.assertEqual(session.run_turn("delegate").text, "handled")
        self.assertFalse(local.calls)
        self.assertIn("does not support thinking 'max'", cloud.calls[-1]["messages"][-1].content)

    def test_worker_permission_ceiling_and_depth(self):
        delegation = call("delegate", {"task": "write", "backend_preference": "local", "read_only": True})
        cloud = ScriptBackend(response(None, delegation), response("done"))
        local = ScriptBackend(response(None, call("apply_patch", {"changes": [{"path": "bad", "operation": "create", "content": "bad"}]})), response("blocked"), local=True)
        session = self.session(cloud, local, permission_mode="full-permission")
        session.run_turn("test")
        self.assertFalse((self.root / "bad").exists())
        self.assertIn("denied", local.calls[-1]["messages"][-1].content)
        self.assertTrue(all(s["function"]["name"] != "delegate" for s in local.calls[0]["tools"]))

    def test_local_only_blocks_cloud_worker(self):
        local = ScriptBackend(response(None, call("delegate", {"task": "secret", "backend_preference": "cloud"})), response("blocked"), local=True)
        cloud = ScriptBackend(response("never"))
        session = self.session(cloud, local, policy="local-only")
        self.assertEqual(session.run_turn("task").status, "completed")
        self.assertFalse(cloud.calls)
        self.assertFalse(session.subagents)

    def test_cloud_worker_requires_boundary_approval_and_resumes_main(self):
        local = ScriptBackend(response(None, call("delegate", {"task": "hard", "backend_preference": "cloud"})), response("main"), local=True)
        cloud = ScriptBackend(response("worker"))
        session = self.session(cloud, local, policy="local-first")
        self.assertEqual(session.run_turn("delegate").status, "approval_required")
        self.assertFalse(cloud.calls)
        self.assertEqual(session.approve().text, "main")
        self.assertIn("worker", local.calls[-1]["messages"][-1].content)

    def test_worker_mutation_requires_parent_mode_approval(self):
        local = ScriptBackend(response(None, call("apply_patch", {"changes": [{"path": "worker.txt", "operation": "create", "content": "ok"}]})), response("worker done"), local=True)
        cloud = ScriptBackend(response(None, call("delegate", {"task": "write", "backend_preference": "local", "read_only": False})), response("main done"))
        session = self.session(cloud, local)
        self.assertEqual(session.run_turn("delegate").status, "approval_required")
        self.assertEqual(session.pending_approval["kind"], "subagent_resume")
        self.assertFalse((self.root / "worker.txt").exists())
        self.assertEqual(session.approve().status, "completed")
        self.assertTrue((self.root / "worker.txt").exists())

    def test_handoff_revokes_delegate_and_switch_approval_before_worker_or_switch(self):
        from computer.runtime import ComputerRuntime
        from tests.test_computer_runtime import MemoryAX, APP
        proposals = [call('delegate', {'task': 'inspect', 'backend_preference': 'cloud'}),
            call('request_model_switch', {'target': 'cloud', 'reason': 'complex', 'task_complexity': 'complex'})]
        for proposal in proposals:
            with self.subTest(name=proposal.name):
                computer = ComputerRuntime(MemoryAX(), allowed_apps=[APP])
                local = ScriptBackend(response(None, proposal), response('replanned'), local=True)
                cloud = ScriptBackend(response('must not start'))
                session = self.session(cloud, local, policy='local-first', computer_runtime=computer)
                self.assertEqual(session.run_turn('work').status, 'approval_required')
                session.take_over_computer()
                result = session.resume_computer()
                self.assertIsNone(session.pending_approval)
                self.assertFalse(session._queue)
                self.assertFalse(cloud.calls)
                self.assertEqual(result.status, 'completed')
                session.close()

    def test_handoff_cancels_waiting_child_without_executing_approved_write(self):
        from computer.runtime import ComputerRuntime
        from tests.test_computer_runtime import MemoryAX, APP
        local = ScriptBackend(response(None, call('apply_patch', {'changes': [
            {'path': 'stale-worker.txt', 'operation': 'create', 'content': 'must not write'}]})), response('worker done'), local=True)
        cloud = ScriptBackend(response(None, call('delegate', {'task': 'write', 'backend_preference': 'local', 'read_only': False,
            'budget': {'steps': 4, 'tools': 2, 'tokens': 100000}})), response('replanned'))
        session = self.session(cloud, local, budgets=SessionBudgets(max_worker_token_units=100000),
            computer_runtime=ComputerRuntime(MemoryAX(), allowed_apps=[APP]))
        self.assertEqual(session.run_turn('delegate').status, 'approval_required')
        child = session.pending_approval['child']
        prior_units = session._token_units
        session.take_over_computer()
        result = session.resume_computer()
        self.assertEqual(result.status, 'incomplete')
        self.assertIsNone(session.pending_approval)
        self.assertEqual(child.state, SessionState.SESSION_FINISHED)
        self.assertEqual(session.subagents[0]['status'], 'cancelled_for_handoff')
        self.assertGreaterEqual(session._token_units, prior_units)
        self.assertEqual(session.subagents[0]["usage"]["token_units"], child._token_units)
        self.assertTrue(session.subagents[0]["unfinished_calls"])
        self.assertTrue(all(usage in session._usage for usage in child._usage))
        self.assertFalse((self.root / 'stale-worker.txt').exists())
        session.close()

    def test_subagent_count_and_step_budgets(self):
        calls = [call("delegate", {"task": "work", "backend_preference": "local"}, f"w{i}") for i in range(3)]
        cloud = ScriptBackend(response(None, *calls), response("done"))
        local = ScriptBackend(response("one"), response("two"), local=True)
        session = self.session(cloud, local)
        session.run_turn("task")
        self.assertEqual(len(local.calls), 2)
        self.assertEqual(len(session.subagents), 2)
        self.assertIn("budget", session.tool_history[-1]["payload"]["result"]["reason"])

    def test_real_time_delta_precedes_final_and_tool_lifecycle(self):
        class StreamBackend(ScriptBackend):
            capabilities = BackendCapabilities(supports_streaming=True, supports_tool_calling=True)
            def stream(self, messages, **kwargs):
                yield BackendChunk("text", "hello")
                self.observed_before_final = any(e.type == "TextDelta" for e in events)
                yield BackendChunk("text", " world")
                yield BackendChunk("response", response=response("hello world"))
        events = self.events
        backend = StreamBackend()
        session = self.session(backend)
        self.assertEqual(session.run_turn("hello").text, "hello world")
        self.assertTrue(backend.observed_before_final)
        self.assertEqual([e.data["text"] for e in events if e.type == "TextDelta"], ["hello", " world"])

    def test_partial_stream_never_retries_or_executes_tools(self):
        class BrokenStream(ScriptBackend):
            capabilities = BackendCapabilities(supports_streaming=True)
            count = 0
            def stream(self, *args, **kwargs):
                self.count += 1
                yield BackendChunk("text", "partial")
                raise TimeoutError("lost connection")
        backend = BrokenStream()
        session = self.session(backend)
        self.assertEqual(session.run_turn("hi").status, "error")
        self.assertEqual(backend.count, 1)
        self.assertFalse(session.tool_history)

    def test_context_compaction_keeps_history_and_pairs(self):
        backend = ScriptBackend(response("ok"), context=24000)
        session = self.session(backend, budgets=SessionBudgets(max_output_tokens=256))
        session.messages.extend([Message("user", "old" * 10000), Message("assistant", "prior")])
        session.run_turn("latest question")
        self.assertIn("ContextCompacted", [e.type for e in self.events])
        self.assertTrue(any(len(m.content or "") > 20000 for m in session.messages))
        self.assertTrue(any(m.content == "latest question" for m in backend.calls[0]["messages"]))

    def test_goals_model_lifecycle_emits_events(self):
        backend = ScriptBackend(response(None, call("manage_goal", {"action": "create", "description": "project"})), response("created"))
        session = self.session(backend)
        session.run_turn("track")
        goal = session.goals.list()[0]
        session._manage_goal({"action": "complete", "id": goal.id})
        self.assertEqual(goal.status, "done")
        self.assertIn("GoalCompleted", [e.type for e in self.events])

    def test_multiple_model_goals_persist_and_evaluate_each_turn(self):
        cloud = ScriptBackend(
            response(None, call("manage_goal", {"action": "create", "description": "A"}, "a"),
                     call("manage_goal", {"action": "create", "description": "B"}, "b")),
            response("working"), response("still working"))
        session = self.session(cloud)
        session.run_turn("complex task")
        self.assertEqual(len(session.goals.list()), 2)
        self.assertEqual(len([e for e in self.events if e.type == "GoalsEvaluated"]), 1)
        self.assertIn("○ A", "\n".join(session.active_goal_lines()))
        session.run_turn("continue")
        self.assertEqual(len([e for e in self.events if e.type == "GoalsEvaluated"]), 2)
        self.assertIn("A", cloud.calls[-1]["messages"][0].content)
        for goal in session.goals.list():
            session._manage_goal({"action": "complete", "id": goal.id})
        self.assertEqual(session.active_goal_lines(), [])
        self.assertEqual(len(session._goal_records()), 2)

    def test_parent_goal_completes_when_all_subgoals_are_done(self):
        session = self.session(ScriptBackend(response("done")))
        parent = session.goals.create("Ship", subgoals=["Build", "Check"])
        children = session.goals.list()[1:]
        session.goals.update(children[0].id, status="done")
        session.run_turn("status")
        self.assertEqual(parent.status, "pending")
        self.assertIn("✓ Build", "\n".join(session.active_goal_lines()))
        session.goals.update(children[1].id, status="done")
        session._evaluate_goals()
        self.assertEqual(parent.status, "done")
        self.assertFalse(session.active_goal_lines())

    def test_reasoning_display_modes_emit_only_requested_content(self):
        class ReasoningBackend(ScriptBackend):
            capabilities = BackendCapabilities(supports_streaming=True, supports_tool_calling=True)
            def stream(self, messages, **kwargs):
                yield BackendChunk("reasoning", "private thought")
                yield BackendChunk("text", "answer")
                yield BackendChunk("response", response=BackendResponse(
                    Message("assistant", "answer", reasoning_content="private thought")))
        for mode in ("hidden", "summary", "full"):
            with self.subTest(mode=mode):
                events = []
                backend = ReasoningBackend()
                session = AgentSession(create_default_registry(self.root), cloud_backend=backend,
                    reasoning=mode, event_callback=events.append)
                self.assertEqual(session.run_turn("hi").text, "answer")
                kinds = [event.type for event in events]
                self.assertEqual("ReasoningDelta" in kinds, mode == "full")
                self.assertEqual("ReasoningSummary" in kinds, mode == "summary")
                self.assertEqual(session.messages[-1].reasoning_content, "private thought")

    def test_deepseek_streamed_reasoning_tool_roundtrip(self):
        class SSE:
            def __init__(self, *events):
                self.body = "".join("data: " + json.dumps(event) + "\n\n" for event in events).encode() + b"data: [DONE]\n\n"
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def __iter__(self):
                return iter(self.body.splitlines(keepends=True))
        first = SSE({"choices": [{"index": 0, "delta": {
            "reasoning_content": "Need note", "tool_calls": [{"index": 0, "id": "r1",
            "function": {"name": "read_file", "arguments": '{"path":"note.txt"}'}}]},
            "finish_reason": "tool_calls"}]})
        second = SSE({"choices": [{"index": 0, "delta": {"content": "The note says fact"},
            "finish_reason": "stop"}]})
        backend = DeepSeekBackend(api_key="fake")
        with patch("agent.deepseek.urlopen", side_effect=[first, second]) as opened:
            session = self.session(backend, reasoning="full")
            self.assertEqual(session.run_turn("Read the note").text, "The note says fact")
        self.assertEqual(len(opened.call_args_list), 2)
        second_payload = json.loads(opened.call_args_list[1].args[0].data)
        self.assertEqual(second_payload["reasoning_effort"], "high")
        self.assertEqual(second_payload["messages"][-2]["reasoning_content"], "Need note")
        self.assertEqual(second_payload["messages"][-1]["role"], "tool")
        self.assertIn("ReasoningDelta", [event.type for event in self.events])

    def test_model_goal_create_keeps_initial_status_and_children(self):
        backend = ScriptBackend(response(None, call("manage_goal", {
            "action": "create", "description": "project", "status": "in_progress",
            "subgoals": ["inspect", "validate"]})), response("tracked"))
        session = self.session(backend)
        self.assertEqual(session.run_turn("track").status, "completed")
        parent, *children = session.goals.list()
        self.assertEqual(parent.status, "in_progress")
        self.assertEqual([child.description for child in children], ["inspect", "validate"])
        self.assertEqual(parent.subgoals, [child.id for child in children])

    def test_safety_judge_is_local_structured_and_no_tools(self):
        local = ScriptBackend(response(json.dumps({"risk_level": "LOW", "reason": "limited change", "potential_impact": "one file", "recommended_action": "allow"})), local=True, size="4B")
        judge = LocalSafetyJudge(local)
        self.assertIsInstance(judge("apply_patch", "medium", ["patch"], {"path": "file"}), RiskAssessment)
        self.assertIsNone(local.calls[0]["tools"])
        self.assertNotIn("conversation", local.calls[0]["messages"][-1].content)
        with self.assertRaises(RuntimeError):
            LocalSafetyJudge(ScriptBackend())("patch", "medium", [], {})

    def test_safety_judge_unavailable_returns_human_approval(self):
        cloud = ScriptBackend(response(None, call("apply_patch", {"changes": [{"path": "new", "operation": "create", "content": "ok"}]})))
        session = self.session(cloud, permission_mode="local-judge-permissive")
        session.registry.gateway.judge = LocalSafetyJudge(session.local_backend)
        self.assertEqual(session.run_turn("write").status, "approval_required")
        self.assertFalse((self.root / "new").exists())

    def test_turn_scope_restore_cannot_override_new_policy(self):
        cloud = ScriptBackend(response(None, call("request_model_switch", {
            "target": "local", "reason": "simple", "task_complexity": "simple"})), response("cloud next"))
        local = ScriptBackend(response("local turn"), local=True)
        session = self.session(cloud, local)
        session.run_turn("first")
        session.approve()
        session.set_policy("cloud-only")
        self.assertEqual(session.run_turn("second").text, "cloud next")
        self.assertEqual(len(local.calls), 1)

    def test_approve_all_applies_to_goal_action(self):
        cloud = ScriptBackend(response(None, call("manage_goal", {"action": "create", "description": "goal"})), response("done"))
        session = self.session(cloud, permission_mode="approve-all")
        self.assertEqual(session.run_turn("track").status, "approval_required")
        self.assertFalse(session.goals.list())
        session.approve()
        self.assertEqual(len(session.goals.list()), 1)

    def test_event_renderer_failure_does_not_replay_mutation(self):
        cloud = ScriptBackend(response(None, call("apply_patch", {"changes": [
            {"path": "new", "operation": "create", "content": "ok"}]})), response("done"))
        session = self.session(cloud, permission_mode="full-permission")
        def broken_observer(event):
            if event.type == "ToolCallCompleted":
                raise RuntimeError("UI disconnected")
        session.events.callback = broken_observer
        self.assertEqual(session.run_turn("write").status, "completed")
        self.assertEqual((self.root / "new").read_text(), "ok")
        self.assertEqual(session.events.observer_errors, ["RuntimeError"])
        self.assertEqual(len([r for r in session.registry.gateway.audit if r.get("status") == "applied"]), 1)

    def test_child_preserves_explicit_read_only_capability(self):
        cloud = ScriptBackend(response(None, call("delegate", {"task": "write", "backend_preference": "local", "read_only": False})), response("done"))
        local = ScriptBackend(response(None, call("apply_patch", {"changes": [
            {"path": "bad", "operation": "create", "content": "bad"}]})), response("denied"), local=True)
        session = self.session(cloud, local, permission_mode="full-permission",
                               capabilities=CapabilityPolicy(read_only=True))
        session.run_turn("write")
        self.assertFalse((self.root / "bad").exists())

    def test_child_depth_and_zero_worker_budget_denied(self):
        for kwargs in ({"depth": 1}, {"budgets": SessionBudgets(max_subagents_per_turn=0)}):
            cloud = ScriptBackend(response(None, call("delegate", {"task": "work", "backend_preference": "local"})), response("denied"))
            local = ScriptBackend(response("never"), local=True)
            session = self.session(cloud, local, **kwargs)
            session.run_turn("task")
            self.assertFalse(local.calls)
            self.assertFalse(session.subagents)

    def test_cloud_only_blocks_local_worker_but_not_local_judge(self):
        cloud = ScriptBackend(response(None, call("delegate", {"task": "work", "backend_preference": "local"})), response("denied"))
        local = ScriptBackend(response(json.dumps({"risk_level": "LOW", "reason": "safe metadata", "potential_impact": "one file", "recommended_action": "allow"})), local=True)
        session = self.session(cloud, local, policy="cloud-only")
        session.run_turn("task")
        self.assertFalse(local.calls)
        assessment = session.registry.gateway.judge("apply_patch", "medium", [], {"path": "new"})
        self.assertEqual(assessment.risk_level, "LOW")

    def test_token_budget_stops_before_sending_request(self):
        cloud = ScriptBackend(response("never"))
        session = self.session(cloud, budgets=SessionBudgets(max_token_units=10))
        self.assertEqual(session.run_turn("hello").status, "error")
        self.assertFalse(cloud.calls)

    def test_duplicate_ids_in_batch_execute_nothing(self):
        cloud = ScriptBackend(response(None, call("apply_patch", {"changes": [
            {"path": "bad", "operation": "create", "content": "bad"}]}), call("read_file", {"path": "note.txt"})))
        session = self.session(cloud, permission_mode="full-permission")
        self.assertEqual(session.run_turn("task").status, "error")
        self.assertFalse((self.root / "bad").exists())

    def test_reject_tool_returns_denial_without_side_effect(self):
        cloud = ScriptBackend(response(None, call("apply_patch", {"changes": [
            {"path": "bad", "operation": "create", "content": "bad"}]})), response("understood"))
        session = self.session(cloud)
        session.run_turn("task")
        self.assertEqual(session.reject().text, "understood")
        self.assertFalse((self.root / "bad").exists())
        self.assertIn("user_rejected", cloud.calls[-1]["messages"][-1].content)

    def test_context_compaction_never_splits_assistant_tool_group(self):
        messages = [Message("system", "base"), Message("user", "old" * 10000),
            Message("assistant", None, [call("read_file", {"path": "note.txt"})]),
            Message("tool", "large result" * 2000, tool_call_id="call-1"), Message("user", "new")]
        view, notice = transfer_context(messages, [], 6000, 100)
        self.assertIsNotNone(notice)
        self.assertEqual(view[-1].content, "new")
        self.assertFalse(any(m.role == "tool" for m in view))
        self.assertIn("recent_tool_results", view[1].content)
        self.assertIn("call-1", view[1].content)

    def test_small_target_context_returns_error_without_request(self):
        cloud = ScriptBackend(response("never"), context=16)
        session = self.session(cloud)
        self.assertEqual(session.run_turn("task").status, "error")
        self.assertFalse(cloud.calls)


    def test_explicit_cloud_backend_data_policy_is_enforced(self):
        cloud = ScriptBackend(response("never"))
        cloud.data_policy = DataPolicy(local_only=True)
        session = self.session(cloud)
        self.assertEqual(session.run_turn("private").status, "error")
        self.assertFalse(cloud.calls)
        with self.assertRaises(PermissionError):
            session.set_policy("cloud-only")

    def test_minimal_zero_session_retains_no_system_prompt(self):
        cloud = ScriptBackend(response("ok"))
        session = self.session(cloud, prompt_profile="minimal_0")
        session.run_turn("hello")
        self.assertFalse(any(m.role == "system" for m in cloud.calls[0]["messages"]))



if __name__ == "__main__":
    unittest.main()
