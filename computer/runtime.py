"""Semantic device controller, not an Agent loop. All tools registered in the existing Gateway."""
from collections import Counter, deque
from copy import deepcopy
from enum import Enum
import hashlib
import inspect
import json
import math
import threading
import time

from agent.permissions import ToolRiskMetadata
from .schemas import SCHEMAS, NATIVE_SCHEMAS, WRITE_NAMES
from .build import FIXTURE_ID
from .backend import AXBackend, ComputerBackend


class ControlState(str, Enum):
    AGENT = "agent_controlling"
    HUMAN = "human_controlling"
    RESYNC = "resync_required"
    LOCKED = "locked"
    INTERFERENCE = "interference_paused"
    CLOSED = "closed"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def error(code, message, **extra):
    return {"status": "error", "error": code, "message": message, **extra}


class ComputerRuntime:
    def __init__(self, adapter, *, allowed_apps, event_callback=None, allow_frontmost=False,
                 observation_ttl=30, verification_timeout=1, clock=time.monotonic, background_safe_apps=None):
        if not allowed_apps or not set(allowed_apps) <= adapter.allowed_apps:
            raise ValueError("Explicit app scope must be within native adapter allowlist")
        self.backend = adapter if isinstance(adapter, ComputerBackend) else AXBackend(adapter)
        self.adapter = self.backend  # Compatibility name for the existing device controller.
        self.allowed_apps = frozenset(allowed_apps)
        # AXPress is app-defined and can activate an app. Default writes are
        # restricted to our measured disposable fixtures. Qualifying other apps
        # is a trusted host decision, separate from read scope and tool approval.
        self.background_safe_apps = frozenset(background_safe_apps if background_safe_apps is not None else
            self.allowed_apps.intersection({FIXTURE_ID, FIXTURE_ID + ".second"}))
        if not self.background_safe_apps <= self.allowed_apps:
            raise ValueError("Background contract must be within allowed app scope")
        self.allow_frontmost = bool(allow_frontmost)  # Host only; never in model schema.
        self.clock, self.observation_ttl = clock, observation_ttl
        self.verification_timeout = verification_timeout
        self.state = ControlState.AGENT
        self.pause_requested = threading.Event()
        self.lock = threading.RLock()
        self.observations = {}
        self.revision = 0
        self.resync_generation = 0
        self.resync_revision = 0
        self.counts = Counter()
        self.events = deque(maxlen=200)
        self.event_callback = event_callback
        self.observer_errors = deque(maxlen=20)
        self.last_receipt = None
        self.last_handoff = None
        self.last_environment = None

    def emit(self, name, **data):
        item = {"type": name, "data": data}
        self.events.append(item)
        if self.event_callback:
            try:
                self.event_callback(name, **deepcopy(data))
            except Exception as exc:
                # A broken renderer must not replay or hide a completed write.
                self.observer_errors.append(type(exc).__name__)

    @property
    def paused(self):
        return self.pause_requested.is_set() or self.state != ControlState.AGENT

    def invalidate(self):
        self.observations.clear()
        self.revision += 1

    def _scope(self, app):
        if app not in self.allowed_apps:
            raise PermissionError("App is outside host allowlist")

    def poll_environment(self):
        env = self.adapter.environment()
        old = self.last_environment
        self.last_environment = env
        if env.get("locked") is not False or not env.get("session_available", False):
            if self.state not in {ControlState.HUMAN, ControlState.CLOSED}:
                if self.last_handoff is None and self.observations:
                    self.last_handoff = deepcopy(self.observations)
                self.state = ControlState.LOCKED
                self.pause_requested.set()
                self.invalidate()
        elif old and (old.get("locked") is not False or old.get("session_id") != env.get("session_id") or
                      env.get("sleep_total_seconds", 0) - old.get("sleep_total_seconds", 0) > 0.5):
            if self.state not in {ControlState.HUMAN, ControlState.CLOSED}:
                if self.last_handoff is None and self.observations:
                    self.last_handoff = deepcopy(self.observations)
                self.state = ControlState.RESYNC
                self.pause_requested.set()
                self.invalidate()
                self.emit("ComputerResyncRequired", reason="unlock_session_or_wake")
        if old and old.get("locked") != env.get("locked"):
            self.emit("ComputerLockChanged", locked=env.get("locked"), state=self.state.value,
                      source=env.get("lock_signal", "UNKNOWN"))
        return env

    def inspect_apps(self):
        with self.lock:
            return self.adapter.inspect_apps()

    def inspect_tree(self, app, max_nodes=256, max_depth=12, window_title=None, include_menu_bar=False):
        self._scope(app)
        if type(max_nodes) is not int or not 1 <= max_nodes <= 512 or type(max_depth) is not int or not 0 <= max_depth <= 20:
            raise ValueError("Invalid AX enumeration bounds")
        if window_title is not None and (not isinstance(window_title, str) or len(window_title) > 2048):
            raise ValueError("Window title must be bounded text")
        if type(include_menu_bar) is not bool:
            raise ValueError("include_menu_bar must be a host/tool boolean")
        with self.lock:
            env = self.poll_environment()
            if env.get("locked") is not False:
                return error("locked_or_unknown", "Unlock manually before AX observation.")
            bounds = {"max_nodes": max_nodes, "max_depth": max_depth, "window_title": window_title, "include_menu_bar": include_menu_bar}
            tree = self.adapter.inspect_tree(app, **bounds)
            # Native handle table is global; every observation invalidates previous handles.
            self.invalidate()
            if tree.get("status") != "ok":
                self.emit("ComputerObservationFailed", app=app, error=tree.get("error", "UNKNOWN"))
                return self._native_admission_failure(app, "inspect_tree", tree)
            token = f"ax-{self.revision}-{digest(tree)[:16]}"
            record = {"token": token, "tree": deepcopy(tree), "at": self.clock(), "environment": env, "bounds": bounds,
                      "generation": self.revision, "resync_generation": self.resync_generation}
            self.observations[app] = record
            self.counts["observations"] += 1
            self.emit("ComputerObserved", app=app, observation=token, tree_hash=digest(tree),
                      nodes=len(tree["nodes"]), truncated=tree.get("truncated", False))
            return {**tree, "observation": token, "observation_generation": self.revision, "observed_at": record["at"]}

    def observe(self, app):
        return self.inspect_tree(app)

    def inspect_windows(self, app):
        tree = self.inspect_tree(app, max_depth=0)
        return tree

    @staticmethod
    def _matches(nodes, selector):
        if (not isinstance(selector, dict) or not selector or set(selector) - {"role", "identifier", "title", "description", "value"}
            or any((type(v) not in {str, int, float, bool, type(None)} if k == "value" else not isinstance(v, str)) for k, v in selector.items())):
            raise ValueError("Selector needs exact semantic fields")
        return [node for node in nodes if all(not node.get(k + "_omitted_chars", 0) and node.get(k) == v for k, v in selector.items())]

    def _native_admission_failure(self, app, action, result):
        """Scoped native FAIL must yield to the host before another model step."""
        if not getattr(self.backend, 'native_keyboard', False) or self.paused:
            return result
        self.last_handoff = {app: deepcopy(self.observations[app])} if app in self.observations else {}
        self.state = ControlState.RESYNC
        self.pause_requested.set()
        self.backend.request_stop()
        self.invalidate()
        self.last_receipt = {**result, 'action': action, 'app': app,
            'action_sent': False, 'verified': None, 'verification_attempted': False,
            'replay_allowed': False, 'fallback': 'human'}
        self.emit('ComputerActionFinished', **self.last_receipt)
        return deepcopy(self.last_receipt)

    def find_element(self, app, selector):
        self._scope(app)
        with self.lock:
            record = self.observations.get(app)
            if not record or self.clock() - record["at"] > self.observation_ttl:
                return self._native_admission_failure(app, "find_element", error("stale_observation", "Observe again before finding an element."))
            matches = self._matches(record["tree"]["nodes"], selector)
            if len(matches) != 1:
                return self._native_admission_failure(app, "find_element", error("element_not_found" if not matches else "ambiguous_element", "Need exactly one observed element.", matches=len(matches)))
            return {"status": "ok", "element": matches[0]["handle"], "observation": record["token"], "node": deepcopy(matches[0])}

    def _postcondition(self, tree, condition):
        self._validate_condition(condition)
        if tree.get("status") != "ok":
            return False
        if (tree.get("truncated", True) or tree.get("payload_truncated") or tree.get("omitted_nodes", 0)
            or tree.get("AXWindows_error", 0) != 0):
            return False  # Partial evidence cannot prove absence or uniqueness.
        if any(node.get(key + "_omitted_chars", 0) for node in tree["nodes"] for key in condition["selector"]):
            return False  # Clipped selector attributes cannot exclude hidden matches.
        matches = self._matches(tree["nodes"], condition["selector"])
        if "exists" in condition:
            return len(matches) == 1 if condition["exists"] else len(matches) == 0
        if len(matches) != 1:
            return False
        value = matches[0].get(condition["attribute"])
        if condition["attribute"] not in matches[0] or value is None:
            return False  # Missing/unavailable AX attributes do not attest to null.
        if matches[0].get(condition["attribute"] + "_omitted_chars", 0):
            return False  # A clipped attribute is not an exact/full-value attestation.
        if "not_equals" in condition:
            # Missing/null observations cannot prove an actual UI change.
            return value is not None and value != condition["not_equals"]
        return value == condition["equals"]

    def _validate_condition(self, condition):
        if not isinstance(condition, dict):
            raise ValueError("Explicit scalar AX postcondition required")
        if set(condition) == {"selector", "exists"}:
            self._matches([], condition["selector"])
            if type(condition["exists"]) is not bool:
                raise ValueError("Existence postcondition requires a boolean")
            return
        operators = set(condition).intersection({"equals", "not_equals"})
        if len(operators) != 1 or set(condition) != {"selector", "attribute", *operators} or condition["attribute"] not in {"value", "title", "enabled", "description", "selected", "expanded", "selection_length"}:
            raise ValueError("One exact or changed scalar AX postcondition required")
        self._matches([], condition["selector"])
        value = condition[next(iter(operators))]
        if value is not None and type(value) not in {str, int, float, bool}:
            raise ValueError("Postcondition must be scalar")

    def verify(self, app, postcondition):
        self._validate_condition(postcondition)
        tree = self.inspect_tree(app)
        passed = self._postcondition(tree, postcondition)
        self.emit("ComputerVerified", app=app, passed=passed, observation=tree.get("observation"))
        return {"status": "ok" if passed else "error", "verified": passed, "error": None if passed else "postcondition_failed",
                "observation": tree.get("observation"), "tree_hash": digest(tree),
                "observation_generation": tree.get("observation_generation"), "observed_at": tree.get("observed_at")}

    @staticmethod
    def _background_input_error(environment):
        focus = environment.get("focused_element") or {}
        role = focus.get("role")
        if environment.get("focus_observable") is not True or not isinstance(role, str) or role in {"", "AXUnknown"}:
            return "background_input_focus_unknown"
        if role in {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField", "AXSecureTextField"} or focus.get("subrole") == "AXSecureTextField":
            return "user_text_input_active"
        idle = environment.get("input_idle_seconds")
        if type(idle) not in {int, float} or not math.isfinite(idle) or idle < 0:
            return "user_input_state_unknown"
        return "user_input_active" if idle < 1 else None

    def _pause_for_input(self, app, reason, environment):
        self.last_handoff = deepcopy(self.observations) or self.last_handoff
        self.state = ControlState.INTERFERENCE
        self.pause_requested.set()
        self.invalidate()
        self.emit("ComputerInputProtectionPause", app=app, reason=reason, action_sent=False,
                  focus_observable=environment.get("focus_observable"),
                  focused_role=(environment.get("focused_element") or {}).get("role"))

    def act(self, name, app, element, observation, postcondition, **args):
        self._scope(app)
        self._validate_condition(postcondition)
        with self.lock:
            self.counts["action_requests"] += 1
            if self.paused:
                return error("computer_paused", "Human/lock/interference pause is active; no action sent.")
            before = self.poll_environment()
            if self.paused:
                return error("computer_paused", "Runtime paused after fresh environment check.")
            if len(before.get("mouse", [])) != 2 or type(before.get("frontmost_pid")) is not int or before["frontmost_pid"] <= 0:
                result = error("non_interference_unknown", "Mouse/foreground observation unavailable; no write sent.")
                return self._native_admission_failure(app, name, result) if name == "type_text" else result
            record = self.observations.get(app)
            if not record or record["token"] != observation or self.clock() - record["at"] > self.observation_ttl:
                result = error("stale_observation", "Observe and find again; no write sent.")
                return self._native_admission_failure(app, name, result) if name == "type_text" else result
            nodes = [n for n in record["tree"]["nodes"] if n["handle"] == element]
            if len(nodes) != 1:
                result = error("stale_element", "Element is not in this observation.")
                return self._native_admission_failure(app, name, result) if name == "type_text" else result
            if nodes[0].get("role") == "AXSecureTextField" or nodes[0].get("subrole") == "AXSecureTextField":
                result = error("secure_element_requires_human", "Secure text controls require human handling; no AX write sent.")
                return self._native_admission_failure(app, name, result) if name == "type_text" else result
            qualification = self.backend.qualify_action(name, app, nodes[0])
            if qualification.get("status") != "ok":
                self.emit("ComputerCapabilityRejected", app=app, action=name, **qualification)
                return self._native_admission_failure(app, name, qualification) if name == "type_text" else qualification
            concurrent_native = qualification.get("concurrent_input") is True and name == "type_text"
            if before.get("frontmost_app") == app and not self.allow_frontmost:
                self.state = ControlState.INTERFERENCE
                self.pause_requested.set()
                self.emit("ComputerFocusRequired", app=app, reason="user_app_active", supported=False)
                return error("user_app_active", "Default background policy refuses to write to user's active app.")
            if before.get("frontmost_app") != app and not concurrent_native:
                input_error = self._background_input_error(before)
                if input_error:
                    self._pause_for_input(app, input_error, before)
                    return error(input_error, "Background write paused to protect human text/IME input. Manual host resume and a fresh proposal are required; no action sent.",
                                 action_sent=False, verified=None, verification_attempted=False, replay_allowed=False)
            baseline = record["environment"]
            input_reset = before.get("input_idle_seconds", 0) + 0.1 < baseline.get("input_idle_seconds", 0)
            if input_reset or before.get("frontmost_pid") != baseline.get("frontmost_pid") or before.get("focused_element") != baseline.get("focused_element") or before.get("mouse") != baseline.get("mouse"):
                # A prior navigation change is not agent-caused interference.
                # Active/unknown text input above pauses background writes;
                # the native helper checks again immediately before dispatch.
                self.emit("ComputerUserActivity", app=app, reason="other_app_activity_before_dispatch",
                          background_continuation=True, frontmost_app=before.get("frontmost_app"))
            if name != "type_text" and self._postcondition(record["tree"], postcondition):
                return error("postcondition_already_satisfied", "Use verify for an existing state; no unnecessary write sent.")
            action = {"press": "AXPress", "select": "AXPick", "expand": "AXExpand"}.get(name)
            if name == "scroll":
                direction = args.get("direction")
                action = {"up": "AXScrollUpByPage", "down": "AXScrollDownByPage", "left": "AXScrollLeftByPage", "right": "AXScrollRightByPage"}.get(direction)
                if not action:
                    raise ValueError("Invalid scroll direction")
            if name == "invoke_action":
                action = args.get("action")
            if name == "type_text":
                text = args.get("text")
                if set(args) != {"text"} or not isinstance(text, str) or not text or len(text.encode("utf-16-le")) // 2 > 64:
                    raise ValueError("Native text requires 1..64 UTF-16 units")
                targets = self._matches(record["tree"]["nodes"], postcondition["selector"])
                if (postcondition.get("attribute") != "value" or not isinstance(postcondition.get("equals"), str)
                    or len(targets) != 1 or targets[0]["handle"] != element):
                    raise ValueError("Native keyboard requires an exact text value postcondition on the target")
                if self._postcondition(record["tree"], postcondition):
                    return self._native_admission_failure(app, name, error("postcondition_already_satisfied", "Use verify for an existing state; no unnecessary write sent."))
                native_args = {"text": text}
            elif name == "set_value":
                if set(args) != {"value"} or not isinstance(args["value"], str) or len(args["value"]) > 2048:
                    raise ValueError("Bounded text value required")
                native_args = {"value": args["value"]}
            elif name in WRITE_NAMES and action:
                if action not in nodes[0].get("actions", []):
                    self.counts["unsupported_actions"] += 1
                    self.emit("ComputerFallbackRequired", app=app, action=action, fallback="human", vision_used=False)
                    return error("unsupported_action", "AX action not exposed; use human handoff.")
                native_args = {"action": action}
            else:
                raise ValueError("Unknown semantic action")
            foreground_menu = (action == "AXShowMenu" or
                (action in {"AXPress", "AXPick"} and nodes[0].get("role") in {"AXMenuBarItem", "AXMenuItem", "AXMenuButton", "AXPopUpButton"}))
            if foreground_menu and before.get("frontmost_app") != app:
                self.emit("ComputerFocusRequired", app=app, reason="menu_requires_human_foreground",
                          requires_activation=True, supported=False)
                return error("foreground_action_required", "Menu display/selection is not background-safe; ask the human to use the target app. No activation or AX action sent.")
            if (app not in self.background_safe_apps and not concurrent_native
                    and not getattr(self.backend, 'controlled_foreground', False)):
                self.emit("ComputerFocusRequired", app=app, reason="background_contract_unknown",
                          requires_activation="UNKNOWN", supported=False)
                return error("background_contract_unknown", "This app has no host-qualified background contract; no action sent. Use human handoff or qualify the app in a controlled test.")
            # Last cooperative cancellation point. Takeover acknowledgment waits
            # on this lock until a previously sent synchronous AX call completes.
            if self.pause_requested.is_set():
                return error("computer_paused", "Takeover requested before write.")
            self.emit("ComputerActionStarted", app=app, action=name, observation=observation,
                      requires_activation=False, requires_keyboard=name == "type_text", requires_mouse=False)
            if self.pause_requested.is_set():
                return error("computer_paused", "Takeover requested by the observer before native dispatch; no action sent.")
            try:
                result = self.adapter.action(app, element, name, allow_frontmost=self.allow_frontmost, **native_args)
            except Exception as exc:
                self.state = ControlState.RESYNC
                self.pause_requested.set()
                self.last_handoff = {app: deepcopy(record)}
                self.invalidate()
                self.counts["unknown_dispatches"] += 1
                receipt = {"status": "error", "error": "action_outcome_unknown", "error_type": type(exc).__name__,
                    "action": name, "app": app, "action_sent": None, "action_may_have_applied": True,
                    "postcondition": deepcopy(postcondition), "observation": observation, "element": element,
                    "verified": None, "verification_attempted": False, "replay_allowed": False, "fallback": "none"}
                receipt.update(deepcopy(getattr(exc, "computer_receipt", {})))
                self.last_receipt = receipt
                self.emit("ComputerActionUnknown", **receipt)
                return receipt
            if result.get("error") in {"background_input_focus_unknown", "user_text_input_active", "user_input_state_unknown", "user_input_active"}:
                self._pause_for_input(app, result["error"], result.get("before", before))
            else:
                self.invalidate()
            sent = bool(result.get("action_sent"))
            if sent:
                self.counts["actions_sent"] += 1
                self.counts["native_actions_sent" if name == "type_text" else "ax_actions_sent"] += 1
            if result.get("status") == "ok" and name != "type_text":
                self.counts["ax_successes"] += 1
            try:
                after = self.poll_environment()
                native_before = result.get("before", before)
                native_after = result.get("after", after)
                focus_changed = any(native_before.get(k) != e.get(k) for e in (native_after, after) for k in ("frontmost_app", "frontmost_pid", "focused_element"))
                mouse_changed = any(native_before.get("mouse") != e.get("mouse") for e in (native_after, after))
                native_interference = concurrent_native and any(native_before.get(k) != e.get(k)
                    for e in (native_after, after) for k in ("frontmost_app", "frontmost_pid"))
                expected_local_focus = (getattr(self.backend, 'controlled_foreground', False) and
                    all(e.get('frontmost_app') == app and e.get('frontmost_pid') == native_before.get('frontmost_pid')
                        for e in (native_after, after)) and not mouse_changed)
                if (native_interference if concurrent_native else (focus_changed and not expected_local_focus) or mouse_changed):
                    self.last_handoff = {app: deepcopy(record)}
                    self.counts["focus_interference"] += int(focus_changed)
                    self.counts["mouse_interference"] += int(mouse_changed)
                    self.state = ControlState.INTERFERENCE
                    self.pause_requested.set()
                    self.emit("ComputerInterferenceDetected", focus_changed=focus_changed, mouse_changed=mouse_changed,
                              attribution="UNKNOWN_app_or_user", action_may_have_applied=sent)
                # A safety pause can prevent verification even after a native write
                # succeeds. Keep "not attempted" distinct from a failed condition.
                verified = None
                verification_attempted = False
                deadline = self.clock() + self.verification_timeout
                tree = {}
                if result.get("status") == "ok" and not self.paused:
                    verification_attempted = True
                    while True:
                        tree = self.inspect_tree(app, **record.get("bounds", {}))
                        if concurrent_native:
                            matches = self._matches(tree.get("nodes", []), postcondition["selector"])
                            if (tree.get("status") != "ok" or len(matches) != 1 or
                                not isinstance(matches[0].get("value"), str) or matches[0].get("value_omitted_chars", 0)):
                                result = {**result, "error": "verification_unavailable"}
                                break  # Missing/clipped native readback is UNKNOWN, not a mismatched value.
                        verified = self._postcondition(tree, postcondition)
                        if verified or self.paused or self.clock() >= deadline:
                            break
                        time.sleep(0.03)
                    self.counts["verification_attempts"] += 1
                    self.counts["verification_successes"] += int(bool(verified))
                verification_failure = sent and not verified and not self.paused
                if verification_failure:
                    self.last_handoff = {app: deepcopy(record)}
                    self.state = ControlState.RESYNC
                    self.pause_requested.set()
                    self.emit("ComputerVerificationFailed", app=app, action=name, action_may_have_applied=True,
                              resume_requires_host=True)
                receipt = {"status": "ok" if verified and not self.paused else "error", "action": name,
                    "postcondition": deepcopy(postcondition),
                    "app": app, "action_sent": sent, "ax_status": result.get("status"), "ax_error": result.get("ax_error"),
                    "verified": verified, "verification_attempted": verification_attempted,
                    "error": None if verified and not self.paused else (result.get("error") or ("ax_action_failed" if result.get("status") != "ok" else "postcondition_failed" if verification_failure else "interference" if self.paused else "postcondition_failed")),
                    "observation": tree.get("observation"), "before_mouse": native_before.get("mouse"),
                    "after_mouse": after.get("mouse"), "focus_changed": focus_changed, "mouse_changed": mouse_changed,
                    "before_frontmost_app": native_before.get("frontmost_app"), "after_frontmost_app": after.get("frontmost_app"),
                    "before_frontmost_pid": native_before.get("frontmost_pid"), "after_frontmost_pid": after.get("frontmost_pid"),
                    "focus_observable": native_before.get("focus_observable", False) and after.get("focus_observable", False),
                    "input_method_interference": "UNKNOWN",  # AX focus/window equality does not attest IME composition.
                    "interference_attribution": "UNKNOWN_app_or_user" if focus_changed or mouse_changed else "none_observed",
                    "fallback": "none", "tree_hash": digest(tree) if tree else None, "replay_allowed": False}
                if name == "type_text":
                    receipt.update({k: deepcopy(result.get(k)) for k in
                        ("backend", "request_id", "target_identity", "lease", "owner", "dispatch_stage", "posted_events", "target_tap", "input_cleanup", "reason")})
                    receipt["input_method_interference"] = "UNKNOWN_product_E2E_NOT_RUN"
                if name == "type_text" and not verified:
                    self.state = ControlState.RESYNC
                    self.pause_requested.set()
                    self.backend.request_stop()
                    self.last_handoff = {app: deepcopy(record)}
                    self.invalidate()
                self.last_receipt = receipt
                self.emit("ComputerActionFinished", **receipt)
                return receipt
            except Exception as exc:
                # A readback failure cannot erase a known/possible dispatched side effect.
                self.state = ControlState.RESYNC
                self.pause_requested.set()
                self.last_handoff = {app: deepcopy(record)}
                self.invalidate()
                receipt = {"status": "error", "error": "action_outcome_unknown", "action": name,
                    "app": app, "error_type": type(exc).__name__, "action_sent": result.get("action_sent"),
                    "action_may_have_applied": result.get("action_sent") is not False,
                    "postcondition": deepcopy(postcondition), "verified": None,
                    "verification_attempted": False, "replay_allowed": False, "fallback": "none"}
                if name == "type_text":
                    receipt.update({k: deepcopy(result.get(k)) for k in
                        ("backend", "request_id", "target_identity", "lease", "owner", "dispatch_stage", "posted_events", "target_tap", "input_cleanup", "reason")})
                self.last_receipt = receipt
                self.emit("ComputerActionUnknown", **receipt)
                return receipt

    def take_over(self):
        self.pause_requested.set()  # Immediate stop intent before waiting on in-flight action.
        self.backend.request_stop()
        with self.lock:
            if self.state == ControlState.CLOSED:
                raise RuntimeError("Computer runtime closed")
            if self.observations or self.last_handoff is None:
                self.last_handoff = deepcopy(self.observations)
            self.state = ControlState.HUMAN
            self.invalidate()
            cleanup = self.backend.quiesce()
            if cleanup.get("status") != "ok":
                self.emit("ComputerInputCleanupUnknown", cleanup=cleanup)
                return error("input_cleanup_unknown", "Dispatch stopped and quiescent; input release is UNKNOWN.",
                             quiescent=True, state=self.state.value, input_cleanup=cleanup)
            if self.backend.native_keyboard:
                try:
                    for app in sorted(self.allowed_apps):
                        bounds = (self.last_handoff or {}).get(app, {}).get("bounds", {})
                        current = self.inspect_tree(app, **bounds)
                        if current.get("status") != "ok":
                            return {**current, "state": self.state.value, "quiescent": True, "input_cleanup": cleanup}
                except Exception as exc:
                    return error("takeover_observation_unknown", "Quiescent, but handoff readback failed.",
                                 error_type=type(exc).__name__, state=self.state.value, quiescent=True)
                finally:
                    # Readback is evidence only: no retained dispatch identity or lease.
                    self.backend.quiesce()
            self.counts["human_interventions"] += 1
            self.emit("ComputerHumanTakeover", quiescent=True, in_flight_actions=0)
            return {"status": "ok", "state": self.state.value, "quiescent": True, "input_cleanup": cleanup}

    def resume(self):
        with self.lock:
            if self.state == ControlState.CLOSED:
                raise RuntimeError("Computer runtime closed")
            # Cleanup uncertainty must block resume even when a failed native
            # helper can no longer answer environment reads.
            cleanup = self.backend.quiesce()
            if cleanup.get("status") != "ok":
                return error("input_cleanup_unknown", "Host recovery required before native resume.", input_cleanup=cleanup)
            env = self.poll_environment()
            if env.get("locked") is not False:
                return error("locked_or_unknown", "Manual unlock required; remains paused.")
            self.state = ControlState.RESYNC
            self.invalidate()
            changes = []
            for app in sorted(self.allowed_apps):
                previous = (self.last_handoff or {}).get(app, {}).get("tree")
                previous_record = (self.last_handoff or {}).get(app, {})
                current = self.inspect_tree(app, **previous_record.get("bounds", {}))
                if current.get("status") != "ok":
                    self.emit("ComputerResumeFailed", app=app, error=current.get("error"))
                    return current
                fields = lambda tree: [{k: v for k, v in n.items() if k != "handle"} for n in tree.get("nodes", [])]
                changes.append({"app": app, "baseline_available": previous is not None,
                    "before_hash": digest(fields(previous)) if previous is not None else None, "after_hash": digest(fields(current)),
                    "changed": fields(previous) != fields(current) if previous is not None else None,
                    "observation": current["observation"]})
            # Human data never replays a previously proposed mutation. Session
            # discards queued computer writes and asks the same Agent to replan.
            self.last_handoff = None
            self.backend.finish_resume()
            self.resync_generation += 1
            self.resync_revision = self.revision
            self.state = ControlState.AGENT
            self.pause_requested.clear()
            self.emit("ComputerResumed", changes=changes, queued_writes_invalidated=True)
            return {"status": "ok", "state": self.state.value, "changes": changes}

    def summary(self):
        def rate(num, den):
            return self.counts[num] / self.counts[den] if self.counts[den] else None
        return {"state": self.state.value, "revision": self.revision, "counts": dict(self.counts),
            "resync_generation": self.resync_generation, "resync_revision": self.resync_revision,
            "rates": {"ax_action_success_rate": rate("ax_successes", "ax_actions_sent"),
                "verification_success_rate": rate("verification_successes", "verification_attempts"),
                "focus_interference_rate": rate("focus_interference", "actions_sent"),
                "mouse_interference_rate": rate("mouse_interference", "actions_sent"),
                "vision_fallback_rate": rate("vision_fallbacks", "action_requests"),
                "coordinate_fallback_rate": rate("coordinate_fallbacks", "action_requests"),
                "human_intervention_rate": rate("human_interventions", "action_requests")},
            "last_receipt": deepcopy(self.last_receipt), "vision_fallback_enabled": False,
            "focus_measurement": {"frontmost_pid": "observed", "AX_focused_element": "observed" if (self.last_environment or {}).get("focus_observable") else "UNKNOWN"},
            "lock_signal": (self.last_environment or {}).get("lock_signal", "UNKNOWN"),
            "background_safe_apps": sorted(self.background_safe_apps), "observer_errors": list(self.observer_errors),
            "backend": self.backend.name, "backend_capabilities": deepcopy(self.backend.capabilities)}

    def register_tools(self, registry):
        for item in SCHEMAS + (NATIVE_SCHEMAS if self.backend.native_keyboard else []):
            name = item["function"]["name"]
            parameters = item["function"]["parameters"]
            def tool(*, workspace_root, _name=name, **kwargs):
                if _name in WRITE_NAMES:
                    return self.act(_name, **kwargs)
                result = getattr(self, _name)(**kwargs)
                if isinstance(result, dict) and "nodes" in result:
                    # Keep a structured semantic tree under the Gateway's
                    # result bound. The generic string preview loses all nodes.
                    limit = registry.gateway.max_output_bytes
                    bounded = {k: v for k, v in result.items() if k != "nodes"}
                    bounded.update(nodes=[], native_node_count=len(result["nodes"]), omitted_nodes=len(result["nodes"]), payload_truncated=False)
                    for node in result["nodes"]:
                        compact = dict(node)  # AX ancestry is needed to distinguish unnamed controls.
                        for key in ("title", "description", "value"):
                            if isinstance(compact.get(key), str) and len(compact[key]) > 256:
                                compact[key + "_omitted_chars"] = compact.get(key + "_omitted_chars", 0) + len(compact[key]) - 256
                                compact[key] = compact[key][:256]
                        candidate = {**bounded, "nodes": bounded["nodes"] + [compact], "omitted_nodes": bounded["omitted_nodes"] - 1}
                        if len(json.dumps(candidate, ensure_ascii=False).encode()) > limit:
                            break
                        bounded = candidate
                    bounded["payload_truncated"] = bool(bounded["omitted_nodes"])
                    bounded["truncated"] = bounded.get("truncated", False) or bounded["payload_truncated"]
                    return bounded
                return result
            # Explicit call signature prevents model injection of host-only
            # policy fields even when an adapter doesn't validate JSON Schema.
            tool.__signature__ = inspect.Signature([
                inspect.Parameter("workspace_root", inspect.Parameter.KEYWORD_ONLY),
                *[inspect.Parameter(key, inspect.Parameter.KEYWORD_ONLY,
                    default=inspect.Parameter.empty if key in parameters["required"] else {"max_nodes": 256, "max_depth": 12, "window_title": None, "include_menu_bar": False}[key])
                  for key in parameters["properties"]]])
            if self.backend.native_keyboard and name in WRITE_NAMES:
                # Host-owned dynamic constraint, outside the model schema. It
                # follows persistent recovery history even across new Sessions.
                tool._requires_host_approval = self.backend.human_recovery_requires_approval
            registry.register(name, tool, metadata=ToolRiskMetadata(read_only=name not in WRITE_NAMES,
                mutating=name in WRITE_NAMES, external_side_effect=name in WRITE_NAMES), schema=item)

    def close(self):
        self.pause_requested.set()
        self.backend.request_stop()
        with self.lock:
            self.state = ControlState.CLOSED
            self.invalidate()
            self.adapter.close()
