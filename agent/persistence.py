"""Optional single-host durable checkpoints. Never deserialize executable objects."""
from collections import deque
from copy import deepcopy
from dataclasses import asdict
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

from .backends import Message, ToolCall
from .events import RuntimeEvent
from .goals import Goal
from .loop import ModelCallUsage
from .async_runtime import policy_snapshot


class PersistenceError(RuntimeError):
    retryable = False


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def json_value(value):
    if value is None or type(value) in {str, int, float, bool}:
        return True
    if type(value) is list:
        return all(json_value(v) for v in value)
    if type(value) is dict:
        return all(type(k) is str and json_value(v) for k, v in value.items())
    return False


def pack(value):
    if isinstance(value, ToolCall):
        return {"$call": asdict(value)}
    if isinstance(value, tuple):
        return {"$tuple": [pack(v) for v in value]}
    if isinstance(value, (list, deque)):
        return [pack(v) for v in value]
    if isinstance(value, dict):
        if json_value(value):
            # A typed native JSON subtree needs no wrapper per nested field.
            # Copy once: pack/snapshot callers still get independent snapshots.
            return {"$json": deepcopy(value)}
        if all(type(k) is str for k in value):
            # Typed string-key maps avoid two pair-list allocations per field.
            # The wrapper preserves tool-controlled type-tag keys as plain data.
            return {"$strmap": {k: pack(v) for k, v in value.items()}}
        # Encode mappings as pairs so tool-controlled keys cannot be type tags.
        return {"$map": [[pack(k), pack(v)] for k, v in value.items()]}
    if value is None or type(value) in {str, int, float, bool}:
        return value
    raise PersistenceError("Unsupported checkpoint value: " + type(value).__name__)


def unpack(value):
    if isinstance(value, list):
        return [unpack(v) for v in value]
    if isinstance(value, dict):
        if set(value) == {"$call"}:
            return ToolCall(**value["$call"])
        if set(value) == {"$tuple"}:
            return tuple(unpack(v) for v in value["$tuple"])
        if set(value) == {"$json"}:
            if not json_value(value['$json']):
                raise PersistenceError('Invalid JSON subtree')
            return deepcopy(value['$json'])
        if set(value) == {"$strmap"}:
            if not isinstance(value['$strmap'], dict):
                raise PersistenceError('Invalid string mapping')
            return {k: unpack(v) for k, v in value['$strmap'].items()}
        if set(value) == {"$map"}:
            return {unpack(k): unpack(v) for k, v in value["$map"]}
        raise PersistenceError("Unknown checkpoint encoding")
    return value


# Explicit schema. Locks, backend objects, callbacks, credentials, caches and
# native handles never cross the process boundary.
FIELDS = """turn_id active_plan pending_approval _queue _child_accounted
_call_context primary _turn_primary_restore _turn_text _planning _streamed
_usage _tool_proposals _token_units _switches _subagent_count
_verification_status _engineering_status _verification _finalizing _final_reason
_final_reserve _attempts _request_bytes _response_bytes _failed_attempts
_read_receipts _computer_receipt_turn _computer_resume_state
base_prompt permission_mode plan_mode thinking_mode reasoning_mode
_durable_phase _durable_intent _durable_interrupted_models""".split()
WORKING = """task revisions evidence operations evicted_evidence evicted_operations
no_progress _seen computer _computer_generation""".split()


def backend_identity(backend):
    if backend is None:
        return None
    endpoint = getattr(backend, "base_url", None)
    capabilities = asdict(backend.capabilities) if getattr(backend, "capabilities", None) is not None else None
    # Preserve v1 checkpoint identities unless the host opts into vision.
    if capabilities is not None and capabilities.get('supports_vision') is False:
        capabilities.pop('supports_vision')
    return {"class": type(backend).__module__ + "." + type(backend).__qualname__,
        "provider": getattr(backend, "provider", None), "is_local": getattr(backend, "is_local", None),
        "endpoint_sha256": digest(str(endpoint)) if endpoint is not None else None,
        "model": asdict(backend.model_info) if getattr(backend, "model_info", None) is not None else getattr(backend, "model", None),
        "capabilities": capabilities,
        **({"cache_layout": {"version":1, "system_prompt_update":"in-history" if getattr(backend, "supports_in_history_system_prompt", False) else "replace"}} if getattr(backend, "service_cache_stable_prefix", False) is True else {}),
        **({"service_contract": backend.service_contract} if hasattr(backend, "service_contract") else {})}


def configuration(runtime):
    gateway = runtime.registry.gateway
    config = {"workspace": str(runtime.workspace), "policy": runtime.routing_policy.value,
        "permission": runtime.permission_mode, "capabilities": asdict(gateway.capabilities),
        "data_policy": asdict(runtime.hard_data_policy), "schemas": runtime.registry.schemas(),
        "cloud": backend_identity(runtime.cloud_backend), "local": backend_identity(runtime.local_backend),
        "workers": {k: backend_identity(v) for k, v in runtime.cloud_worker_backends.items()},
        "budgets": asdict(runtime.budgets), "controls": asdict(runtime.controls),
        "prompt": runtime.base_prompt, "thinking": runtime.thinking_mode,
        "retry": asdict(runtime.retry_policy), "streaming": runtime.streaming,
        "computer": None if not runtime.computer else {
            "apps": sorted(runtime.computer.allowed_apps), "background": sorted(runtime.computer.background_safe_apps),
            "native": bool(getattr(runtime.computer.backend, "native_keyboard", False)),
            "backend": type(runtime.computer.backend).__name__, "frontmost": runtime.computer.allow_frontmost,
            "ttl": runtime.computer.observation_ttl},
        "verification": runtime.verification_callback is not None}
    if runtime.computer and getattr(runtime.computer, 'v5_integration_revision', None) == 1:
        config['computer'].update(scope_configuration=runtime.computer.configuration(),frontmost=False)
    if getattr(runtime.registry, 'scope_policy', None):
        config['file_scope_policy'] = runtime.registry.scope_policy
    if runtime.strict_task:
        config['strict_task'] = True
    if hasattr(runtime.verification_callback, 'identity'):
        config['host_acceptance'] = runtime.verification_callback.identity
    if runtime.finalization_policy:
        config['finalization'] = {'policy': asdict(runtime.finalization_policy),
                                  'completion_check': runtime.completion_check is not None}
    if runtime.async_policy:
        config['async'] = policy_snapshot(runtime.async_policy)
    if runtime.hybrid:
        config['hybrid'] = runtime.hybrid.configuration()
    if runtime.delivery_instruction is not None:
        config['delivery_instruction'] = runtime.delivery_instruction
    if runtime.engine_policy:
        config['engine_v5'] = asdict(runtime.engine_policy)
    if runtime.adaptive:
        config['adaptive'] = runtime.adaptive.configuration()
    if runtime.harness_policy:
        harness_policy = asdict(runtime.harness_policy)
        # Preserve fingerprints of existing/default checkpoints. Enabled views
        # are configuration-bound and cannot be toggled during recovery.
        if not harness_policy.get('cache_stable_prefix'):
            harness_policy.pop('cache_stable_prefix', None)
        config['harness'] = {'policy':harness_policy,
            'contract':asdict(runtime.task_contract) if runtime.task_contract else None}
    return config


def snapshot_runtime(runtime):
    from .session import SessionState
    fields = {k: getattr(runtime, k) for k in FIELDS}
    fields["_usage"] = [asdict(v) for v in runtime._usage]
    fields["_computer_resume_state"] = runtime._computer_resume_state.value if runtime._computer_resume_state else None
    pending = fields["pending_approval"]
    if pending:
        fields["pending_approval"] = {k: v for k, v in pending.items() if k != "child"}
    # A recorded receipt is committed before queue.pop. Canonical queue excludes
    # that consumed proposal, including reused IDs. Pending approvals stay queued.
    fields["_queue"] = list(runtime._queue)
    if (runtime._durable_phase == "receipt" and fields["_queue"] and runtime.tool_history
            and fields["_queue"][0].id == runtime.tool_history[-1]["id"]
            and fields["_queue"][0].arguments == runtime.tool_history[-1]["arguments"]):
        fields["_queue"] = fields["_queue"][1:]
    snapshot = {"version": 1, "state": runtime.state.value, "fields": pack(fields),
        "messages": [m.to_dict(include_reasoning=True) for m in runtime.messages],
        "history": deepcopy(runtime.tool_history), "completed": pack(runtime.completed_tool_calls),
        "goals": [asdict(g) for g in runtime.goals.list()], "subagents": deepcopy(runtime.subagents),
        "working": pack({k: getattr(runtime.working, k) for k in WORKING}),
        "budgets": asdict(runtime.budgets), "gateway_audit": deepcopy(runtime.registry.gateway.audit),
        "judge_calls": getattr(runtime.registry.gateway.judge, "calls", 0),
        "stop": runtime._stop_reason if runtime._stop_requested.is_set() else None,
        "events": [e.to_dict() for e in runtime.events.events], "sequence": runtime.events.sequence,
        "computer": None if not runtime.computer else {"revision": runtime.computer.revision,
            "resync_generation": runtime.computer.resync_generation},
        "children": {k: snapshot_runtime(v) for k, v in runtime._children.items()}}
    if runtime.strict_task:
        snapshot['strict_task'] = True
    if hasattr(runtime.verification_callback, 'identity'):
        snapshot['host_acceptance'] = runtime.verification_callback.identity
    if getattr(runtime.registry, 'plugin_manager', None):
        snapshot['plugin_namespace'] = runtime._plugin_namespace
    if runtime.async_policy:
        snapshot['async'] = {'policy': policy_snapshot(runtime.async_policy)}
    if runtime.finalization_policy:
        snapshot["delivery"] = pack({"completion": runtime._completion, "view": runtime._delivery_view,
                                     "output_tokens": runtime._request_output_tokens})
    if runtime.hybrid:
        from .hybrid import sha
        snapshot['hybrid'] = {'configuration': sha(runtime.hybrid.configuration()),
                              'state': deepcopy(runtime.hybrid.state)}
    if runtime.adaptive:
        from .hybrid import sha
        snapshot['adaptive'] = {'configuration': sha(runtime.adaptive.configuration()), 'state': deepcopy(runtime.adaptive.state)}
    if runtime.delivery_instruction is not None:
        snapshot['delivery_instruction_sha256'] = digest(runtime.delivery_instruction)
    if runtime.harness_policy:
        snapshot['harness_sha256'] = digest(json.dumps(configuration(runtime)['harness'],sort_keys=True))
    if runtime._drain_current_model:
        snapshot["drain_current_model"]=True
    if runtime._host_pause_requested:snapshot['host_pause_requested']=True
    if runtime.engine_policy:
        snapshot['engine_v5'] = asdict(runtime.engine_policy)
    return snapshot


def restore_runtime(runtime, data, *, conservative_interrupts=False):
    if data.get('strict_task', False) != runtime.strict_task:
        raise PersistenceError('Task acceptance contract checkpoint mismatch')
    if data.get('host_acceptance') != getattr(runtime.verification_callback, 'identity', None):
        raise PersistenceError('Host assertion identity checkpoint mismatch')
    if data.get('engine_v5') != (asdict(runtime.engine_policy) if runtime.engine_policy else None):
        raise PersistenceError('V5 engine checkpoint mismatch')
    if data.get('harness_sha256') != (digest(json.dumps(configuration(runtime)['harness'],sort_keys=True)) if runtime.harness_policy else None):
        raise PersistenceError('Harness task contract checkpoint mismatch')
    from .session import AgentSession, SessionBudgets, SessionState
    from .registry import create_default_registry
    from .policy import DataPolicy
    from .safety import CapabilityPolicy
    if data["version"] != 1:
        raise PersistenceError("Unsupported runtime checkpoint version")
    if runtime.async_policy:
        if data.get('async') != {'policy': policy_snapshot(runtime.async_policy)}:
            raise PersistenceError('Async policy checkpoint mismatch')
    elif 'async' in data:
        raise PersistenceError('Async execution no longer configured')
    if data.get('delivery_instruction_sha256') != (digest(runtime.delivery_instruction) if runtime.delivery_instruction is not None else None):
        raise PersistenceError('Delivery format contract checkpoint mismatch')
    runtime._drain_current_model=data.get("drain_current_model") is True
    if data.get('plugin_namespace'):
        runtime._plugin_namespace = data['plugin_namespace']
    runtime._host_pause_requested=data.get('host_pause_requested') is True
    values = unpack(data["fields"])
    if set(values) != set(FIELDS):
        raise PersistenceError("Incomplete runtime checkpoint")
    for k, v in values.items():
        setattr(runtime, k, v)
    runtime.state = SessionState(data["state"])
    runtime._computer_resume_state = SessionState(runtime._computer_resume_state) if runtime._computer_resume_state else None
    runtime._queue = deque(runtime._queue)
    runtime._usage = [ModelCallUsage(**v) for v in runtime._usage]
    runtime.messages = [Message.from_dict(v) for v in data["messages"]]
    runtime.tool_history = deepcopy(data["history"])
    runtime.completed_tool_calls = unpack(data["completed"])
    runtime.budgets = SessionBudgets(**data["budgets"])
    runtime.goals._goals = {g["id"]: Goal(**g) for g in data["goals"]}
    runtime.subagents = deepcopy(data["subagents"])
    if runtime.hybrid:
        if 'hybrid' not in data:
            raise PersistenceError('Missing Hybrid checkpoint')
        runtime.hybrid.restore(data['hybrid'])
    elif 'hybrid' in data:
        raise PersistenceError('Hybrid policy no longer configured')
    if runtime.adaptive:
        if 'adaptive' not in data:
            raise PersistenceError('Missing adaptive checkpoint')
        runtime.adaptive.restore(data['adaptive'])
    elif 'adaptive' in data:
        raise PersistenceError('Adaptive policy no longer configured')
    working = unpack(data["working"])
    if set(working) != set(WORKING):
        raise PersistenceError("Incomplete working state")
    for k, v in working.items():
        old = getattr(runtime.working, k)
        setattr(runtime.working, k, deque(v, maxlen=old.maxlen) if isinstance(old, deque) else v)
    runtime.working.cache.invalidate()
    runtime.registry.gateway.mode = runtime.permission_mode
    runtime.registry.gateway.plan_read_only = runtime._planning
    runtime.registry.gateway.audit = deepcopy(data["gateway_audit"])
    if hasattr(runtime.registry.gateway.judge, "calls"):
        runtime.registry.gateway.judge.calls = data["judge_calls"]
    runtime.events.events = [RuntimeEvent(**e) for e in data["events"]]
    runtime.events.sequence = data["sequence"]
    if data["stop"]:
        runtime.request_cancel(data["stop"])
    if runtime.finalization_policy:
        if "delivery" not in data:
            raise PersistenceError("Missing finalization checkpoint")
        delivery = unpack(data["delivery"])
        if set(delivery) != {"completion", "view", "output_tokens"}:
            raise PersistenceError("Invalid finalization checkpoint")
        runtime._completion, runtime._delivery_view, runtime._request_output_tokens = delivery["completion"], delivery["view"], delivery["output_tokens"]
        if runtime._durable_phase == 'model_inflight':
            # Input and attempt were committed before dispatch. Unknown output
            # must consume its conservative allowance once after process death;
            # otherwise restart would silently replenish the turn budget.
            runtime._failed_attempts += 1
            runtime._token_units += (runtime._request_output_tokens or runtime.budgets.max_output_tokens) * 16
        if runtime._completion:
            completion = runtime._completion
            if runtime.harness_policy:
                repairs = completion.get('harness_repairs',0)
                if type(repairs) is not int or not 0<=repairs<=runtime.harness_policy.max_completion_repairs:
                    raise PersistenceError('Invalid harness completion repair budget')
            if (type(completion['attempts']) is not int or not 0 <= completion['attempts'] <= runtime.finalization_policy.max_attempts
                    or not isinstance(completion['history'], list) or len(completion['history']) > runtime.finalization_policy.max_attempts):
                raise PersistenceError('Invalid finalization attempt history')
            if runtime._delivery_view is not None:
                from .finalization import ledger_projection
                projection = ledger_projection(runtime)
                if any(value != projection['ledger_sha256'] for value in (
                        completion.get('ledger_sha256'), runtime._delivery_view.get('ledger_sha256'))):
                    raise PersistenceError('Finalization view does not match canonical ledger')
        if runtime._durable_phase == "model_inflight" and runtime._finalizing:
            runtime._durable_interrupted_models += 1
            runtime._delivery_failure("process_interrupted", "Finalization request interrupted; provider usage UNKNOWN")
    elif "delivery" in data:
        raise PersistenceError("Finalization policy no longer configured")
    elif (conservative_interrupts or runtime.hybrid) and runtime._durable_phase == 'model_inflight':
        # A V4.1 parent retains the existing child execution/retry semantics,
        # but unknown child output must also stay charged to its parent budget.
        runtime._failed_attempts += 1
        runtime._token_units += runtime.budgets.max_output_tokens * 16
    if runtime._durable_phase == "model_inflight":
        runtime._durable_interrupted_models += 1
        runtime._streamed = False
        runtime._durable_phase = "ready"
    runtime._durable_phase = "ready" if runtime._durable_phase == "receipt" else runtime._durable_phase
    if runtime.computer and data["computer"]:
        from computer.runtime import ControlState
        runtime.computer.revision = data["computer"]["revision"] + 1
        runtime.computer.resync_generation = data["computer"]["resync_generation"] + 1
        runtime.computer.resync_revision = runtime.computer.revision
        runtime.computer.pause_requested.set()
        runtime.computer.state = ControlState.HUMAN
        runtime.computer.observations.clear()
        runtime._computer_resume_state = runtime.state
        runtime.state = SessionState.COMPUTER_PAUSED
    for worker_id, child_data in data["children"].items():
        record = next(r for r in runtime.subagents if r["id"] == worker_id)
        target, tier = record["backend"], record.get("tier")
        backend = runtime.local_backend if target == "local" else runtime.cloud_worker_backends.get(tier) if tier else runtime.cloud_backend
        if runtime.hybrid:
            _, backend = runtime.hybrid.resolve(target, record.get('backend_id'), record.get('configured_model'), tier)
        if backend is None:
            raise PersistenceError("Child backend no longer configured")
        ceiling = runtime.registry.gateway.capabilities
        read_only = record["read_only"]
        registry = create_default_registry(runtime.workspace, permission_mode=runtime.permission_mode,
            capabilities=CapabilityPolicy(read=ceiling.read, write=ceiling.write and not read_only,
                execute=ceiling.execute and not read_only, read_only=ceiling.read_only or read_only),
            data_policy=DataPolicy(local_only=runtime.hard_data_policy.local_only if runtime.hybrid else target == "local"),file_operations="move_file" in runtime.registry._tools)
        registry.authorization_guard=getattr(runtime.registry,"authorization_guard",None)
        registry.scope_policy=getattr(runtime.registry,"scope_policy",None)
        child = AgentSession(registry, backend=backend,
            local_backend=runtime.local_backend if runtime.hybrid else None,
            cloud_backend=runtime.cloud_backend if runtime.hybrid else None,
            cloud_worker_backends=runtime.cloud_worker_backends if runtime.hybrid else None,
            policy=runtime.routing_policy if runtime.hybrid else "local-only" if target == "local" else "cloud-only",
            budgets=SessionBudgets(**child_data["budgets"]), thinking=runtime.thinking_mode,
            reasoning=runtime.reasoning_mode, streaming=runtime.streaming, runtime_tools=False,
            depth=runtime.depth + 1, retry_policy=runtime.retry_policy, stabilization=runtime.controls,
            engine_policy=runtime.engine_policy,
            computer_runtime=runtime.computer, computer_owner=False,
            event_callback=lambda e, w=worker_id: runtime._emit("SubagentEvent", id=w, event=e.to_dict()),
            hybrid_policy=runtime.hybrid.policy if runtime.hybrid else None,
            hybrid_backends=runtime.hybrid.catalog if runtime.hybrid else None,
            hybrid_primary=record.get('backend_id'),
            harness_policy=runtime.harness_policy,
            adaptive_policy=runtime.adaptive.policy if runtime.adaptive else None,
            capability_profiles=runtime.adaptive.profiles if runtime.adaptive else None,
            task_traits=runtime._child_traits() if runtime.adaptive else None)
        if runtime.async_policy:
            child._async_enabled = True
            child._state_condition, child._scheduler = runtime._state_condition, runtime._scheduler
            child._scheduler_owner = runtime._scheduler_owner
            from .judge import LocalSafetyJudge
            if isinstance(child.registry.gateway.judge, LocalSafetyJudge):
                child.registry.gateway.judge.request_context = lambda c=child: c._scheduler.model_slot(c, c.local_backend)
        child._cancel_parent = child._ledger_parent = runtime
        child._worker_id = worker_id
        child._eligible = lambda c=child: bool(c.current_backend.health_check()) if c.primary == 'local' else False
        restore_runtime(child, child_data, conservative_interrupts=bool(runtime.finalization_policy or runtime.async_policy or conservative_interrupts))
        runtime._children[worker_id] = child
    if runtime.pending_approval and runtime.pending_approval.get("kind") in {"subagent_resume", "async_child"}:
        runtime.pending_approval["child"] = runtime._children[runtime.pending_approval["worker_id"]]


def nodes(runtime):
    yield runtime
    for child in runtime._children.values():
        yield from nodes(child)


def recovery_class(runtime):
    for node in nodes(runtime):
        intent = node._durable_intent
        if intent and not intent["read_only"]:
            return "UNKNOWN_BLOCKED"
        if any(r.get("side_effect_status") in {"unknown", "partial"} for r in node.tool_history):
            return "UNKNOWN_BLOCKED"
    if runtime.computer:
        journal=getattr(runtime.computer,"journal",None)
        if journal and any(journal.blocked(app) for app in runtime.computer.allowed_apps):return "UNKNOWN_BLOCKED"
        return "REQUIRES_REOBSERVATION"
    if any(n.pending_approval for n in nodes(runtime)):
        return "REQUIRES_APPROVAL"
    return "SAFE_TO_RESUME"


class SQLiteRuntimeStore:
    """Single live TaskService owner; one transaction per session tree boundary."""
    VERSION = 1

    def __init__(self, path, *, fault_hook=None):
        self.path = Path(path).expanduser().absolute()
        self.lock = threading.RLock()
        self.fault_hook = fault_hook
        self.failed = False
        self.connection = None
        self.owner = None
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            for p in (self.path, Path(str(self.path) + ".owner")):
                if p.is_symlink():
                    raise PersistenceError("Symlink runtime store refused")
            fd = os.open(str(self.path) + ".owner", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            self.owner = os.fdopen(fd, "a+")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.connection = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None, cached_statements=0)
            os.chmod(self.path, 0o600)
            db = self.connection
            version = db.execute("PRAGMA user_version").fetchone()[0]
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if version not in {0, self.VERSION} or (version == 0 and tables):
                raise PersistenceError("Unsupported persistent runtime schema; explicit migration required")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise PersistenceError("Runtime database integrity check failed")
            if db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                raise PersistenceError("WAL unavailable")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA fullfsync=ON")
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript("""BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS checkpoints(session_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                    payload TEXT NOT NULL, sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS journal(session_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    point TEXT NOT NULL, sha256 TEXT NOT NULL, at REAL NOT NULL,
                    PRIMARY KEY(session_id, revision));
                PRAGMA user_version=1; COMMIT;""")
        except Exception as exc:
            self.close()
            raise PersistenceError("Cannot open runtime store: " + type(exc).__name__) from exc

    def ensure_available(self):
        if self.failed or self.connection is None:
            raise PersistenceError("Persistent runtime fenced after storage failure/close")

    def save(self, session_id, payload, point):
        with self.lock:
            self.ensure_available()
            try:
                raw = dumps(payload)
                checksum = digest(raw)
                db = self.connection
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT revision FROM checkpoints WHERE session_id=?", (session_id,)).fetchone()
                revision = (row[0] if row else 0) + 1
                db.execute("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?,?)", (session_id, revision, raw, checksum))
                db.execute("INSERT INTO journal VALUES(?,?,?,?,?)", (session_id, revision, point, checksum, time.time()))
                if self.fault_hook:
                    self.fault_hook("before_commit", point)
                db.execute("COMMIT")
                if self.fault_hook:
                    self.fault_hook("after_commit", point)
                return revision
            except Exception as exc:
                self.failed = True
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise PersistenceError("Checkpoint failed; service fenced: " + type(exc).__name__) from exc

    def load(self):
        with self.lock:
            self.ensure_available()
            try:
                rows = self.connection.execute("SELECT session_id,revision,payload,sha256 FROM checkpoints").fetchall()
                result = []
                for session_id, revision, raw, checksum in rows:
                    events = self.connection.execute("SELECT revision,sha256 FROM journal WHERE session_id=? ORDER BY revision", (session_id,)).fetchall()
                    if digest(raw) != checksum or not events or events[-1] != (revision, checksum) or [e[0] for e in events] != list(range(1, revision + 1)):
                        raise PersistenceError("Checkpoint/journal integrity mismatch")
                    payload = json.loads(raw)
                    if payload["session"]["id"] != session_id:
                        raise PersistenceError("Session identity mismatch")
                    result.append(payload)
                if self.connection.execute("SELECT count(DISTINCT session_id) FROM journal").fetchone()[0] != len(rows):
                    raise PersistenceError("Orphan runtime journal")
                return result
            except Exception as exc:
                self.failed = True
                raise PersistenceError("Cannot load runtime checkpoints: " + type(exc).__name__) from exc

    def close(self):
        with self.lock:
            if self.connection:
                self.connection.close()
                self.connection = None
            if self.owner:
                self.owner.close()
                self.owner = None
