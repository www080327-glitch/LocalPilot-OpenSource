"""Deterministic controller/Session tests. These do not establish native AX or LLM capability."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest

from agent.backends import BackendCapabilities, BackendResponse, Message, ModelInfo, ToolCall
from agent.registry import create_default_registry
from agent.safety import CapabilityPolicy
from agent.session import AgentSession, SessionBudgets, SessionState
from computer.cli import control
from computer.runtime import ComputerRuntime, ControlState

APP = "org.localpilot.axfixture"


def condition(identifier="input", value="new"):
    return {"selector": {"identifier": identifier}, "attribute": "value", "equals": value}


class MemoryAX:
    """Scripted fault adapter. Never described as real macOS evidence."""
    allowed_apps = frozenset([APP])
    def __init__(self):
        self.env = {"trusted": True, "frontmost_app": "user.app", "frontmost_pid": 1,
            "focused_element": {"identifier": "user.focus", "role": "AXButton"}, "focus_observable": True,
            "mouse": [100, 200], "locked": False,
            "session_available": True, "session_id": 1, "input_idle_seconds": 10}
        self.nodes = [
            {"handle": "input", "role": "AXTextField", "identifier": "input", "value": "old", "value_settable": True, "actions": []},
            {"handle": "button", "role": "AXButton", "identifier": "button", "title": "Apply", "value": None, "actions": ["AXPress"]},
            {"handle": "result", "role": "AXStaticText", "identifier": "result", "value": "ready", "actions": []}]
        self.closed = False
        self.sent = 0
        self.fault = None
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False

    def environment(self):
        return deepcopy(self.env)

    def inspect_apps(self):
        return {"status": "ok", "apps": [] if self.closed else [{"app": APP}]}

    def inspect_tree(self, app, **bounds):
        if self.closed:
            return {"status": "error", "error": "app_closed"}
        return {"status": "ok", "app": app, "nodes": deepcopy(self.nodes), "truncated": False}

    def action(self, app, handle, kind, **args):
        self.entered.set()
        if self.block:
            self.release.wait(2)
        if self.closed:
            return {"status": "error", "error": "app_closed"}
        if self.fault in {"stale_element", "element_changed"}:
            return {"status": "error", "error": self.fault}
        if self.fault == "timeout":
            raise TimeoutError("scripted unknown outcome")
        before = self.environment()
        self.sent += 1
        if self.fault != "noop":
            if kind == "set_value":
                self.nodes[0]["value"] = args["value"]
            else:
                self.nodes[2]["value"] = "applied:" + self.nodes[0]["value"]
        if self.fault == "focus":
            self.env["frontmost_pid"] = 2
            self.env["frontmost_app"] = APP
        if self.fault == "mouse":
            self.env["mouse"] = [400, 500]
        return {"status": "ok", "ax_error": 0, "action_sent": True, "before": before, "after": self.environment()}

    def close(self):
        self.closed = True


class ScriptBackend:
    is_local = False
    capabilities = BackendCapabilities(supports_tool_calling=True)
    model_info = ModelInfo("script", "scripted-controller", 131072)
    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []
    def request(self, messages, **kwargs):
        self.requests.append(deepcopy(messages))
        step = self.steps.pop(0)
        return step(messages) if callable(step) else step


def response(name=None, args=None, id="call"):
    return BackendResponse(Message("assistant", "done" if not name else None,
        [] if not name else [ToolCall(id, name, json.dumps(args))]))


class ComputerTests(unittest.TestCase):
    def test_incomplete_tree_cannot_prove_absence_or_unique_match(self):
        for flags in [{'truncated': True}, {'payload_truncated': True}, {'omitted_nodes': 1}, {'AXWindows_error': -25204}]:
            tree = {**self.adapter.inspect_tree(APP), **flags}
            self.assertFalse(self.runtime._postcondition(tree, {'selector': {'identifier': 'hidden'}, 'exists': False}))
            self.assertFalse(self.runtime._postcondition(tree, condition(value='old')))

    def test_missing_or_unavailable_attribute_cannot_verify_null(self):
        for node in [{'identifier': 'input'}, {'identifier': 'input', 'value': None}]:
            tree = {'status': 'ok', 'truncated': False, 'nodes': [node]}
            self.assertFalse(self.runtime._postcondition(tree, condition(value=None)))

    def test_clipped_selector_cannot_prove_absence(self):
        tree = {'status': 'ok', 'truncated': False, 'nodes': [
            {'identifier': 'input', 'value': 'prefix', 'value_omitted_chars': 3000}]}
        self.assertFalse(self.runtime._postcondition(tree, {'selector': {'value': 'hidden full value'}, 'exists': False}))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.adapter = MemoryAX()
        self.runtime = ComputerRuntime(self.adapter, allowed_apps=[APP], verification_timeout=0)
        self.registry = create_default_registry(self.tmp.name, permission_mode="full-permission")
        self.runtime.register_tools(self.registry)

    def tearDown(self):
        self.tmp.cleanup()

    def action(self, name="set_value", handle="input", post=None, **args):
        observed = self.registry.call("inspect_tree", {"app": APP})
        return self.registry.call(name, {"app": APP, "element": handle, "observation": observed["observation"],
            "postcondition": post or condition(), **({"value": "new"} if name == "set_value" else {}), **args})

    def test_ax_tree_enumeration_and_exact_semantic_find(self):
        tree = self.registry.call("inspect_tree", {"app": APP})
        found = self.registry.call("find_element", {"app": APP, "selector": {"identifier": "input"}})
        self.assertEqual(found["observation"], tree["observation"])
        self.assertEqual(found["element"], "input")

    def test_semantic_press_verified(self):
        result = self.action("press", "button", condition("result", "applied:old"))
        self.assertTrue(result["verified"])
        self.assertEqual(self.adapter.sent, 1)

    def test_set_value_verified(self):
        self.assertTrue(self.action()["verified"])
        self.assertEqual(self.adapter.nodes[0]["value"], "new")

    def test_ax_success_without_postcondition_is_failure(self):
        self.adapter.fault = "noop"
        result = self.action()
        self.assertEqual(result["ax_status"], "ok")
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "error")
        self.assertTrue(self.runtime.paused)
        self.assertEqual(self.action()["error"], "computer_paused")
        self.assertEqual(self.adapter.sent, 1)

    def test_pause_after_applied_write_is_unverified_not_failed_verification(self):
        self.adapter.fault = "mouse"
        result = self.action()
        self.assertEqual(self.adapter.nodes[0]["value"], "new")
        self.assertEqual(result["ax_status"], "ok")
        self.assertTrue(result["action_sent"])
        self.assertEqual(result["error"], "interference")
        self.assertIsNone(result["verified"])
        self.assertFalse(result["verification_attempted"])
        self.assertEqual(self.runtime.counts["verification_attempts"], 0)
        self.assertTrue(self.runtime.paused)
        self.assertEqual(self.action()["error"], "computer_paused")
        self.assertEqual(self.adapter.sent, 1)

    def test_already_satisfied_does_not_send_write(self):
        result = self.action(post=condition(value="old"))
        self.assertEqual(result["error"], "postcondition_already_satisfied")
        self.assertEqual(self.adapter.sent, 0)

    def test_verify_fresh_tree(self):
        self.registry.call("inspect_tree", {"app": APP})
        self.adapter.nodes[0]["value"] = "human"
        result = self.registry.call("verify", {"app": APP, "postcondition": condition(value="human")})
        self.assertTrue(result["verified"])

    def test_ambiguous_selector_and_missing_element_fail_closed(self):
        self.adapter.nodes.append(deepcopy(self.adapter.nodes[0]))
        self.registry.call("inspect_tree", {"app": APP})
        self.assertEqual(self.runtime.find_element(APP, {"identifier": "input"})["error"], "ambiguous_element")
        self.assertEqual(self.runtime.find_element(APP, {"identifier": "missing"})["error"], "element_not_found")

    def test_old_observation_is_stale(self):
        first = self.runtime.inspect_tree(APP)
        self.runtime.observe(APP)
        result = self.registry.call("set_value", {"app": APP, "element": "input", "observation": first["observation"], "value": "new", "postcondition": condition()})
        self.assertEqual(result["error"], "stale_observation")
        self.assertEqual(self.adapter.sent, 0)

    def test_observation_ttl(self):
        now = [0]
        self.runtime.clock = lambda: now[0]
        self.runtime.inspect_tree(APP)
        now[0] = 31
        self.assertEqual(self.runtime.find_element(APP, {"identifier": "input"})["error"], "stale_observation")

    def test_native_stale_element_rejected(self):
        self.adapter.fault = "stale_element"
        self.assertEqual(self.action()["error"], "stale_element")
        self.assertEqual(self.adapter.sent, 0)

    def test_native_element_changed_rejected(self):
        self.adapter.fault = "element_changed"
        self.assertEqual(self.action()["error"], "element_changed")
        self.assertEqual(self.adapter.sent, 0)

    def test_app_closed(self):
        self.adapter.closed = True
        self.assertEqual(self.runtime.inspect_tree(APP)["error"], "app_closed")

    def test_app_closed_between_observation_and_action(self):
        observed = self.runtime.inspect_tree(APP)
        self.adapter.closed = True
        result = self.registry.call("set_value", {"app": APP, "element": "input", "observation": observed["observation"], "value": "new", "postcondition": condition()})
        self.assertFalse(result["action_sent"])

    def test_focus_stealing_is_detected_and_pauses(self):
        self.adapter.fault = "focus"
        result = self.action()
        self.assertTrue(result["focus_changed"])
        self.assertTrue(self.runtime.paused)
        self.assertEqual(self.runtime.summary()["rates"]["focus_interference_rate"], 1)

    def test_real_mouse_position_contract_unchanged(self):
        result = self.action()
        self.assertEqual(result["before_mouse"], result["after_mouse"])
        self.assertEqual(self.runtime.summary()["rates"]["mouse_interference_rate"], 0)

    def test_mouse_change_is_detected_and_pauses(self):
        self.adapter.fault = "mouse"
        self.assertTrue(self.action()["mouse_changed"])
        self.assertTrue(self.runtime.paused)

    def test_default_blocks_users_foreground_app(self):
        self.adapter.env["frontmost_app"] = APP
        self.assertEqual(self.action()["error"], "user_app_active")
        self.assertEqual(self.adapter.sent, 0)

    def test_other_app_recent_input_pauses_before_background_dispatch(self):
        tree = self.runtime.observe(APP)
        self.adapter.env["input_idle_seconds"] = 0
        result = self.runtime.act("set_value", APP, "input", tree["observation"], condition(), value="new")
        self.assertEqual(result["error"], "user_input_active")
        self.assertFalse(result["action_sent"])
        self.assertEqual(self.adapter.sent, 0)
        self.assertTrue(self.runtime.paused)

    def test_unknown_focus_blocks_background_write_but_not_ax_reads(self):
        self.adapter.env.update(focus_observable=False, focused_element={})
        self.assertEqual(self.action()["error"], "background_input_focus_unknown")
        self.assertEqual(self.adapter.sent, 0)
        self.assertTrue(self.runtime.paused)
        self.assertEqual(self.runtime.observe(APP)["status"], "ok")

    def test_idle_timer_does_not_attest_ime_composition_is_finished(self):
        for role in ("AXTextField", "AXTextArea", "AXComboBox", "AXSecureTextField"):
            with self.subTest(role=role):
                self.runtime.pause_requested.clear()
                self.runtime.state = ControlState.AGENT
                self.adapter.env.update(focused_element={"role": role}, input_idle_seconds=60)
                self.assertEqual(self.action()["error"], "user_text_input_active")
        self.assertEqual(self.adapter.sent, 0)

    def test_input_started_between_runtime_check_and_native_dispatch_pauses(self):
        original = self.adapter.action
        def native_block(*args, **kwargs):
            before = self.adapter.environment()
            before["input_idle_seconds"] = 0
            return {"status": "error", "error": "user_input_active", "action_sent": False, "before": before}
        self.adapter.action = native_block
        result = self.action()
        self.assertEqual(result["error"], "user_input_active")
        self.assertFalse(result["action_sent"])
        self.assertFalse(result["verification_attempted"])
        self.assertTrue(self.runtime.paused)
        self.assertIsNotNone(self.runtime.last_handoff)
        self.adapter.action = original
        self.assertEqual(self.action()["error"], "computer_paused")
        self.assertEqual(self.adapter.sent, 0)

    def test_other_app_mouse_and_foreground_change_before_action_is_not_agent_interference(self):
        tree = self.runtime.observe(APP)
        self.adapter.env.update(frontmost_app="notes.app", frontmost_pid=42, mouse=[300, 400])
        result = self.runtime.act("set_value", APP, "input", tree["observation"], condition(), value="new")
        self.assertTrue(result["verified"])
        self.assertFalse(result["focus_changed"])
        self.assertFalse(result["mouse_changed"])

    def test_background_show_menu_is_blocked_before_dispatch(self):
        self.adapter.nodes[1]["actions"].append("AXShowMenu")
        result = self.action("invoke_action", "button", condition("result", "menu"), action="AXShowMenu")
        self.assertEqual(result["error"], "foreground_action_required")
        self.assertEqual(self.adapter.sent, 0)

    def test_background_popup_press_and_menu_pick_are_blocked(self):
        for role, tool, args in [("AXPopUpButton", "press", {}), ("AXMenuButton", "press", {}), ("AXMenuItem", "select", {})]:
            self.adapter.nodes[1].update(role=role, actions=["AXPress", "AXPick"])
            result = self.action(tool, "button", condition("result", "changed"), **args)
            self.assertEqual(result["error"], "foreground_action_required")
        self.assertEqual(self.adapter.sent, 0)

    def test_postcondition_changed_requires_actual_observed_value(self):
        tree = self.runtime.observe(APP)
        check = {"selector": {"identifier": "input"}, "attribute": "value", "not_equals": "old"}
        self.assertFalse(self.runtime._postcondition(tree, check))
        tree["nodes"][0]["value"] = "new"
        self.assertTrue(self.runtime._postcondition(tree, check))
        tree["nodes"][0]["value"] = None
        self.assertFalse(self.runtime._postcondition(tree, check))

    def test_existence_and_dynamic_text_selector(self):
        tree = self.runtime.observe(APP)
        check = {"selector": {"role": "AXStaticText", "value": "ready"}, "exists": True}
        self.assertTrue(self.runtime._postcondition(tree, check))
        check["exists"] = False
        self.assertFalse(self.runtime._postcondition(tree, check))
        check["selector"]["value"] = "absent"
        self.assertTrue(self.runtime._postcondition(tree, check))

    def test_conflicting_postconditions_are_rejected(self):
        with self.assertRaises(ValueError):
            self.runtime._validate_condition({**condition(), "not_equals": "old"})
        with self.assertRaises(ValueError):
            self.runtime._validate_condition({"selector": {"role": "AXButton"}, "exists": "yes"})

    def test_clipped_value_cannot_pass_full_value_postcondition(self):
        tree = self.runtime.observe(APP)
        tree["nodes"][0]["value_omitted_chars"] = 100
        self.assertFalse(self.runtime._postcondition(tree, condition(value="old")))

    def test_secure_text_subrole_is_denied_before_native_dispatch(self):
        self.adapter.nodes[0]["subrole"] = "AXSecureTextField"
        self.assertEqual(self.action()["error"], "secure_element_requires_human")
        self.assertEqual(self.adapter.sent, 0)

    def test_structured_tree_survives_output_limit(self):
        self.adapter.nodes[0]["path"] = [0, 0]
        self.adapter.nodes.extend([{**self.adapter.nodes[0], "handle": f"extra-{i}", "value": "x" * 1000} for i in range(100)])
        self.registry.gateway.max_output_bytes = 1800
        result = self.registry.call("inspect_tree", {"app": APP})
        self.assertIn("nodes", result)
        self.assertTrue(result["payload_truncated"])
        self.assertGreater(result["omitted_nodes"], 0)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode()), 1800)
        self.assertNotIn("result_preview", result)
        self.assertEqual(result["nodes"][0]["path"], [0, 0])

    def test_verification_and_resync_preserve_window_scope(self):
        bounds_seen = []
        original = self.adapter.inspect_tree
        def record(app, **bounds):
            bounds_seen.append(bounds)
            return original(app, **bounds)
        self.adapter.inspect_tree = record
        tree = self.runtime.inspect_tree(APP, window_title="Disposable doc", include_menu_bar=True)
        self.registry.call("set_value", {"app": APP, "element": "input", "observation": tree["observation"], "value": "new", "postcondition": condition()})
        self.runtime.take_over(); self.runtime.resume()
        self.assertTrue(all(b.get("window_title") == "Disposable doc" for b in bounds_seen))
        self.assertTrue(all(b.get("include_menu_bar") for b in bounds_seen))

    def test_unknown_action_replaces_previous_success_receipt(self):
        self.assertTrue(self.action()["verified"])
        self.adapter.fault = "timeout"
        result = self.action(post=condition(value="later"), value="later")
        self.assertEqual(result["error"], "action_outcome_unknown")
        self.assertIsNone(self.runtime.last_receipt["verified"])
        self.assertEqual(self.runtime.counts["unknown_dispatches"], 1)

    def test_interference_takeover_retains_pre_action_baseline(self):
        self.runtime.inspect_tree(APP, window_title="scope")
        self.adapter.fault = "focus"
        hit = self.runtime.find_element(APP, {"identifier": "input"})
        self.runtime.act("set_value", APP, "input", hit["observation"], condition(), value="new")
        self.runtime.take_over()
        self.assertEqual(self.runtime.last_handoff[APP]["bounds"]["window_title"], "scope")

    def test_user_takeover_resume_diff_and_handle_invalidation(self):
        first = self.runtime.observe(APP)
        self.assertTrue(self.runtime.take_over()["quiescent"])
        self.assertEqual(self.runtime.act("set_value", APP, "input", first["observation"], condition(), value="new")["error"], "computer_paused")
        self.adapter.nodes[0]["value"] = "manual"
        resumed = self.runtime.resume()
        self.assertTrue(resumed["changes"][0]["changed"])
        self.assertNotEqual(resumed["changes"][0]["observation"], first["observation"])
        self.assertFalse(self.runtime.paused)

    def test_takeover_ack_waits_for_inflight_and_stops_next_action(self):
        self.adapter.block = True
        action_thread = threading.Thread(target=self.action)
        action_thread.start()
        self.assertTrue(self.adapter.entered.wait(1))
        ack = []
        takeover = threading.Thread(target=lambda: ack.append(self.runtime.take_over()))
        takeover.start()
        self.assertTrue(self.runtime.pause_requested.wait(1))
        self.assertFalse(ack)
        self.adapter.release.set()
        action_thread.join(2); takeover.join(2)
        self.assertTrue(ack[0]["quiescent"])
        self.assertEqual(self.action()["error"], "computer_paused")
        self.assertEqual(self.adapter.sent, 1)

    def test_locked_unlocked_transition_requires_explicit_resync(self):
        self.runtime.poll_environment()
        self.adapter.env["locked"] = True
        self.runtime.poll_environment()
        self.assertEqual(self.runtime.state, ControlState.LOCKED)
        self.assertEqual(self.runtime.resume()["status"], "error")
        self.adapter.env["locked"] = False
        self.runtime.poll_environment()
        self.assertEqual(self.runtime.state, ControlState.RESYNC)
        self.assertTrue(self.runtime.paused)
        self.assertEqual(self.runtime.resume()["status"], "ok")

    def test_unknown_session_pauses(self):
        self.adapter.env["session_available"] = False
        self.runtime.poll_environment()
        self.assertTrue(self.runtime.paused)

    def test_wake_invalidates_handles_even_without_lock_transition(self):
        self.runtime.observe(APP)
        self.adapter.env["sleep_total_seconds"] = 5
        self.runtime.poll_environment()
        self.assertEqual(self.runtime.state, ControlState.RESYNC)
        self.assertFalse(self.runtime.observations)

    def test_failed_resync_keeps_all_actions_paused(self):
        self.runtime.take_over()
        self.adapter.closed = True
        self.assertEqual(self.runtime.resume()["error"], "app_closed")
        self.assertTrue(self.runtime.paused)

    def test_resync_without_baseline_does_not_invent_a_change(self):
        self.runtime.take_over()
        change = self.runtime.resume()["changes"][0]
        self.assertIsNone(change["changed"])
        self.assertFalse(change["baseline_available"])

    def test_unobservable_focus_is_unknown_not_proven_unchanged(self):
        self.adapter.env.update(focus_observable=False, focused_element={})
        self.runtime.observe(APP)
        self.assertEqual(self.runtime.summary()["focus_measurement"]["AX_focused_element"], "UNKNOWN")

    def test_unknown_mouse_position_denies_write(self):
        self.adapter.env["mouse"] = []
        self.assertEqual(self.action()["error"], "non_interference_unknown")
        self.assertEqual(self.adapter.sent, 0)

    def test_negative_foreground_pid_is_unknown_not_valid_process(self):
        self.adapter.env["frontmost_pid"] = -1
        self.assertEqual(self.action()["error"], "non_interference_unknown")
        self.assertEqual(self.adapter.sent, 0)

    def test_failing_observer_does_not_replay_or_hide_action_receipt(self):
        def broken(*args, **kwargs):
            raise RuntimeError("renderer failed")
        self.runtime.event_callback = broken
        result = self.action()
        self.assertTrue(result["verified"])
        self.assertEqual(self.adapter.sent, 1)
        self.assertTrue(self.runtime.observer_errors)

    def test_action_started_observer_takeover_cancels_native_dispatch(self):
        acknowledgments = []
        def observer(name, **data):
            if name == "ComputerActionStarted":
                acknowledgments.append(self.runtime.take_over())
        self.runtime.event_callback = observer
        self.assertEqual(self.action()["error"], "computer_paused")
        self.assertTrue(acknowledgments[0]["quiescent"])
        self.assertEqual(self.adapter.sent, 0)

    def test_fallback_usage_accounting_no_vision(self):
        result = self.action("expand", "button", condition("result", "expanded"))
        self.assertEqual(result["error"], "unsupported_action")
        self.assertEqual(self.runtime.summary()["rates"]["vision_fallback_rate"], 0)
        self.assertEqual(self.adapter.sent, 0)
        self.assertTrue(any(e["type"] == "ComputerFallbackRequired" for e in self.runtime.events))

    def test_transport_unknown_outcome_never_retries(self):
        self.adapter.fault = "timeout"
        result = self.action()
        self.assertEqual(result["error"], "action_outcome_unknown")
        self.assertIsNone(result["verified"])
        self.assertIsNone(result["action_sent"])
        self.assertTrue(self.runtime.paused)
        self.assertEqual(self.runtime.last_receipt, result)

    def test_permission_preview_and_audit(self):
        self.registry.gateway.mode = "approve-mutations"
        result = self.action()
        self.assertEqual(result["status"], "approval_required")
        self.assertEqual(result["risk_summary"]["resource"]["arguments"]["app"], APP)
        self.assertEqual(self.adapter.sent, 0)
        self.assertTrue(self.registry.gateway.audit)

    def test_plan_and_readonly_worker_cannot_write_even_with_approval(self):
        self.registry.gateway.plan_read_only = True
        result = self.action()
        self.assertEqual(result["status"], "denied")
        self.registry.gateway.plan_read_only = False
        self.registry.gateway.capabilities = CapabilityPolicy(read_only=True)
        self.assertEqual(self.action()["status"], "denied")

    def test_host_policy_arguments_cannot_be_injected(self):
        with self.assertRaises(TypeError):
            self.action(allow_frontmost=True)
        self.assertEqual(self.adapter.sent, 0)

    def test_app_allowlist_cannot_be_relaxed(self):
        with self.assertRaises(PermissionError):
            self.runtime.observe("other.app")

    def test_unqualified_background_contract_blocks_write(self):
        self.runtime.background_safe_apps = frozenset()
        self.assertEqual(self.action()["error"], "background_contract_unknown")
        self.assertEqual(self.adapter.sent, 0)

    def test_metrics_without_samples_are_unknown(self):
        self.assertIsNone(self.runtime.summary()["rates"]["ax_action_success_rate"])

    def test_schema_host_handoff_not_model_visible(self):
        names = {s["function"]["name"] for s in self.registry.schemas()}
        self.assertIn("set_value", names)
        self.assertNotIn("take_over", names)
        self.assertNotIn("resume", names)

    def test_cli_takeover_cancels_pending_approval(self):
        self.registry.gateway.mode = "approve-mutations"
        tree = self.runtime.observe(APP)
        pending = {}
        args = {"app": APP, "element": "input", "observation": tree["observation"], "value": "new", "postcondition": condition()}
        control(self.runtime, self.registry, "set_value " + json.dumps(args), pending)
        self.assertTrue(pending)
        control(self.runtime, self.registry, "/takeover", pending)
        self.assertFalse(pending)
        self.assertEqual(self.adapter.sent, 0)


class SessionComputerTests(unittest.TestCase):
    def make_session(self, backend, mode="full-permission", budgets=None, **kwargs):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.adapter = MemoryAX()
        self.runtime = ComputerRuntime(self.adapter, allowed_apps=[APP], verification_timeout=0)
        registry = create_default_registry(self.tmp.name, permission_mode=mode)
        return AgentSession(registry, backend=backend, policy="cloud-only", computer_runtime=self.runtime,
            budgets=budgets or SessionBudgets(max_steps=10), streaming=False, **kwargs)

    def dynamic_write(self, messages):
        tree = json.loads(next(m.content for m in reversed(messages) if m.role == "tool"))["result"]
        return response("set_value", {"app": APP, "element": "input", "observation": tree["observation"], "value": "new", "postcondition": condition()}, "write")

    def test_same_session_events_working_evidence_and_goals(self):
        backend = ScriptBackend(response("manage_goal", {"action": "create", "description": "AX task"}, "goal"),
            response("inspect_tree", {"app": APP}, "observe"), self.dynamic_write, response())
        session = self.make_session(backend)
        result = session.run_turn("Test the fixture")
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(session._goal_records()), 1)
        self.assertTrue(session.working.operations[-1]["computer"]["verified"])
        self.assertEqual(session.working.snapshot(phase="test", plan=None, goals=[], pending=None)["computer"]["counts"]["actions_sent"], 1)
        self.assertTrue(any(e.type == "ComputerActionFinished" for e in session.events.events))
        self.assertEqual(result.engineering_status, "unverified")

    def test_gateway_approval_resumes_same_call_once(self):
        session = self.make_session(ScriptBackend(response("inspect_tree", {"app": APP}, "observe"), self.dynamic_write, response()), mode="approve-mutations")
        self.assertEqual(session.run_turn("Edit fixture").status, "approval_required")
        self.assertEqual(self.adapter.sent, 0)
        self.assertEqual(session.approve().status, "completed")
        self.assertEqual(self.adapter.sent, 1)

    def test_handoff_at_approval_invalidates_old_write_and_replans(self):
        session = self.make_session(ScriptBackend(response("inspect_tree", {"app": APP}, "observe"), self.dynamic_write, response()), mode="approve-mutations")
        session.run_turn("Edit fixture")
        session.take_over_computer()
        self.adapter.nodes[0]["value"] = "human"
        result = session.resume_computer()
        self.assertEqual(result.status, "completed")
        self.assertEqual(self.adapter.sent, 0)
        self.assertIsNone(session.pending_approval)
        self.assertTrue(any("human_handoff_invalidated" in (m.content or "") for m in session.messages if m.role == "tool"))

    def test_approval_never_resumes_human_control(self):
        session = self.make_session(ScriptBackend(response("inspect_tree", {"app": APP}, "observe"), self.dynamic_write, response()), mode="approve-mutations")
        session.run_turn("Edit fixture")
        session.take_over_computer()
        self.assertEqual(session.approve().status, "computer_paused")
        self.assertEqual(self.adapter.sent, 0)

    def test_handoff_model_receives_human_change_and_fresh_state_with_same_budget(self):
        def resumed(messages):
            handoff = next(m.content for m in reversed(messages) if m.role == "user" and "Computer control returned" in (m.content or ""))
            data = json.loads(handoff.split("\n", 1)[1])
            self.assertTrue(data["changes"][0]["changed"])
            tree = data["observations"][APP]
            self.assertEqual(tree["nodes"][0]["value"], "human edit")
            self.assertNotEqual(tree["observation"], old_observation)
            self.assertEqual(session.working.no_progress, 0)
            self.assertEqual(session.state, SessionState.TURN_RUNNING)
            self.assertEqual(session._attempts, attempts + 1)
            self.assertGreater(session._token_units, units)
            return response("set_value", {"app": APP, "element": "input", "observation": tree["observation"],
                "value": "new", "postcondition": condition()}, "fresh-write")
        session = self.make_session(ScriptBackend(response("inspect_tree", {"app": APP}, "observe"),
            self.dynamic_write, resumed, response()), mode="approve-mutations")
        session.run_turn("Edit fixture")
        old_observation = self.runtime.observations[APP]["token"]
        attempts, units = session._attempts, session._token_units
        session.working.no_progress = 3
        session.take_over_computer()
        self.adapter.nodes[0]["value"] = "human edit"
        result = session.resume_computer()
        self.assertEqual(result.status, "approval_required")
        self.assertFalse(session._finalizing)
        self.assertEqual(session._attempts, attempts + 1)
        self.assertEqual(self.adapter.sent, 0)
        self.assertEqual(session.approve().status, "completed")
        self.assertEqual(self.adapter.sent, 1)
        self.assertEqual(self.adapter.nodes[0]["value"], "new")

    def test_changed_ax_content_is_progress_but_handle_churn_is_not(self):
        session = self.make_session(ScriptBackend())
        session.working.start("Observe fixture")
        for i, value in enumerate(["old", "human", "human", "human", "human"]):
            tree = {"status": "ok", "app": APP, "epoch": i, "observation": str(i),
                "nodes": [{"handle": str(i), "identifier": "input", "value": value, "value_sha256": value}]}
            call = ToolCall(str(i), "inspect_tree", json.dumps({"app": APP}))
            session.working.record(call, {"ok": True, "result": tree})
            self.assertEqual(session.working.no_progress, max(0, i - 1))

    def test_repeated_ax_verification_hash_churn_still_reaches_stagnation(self):
        session = self.make_session(ScriptBackend())
        for i in range(4):
            call = ToolCall(str(i), "verify", json.dumps({"app": APP, "postcondition": condition()}))
            session.working.record(call, {"ok": True, "result": {"status": "ok", "verified": True,
                "observation": str(i), "tree_hash": str(i)}})
        self.assertEqual(session.working.no_progress, 3)

    def test_failed_locked_resume_does_not_reset_stagnation_or_resume_model(self):
        backend = ScriptBackend(response("inspect_tree", {"app": APP}, "observe"), self.dynamic_write)
        session = self.make_session(backend, mode="approve-mutations")
        session.run_turn("Edit fixture")
        session.take_over_computer()
        session.working.no_progress = 3
        attempts = session._attempts
        self.adapter.env["locked"] = True
        self.assertEqual(session.resume_computer()["error"], "locked_or_unknown")
        self.assertEqual(session.working.no_progress, 3)
        self.assertEqual(session._attempts, attempts)
        self.assertEqual(session.state, SessionState.COMPUTER_PAUSED)
        self.assertEqual(self.adapter.sent, 0)

    def test_handoff_preserves_existing_finalization_and_receipts(self):
        def final(messages):
            self.assertTrue(session._finalizing)
            self.assertEqual(session._final_reason, "step_reserve")
            self.assertEqual(session.state, SessionState.FINALIZING)
            return response()
        session = self.make_session(ScriptBackend(response("inspect_tree", {"app": APP}, "observe"),
            self.dynamic_write, final), mode="approve-mutations")
        session.run_turn("Edit fixture")
        session._enter_finalizing("step_reserve")
        session.take_over_computer()
        session.resume_computer()
        self.assertTrue(any(r["payload"].get("error", {}).get("type") == "human_handoff_invalidated"
                            for r in session.tool_history))
        self.assertEqual(self.adapter.sent, 0)

    def test_new_turn_does_not_treat_previous_ax_receipt_as_current_success(self):
        def second_turn(messages):
            state = session._working_snapshot()
            self.assertEqual(state["original_task"], "Restore old value")
            self.assertIsNone(state["computer"]["last_receipt"])
            self.assertTrue(state["computer"]["prior_turn_receipt_omitted"])
            self.assertEqual(state["computer"]["last_receipt_turn_id"], 1)
            self.assertEqual(state["operations"], [])
            return response()
        session = self.make_session(ScriptBackend(response("inspect_tree", {"app": APP}, "observe"),
            self.dynamic_write, response(), second_turn))
        session.run_turn("Edit fixture")
        self.assertEqual(self.runtime.last_receipt["postcondition"], condition())
        self.assertTrue(session.working.computer["last_receipt"]["verified"])
        session.run_turn("Restore old value")
        self.assertTrue(self.runtime.last_receipt["verified"])

    def test_resume_preserves_locked_write_intent_after_failed_call_left_queue(self):
        def resumed(messages):
            data = json.loads(next(m.content for m in reversed(messages) if m.role == "user").split("\n", 1)[1])
            intent = data["pending_actions"][0]
            self.assertEqual(intent["desired_value"], "new")
            self.assertEqual(intent["postcondition"], condition())
            self.assertEqual(intent["status"], "unverified_intent_requires_replan")
            self.assertIs(intent["prior_action_sent"], False)
            self.assertEqual(session._working_snapshot()["computer"]["pending_actions"], data["pending_actions"])
            tree = data["observations"][APP]
            return response("set_value", {"app": APP, "element": "input", "observation": tree["observation"],
                "value": "new", "postcondition": condition()}, "resumed-new-write")
        session = self.make_session(ScriptBackend(response("inspect_tree", {"app": APP}, "observe"),
            self.dynamic_write, resumed, response()), mode="approve-mutations")
        session.run_turn("Edit fixture")
        self.adapter.env["locked"] = True
        self.assertEqual(session.approve().status, "computer_paused")
        self.assertFalse(session._queue)
        self.adapter.env["locked"] = False
        self.assertEqual(session.resume_computer().status, "approval_required")
        self.assertEqual(self.adapter.sent, 0)
        self.assertEqual(session.approve().status, "completed")
        self.assertEqual(self.adapter.sent, 1)
        self.assertFalse(session._working_snapshot()["computer"]["pending_actions"])

    def test_compacted_resume_preserves_latest_target_and_scoped_observation(self):
        def initial_write(messages):
            host = next(m.content for m in messages if m.role == "user" and (m.content or "").startswith("Host working state"))
            observed = json.loads(host.split("\n", 1)[1])["computer"]["current_observation"]
            node = next(n for n in observed["nodes"] if n.get("identifier") == "input")
            return response("set_value", {"app": APP, "element": node["handle"], "observation": observed["observation"],
                "value": "new", "postcondition": condition()}, "initial-write")
        def replanned(messages):
            host = next(m.content for m in messages if m.role == "user" and (m.content or "").startswith("Host working state"))
            state = json.loads(host.split("\n", 1)[1])
            self.assertTrue(state["computer"]["host_resume_completed"])
            self.assertEqual(state["computer"]["resync_generation"], 1)
            observed = state["computer"]["current_observation"]
            node = next(n for n in observed["nodes"] if n.get("identifier") == "input")
            self.assertEqual(node["value"], "human")
            self.assertTrue(observed["omitted_nodes"])
            self.assertFalse(observed["expired"])
            compacted = [e for e in session.events.events if e.type == "ContextCompacted"]
            self.assertTrue(compacted)
            self.assertLess(compacted[-1].data["state_limit_bytes"], session.working.max_snapshot_bytes)
            self.assertFalse(state["plan_mode"])
            self.assertEqual(messages[-1].role, "user")
            self.assertIn("Computer control returned by the human host", messages[-1].content)
            self.assertIn("Request projection", messages[-1].content)
            self.assertTrue(compacted[-1].data["retained_host_resume_instruction"])
            canonical = session._computer_resume_message
            self.assertNotIn("Request projection", canonical.content)
            self.assertIn('"observations"', canonical.content)
            return response("set_value", {"app": APP, "element": node["handle"], "observation": observed["observation"],
                "value": "new", "postcondition": condition()}, "compacted-new-write")
        backend = ScriptBackend(response("inspect_tree", {"app": APP}, "observe"), initial_write, replanned, response())
        backend.model_info = ModelInfo("script", "scripted-controller", 65536)
        session = self.make_session(backend, mode="approve-mutations", budgets=SessionBudgets(max_steps=16, max_token_units=1048576))
        self.adapter.nodes += [{"handle": "label" + str(i), "role": "AXStaticText", "value": "unrelated UI text " * 12} for i in range(40)]
        session.run_turn("Edit fixture. " + "Known task context. " * 45)
        session.take_over_computer()
        self.adapter.nodes[0]["value"] = "human"
        self.assertEqual(session.resume_computer().status, "approval_required")
        self.assertEqual(self.adapter.sent, 0)
        self.assertEqual(session.approve().status, "completed")
        self.assertEqual(self.adapter.sent, 1)

    def test_compacted_resume_keeps_latest_read_as_complete_partial_tool_group(self):
        def find_after_read(messages):
            host = next(m.content for m in messages if m.role == "user" and (m.content or "").startswith("Host working state"))
            state = json.loads(host.split("\n", 1)[1])
            self.assertEqual([m.role for m in messages[-2:]], ["assistant", "tool"])
            call = messages[-2].tool_calls[0]
            self.assertEqual(messages[-1].tool_call_id, call.id)
            result = json.loads(messages[-1].content)["result"]
            self.assertTrue(result["truncated"])
            self.assertIn("context_projection", result)
            target = next(n for n in result["nodes"] if n.get("identifier") == "input")
            self.assertEqual(target["value"], "human" if state["computer"]["host_resume_completed"] else "old")
            self.assertEqual(result["observation"], self.runtime.observations[APP]["token"])
            # Projection must leave the canonical receipt and its full nodes intact.
            canonical = json.loads(session.messages[-1].content)["result"]
            self.assertEqual(len(canonical["nodes"]), 43)
            self.assertNotIn("context_projection", canonical)
            if call.id == "resumed-read":
                self.assertIsNone(messages[-2].content)
                self.assertTrue(json.loads(messages[-1].content)["context_projection"]["assistant_narration_omitted"])
                self.assertGreater(len(session.messages[-2].content), 8000)
                self.assertEqual(len(state["computer"]["current_observation"]["nodes"]), 1)
            return response("find_element", {"app": APP, "selector": {"identifier": "input"}}, "find-" + call.id)

        def write(messages):
            last = json.loads(messages[-1].content)["result"]
            return response("set_value", {"app": APP, "element": last["element"], "observation": last["observation"],
                "value": "new", "postcondition": condition()}, "write-" + messages[-1].tool_call_id)

        narrated_read = response("observe", {"app": APP}, "resumed-read")
        narrated_read.message.content = "I need to inspect the tree before finding and writing. " * 200
        backend = ScriptBackend(response("inspect_tree", {"app": APP}, "initial-read"), find_after_read, write,
            narrated_read, find_after_read, write, response())
        backend.model_info = ModelInfo("script", "scripted-controller", 65536)
        session = self.make_session(backend, mode="approve-mutations", budgets=SessionBudgets(max_steps=16, max_token_units=1048576))
        self.adapter.nodes += [{"handle": "label" + str(i), "role": "AXStaticText", "value": "unrelated UI text " * 12} for i in range(40)]
        self.assertEqual(session.run_turn("Edit fixture. " + "Known task context. " * 40).status, "approval_required")
        attempts = session._attempts
        session.take_over_computer()
        self.adapter.nodes[0]["value"] = "human"
        self.assertEqual(session.resume_computer().status, "approval_required")
        self.assertGreater(session._attempts, attempts)
        self.assertEqual(self.adapter.sent, 0)
        self.assertTrue(any(e.data.get("projected_ax_read_call_ids") == ["resumed-read"]
                            for e in session.events.events if e.type == "ContextCompacted"))
        self.assertEqual(session.approve().status, "completed")
        self.assertEqual(self.adapter.sent, 1)

    def test_invalidated_read_cannot_be_projected_as_current_tool_result(self):
        session = self.make_session(ScriptBackend(response("inspect_tree", {"app": APP}), response()))
        self.adapter.nodes += [{"handle": "label" + str(i), "role": "AXStaticText", "value": "UI text " * 30} for i in range(40)]
        session.run_turn("Inspect fixture")
        session.messages.pop()  # Inspect the existing complete read group, before its final answer.
        self.runtime.take_over()
        view, sources, _ = session._computer_context_read()
        self.assertIs(view, session.messages)
        self.assertEqual(sources, [])

    def test_copied_resume_text_does_not_acquire_host_message_provenance(self):
        backend = ScriptBackend(response("inspect_tree", {"app": APP}), self.dynamic_write, response())
        session = self.make_session(backend, mode="approve-mutations")
        session.run_turn("Edit fixture")
        session.take_over_computer()
        session.resume_computer()
        session.messages.append(Message("user", session._computer_resume_message.content))
        view, projected, units = session._computer_context_resume()
        self.assertIs(view, session.messages)
        self.assertFalse(projected)
        self.assertEqual(units, 0)

    def test_session_failure_receipt_preserves_applied_ax_side_effect(self):
        session = self.make_session(ScriptBackend(response("inspect_tree", {"app": APP}, "observe"), self.dynamic_write, response()))
        self.adapter.fault = "focus"
        result = session.run_turn("Edit fixture")
        self.assertEqual(result.status, "computer_paused")
        self.assertEqual(session.tool_history[-1]["side_effect_status"], "partial")
        self.assertTrue(session.tool_history[-1]["payload"]["result"]["action_sent"])
        self.assertIsNone(session.tool_history[-1]["payload"]["result"]["verified"])
        self.assertEqual(session.working.operations[-1]["verification"], "unknown")
        self.assertFalse(session.working.operations[-1]["computer"]["verification_attempted"])

    def test_session_timeout_side_effect_is_unknown_not_not_completed(self):
        session = self.make_session(ScriptBackend(response("inspect_tree", {"app": APP}, "observe"), self.dynamic_write, response()))
        self.adapter.fault = "timeout"
        self.assertEqual(session.run_turn("Edit fixture").status, "computer_paused")
        self.assertEqual(session.tool_history[-1]["side_effect_status"], "unknown")
        self.assertEqual(session.working.operations[-1]["verification"], "unknown")

    def test_shared_computer_has_worker_permission_ceiling(self):
        session = self.make_session(ScriptBackend(response()))
        registry = create_default_registry(self.tmp.name, permission_mode="full-permission", capabilities=CapabilityPolicy(read_only=True))
        child = AgentSession(registry, backend=ScriptBackend(response("inspect_tree", {"app": APP}, "observe"), self.dynamic_write, response()), policy="cloud-only", computer_runtime=self.runtime, computer_owner=False, streaming=False)
        self.assertEqual(child.run_turn("Read-only worker").status, "completed")
        self.assertEqual(self.adapter.sent, 0)
        child.close()
        self.assertNotEqual(self.runtime.state, ControlState.CLOSED)
        session.close()
        self.assertEqual(self.runtime.state, ControlState.CLOSED)
