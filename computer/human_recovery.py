"""Host control recovery. Human risk acceptance never attests physical release.

The durable journal precedes admission. App/PID flocks serialize this protocol
with dispatch and V3 reconciliation; uncertain sidecars remain the admission
authority until the final atomic clean publication. No input is dispatched here.
"""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

from .backend import AXBackend
from .local_native import reject


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def durable_json(path, value):
    """Only publish after all fallible durability checks. Reboot may fail closed."""
    path = Path(path)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(raw.encode()) > 1048576:
        raise ValueError("Recovery journal capacity reached; retain evidence and quarantine")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".recovery-", delete=False) as out:
            temporary = Path(out.name)
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, path)
        temporary = None  # No fallible cleanup after an admission publication.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_json(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Symlink recovery evidence")
    with path.open() as source:
        raw = source.read(1048577)
    if len(raw.encode()) > 1048576:
        raise ValueError("Oversized recovery evidence")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Invalid recovery evidence")
    return value


CONFIRMATIONS = {
    "app_terminated_or_restarted": "I deliberately terminated or restarted the affected App.",
    "physical_release_unverified": "Physical input release remains UNKNOWN; this is risk acceptance.",
    "original_may_have_applied": "The original mutation may have applied and must not be replayed.",
    "new_task_requires_approval": "Only a new task with fresh observation and Gateway approval may proceed.",
}
ACTIVE = {"RECOVERY_REQUESTED", "AWAITING_HUMAN", "REVALIDATING"}


class HumanRecovery:
    def __init__(self, backend, *, clock=time.time, ttl=120):
        self.backend, self.clock, self.ttl = backend, clock, ttl

    def path(self, app):
        return self.backend._lease_directory() / ("app-" + hashlib.sha256(app.encode()).hexdigest() + ".human-recovery.json")

    def journal(self, app):
        path = self.path(app)
        if not path.exists():
            return {"version": 1, "app": app, "attempts": []}
        value = read_json(path)
        if (type(value.get("version")) is not int or value["version"] != 1 or value.get("app") != app or
                not isinstance(value.get("attempts"), list) or any(not isinstance(a, dict) for a in value["attempts"])):
            raise ValueError("Invalid recovery journal")
        states = {*ACTIVE, "RECOVERED", "STILL_QUARANTINED"}
        for generation, attempt in enumerate(value["attempts"], 1):
            if (attempt.get("state") not in states or type(attempt.get("generation")) is not int or
                    attempt["generation"] != generation or not isinstance(attempt.get("id"), str) or
                    not isinstance(attempt.get("original"), dict) or not isinstance(attempt.get("events"), list)):
                raise ValueError("Invalid recovery attempt")
        return value

    def save(self, journal):
        durable_json(self.path(journal["app"]), journal)

    @contextmanager
    def locked(self, app):
        b = self.backend
        if app not in b.allowed_apps or b._closed:
            raise ValueError("Recovery App unavailable")
        with b._lock:
            acquired = []
            try:
                if b._closed:
                    raise ValueError("Recovery backend closed")
                b._app_lock(app)
                pending = b._pending_app_inputs(app)
                for path, record in pending:
                    stream = b._leases.get(record["pid"])
                    if stream is None:
                        stream = Path(str(path)[:-6]).open("a+")
                        acquired.append(stream)
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    if b._lease_record(stream) != record:
                        raise ValueError("Obligation changed")
                yield pending
            finally:
                for stream in acquired:
                    stream.close()
                b._release_leases()  # Never retain a recovery dispatch identity.

    def _target(self, app, expected=None):
        b = self.backend
        if expected is None:
            tree = AXBackend.inspect_tree(b, app, max_nodes=512, max_depth=20)
            if tree.get("status") != "ok" or tree.get("truncated", True):
                raise ValueError("Incomplete AX recovery observation")
            candidates = []
            for policy in b.targets:
                if policy["app"] != app:
                    continue
                key = "dom_identifier" if "dom_identifier" in policy else "identifier"
                nodes = [n for n in tree.get("nodes", []) if n.get(key) == policy[key]]
                if len(nodes) == 1:
                    result = b.transport.request(op="native_context", app=app, handle=nodes[0]["handle"], policy=policy)
                    if (result.get("status") == "ok" and result.get("recovery_readiness", {}).get("event_access") is True and
                            result.get("recovery_readiness", {}).get("secure_event_input") is False):
                        candidates.append({"policy": deepcopy(policy), "target": result["target"], "handle": nodes[0]["handle"]})
            if len(candidates) != 1:
                raise ValueError("Need exactly one fully qualified recovery target")
            return candidates[0]
        result = b.transport.request(op="native_context", app=app, handle=expected["handle"], policy=expected["policy"])
        if (result.get("status") != "ok" or result.get("target") != expected["target"] or
                result.get("recovery_readiness", {}).get("event_access") is not True or
                result.get("recovery_readiness", {}).get("secure_event_input") is not False):
            raise ValueError("Recovery target identity changed")
        return expected

    def _exit_evidence(self, app, original, candidate):
        controller = original.get("controller")
        if (not isinstance(controller, dict) or not controller.get("instance") or
                original.get("owner") == self.backend.owner or not original.get("lease") or not original.get("fence")):
            raise ValueError("Original owner/lease/controller cannot be fenced")
        evidence = []
        for identity in (original, controller):
            pid, birth = identity.get("pid"), identity.get("process_birth")
            if type(pid) is not int or pid <= 0 or not isinstance(birth, str) or not birth or birth == "UNKNOWN":
                raise ValueError("Old process identity unavailable")
            result = self.backend.transport.request(op="native_process_status", app=app, pid=pid, process_birth=birth)
            if (result.get("status") != "ok" or result.get("pid") != pid or result.get("process_birth") != birth or
                    result.get("old_generation_exited") is not True or
                    result.get("evidence") not in {"proc_pidinfo_birth", "kill_zero_ESRCH"}):
                raise ValueError("Old process/helper exit unconfirmed")
            evidence.append(result)
        old = original.get("target_identity", {})
        new = candidate["target"]
        # A changed PID by itself is never a release/recovery criterion.
        if (new.get("app") != app or (new.get("pid"), new.get("process_birth")) == (original["pid"], original["process_birth"]) or
                new.get("window_id") == old.get("window_id") or new == old or
                new.get("controller", {}).get("instance") == controller["instance"]):
            raise ValueError("New process/window/target/controller required")
        return evidence

    def _result(self, attempt, **extra):
        return {"status": "ok" if attempt["state"] == "RECOVERED" else "pending" if attempt["state"] in ACTIVE else "error",
                "state": attempt["state"], "recovery": deepcopy(attempt), "physical_release": "UNKNOWN",
                "verified": None, "original_task_success": False, "replay_allowed": False,
                "requires_new_task": True, "requires_fresh_observation": True, "requires_gateway_approval": True, **extra}

    def receipts(self, record):
        receipts = {}
        proof_path = self.backend._lease_directory() / f'{record["pid"]}.{record.get("request_id")}.no-dispatch.json'
        for label, path in (("no_dispatch", str(proof_path) if record.get("receipt_path") == str(proof_path) else None),
                            ("dispatch_release_cleanup", str(self.backend._lease_directory() / f'{record["pid"]}.{record.get("request_id")}.outcome.json'))):
            try:
                receipts[label] = read_json(path) if path else {"availability": "UNKNOWN"}
            except (OSError, ValueError, TypeError):
                receipts[label] = {"availability": "UNKNOWN"}
        return receipts

    def committed(self, attempt, pending):
        if pending:
            return False
        path = self.backend._lease_directory() / f'{attempt["original"]["pid"]}.lock.state'
        clean = read_json(path)
        certificate = clean.get("reconciliation", {})
        return (clean.get("status") == "clean" and certificate.get("recovery_id") == attempt["id"] and
                certificate.get("generation") == attempt["generation"])

    def inspect(self, app):
        try:
            # Read-only snapshots remain available while the old owner holds
            # admission locks. They confer no permission; all mutations re-read
            # the exact obligation under both App and PID flocks.
            with self.backend._lock:
                if app not in self.backend.allowed_apps:
                    raise ValueError("Recovery App unavailable")
                pending = self.backend._pending_app_inputs(app)
                journal = self.journal(app)
                obligations = []
                for _, record in pending:
                    obligations.append({"intent": record, "receipts": self.receipts(record), "input_state": "UNKNOWN",
                                        "reason": "dispatch_may_have_applied_release_unconfirmed"})
                state = "QUARANTINED" if pending else "NO_QUARANTINE"
                if journal["attempts"]:
                    latest = journal["attempts"][-1]["state"]
                    state = "STILL_QUARANTINED" if pending and latest == "RECOVERED" else latest
                return {"status": "ok", "app": app, "state": state, "admission_committed": not pending, "snapshot_only": True,
                        "obligations": obligations, "attempts": journal["attempts"], "confirmations": CONFIRMATIONS,
                        "physical_release": "UNKNOWN", "verified": None}
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return reject("recovery_inspection_unavailable", state="STILL_QUARANTINED", detail=type(exc).__name__)

    def operate(self, action, app, *, binding, principal, **body):
        """Only trusted host callers supply binding/principal; neither is a tool argument."""
        try:
            if not isinstance(principal, str) or not principal or not isinstance(binding, dict):
                raise ValueError("Trusted host identity required")
            with self.locked(app) as pending:
                journal = self.journal(app)
                attempts = journal["attempts"]
                if action == "request":
                    if self.backend._stopped.is_set():
                        raise ValueError("Recovery stopped by host control")
                    if set(body) != {"request_id", "idempotency_key"} or any(not isinstance(v, str) or not 1 <= len(v) <= 128 for v in body.values()):
                        raise ValueError("request requires bounded request_id/idempotency_key")
                    duplicate = next((a for a in attempts if a["idempotency_key"] == body["idempotency_key"] and a["binding"] == binding), None)
                    if duplicate:
                        if duplicate["original"]["request_id"] != body["request_id"]:
                            raise ValueError("Idempotency payload conflict")
                        if duplicate["state"] == "RECOVERED" and not self.committed(duplicate, pending):
                            return reject("recovery_superseded_or_commit_missing", state="STILL_QUARANTINED",
                                          historical_recovery=deepcopy(duplicate))
                        return self._result(duplicate, idempotent=True)
                    if attempts and attempts[-1]["state"] in ACTIVE:
                        return reject("recovery_conflict", state=attempts[-1]["state"])
                    if len(pending) != 1 or pending[0][1].get("request_id") != body["request_id"]:
                        raise ValueError("Exact single UNKNOWN obligation required")
                    original = deepcopy(pending[0][1])
                    attempt = {"id": uuid.uuid4().hex, "generation": len(attempts) + 1, "state": "RECOVERY_REQUESTED",
                               "idempotency_key": body["idempotency_key"], "binding": deepcopy(binding), "requested_by": principal,
                               "original": original, "receipts": self.receipts(original), "obligation_hash": fingerprint(original), "created_at": self.clock(),
                               "expires_at": self.clock() + self.ttl, "events": []}
                    attempts.append(attempt)
                    self.transition(journal, attempt, "RECOVERY_REQUESTED", principal)
                    try:
                        candidate = self._target(app)
                    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
                        self.transition(journal, attempt, "STILL_QUARANTINED", principal, reason=str(exc)[:256])
                        return self._result(attempt)
                    attempt["candidate"] = deepcopy(candidate)
                    attempt["target_fingerprint"] = fingerprint(candidate)
                    self.transition(journal, attempt, "AWAITING_HUMAN", principal)
                    return self._result(attempt, confirmations=CONFIRMATIONS)
                if action not in {"authorize", "revalidate", "reject"}:
                    raise ValueError("Unknown recovery operation")
                fields = {"recovery_id", "generation"}
                if action == "authorize":
                    fields |= {"target_fingerprint", "confirmations"}
                if set(body) != fields or type(body.get("generation")) is not int:
                    raise ValueError("Exact recovery identity and generation required")
                attempt = next((a for a in attempts if a["id"] == body["recovery_id"] and a["generation"] == body["generation"]), None)
                if attempt is None or attempt is not attempts[-1]:
                    raise ValueError("Stale recovery generation")
                if action == "reject":
                    # Host can abandon an orphaned request after Runtime restart.
                    # Abandonment is never admission and records the new principal.
                    if attempt["state"] == "RECOVERED":
                        raise ValueError("Committed recovery cannot be rejected retroactively")
                    if attempt["state"] == "STILL_QUARANTINED":
                        return self._result(attempt, idempotent=True)
                    self.transition(journal, attempt, "STILL_QUARANTINED", principal, reason="host_rejected")
                    return self._result(attempt)
                if attempt["binding"] != binding or attempt["requested_by"] != principal:
                    raise ValueError("Recovery host/session binding mismatch")
                if attempt["state"] == "RECOVERED":
                    # A journal commit without a clean sidecar is never success.
                    if action == "authorize" and (body["target_fingerprint"] != attempt["target_fingerprint"] or
                            body["confirmations"] != attempt["authorization"]["confirmations"]):
                        raise ValueError("Idempotency payload conflict")
                    if not self.committed(attempt, pending):
                        return reject("recovery_superseded_or_commit_missing", state="STILL_QUARANTINED")
                    return self._result(attempt, idempotent=True)
                if attempt["state"] not in ACTIVE:
                    return self._result(attempt)
                if len(pending) != 1 or fingerprint(pending[0][1]) != attempt["obligation_hash"]:
                    raise ValueError("Recovery obligation changed")
                if not attempt["created_at"] <= self.clock() <= attempt["expires_at"]:
                    self.transition(journal, attempt, "STILL_QUARANTINED", principal, reason="authorization_expired")
                    return self._result(attempt)
                try:
                    candidate = self._target(app, attempt["candidate"])
                    exits = self._exit_evidence(app, attempt["original"], candidate)
                    env = self.backend.environment()
                    if (self.backend._stopped.is_set() or env.get("locked") is not False or env.get("session_available") is not True or
                            env.get("frontmost_app") in {None, "UNKNOWN", app} or type(env.get("frontmost_pid")) is not int or
                            env["frontmost_pid"] <= 0 or env["frontmost_pid"] == candidate["target"]["pid"]):
                        raise ValueError("Environment unqualified")
                    if action == "authorize":
                        if (body["target_fingerprint"] != attempt["target_fingerprint"] or
                                not isinstance(body["confirmations"], dict) or set(body["confirmations"]) != set(CONFIRMATIONS) or
                                any(v is not True for v in body["confirmations"].values())):
                            raise ValueError("Explicit complete human risk authorization required")
                        if attempt["state"] == "REVALIDATING":
                            return self._result(attempt, idempotent=True)
                        if attempt["state"] != "AWAITING_HUMAN":
                            raise ValueError("Recovery not awaiting human")
                        attempt["authorization"] = {"principal": principal, "basis": "HUMAN_RISK_ACCEPTANCE",
                            "confirmations": deepcopy(body["confirmations"]), "target_fingerprint": attempt["target_fingerprint"],
                            "at": self.clock(), "physical_release": "UNKNOWN"}
                        attempt["exit_evidence"] = exits
                        self.transition(journal, attempt, "REVALIDATING", principal)
                        return self._result(attempt)
                    if attempt["state"] != "REVALIDATING" or not attempt.get("authorization"):
                        raise ValueError("Human authorization required before revalidation")
                    # Query old generations again after target qualification, then
                    # resolve target one final time. Future dispatch still performs
                    # its own full qualification and helper fence check.
                    attempt["exit_evidence"] = self._exit_evidence(app, attempt["original"], candidate)
                    self._target(app, candidate)
                    if self.backend._stopped.is_set():
                        raise ValueError("Recovery stopped by host control")
                    attempt["basis"] = "HUMAN_RISK_ACCEPTANCE"
                    self.transition(journal, attempt, "RECOVERED", principal)
                    original = attempt["original"]
                    clean = {**deepcopy(original), "status": "clean", "reconciliation": {
                        "kind": "HUMAN_RISK_ACCEPTANCE", "recovery_id": attempt["id"], "generation": attempt["generation"],
                        "physical_release": "UNKNOWN", "verified": None, "original_obligation_hash": attempt["obligation_hash"]}}
                    # Journal must be durable before publishing the admission commit.
                    fd = os.open(self.path(app), os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                    durable_json(pending[0][0], clean)
                    return self._result(attempt)
                except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
                    # If clean publication failed, the uncertain intent is intact.
                    # Failure to write this terminal state also fails closed.
                    self.transition(journal, attempt, "STILL_QUARANTINED", principal, reason=str(exc)[:256])
                    return self._result(attempt)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            return reject("human_recovery_refused", state="STILL_QUARANTINED", detail=str(exc)[:256])

    def transition(self, journal, attempt, state, principal, **facts):
        attempt["state"] = state
        attempt["events"].append({"state": state, "at": self.clock(), "principal": principal, **facts})
        self.save(journal)
