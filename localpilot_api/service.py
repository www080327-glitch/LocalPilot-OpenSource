"""In-process task/session lifecycle. AgentSession remains the only Agent engine."""
from copy import deepcopy
from dataclasses import dataclass, field, fields
import json
import math
import threading
import time
import uuid

from agent.async_runtime import AsyncPolicy, AsyncScheduler
from agent.computer_ledger import computer_obligations
from agent.backends import Message
from agent.session import AgentSession
from agent.persistence import (PersistenceError, SQLiteRuntimeStore, configuration, digest, dumps,
    snapshot_runtime, restore_runtime, recovery_class, nodes, pack, unpack)
from computer.schemas import WRITE_NAMES


SETTLED = {"completed", "incomplete", "failed", "cancelled", "timed_out",
           "requires_approval", "requires_human"}
TERMINAL = SETTLED - {"requires_approval", "requires_human"}
HUMAN_EVENTS = {"ComputerFallbackRequired", "ComputerFocusRequired", "ComputerResumeFailed", "ComputerObservationFailed",
                "ComputerVerificationFailed", "ComputerInterferenceDetected", "ComputerResyncRequired",
                "ComputerHumanTakeover"}
HUMAN_ERRORS = {"secure_element_requires_human", "unsupported_action", "foreground_action_required",
                "background_contract_unknown", "locked_or_unknown", "accessibility_not_trusted"}


def identifier(prefix):
    return prefix + "_" + uuid.uuid4().hex


class APIError(ValueError):
    def __init__(self, message, code="invalid_request", status=400):
        super().__init__(message)
        self.code, self.status = code, status

    def body(self):
        return {"error": {"message": str(self), "type": "invalid_request_error" if self.status < 500 else "server_error",
                          "code": self.code, "param": None}}


@dataclass(frozen=True)
class TaskRequest:
    input: str
    model: str = "localpilot"
    session_id: str | None = None
    history: tuple[Message, ...] = ()
    instructions: str | None = None
    timeout_seconds: float = 120
    max_output_tokens: int | None = None
    previous_task_id: str | None = None
    idempotency_key: str | None = None
    routing_preferences: dict | None = None
    reasoning_effort: str | None = None
    origin_agent: str | None = None
    parent_task_id: str | None = None
    low_power_consent: bool = False


@dataclass
class SessionRecord:
    id: str
    model: str
    runtime: AgentSession
    base_prompt: str
    active_task: str | None = None
    last_task: str | None = None
    closed: bool = False
    task_generation: int = 0
    recovery_epoch: int = 0
    owner_subject: str | None = None  # Service identity, never accepted from model/client JSON.
    thinking_override: str | None = None
    desktop_options: dict | None = None
    desktop_key: str | None = None
    desktop_fingerprint: str | None = None
    extensions: dict | None = None  # Host extensions committed with their configuration identity.


@dataclass
class TaskRecord:
    id: str
    session_id: str
    model: str
    input: str
    previous_task_id: str | None
    created_at: int = field(default_factory=lambda: int(time.time()))
    status: str = "queued"
    result: dict | None = None
    error: dict | None = None
    required_action: dict | None = None
    events: list = field(default_factory=list)
    sequence: int = 0
    executing: bool = False
    stop_reason: str | None = None
    human_signal: dict | None = None
    timer: object = None
    history_start: int = 0
    turn_id: int = 0
    output: list = field(default_factory=list)
    tools: list = field(default_factory=list)
    goals: list = field(default_factory=list)
    subagents: list = field(default_factory=list)
    computer: dict | None = None
    tool_start: int = 0
    operation_tool_start: int = 0
    output_cap: int | None = None
    pending_text: str = ""
    generation_start: int = 0
    model_calls_by_turn: dict = field(default_factory=dict)
    generation: int = 0
    control_pending: bool = False
    deadline: float | None = None
    recovery: dict | None = None
    host_action: dict | None = None
    request_key_digest: str | None = None
    request_fingerprint: str | None = None
    service_metadata: dict | None = None
    execution_metadata: dict | None = None


class TaskService:
    """One serialized turn per session; independent sessions may run concurrently.

    Factories are trusted host routing configuration: logical model IDs do not
    imply a backend. Request data cannot replace a factory, registry or Gateway.
    Sessions/tasks are bounded; an optional store restores durable checkpoints.
    """
    def __init__(self, routes, *, max_sessions=64, max_tasks=512, max_events=4096,
                 max_timeout=3600, persistence=None, auto_resume=False, async_policy=None,
                 session_initializer=None, resource_finalizer=None, configuration_migration=None):
        if not routes or not all(isinstance(k, str) and callable(v) for k, v in routes.items()):
            raise ValueError("routes must map logical model IDs to AgentSession factories")
        if any(type(v) is not int or v <= 0 for v in (max_sessions, max_tasks, max_events, max_timeout)):
            raise ValueError("Service limits must be positive integers")
        self.routes = dict(routes)
        self.session_initializer = session_initializer
        self.resource_finalizer = resource_finalizer
        self.configuration_migration = configuration_migration
        self.max_sessions, self.max_tasks = max_sessions, max_tasks
        self.max_events, self.max_timeout = max_events, max_timeout
        self.sessions, self.tasks = {}, {}
        self.condition = threading.Condition(threading.RLock())
        if async_policy is not None and not isinstance(async_policy, AsyncPolicy):
            raise TypeError('async_policy must be a host AsyncPolicy')
        self.async_policy = async_policy
        self.scheduler = AsyncScheduler(async_policy, self.condition) if async_policy else None
        self.closed = False
        self.store = (SQLiteRuntimeStore(persistence) if isinstance(persistence, (str, bytes)) or hasattr(persistence, "__fspath__") else persistence)
        if self.store is not None and not isinstance(self.store, SQLiteRuntimeStore):
            raise TypeError("persistence must be a SQLiteRuntimeStore or path")
        if self.store:
            try:
                self._restore()
            except Exception as exc:
                self.store.close()
                raise PersistenceError("Persistent service restore refused: " + type(exc).__name__) from exc
            if auto_resume:
                for task in list(self.tasks.values()):
                    if task.recovery and task.recovery["class"] == "SAFE_TO_RESUME":
                        try:
                            self.act(task.id, "continue", task.required_action["id"])
                        except APIError as exc:
                            if exc.code != "action_conflict":
                                raise

    def _available(self):
        if self.store:
            self.store.ensure_available()

    def _checkpoint(self, session_id, point):
        if not self.store:
            return
        with self.condition:
            session = self._session(session_id)
            payload = {"version": 1, "configuration": session.runtime._persistence_config,
                "session": {f.name: getattr(session, f.name) for f in fields(SessionRecord) if f.name != "runtime" and not (f.name=='extensions' and not session.extensions)},
                "runtime": snapshot_runtime(session.runtime),
                "tasks": [pack({f.name: getattr(t, f.name) for f in fields(TaskRecord) if f.name != "timer"})
                          for t in self.tasks.values() if t.session_id == session_id]}
            self.store.save(session_id, payload, point)

    def _attach_persistence(self, session):
        if session.runtime.async_policy != self.async_policy:
            raise ValueError('Async Session and TaskService policies must match')
        if self.scheduler:
            for runtime in nodes(session.runtime):
                runtime._owns_scheduler = False
                runtime._async_enabled = True
                runtime._state_condition, runtime._scheduler = self.condition, self.scheduler
                runtime._scheduler_owner = session.id
        if not self.store:
            return
        if self.store and self.store.path.resolve().is_relative_to(session.runtime.workspace.resolve()):
            raise PersistenceError("Runtime database must be outside the tool workspace")
        for runtime in nodes(session.runtime):
            runtime._persistence_hook = lambda point, sid=session.id: self._checkpoint(sid, point)

    def _arm_timer(self, task):
        if task.deadline is None:
            return
        task.timer = threading.Timer(max(0, task.deadline - time.time()), lambda: self.cancel(task.id, "timed_out"))
        task.timer.daemon = True
        task.timer.start()

    def _restore(self):
        from agent.session import SessionState
        payloads = self.store.load()
        if len(payloads) > self.max_sessions or sum(len(p["tasks"]) for p in payloads) > self.max_tasks:
            raise PersistenceError("Stored tasks exceed host limits")
        # Load/validate all records before arming timers or launching any worker.
        request_keys = set()
        migrated = []
        for payload in payloads:
            if payload["version"] != 1:
                raise PersistenceError("Unsupported service checkpoint version")
            saved = payload["session"]
            sid, model = saved["id"], saved["model"]
            if model not in self.routes:
                raise PersistenceError("Stored route is not configured")
            runtime = self.routes[model](lambda event, s=sid: self._runtime_event(s, event))
            if saved.get('desktop_options') is not None:
                from localpilot_service.desktop_sessions import apply_options
                apply_options(runtime, saved['desktop_options'])
            if saved.get('thinking_override') is not None:
                runtime.thinking_mode=saved['thinking_override']
            runtime._service_extensions = dict(saved.get('extensions') or {})
            if self.session_initializer:
                self.session_initializer(runtime, sid, saved.get('owner_subject'))
            cfg = digest(dumps(configuration(runtime)))
            if cfg != payload["configuration"]:
                migration = getattr(self, 'configuration_migration', None)
                if migration is None or not migration(runtime, payload):
                    raise PersistenceError("Host configuration changed; explicit migration required")
                migrated.append(sid)
            if self.scheduler:
                runtime._state_condition, runtime._scheduler = self.condition, self.scheduler
                runtime._scheduler_owner = sid
            restore_runtime(runtime, payload["runtime"])
            runtime._effective_thinking()
            runtime._persistence_config = cfg
            session = SessionRecord(runtime=runtime, **saved)
            session.recovery_epoch += 1
            self.sessions[sid] = session
            for raw in payload["tasks"]:
                task = TaskRecord(**unpack(raw))
                if task.id in self.tasks or task.session_id != sid:
                    raise PersistenceError("Task identity mismatch")
                if task.request_key_digest is not None or task.request_fingerprint is not None:
                    if any(not isinstance(v, str) or len(v) != 64 or any(c not in '0123456789abcdef' for c in v)
                           for v in (task.request_key_digest, task.request_fingerprint)):
                        raise PersistenceError("Invalid durable request identity")
                    if task.request_key_digest in request_keys:
                        raise PersistenceError("Duplicate durable request identity")
                    request_keys.add(task.request_key_digest)
                task.executing = task.control_pending = False
                self.tasks[task.id] = task
            if session.active_task and (session.active_task not in self.tasks or
                    self.tasks[session.active_task].generation != session.task_generation):
                raise PersistenceError("Active task generation mismatch")
            self._attach_persistence(session)
        for sid in migrated:
            self._checkpoint(sid, 'host_restore_private_paths_rebased')
        for session in self.sessions.values():
            if not session.active_task:
                continue
            task = self.tasks[session.active_task]
            runtime = session.runtime
            if runtime.computer and getattr(runtime.computer.backend, "native_keyboard", False):
                runtime.computer.backend.task_context = {"session_id": session.id, "task_id": task.id,
                    "task_generation": task.generation}
            category = recovery_class(runtime)
            # A child may have persisted its own approval before returning to
            # _worker_result in the interrupted parent stack.
            for worker_id, child in runtime._children.items():
                record = next(r for r in runtime.subagents if r["id"] == worker_id)
                if record.get('async'):
                    continue
                if record["status"] in {"running", "approval_required"} and child.pending_approval and not runtime.pending_approval:
                    runtime.pending_approval = {"kind": "subagent_resume", "call": runtime._queue[0],
                        "child": child, "worker_id": worker_id, "preview": child._approval_view()}
                    record["status"] = "approval_required"
            if runtime.async_policy and category == 'REQUIRES_APPROVAL' and not runtime.pending_approval:
                r = next(r for r in runtime.subagents if r.get('async') and runtime._children[r['id']].pending_approval)
                child = runtime._children[r['id']]
                r['status'] = 'approval_required'
                wait_call = runtime._queue[0] if runtime._queue and runtime._queue[0].name == 'wait_children' else None
                runtime.pending_approval = {'kind':'async_child', 'call':wait_call,
                    'worker_id':r['id'], 'child':child, 'preview':child._approval_view()}
            if task.stop_reason or (task.deadline is not None and task.deadline <= time.time()):
                task.stop_reason = task.stop_reason or "timed_out"
                task.status = task.stop_reason
                runtime.request_cancel(task.stop_reason)
                session.closed = True
                session.active_task = None
                category = "TERMINAL"
            elif task.status in TERMINAL:
                category = "TERMINAL"
                session.active_task = None
            elif runtime._durable_phase == "terminal" and runtime.turn_id >= task.turn_id and category != "UNKNOWN_BLOCKED":
                finished = next((e.data["status"] for e in reversed(runtime.events.events) if e.type == "TurnFinished"), "error")
                task.status = finished if finished in TERMINAL else "failed" if finished == "error" else "incomplete"
                session.active_task = None
                category = "TERMINAL"
            elif category == "REQUIRES_APPROVAL":
                task.status = "requires_approval"
                task.required_action = {"type": "approval", "id": identifier("approval"),
                    "requests": [runtime._approval_view()]}
            else:
                task.status = "requires_human"
                task.required_action = {"type": "runtime_continuation", "id": identifier("recovery"),
                    "reason": category, "continue_endpoint": f"/localpilot/v1/tasks/{task.id}/continue"}
            task.recovery = {"class": category, "epoch": session.recovery_epoch,
                "interrupted_model_requests": sum(n._durable_interrupted_models for n in nodes(runtime)),
                "unknown_model_usage": any(n._durable_interrupted_models for n in nodes(runtime)),
                "automatic_tool_replay": False,
                "unresolved_intents": [{"worker_id": n._worker_id, **deepcopy(n._durable_intent)}
                    for n in nodes(runtime) if n._durable_intent and not n._durable_intent["read_only"]],
                "unknown_receipts": [r["receipt_id"] for r in runtime.tool_history
                    if r.get("side_effect_status") in {"unknown", "partial"}]}
            if category == "TERMINAL":
                task.required_action = None
            expected_turn = task.turn_id
            self._capture(task, session, runtime._result(status=task.status) if runtime.turn_id >= expected_turn else None)
            task.turn_id = max(expected_turn, task.turn_id)
            self._checkpoint(session.id, "service_recovered")
        for task in list(self.tasks.values()):
            if task.status not in TERMINAL:
                self._arm_timer(task)

    def models(self):
        return sorted(self.routes)

    def _session(self, session_id):
        if not isinstance(session_id, str) or session_id not in self.sessions:
            raise APIError("Session not found", "session_not_found", 404)
        return self.sessions[session_id]

    def _task(self, task_id):
        if not isinstance(task_id, str) or task_id not in self.tasks:
            raise APIError("Task not found", "task_not_found", 404)
        return self.tasks[task_id]

    def create_session(self, model="localpilot", *, owner_subject=None, thinking_override=None, desktop_options=None, desktop_key=None, desktop_fingerprint=None):
        with self.condition:
            self._available()
            if self.closed:
                raise APIError("Service closed", "service_closed", 503)
            if not isinstance(model, str) or model not in self.routes:
                raise APIError("Unknown logical model/route", "model_not_found", 404)
            if len(self.sessions) >= self.max_sessions:
                raise APIError("Session capacity reached; restart or increase the host limit", "capacity_exceeded", 429)
            session_id = identifier("sess")
            runtime = self.routes[model](lambda event: self._runtime_event(session_id, event))
            if not isinstance(runtime, AgentSession) or runtime.legacy:
                raise TypeError("Route factory must return a non-legacy AgentSession")
            if desktop_options is not None:
                from localpilot_service.desktop_sessions import apply_options
                apply_options(runtime, desktop_options)
            if thinking_override is not None:
                try:runtime.set_thinking(thinking_override)
                except ValueError as exc:
                    runtime.close()
                    raise APIError(str(exc),'thinking_not_supported',409) from None
            if self.store and self.store.path.resolve().is_relative_to(runtime.workspace.resolve()):
                runtime.close()
                raise PersistenceError("Runtime database must be outside the tool workspace")
            if self.session_initializer:
                runtime._service_extensions = {}
                self.session_initializer(runtime, session_id, owner_subject)
            self.sessions[session_id] = SessionRecord(session_id, model, runtime, runtime.base_prompt,
                                                     owner_subject=owner_subject,thinking_override=thinking_override,desktop_options=desktop_options,desktop_key=desktop_key,desktop_fingerprint=desktop_fingerprint)
            if self.store:
                runtime._persistence_config = digest(dumps(configuration(runtime)))
            self._attach_persistence(self.sessions[session_id])
            self._checkpoint(session_id, "session_created")
            return self.session_snapshot(session_id)

    def session_snapshot(self, session_id):
        with self.condition:
            session = self._session(session_id)
            return {"id": session.id, "object": "localpilot.session", "model": session.model,
                    "state": "closed" if session.closed else session.runtime.state.value,
                    "active_task_id": session.active_task, "last_task_id": session.last_task, "desktop_options": session.desktop_options}

    def create_task(self, request, *, owner_subject=None, service_metadata=None):
        self._available()
        if type(request.low_power_consent) is not bool:
            raise APIError("low_power_consent must be boolean")
        service_metadata = {**(service_metadata or {}), "low_power_consent": request.low_power_consent}
        if not isinstance(request.input, str) or not request.input.strip():
            raise APIError("input must be nonempty text")
        if request.instructions is not None and not isinstance(request.instructions, str):
            raise APIError("instructions must be text")
        timeout = request.timeout_seconds
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= self.max_timeout:
            raise APIError(f"timeout_seconds must be within (0, {self.max_timeout}]")
        if request.max_output_tokens is not None and (type(request.max_output_tokens) is not int or request.max_output_tokens <= 0):
            raise APIError("max_output_tokens must be a positive integer")
        if any(not isinstance(m, Message) or m.role not in {"user", "assistant"} or not isinstance(m.content, str)
               or m.tool_calls or m.tool_call_id for m in request.history):
            raise APIError("history supports only user/assistant text")
        for label in (request.origin_agent,request.parent_task_id):
            if label is not None and (not isinstance(label,str) or not 1<=len(label)<=128 or any(ord(c)<32 for c in label)):
                raise APIError("Invalid delegation provenance")
        key = request.idempotency_key
        if key is not None and (not isinstance(key, str) or not 1 <= len(key) <= 128
                                or any(not 33 <= ord(c) <= 126 for c in key)):
            raise APIError("idempotency_key must contain 1-128 visible ASCII characters")
        key_digest = digest(key) if key is not None else None
        fingerprint = digest(dumps({f.name: ([m.to_dict() for m in request.history] if f.name == 'history'
                                            else getattr(request, f.name))
                                    for f in fields(TaskRequest) if f.name != 'idempotency_key'
                                    and not (f.name == 'low_power_consent' and request.low_power_consent is False)
                                    and not (f.name in {'routing_preferences','reasoning_effort','origin_agent','parent_task_id'} and getattr(request,f.name) is None)})) if key is not None else None
        with self.condition:
            if self.closed:
                raise APIError("Service closed", "service_closed", 503)
            # An accepted retry retrieves its original task, including approval,
            # UNKNOWN and failed states. It cannot launch or authorize new work.
            # Lookup precedes capacity, busy-session and session-head checks.
            if key_digest is not None:
                prior = next((t for t in self.tasks.values() if t.request_key_digest == key_digest), None)
                if prior is not None:
                    if owner_subject is not None and self._session(prior.session_id).owner_subject != owner_subject:
                        raise APIError("Task not found", "task_not_found", 404)
                    if prior.request_fingerprint != fingerprint:
                        raise APIError("Idempotency key was used for a different request", "idempotency_conflict", 409)
                    return self._snapshot(prior)
            if len(self.tasks) >= self.max_tasks:
                raise APIError("Task capacity reached; restart or increase the host limit", "capacity_exceeded", 429)
            if not isinstance(request.model, str) or request.model not in self.routes:
                raise APIError("Unknown logical model/route", "model_not_found", 404)
            session = self._session(request.session_id) if request.session_id else None
            if session:
                if owner_subject is not None and session.owner_subject != owner_subject:
                    raise APIError("Session not found", "session_not_found", 404)
                if session.closed:
                    raise APIError("Session closed", "session_closed", 409)
                if session.model != request.model:
                    raise APIError("A persistent session cannot change its route", "route_conflict", 409)
                if session.active_task:
                    raise APIError("Resolve the active task first", "session_busy", 409)
                if request.history:
                    raise APIError("Persistent sessions accept only the new user turn, not replayed history")
                if request.previous_task_id and session.last_task != request.previous_task_id:
                    raise APIError("previous_response_id must be the current session head; forks are unsupported", "stale_response", 409)
            elif request.previous_task_id:
                raise APIError("previous_task_id requires its existing session")
            if session is None:
                session = self._session(self.create_session(request.model, owner_subject=owner_subject,thinking_override=request.reasoning_effort)["id"])
            elif request.reasoning_effort is not None:
                try:session.runtime.set_thinking(request.reasoning_effort)
                except ValueError as exc:raise APIError(str(exc),'thinking_not_supported',409) from None
                session.thinking_override=request.reasoning_effort
                if self.store:session.runtime._persistence_config=digest(dumps(configuration(session.runtime)))
            if request.max_output_tokens and request.max_output_tokens > session.runtime.budgets.max_output_tokens:
                if not request.session_id:
                    session.runtime.close()
                    del self.sessions[session.id]
                raise APIError("max_output_tokens exceeds the host budget")
            task = TaskRecord(identifier("resp"), session.id, request.model, request.input, request.previous_task_id)
            task.service_metadata = deepcopy(service_metadata)
            task.request_key_digest, task.request_fingerprint = key_digest, fingerprint
            task.turn_id = session.runtime.turn_id + 1
            session.task_generation += 1
            task.generation = session.task_generation
            if session.runtime.hybrid:
                session.runtime.hybrid.state['task'] = {'session_id': session.id, 'task_id': task.id,
                                                      'generation': task.generation}
            if session.runtime.computer and getattr(session.runtime.computer.backend, "native_keyboard", False):
                session.runtime.computer.backend.task_context = {"session_id": session.id,
                    "task_id": task.id, "task_generation": task.generation}
            self.tasks[task.id] = task
            session.active_task = session.last_task = task.id
            if session.runtime.engine_policy:
                # Caller guidance belongs to this turn's data, not the frozen
                # host instruction prefix or permission authority.
                if request.instructions:
                    session.runtime.messages.append(Message('user','Client guidance for the following turn only; host permissions remain authoritative:\n'+request.instructions))
            else:
                session.runtime.base_prompt = session.base_prompt + ("\nClient instructions:\n" + request.instructions if request.instructions else "")
            session.runtime.messages.extend(deepcopy(request.history))
            task.history_start = len(session.runtime.messages)
            task.tool_start = len(session.runtime.tool_history)
            if request.max_output_tokens:
                # Per-turn cap is restored when the worker yields.
                output_cap = request.max_output_tokens
            else:
                output_cap = session.runtime.budgets.max_output_tokens
            task.output_cap = output_cap
            task.deadline = time.time() + timeout
            task.timer = threading.Timer(timeout, lambda: self.cancel(task.id, "timed_out"))
            task.timer.daemon = True
            self._emit(task, "task.created", self._snapshot(task))
            self._launch(task, lambda: session.runtime.run_turn(request.input), output_cap)
            task.timer.start()
            return self._snapshot(task)

    def _emit(self, task, event_type, data):
        task.sequence += 1
        task.events.append({"sequence": task.sequence, "type": event_type, "task_id": task.id,
                            "session_id": task.session_id, "data": deepcopy(data)})
        del task.events[:-self.max_events]
        if event_type in {"task.created", "task.status"}:
            self._checkpoint(task.session_id, event_type)
        self.condition.notify_all()

    def _runtime_event(self, session_id, event):
        with self.condition:
            session = self.sessions.get(session_id)
            if not session or not session.active_task:
                return
            task = self.tasks[session.active_task]
            # A host takeover thread is the only other event producer. Workers
            # have their own EventStream and do not masquerade as parent output.
            if event.type in HUMAN_EVENTS or (event.type == "ComputerLockChanged" and event.data.get("locked") is not False):
                task.human_signal = event.to_dict()
            elif event.type == "ComputerResumed":
                task.human_signal = None
            wire = event.to_dict()
            if event.type == "ModelResponseStarted":
                task.pending_text = ""
                task.generation_start = len(session.runtime.messages)
            elif event.type == "TextDelta":
                task.pending_text += event.data["text"]
            if event.type == "ToolCallRequested":
                # Runtime traces intentionally summarize code/content arguments.
                # The authenticated API needs the actual generated function call
                # to preserve the Responses item contract; it still cannot execute
                # that call outside the existing Registry/Gateway.
                call = next((c for m in reversed(session.runtime.messages) for c in m.tool_calls
                             if c.id == event.data["tool_call_id"]), None)
                if call:
                    wire["data"]["call"] = call.to_dict()
            self._emit(task, "runtime.event", wire)

    def _launch(self, task, operation, output_cap=None):
        self._available()
        if task.executing:
            raise APIError("Task is still executing", "task_busy", 409)
        task.executing = True
        task.status = "cancelling" if task.stop_reason else "running"
        task.operation_tool_start = len(self._session(task.session_id).runtime.tool_history)
        task.required_action = None
        self._emit(task, "task.status", self._snapshot(task))
        worker = threading.Thread(target=self._run, args=(task.id, operation, output_cap or task.output_cap), daemon=True)
        worker.start()

    def _capture(self, task, session, result=None):
        runtime = session.runtime
        task.execution_metadata=self._execution_metadata(session)
        task.turn_id = runtime.turn_id
        # Snapshot once at a quiescent boundary. Old task results never absorb
        # subsequent turns' messages, usage or tool receipts.
        task.output = [m.to_dict() for m in runtime.messages[task.history_start:]
                       if m.role in {"assistant", "tool"}]
        if task.pending_text and not any(m.role == "assistant" for m in runtime.messages[task.generation_start:]):
            # Preserve already-emitted partial text without admitting an
            # incomplete assistant/tool group into the Runtime transcript.
            task.output.append({"role": "assistant", "content": task.pending_text, "status": "incomplete"})
        task.tools = deepcopy(runtime.tool_history[task.tool_start:])
        task.goals = deepcopy(runtime._goal_records())
        task.subagents = deepcopy([r for r in runtime.subagents if task.turn_id >= r["turn_id"]
                                  and r["turn_id"] in task.model_calls_by_turn.keys() | {runtime.turn_id}])
        task.computer = runtime.computer.summary() if runtime.computer else None
        if result is not None:
            summary = result.usage_summary()
            task.model_calls_by_turn[runtime.turn_id] = summary["model_calls"]
            calls = [call for turn in sorted(task.model_calls_by_turn) for call in task.model_calls_by_turn[turn]]
            cache_known = bool(calls) and all(c["prompt_cache_hit_tokens"] is not None and c["prompt_cache_miss_tokens"] is not None for c in calls)
            hits = sum(c["prompt_cache_hit_tokens"] or 0 for c in calls)
            misses = sum(c["prompt_cache_miss_tokens"] or 0 for c in calls)
            task.result = {"text": result.text, **summary, "model_calls": calls,
                "total_steps": len(calls), "total_tool_calls": sum(c["tool_call_count"] for c in calls),
                "reported_models": sorted({c["reported_model"] for c in calls if c["reported_model"]}),
                "model_latency_seconds": sum(c["latency_seconds"] for c in calls),
                "runtime_metrics_scope": "latest_runtime_turn",
                "cache": {"status": "available" if cache_known else "unavailable", "hit_tokens": hits if cache_known else None,
                          "miss_tokens": misses if cache_known else None, "hit_ratio": hits / (hits + misses) if cache_known and hits + misses else None}}

    def _run(self, task_id, operation, output_cap):
        with self.condition:
            task = self._task(task_id)
            session = self._session(task.session_id)
        runtime = session.runtime
        original_budgets = runtime.budgets
        before_operation=(runtime.turn_id,runtime._attempts,len(runtime.messages),len(runtime.tool_history))
        pre_start_failure=False
        try:
            if output_cap:
                from dataclasses import replace
                runtime.budgets = replace(original_budgets, max_output_tokens=output_cap)
            from agent.power_consent import task_consent
            with task_consent(task.service_metadata.get("low_power_consent") is True):
                manager=getattr(runtime.current_backend,"manager",None)
                if manager and not task.stop_reason:
                    with manager.lease(task.id,consent=task.service_metadata.get("resource_consent"),client_subject=session.owner_subject,cancelled=lambda:bool(task.stop_reason),control_ticket=task.service_metadata.get("control_ticket")):
                        result=operation()
                else:
                    result = operation()
            with self.condition:
                if isinstance(result, dict):
                    if result.get("status") != "ok":
                        task.human_signal = {"type": "ComputerResumeFailed", "data": result}
                        result = runtime._result(result.get("message", "Computer remains paused"), "computer_paused")
                    else:
                        # A fallback may have yielded a completed Runtime turn;
                        # host resume must start a fresh turn with retained context.
                        result = None
                if result is None:
                    raise RuntimeError("Host operation returned no Agent result")
                self._capture(task, session, result)
                human_tool = next((r for r in reversed(runtime.tool_history[task.operation_tool_start:]) if isinstance(r["payload"].get("result"), dict)
                                   and r["payload"]["result"].get("error") in HUMAN_ERRORS), None)
                # A model final sentence is not evidence that a refused AX write
                # succeeded. A later verified write/verify of the same intended
                # postcondition can resolve it; unrelated reads cannot.
                unresolved, unfinished_handoff = computer_obligations(runtime.tool_history[task.tool_start:])
                persistent_unknown = bool(self.store and recovery_class(runtime) == "UNKNOWN_BLOCKED")
                if persistent_unknown:
                    task.recovery = {"class": "UNKNOWN_BLOCKED", "epoch": session.recovery_epoch,
                        "automatic_tool_replay": False, "reason": "unproven_external_effect"}
                if result.status != "approval_required":
                    human_tool = human_tool or next(iter(unresolved.values()), None)
                if task.stop_reason:
                    task.status = task.stop_reason
                elif persistent_unknown or result.status == "computer_paused" or task.human_signal or human_tool or task.control_pending:
                    task.status = "requires_human"
                    task.required_action = {"type": "human_intervention", "id": identifier("human"),
                        "reason": "UNKNOWN_BLOCKED" if persistent_unknown else task.human_signal or (human_tool and human_tool["payload"].get("result", human_tool["payload"].get("error"))),
                        "computer": task.computer, "approval": result.approvals,
                        "resume_endpoint": f"/localpilot/v1/tasks/{task.id}/computer/resume"}
                elif result.status == "approval_required":
                    task.status = "requires_approval"
                    task.required_action = {"type": "approval", "id": identifier("approval"), "requests": result.approvals,
                        "approve_endpoint": f"/localpilot/v1/tasks/{task.id}/approve",
                        "reject_endpoint": f"/localpilot/v1/tasks/{task.id}/reject"}
                elif result.status=='host_paused':
                    task.status='requires_human'
                    task.recovery={'class':'SAFE_TO_RESUME','reason':'host_paused','epoch':session.recovery_epoch,'automatic_tool_replay':False}
                    task.required_action={'type':'runtime_continuation','id':identifier('pause'),'reason':'host_paused','continue_endpoint':f'/localpilot/v1/tasks/{task.id}/continue'}
                elif result.status == "completed" and (result.task_outcome in {'failed','unknown','blocked','incomplete'} or unfinished_handoff or result.deliverable_status in {"incomplete", "missing"}):
                    # Bounded finalization may end the model turn while leaving
                    # the requested work unfinished. Preserve Runtime evidence.
                    task.status = "incomplete"
                elif result.status == 'completed' and result.completion and (
                        (result.completion['execution'] != 'completed' and not (
                            runtime.engine_policy and runtime.completion_check is None and
                            result.completion['execution'] == 'settled')) or
                        result.verification_status in {'failed','blocked','unknown'}):
                    task.status = 'incomplete'
                elif (result.status == 'completed' and task.service_metadata is not None
                        and runtime.verification_callback is not None
                        and result.verification_status in {'failed', 'blocked', 'unknown'}):
                    # Packaged service attestation cannot be hidden by a finished
                    # model turn. Preserve result.runtime_status independently.
                    task.status = 'incomplete'
                elif result.status in {"completed", "cancelled", "timed_out"}:
                    task.status = result.status
                elif result.status == "error":
                    task.status = "failed"
                    task.error = {"code": "runtime_error", "message": result.text}
                else:
                    task.status = "incomplete"
        except Exception as exc:
            with self.condition:
                pre_start_failure=before_operation==(runtime.turn_id,runtime._attempts,len(runtime.messages),len(runtime.tool_history))
                self._capture(task, session)
                task.status = task.stop_reason or "failed"
                task.error = {"code": type(exc).__name__, "message": str(exc)}
                # Unexpected host failures cannot leave a reusable half turn.
                session.closed = True
        finally:
            runtime.budgets = original_budgets
            with self.condition:
                # Retire cancelled/timed-out sessions to avoid resuming a partial
                # transcript or replaying a side effect with an unknown outcome.
                retire = task.status in {"cancelled", "timed_out"} or session.closed
            if retire:
                try:
                    runtime.close()
                except Exception as exc:
                    with self.condition:
                        task.error = task.error or {"code": "close_failed", "message": str(exc)}
                with self.condition:
                    session.closed = True
                    # Child close may append retirement obligations or finish accounting.
                    # Capture those facts before publishing the terminal task snapshot.
                    text = (task.result or {}).get("text", (task.error or {}).get("message", ""))
                    if pre_start_failure:
                        from agent.loop import AgentResult
                        fresh=AgentResult(text=text,messages=[],model_calls=[],prompt_version=f"{runtime.prompt_profile}-v0.1" if runtime.legacy else "runtime-v2-computer-use-alpha" if runtime.computer else "runtime-v1.4",prompt_profile=runtime.prompt_profile,tool_profile=runtime.registry.tool_profile,status=task.status,runtime_status=task.status,deliverable_status="incomplete",verification_status="not_run",engineering_status="unverified")
                        self._capture(task,session,fresh)
                        task.result["runtime_metrics_scope"]="pre_turn_failure_no_inference"
                    else:
                        self._capture(task, session, runtime._result(text, task.status))
            with self.condition:
                task.executing = False
                if task.status in TERMINAL and not task.control_pending:
                    runtime._host_pause_requested=False
                    if task.recovery:
                        task.recovery = {**task.recovery, "class": "TERMINAL",
                            "effect_state": "UNKNOWN_BLOCKED" if recovery_class(runtime) == "UNKNOWN_BLOCKED" else "receipted_or_no_dispatch"}
                    task.required_action = None
                    session.active_task = None
                    if task.timer:
                        task.timer.cancel()
                try:
                    self._emit(task, "task.status", self._snapshot(task))
                except PersistenceError:
                    task.status = "requires_human"
                    task.recovery = {"class": "UNKNOWN_BLOCKED", "reason": "storage_failure", "automatic_tool_replay": False}
                    self.condition.notify_all()

    def _execution_metadata(self,session):
        runtime=session.runtime;caps=runtime.current_backend.capabilities
        return {'execution_model':runtime.current_primary_model,'desktop_options':deepcopy(session.desktop_options),
                'thinking':{'requested':session.thinking_override,'effective':runtime.thinking_mode if runtime.thinking_mode is not None else caps.default_thinking_effort,'supported':list(caps.supported_thinking_efforts)}}

    def _snapshot(self, task):
        session=self._session(task.session_id)
        metadata=self._execution_metadata(session) if session.active_task==task.id else task.execution_metadata or {}
        question=task.input
        try:
            parsed=json.loads(question)
            if isinstance(parsed,dict) and parsed.get('format')=='companion.escalation.v1' and isinstance(parsed.get('user_request'),str):question=parsed['user_request']
        except (ValueError,TypeError):pass
        return deepcopy({"id": task.id, "object": "localpilot.task", "session_id": task.session_id,
            'user_input':question,**metadata,'pause_requested':session.active_task==task.id and session.runtime._host_pause_requested,
            "model": task.model, "previous_task_id": task.previous_task_id, "created_at": task.created_at,
            "status": task.status, "quiescent": not task.executing and not task.control_pending, "result": task.result,
            "required_action": task.required_action, "error": task.error, "output": task.output,
            "tools": task.tools, "goals": task.goals, "subagents": task.subagents, "computer": task.computer,
            "completion": (task.result or {}).get('completion'),
            "last_event_id": task.sequence, **({"recovery": task.recovery} if task.recovery else {}),
            **({"service": task.service_metadata} if task.service_metadata else {})})

    def task_snapshot(self, task_id):
        with self.condition:
            return self._snapshot(self._task(task_id))

    def children(self, task_id):
        with self.condition:
            task = self._task(task_id)
            session = self._session(task.session_id)
            if task.status in TERMINAL or session.active_task != task.id:
                return deepcopy(task.subagents)
            return session.runtime.children_snapshot()

    def cancel_child(self, task_id, worker_id):
        with self.condition:
            self._available()
            task = self._task(task_id)
            session = self._session(task.session_id)
            if (task.status in TERMINAL or task.stop_reason or session.closed or session.active_task != task.id
                    or session.task_generation != task.generation or not session.runtime.async_policy):
                raise APIError('Child control requires the current active async task', 'action_conflict', 409)
            try:
                session.runtime.cancel_child(worker_id)
            except ValueError as error:
                raise APIError(str(error), 'child_not_found', 404) from error
            return session.runtime.children_snapshot()

    def finalize(self, task_id, action_id=None):
        """Idempotent delivery retrieval, or fenced final-only crash continuation.

        Never creates a new turn, resets budgets, or replays tool proposals.
        """
        with self.condition:
            self._available()
            task = self._task(task_id)
            completion = (task.result or {}).get('completion') or {}
            if completion.get('delivery') == 'delivered':
                return self._snapshot(task)
            runtime = self._session(task.session_id).runtime
            if (not runtime.finalization_policy or not runtime._finalizing or
                    not task.recovery or task.recovery['class'] != 'SAFE_TO_RESUME'):
                raise APIError('No resumable finalization; inspect retained evidence', 'finalization_unavailable', 409)
            return self.act(task_id, 'continue', action_id)

    def wait(self, task_id):
        with self.condition:
            self.condition.wait_for(lambda: self._task(task_id).status in SETTLED and not self._task(task_id).executing and not self._task(task_id).control_pending)
            return self._snapshot(self._task(task_id))

    def events(self, task_id, after=0, wait_seconds=15):
        if type(after) is not int or after < 0:
            raise APIError("after must be a nonnegative event sequence")
        with self.condition:
            task = self._task(task_id)
            if after > task.sequence:
                raise APIError("Event cursor is ahead of the task", "invalid_cursor", 409)
            if task.events and after < task.events[0]["sequence"] - 1:
                raise APIError("Event history expired; retrieve the task snapshot", "event_history_expired", 409)
            self.condition.wait_for(lambda: task.sequence > after or (task.status in SETTLED and not task.executing and not task.control_pending), timeout=wait_seconds)
            if task.events and after < task.events[0]["sequence"] - 1:
                raise APIError("Event history expired; retrieve the task snapshot", "event_history_expired", 409)
            return deepcopy([e for e in task.events if e["sequence"] > after]), self._snapshot(task)

    def pause(self,task_id):
        with self.condition:
            task=self._task(task_id)
            if task.status in TERMINAL or not task.executing:return self._snapshot(task)
            runtime=self._session(task.session_id).runtime
            if runtime.computer or runtime.async_policy:raise APIError('Use the existing qualified Computer/child control path','pause_not_qualified',409)
            runtime.request_pause()
            self._emit(task,'task.status',self._snapshot(task))
            return self._snapshot(task)

    def cancel(self, task_id, reason="cancelled", *, drain_response=False):
        if reason not in {"cancelled", "timed_out"}:
            raise APIError("Invalid cancellation reason")
        with self.condition:
            task = self._task(task_id)
            if task.status in TERMINAL or task.stop_reason:
                return self._snapshot(task)
            task.stop_reason, task.status = reason, "cancelling"
            session = self._session(task.session_id)
            session.runtime._drain_current_model = drain_response is True and not session.runtime.current_backend.is_local
            session.runtime.request_cancel(reason)
            task.required_action = None
            self._emit(task, "task.status", self._snapshot(task))
            if not task.executing:
                self._launch(task, session.runtime._drive)
                task.status = "cancelling"
            return self._snapshot(task)

    def act(self, task_id, action, action_id, reason="User rejected the request."):
        with self.condition:
            self._available()
            task = self._task(task_id)
            expected = "requires_human" if action in {"resume", "continue"} else "requires_approval"
            session = self._session(task.session_id)
            if (task.executing or task.control_pending or task.stop_reason or task.status != expected or
                    session.closed or session.active_task != task.id or session.task_generation != task.generation):
                raise APIError("Task is not awaiting this action", "action_conflict", 409)
            if not task.required_action or action_id != task.required_action["id"]:
                raise APIError("Stale or missing action_id", "stale_action", 409)
            if action not in {"approve", "reject", "resume", "continue"}:
                raise APIError("Unknown host action")
            runtime = self._session(task.session_id).runtime
            if task.recovery and task.recovery["class"] == "UNKNOWN_BLOCKED":
                raise APIError("Uncertain external effects are quarantined; cancel or inspect", "unknown_blocked", 409)
            if action == "continue" and (not task.recovery or task.recovery["class"] != "SAFE_TO_RESUME"):
                raise APIError("Checkpoint requires approval or reobservation", "recovery_conflict", 409)
            task.host_action = {"action": action, "action_id": action_id, "epoch": session.recovery_epoch}
            self._checkpoint(session.id, "host_action")
            if action == "resume":
                def operation():
                    result = runtime.resume_computer()
                    if (isinstance(result, dict) and result.get("status") == "ok" and
                            result.get("continuation") == "new_turn_required"):
                        return runtime.run_turn("Human intervention finished. Continue the original task from fresh state: " + task.input)
                    return result
            elif action == "continue":
                operation = (lambda: runtime.run_turn(task.input)) if runtime.turn_id < task.turn_id else runtime.continue_checkpoint
            else:
                if runtime.async_policy:
                    runtime._recover_async_children()
                operation = runtime.approve if action == "approve" else lambda: runtime.reject(reason)
            self._launch(task, operation)
            return self._snapshot(task)

    def takeover(self, task_id, *, revoke_app=None):
        with self.condition:
            task = self._task(task_id)
            session = self._session(task.session_id)
            if (task.status in TERMINAL or task.stop_reason or task.control_pending or session.closed or
                    session.active_task != task.id or session.task_generation != task.generation):
                raise APIError("Task cannot be taken over", "action_conflict", 409)
            runtime = session.runtime
            if not runtime.computer:
                raise APIError("Computer Use is disabled", "computer_disabled", 409)
            if revoke_app is not None and (not isinstance(revoke_app,str) or revoke_app not in runtime.computer.allowed_apps or not callable(getattr(runtime.computer,'request_revoke',None))):
                raise APIError('Revocation requires an app in the scoped native runtime','computer_scope_invalid',409)
            # Reserve this generation before dropping the condition. The worker
            # must yield requires_human even if its model finishes during handoff.
            # No new task, resume or second takeover can use this Session meanwhile.
            task.control_pending = True
            self._checkpoint(session.id, "takeover_intent")
        # Never hold the service condition while waiting for an in-flight AX
        # call; that call publishes its receipt through this same condition.
        failure = None
        try:
            if revoke_app is not None:runtime.computer.request_revoke(revoke_app)
            runtime.take_over_computer()
        except Exception as exc:
            failure = {"type": "ComputerResumeFailed", "data": {"error": type(exc).__name__, "message": str(exc)}}
        finally:
            with self.condition:
                task.control_pending = False
                if task.status not in TERMINAL and not task.stop_reason:
                    task.status = "requires_human"
                    task.human_signal = failure or task.human_signal or {"type": "ComputerHumanTakeover", "data": {"reason": "host_takeover"}}
                    task.computer = runtime.computer.summary()
                    task.required_action = {"type": "human_intervention", "id": identifier("human"),
                        "reason": task.human_signal, "computer": task.computer,
                        "resume_endpoint": f"/localpilot/v1/tasks/{task.id}/computer/resume"}
                elif not task.executing and session.active_task == task.id:
                    session.active_task = None
                    task.timer.cancel()
                self._emit(task, "task.status", self._snapshot(task))
        return self.task_snapshot(task_id)

    def revoke_computer(self, task_id, app):
        return self.takeover(task_id,revoke_app=app)

    def native_recovery(self, session_id, action, body, *, principal):
        """Trusted host control only; unused successor Session, no model drive.

        Serializing under the condition fences create/cancel/close/takeover.
        Only fresh successor Sessions are eligible, so no worker can hold the
        device lock while publishing events through this condition.
        """
        from computer.human_recovery import HumanRecovery
        with self.condition:
            session = self._session(session_id)
            computer = session.runtime.computer
            if self.closed or session.closed or not computer or not getattr(computer.backend, "native_keyboard", False):
                raise APIError("Native recovery unavailable", "recovery_unavailable", 409)
            if session.task_generation != 0 or session.active_task is not None:
                raise APIError("Recovery requires an unused successor Session", "recovery_session_conflict", 409)
            if any(other.id != session.id and other.runtime.computer and
                   other.runtime.computer.backend is computer.backend and other.task_generation != 0
                   for other in self.sessions.values()):
                raise APIError("Recovery requires a fresh backend owner", "recovery_owner_conflict", 409)
            if not isinstance(body, dict) or not isinstance(body.get("app"), str) or body["app"] not in computer.allowed_apps:
                raise APIError("Exact allowed App required")
            allowed = {"app"}
            if action == "request":
                allowed |= {"request_id", "idempotency_key"}
            elif action in {"authorize", "revalidate", "reject"}:
                allowed |= {"recovery_id", "generation"}
                if action == "authorize":
                    allowed |= {"target_fingerprint", "confirmations"}
            if set(body) != allowed:
                raise APIError("Exact recovery fields required; identity is host-configured")
            manager = HumanRecovery(computer.backend)
            computer.invalidate()
            if action == "inspect":
                if set(body) != {"app"}:
                    raise APIError("Recovery inspection accepts only app")
                return manager.inspect(body["app"])
            return manager.operate(action, body["app"], binding={"session_id": session.id,
                "task_generation": session.task_generation}, principal=principal,
                **{k: v for k, v in body.items() if k != "app"})

    def close_session(self, session_id):
        with self.condition:
            session = self._session(session_id)
            if session.active_task:
                raise APIError("Cancel/resolve the active task before closing", "session_busy", 409)
            session.closed = True
        session.runtime.close()
        self._checkpoint(session.id, "session_closed")
        return self.session_snapshot(session_id)

    def _children_drained(self):
        return not self.scheduler or not (self.scheduler.queue or any(self.scheduler.running.values()) or self.scheduler.models)

    def suspend(self):
        """Planned restart at a yielded boundary, preserving active approvals/tasks."""
        with self.condition:
            if any(t.executing or t.control_pending for t in self.tasks.values()):
                raise APIError("Suspend requires all workers to yield", "service_busy", 409)
            if not self.condition.wait_for(self._children_drained, timeout=1):
                raise APIError('Suspend requires child scheduler to drain', 'service_busy', 409)
            self.closed = True
            for session in self.sessions.values():
                self._checkpoint(session.id, "service_suspended")
            for task in self.tasks.values():
                if task.timer:
                    task.timer.cancel()
            if self.scheduler:
                self.scheduler.close()
            if self.resource_finalizer:
                self.resource_finalizer()
            if self.store:
                self.store.close()
            for session in self.sessions.values():
                if session.runtime.computer:
                    session.runtime.computer.close()
                plugin_manager = getattr(session.runtime.registry, 'plugin_manager', None)
                if plugin_manager:
                    plugin_manager.close()
            return {"status": "ok", "quiescent": True}

    def shutdown(self, timeout=None):
        if timeout is not None and (type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout < 0):
            raise ValueError("Shutdown timeout must be nonnegative and finite")
        with self.condition:
            self.closed = True
            active = [t.id for t in self.tasks.values() if t.status not in TERMINAL]
        for task_id in active:
            self.cancel(task_id)
        with self.condition:
            drained = self.condition.wait_for(lambda: not any(t.executing or t.control_pending for t in self.tasks.values()) and self._children_drained(), timeout)
            if not drained:
                return {"status": "error", "error": "shutdown_not_quiescent", "quiescent": False,
                        "inflight": [t.id for t in self.tasks.values() if t.executing or t.control_pending]}
        for session_id in list(self.sessions):
            with self.condition:
                session = self.sessions[session_id]
                idle = not session.active_task and not session.closed
            if idle:
                self.close_session(session_id)
        if self.scheduler:
            self.scheduler.close()
        if self.resource_finalizer:
            self.resource_finalizer()
        if self.store:
            self.store.close()
        return {"status": "ok", "quiescent": True}
