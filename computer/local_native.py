"""Default-off native keyboard backend with host-qualified, observation-scoped targets.

Only bounded Unicode key pairs are exposed. No activation, mouse dispatch,
helper broadcasting, private focus SPI, or automatic retry/fallback.
"""
from copy import deepcopy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid

from .backend import AXBackend
from .build import BUILD
from .macos import MacOSAXAdapter

KINDS = {"NSTextView", "WKWebView", "AppKit_sheet"}


def reject(reason, **extra):
    return {"status": "error", "error": "capability_rejected", "reason": reason,
            "action_sent": False, "verified": None, "replay_allowed": False,
            "fallback": "human", **extra}


class NativeOutcomeUnknown(RuntimeError):
    def __init__(self, cause, receipt):
        super().__init__(f"Native dispatch outcome UNKNOWN ({type(cause).__name__}); no replay")
        self.computer_receipt = receipt


class LocalNativeBackend(AXBackend):
    name = "local_native_experimental"
    native_keyboard = True
    capabilities = {**AXBackend.capabilities,
        **{key: "experimental_scoped_PoC_accepted_product_E2E_NOT_RUN" for key in
           ("background_keyboard", "ime_isolation", "modifier_isolation", *KINDS)},
        **{key: "capability_rejected_NOT_RUN" for key in
           ("ViewBridge", "Electron", "menu", "background_mouse")}}

    def __init__(self, allowed_apps, *, enabled=False, targets=(), transport=None,
                 lease_seconds=120, clock=time.monotonic):
        if not enabled:
            raise ValueError("LocalNativeBackend requires explicit experimental host opt-in")
        if not math.isfinite(lease_seconds) or not 0 < lease_seconds <= 120:
            raise ValueError("Native lease must be within (0, 120] seconds")
        self.targets = [self._validate_target(t, allowed_apps) for t in targets]
        if not self.targets:
            raise ValueError("Explicit qualified native targets required; no default app qualification")
        super().__init__(transport if transport is not None else
                         MacOSAXAdapter(allowed_apps, binary=BUILD / "localnativebridge"))
        self.clock, self.lease_seconds = clock, lease_seconds
        self.owner = uuid.uuid4().hex
        self._control = tempfile.TemporaryDirectory(prefix="localpilot-native-")
        self._stop_path = Path(self._control.name) / "stop"
        self._stopped = threading.Event()
        self._closed = False
        self._lock = threading.RLock()
        self._states = {}
        self._qualification_failures = {}
        self._leases = {}
        self._app_leases = {}
        self._cleanup = {"status": "ok", "cleanup": "no_owned_inputs"}
        self.task_context = None  # Assigned only by the trusted TaskService.

    @staticmethod
    def _validate_target(target, allowed_apps):
        fields = {"app", "kind", "window_title", "identifier", "bundle_path", "executable_sha256", "evidence"}
        # WK textarea exports an actual AXDOMIdentifier, not an AXIdentifier alias.
        dom_target = isinstance(target, dict) and "dom_identifier" in target
        if dom_target:
            fields = (fields - {"identifier"}) | {"dom_identifier"}
        if (not isinstance(target, dict) or set(target) != fields or
            any(not isinstance(v, str) or not v or len(v) > 2048 for v in target.values()) or
            target["app"] not in allowed_apps or target["kind"] not in KINDS or
            (dom_target and target["kind"] != "WKWebView") or
            not Path(target["bundle_path"]).is_absolute() or
            len(target["executable_sha256"]) != 64 or
            any(c not in "0123456789abcdef" for c in target["executable_sha256"])):
            raise ValueError("Native qualification needs exact app/kind/window/control/path/hash/evidence")
        return deepcopy(target)

    def _release_leases(self):
        for stream in self._leases.values():
            stream.close()  # flock ownership ends; lockfiles must never be unlinked.
        self._leases.clear()
        for stream in self._app_leases.values():
            stream.close()
        self._app_leases.clear()
        self._states.clear()
        self._qualification_failures.clear()

    @staticmethod
    def _lease_record(stream):
        path = Path(str(stream.name) + ".state")
        if not path.exists():
            return None
        with path.open() as record_stream:
            raw = record_stream.read(8193)
        if not raw:
            raise ValueError("Native lease recovery state empty; host recovery required")
        record = json.loads(raw)
        if (len(raw) > 8192 or not isinstance(record, dict) or type(record.get("version")) is not int or record["version"] != 1 or
                record.get("status") not in {"clean", "uncertain"} or
                type(record.get("pid")) is not int or
                not isinstance(record.get("process_birth"), str) or not record["process_birth"] or
                not isinstance(record.get("app"), str) or not record["app"]):
            raise ValueError("Native lease recovery state invalid; host recovery required")
        return record

    @staticmethod
    def _lease_directory():
        directory = BUILD.parent / "native-leases"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if directory.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise OSError("Native recovery directory must be private and host-owned")
        return directory

    def _app_lock(self, app):
        if app in self._app_leases:
            return self._app_leases[app]
        path = self._lease_directory() / ("app-" + hashlib.sha256(app.encode()).hexdigest() + ".guard")
        stream = path.open("a+")
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            stream.close()
            raise
        self._app_leases[app] = stream
        return stream

    def _pending_app_inputs(self, app):
        # The guard serializes every PID generation for this app. Legacy v1
        # uncertain records remain obligations, including after PID reuse.
        records = []
        for path in sorted(self._lease_directory().glob("*.lock.state")):
            class StatePath:
                name = str(path)[:-6]
            record = self._lease_record(StatePath())
            if record["status"] == "clean" and record.get("reconciliation", {}).get("kind") == "HUMAN_RISK_ACCEPTANCE":
                from .human_recovery import HumanRecovery, fingerprint, CONFIRMATIONS
                journal = HumanRecovery(self).journal(record["app"])
                reconciliation = record["reconciliation"]
                attempts = [a for a in journal["attempts"] if a.get("id") == reconciliation.get("recovery_id") and
                            a.get("generation") == reconciliation.get("generation")]
                original = {k: v for k, v in record.items() if k != "reconciliation"}
                original["status"] = "uncertain"
                if (len(attempts) != 1 or attempts[0].get("state") != "RECOVERED" or
                        attempts[0].get("basis") != "HUMAN_RISK_ACCEPTANCE" or
                        attempts[0].get("original") != original or
                        fingerprint(original) != reconciliation.get("original_obligation_hash") or
                        attempts[0].get("authorization", {}).get("physical_release") != "UNKNOWN" or
                        attempts[0].get("authorization", {}).get("basis") != "HUMAN_RISK_ACCEPTANCE" or
                        set(attempts[0].get("authorization", {}).get("confirmations", {})) != set(CONFIRMATIONS) or
                        any(v is not True for v in attempts[0].get("authorization", {}).get("confirmations", {}).values())):
                    raise ValueError("Human recovery admission certificate invalid")
            if record["status"] == "uncertain" and record["app"] == app:
                records.append((path, record))
        return records

    @staticmethod
    def _persist_lease(stream, identity, status, **facts):
        record = {"version": 1, "pid": identity["pid"], "process_birth": identity["process_birth"],
                  "app": identity["app"], "status": status, **facts}
        path = Path(str(stream.name) + ".state")
        temporary = None
        try:
            # Replace only the state sidecar, never the flock inode. A failed
            # clean-marker write leaves the previous uncertain record intact.
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".native-state-", delete=False) as output:
                temporary = Path(output.name)
                output.write(json.dumps(record, ensure_ascii=False))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            temporary = None  # A committed clean marker has no fallible temp cleanup.
            if status == "uncertain":
                fd = os.open(path.parent, os.O_RDONLY)
                try: os.fsync(fd)  # Admit dispatch only after durable uncertain intent.
                finally: os.close(fd)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def inspect_tree(self, app, **bounds):
        with self._lock:
            self._release_leases()  # Native bridge's AX handles are also globally observation-scoped.
            tree = super().inspect_tree(app, **bounds)
            if tree.get("status") != "ok":
                return tree
            for node in tree.get("nodes", []):
                candidates = [t for t in self.targets if t["app"] == app and
                              (t.get("dom_identifier") == node.get("dom_identifier") and
                               node.get("role") == "AXTextArea" and not tree.get("truncated", True) and
                               sum(n.get("dom_identifier") == t["dom_identifier"] for n in tree["nodes"]) == 1
                               if "dom_identifier" in t else t["identifier"] == node.get("identifier")) and
                              node.get("role") in {"AXTextArea", "AXTextField"}]
                if len(candidates) != 1:
                    continue
                policy = candidates[0]
                result = self.transport.request(op="native_context", app=app, handle=node["handle"], policy=policy)
                if result.get("status") != "ok":
                    self._qualification_failures[(app, node["handle"])] = deepcopy(result)
                    continue  # Read observation remains useful; action qualification fails closed.
                target = result["target"]
                pid = target["pid"]
                if pid not in self._leases:
                    BUILD.mkdir(parents=True, exist_ok=True)
                    # Shared across checkouts: one local product owner per PID.
                    try:
                        self._app_lock(app)
                        pending = self._pending_app_inputs(app)
                        if pending:
                            self._qualification_failures[(app, node["handle"])] = reject("input_cleanup_unknown", recovery=pending[0][1])
                            continue
                        lease_dir = self._lease_directory()
                    except BlockingIOError:
                        self._qualification_failures[(app, node["handle"])] = reject("pid_lease_conflict", pid=pid)
                        continue
                    except (OSError, ValueError) as exc:
                        self._qualification_failures[(app, node["handle"])] = reject("native_lease_state_unknown", detail=str(exc))
                        continue
                    stream = (lease_dir / f"{pid}.lock").open("a+")
                    try:
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        stream.close()
                        self._qualification_failures[(app, node["handle"])] = reject("pid_lease_conflict", pid=pid)
                        continue
                    try:
                        recovery = self._lease_record(stream)
                        if recovery and (recovery["pid"] != pid or recovery["status"] == "uncertain"):
                            self._qualification_failures[(app, node["handle"])] = reject("input_cleanup_unknown", recovery=recovery)
                            stream.close()
                            continue
                        # Process/window/helper death cannot establish release.
                    except (OSError, ValueError) as exc:
                        stream.close()
                        self._qualification_failures[(app, node["handle"])] = reject("native_lease_state_unknown", detail=str(exc))
                        continue
                    self._leases[pid] = stream
                self._states[(app, node["handle"])] = {
                    "identity": deepcopy(target), "policy": policy,
                    "lease": uuid.uuid4().hex, "owner": self.owner,
                    "expires": self.clock() + self.lease_seconds,
                    "software_cursor": {"position": None, "visible": False},
                    "keys": [], "buttons": [], "modifiers": [],
                }
            return tree

    def qualify_action(self, name, app, node):
        if name != "type_text":
            return super().qualify_action(name, app, node)
        with self._lock:
            state = self._states.get((app, node["handle"]))
            if self._stopped.is_set():
                return reject("dispatch_stopped")
            if self._cleanup.get("status") != "ok":
                return reject("input_cleanup_unknown")
            if not state:
                failure = self._qualification_failures.get((app, node["handle"]))
                return reject(failure.get("reason", "native_qualification_failed"),
                              qualification=deepcopy(failure)) if failure else reject("target_unverified_or_lease_conflict")
            if self.clock() >= state["expires"]:
                return reject("lease_expired")
            return {"status": "ok", "concurrent_input": True, "native": True}

    def action(self, app, handle, kind, **args):
        if kind != "type_text":
            return super().action(app, handle, kind, **args)  # Explicit semantic AX path, old protection retained.
        with self._lock:
            check = self.qualify_action(kind, app, {"handle": handle})
            if check["status"] != "ok":
                return check
            text = args.get("text")
            if not isinstance(text, str) or not text or len(text.encode("utf-16-le")) // 2 > 64:
                raise ValueError("Native text requires 1..64 UTF-16 units")
            state = self._states[(app, handle)]
            request_id = uuid.uuid4().hex
            fence = uuid.uuid4().hex
            self._cleanup = {"status": "error", "cleanup": "UNKNOWN", "request_id": request_id}
            metadata = {"backend": self.name, "request_id": request_id,
                        "target_identity": deepcopy(state["identity"]), "lease": state["lease"], "owner": self.owner}
            stream = self._leases[state["identity"]["pid"]]
            receipt_path = self._lease_directory() / f'{state["identity"]["pid"]}.{request_id}.no-dispatch.json'
            intent = {"owner": self.owner, "request_id": request_id, "lease": state["lease"],
                      "fence": fence, "target_identity": deepcopy(state["identity"]),
                      "controller": deepcopy(state["identity"].get("controller")),
                      "receipt_path": str(receipt_path), "task_context": deepcopy(self.task_context),
                      "input_state": "UNKNOWN", "unknown_reason": "dispatch_may_have_applied_release_unconfirmed"}
            try:
                # Durable intent before helper dispatch: death/exception cannot
                # erase uncertainty when flock ownership is released by the OS.
                self._persist_lease(stream, state["identity"], "uncertain", **intent)
            except OSError as exc:
                return reject("native_lease_persistence_unknown", **metadata,
                              input_cleanup=deepcopy(self._cleanup), detail=str(exc))
            try:
                result = self.transport.request(op="native_text", app=app, handle=handle,
                    policy=state["policy"], target=state["identity"], text=text,
                    stop_path=str(self._stop_path), lease=state["lease"], owner=self.owner,
                    fence=fence, receipt_path=str(receipt_path),
                    lease_remaining=max(0, state["expires"] - self.clock()), request_id=request_id)
                if (not isinstance(result, dict) or result.get("status") not in {"ok", "error"} or
                    not isinstance(result.get("input_cleanup"), dict) or
                    (result.get("action_sent") is not False and result.get("request_id") != request_id)):
                    raise RuntimeError("Invalid native receipt or request identity")
                self._cleanup = deepcopy(result["input_cleanup"])
                if (self._cleanup.get("status") == "ok" and
                        (self._cleanup.get("cleanup") not in {"no_owned_inputs", "owned_key_up_POSTED"} or
                         any(self._cleanup.get(k, []) != [] for k in ("keys", "buttons", "modifiers")))):
                    self._cleanup = {"status": "error", "cleanup": "UNKNOWN",
                                     "reason": "invalid_cleanup_proof", "helper_cleanup": deepcopy(result["input_cleanup"])}
                    result = {**result, "input_cleanup": deepcopy(self._cleanup)}
            except Exception as exc:
                self._record_outcome(state["identity"]["pid"], request_id, {**metadata,
                    "input_cleanup": deepcopy(self._cleanup), "action_sent": None, "verified": None,
                    "error_type": type(exc).__name__, "replay_allowed": False})
                raise NativeOutcomeUnknown(exc, {**metadata, "input_cleanup": deepcopy(self._cleanup),
                    "dispatch_stage": "UNKNOWN", "target_tap": "NOT_RUN"}) from exc
            if self._cleanup.get("status") == "ok":
                try:
                    self._persist_lease(stream, state["identity"], "clean", owner=self.owner, request_id=request_id)
                except OSError:
                    self._cleanup = {"status": "error", "cleanup": "UNKNOWN",
                                     "reason": "native_lease_persistence_unknown", "request_id": request_id,
                                     "helper_cleanup": deepcopy(result["input_cleanup"])}
                    result = {**result, "input_cleanup": deepcopy(self._cleanup)}
            if self._cleanup.get("status") != "ok":
                result = {**result, "status": "error", "error": "input_cleanup_unknown"}
            self._record_outcome(state["identity"]["pid"], request_id, {**result, **metadata})
            return {**result, "backend": self.name, "request_id": request_id,
                    "target_identity": state["identity"], "lease": state["lease"],
                    "owner": self.owner,
                    "target_tap": "NOT_RUN", "replay_allowed": False}

    def _record_outcome(self, pid, request_id, receipt):
        # Supplemental evidence only. Missing/torn outcome files never admit input.
        from .human_recovery import durable_json
        try:
            durable_json(self._lease_directory() / f"{pid}.{request_id}.outcome.json", receipt)
        except (OSError, ValueError, TypeError):
            pass

    def human_recovery_requires_approval(self):
        from .human_recovery import HumanRecovery
        try:
            return any(HumanRecovery(self).path(app).exists() for app in self.allowed_apps)
        except (OSError, ValueError):
            return True  # Unreadable policy store cannot grant an auto-approval.

    def recover_input(self, app, *, request_id, authorized=False):
        """Host-only reconciliation of a durable NO_DISPATCH terminal.

        No model tool, release event, mutation replay or automatic resume. The
        caller must authorize this exact request after reviewing the obligation.
        POSTED/empty owned collections/target death are insufficient.
        """
        if app not in self.allowed_apps or authorized is not True:
            return reject("native_recovery_authorization_required")
        with self._lock:
            if self._closed:
                return reject("dispatch_stopped")
            acquired = []
            try:
                self._app_lock(app)
                from .human_recovery import HumanRecovery, ACTIVE
                attempts = HumanRecovery(self).journal(app)["attempts"]
                if attempts and attempts[-1]["state"] in ACTIVE:
                    return reject("human_recovery_in_progress")
                pending = self._pending_app_inputs(app)
                if len(pending) != 1 or pending[0][1].get("request_id") != request_id:
                    return reject("native_recovery_obligation_mismatch")
                path, record = pending[0]
                pid = record["pid"]
                stream = self._leases.get(pid)
                if stream is None:
                    stream = Path(str(path)[:-6]).open("a+")
                    acquired.append(stream)
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Re-read under both locks. Bind every proof field to the
                # original intent, never to a new observation or controller.
                if self._lease_record(stream) != record:
                    return reject("native_recovery_obligation_mismatch")
                if (not isinstance(request_id, str) or len(request_id) != 32 or
                        any(c not in "0123456789abcdef" for c in request_id)):
                    return reject("native_recovery_proof_unavailable")
                proof_path = self._lease_directory() / f"{pid}.{request_id}.no-dispatch.json"
                if record.get("receipt_path") != str(proof_path) or proof_path.is_symlink():
                    return reject("native_recovery_proof_unavailable")
                with proof_path.open() as source:
                    raw = source.read(65537)
                proof = json.loads(raw)
                fields = ("owner", "request_id", "lease", "fence", "target_identity", "controller")
                controller = record.get("controller")
                if (len(raw) > 65536 or not isinstance(proof, dict) or
                        type(proof.get("version")) is not int or proof["version"] != 1 or
                        proof.get("kind") != "NO_DISPATCH" or proof.get("terminal") is not True or
                        type(proof.get("posted_events")) is not int or proof["posted_events"] != 0 or
                        proof.get("input_cleanup") != {"status": "ok", "cleanup": "no_owned_inputs", "keys": [], "buttons": [], "modifiers": []} or
                        not isinstance(controller, dict) or not controller.get("instance") or
                        any(record.get(k) is None or proof.get(k) != record[k] for k in fields)):
                    return reject("native_recovery_proof_invalid")
                identity = {k: record[k] for k in ("app", "pid", "process_birth")}
                # Complete fallible durability checks before publishing clean.
                # The old uncertain intent and zero-dispatch proof are already
                # durable. Clean is an atomic admission commit, not a promise
                # that recovery survives power loss: an unflushed rename may
                # revert to uncertain after reboot, which safely blocks again.
                # Never publish clean then attempt a fallible rollback.
                fd = os.open(path.parent, os.O_RDONLY)
                try: os.fsync(fd)
                finally: os.close(fd)
                self._persist_lease(stream, identity, "clean", **{k: v for k, v in record.items()
                    if k not in {"version", "app", "pid", "process_birth", "status"}},
                    reconciliation={"kind": "NO_DISPATCH", "authorized_by_owner": self.owner})
                if self._cleanup.get("request_id") == request_id:
                    self._cleanup = {"status": "ok", "cleanup": "no_owned_inputs", "request_id": request_id}
                self._states.clear()  # New observation/proposal/approval required.
                return {"status": "ok", "recovery": "NO_DISPATCH", "request_id": request_id,
                        "action_sent": False, "replay_allowed": False, "requires_resync": True}
            except BlockingIOError:
                return reject("pid_lease_conflict")
            except (OSError, ValueError, TypeError, KeyError) as exc:
                return reject("native_recovery_proof_unavailable", detail=type(exc).__name__)
            finally:
                for stream in acquired: stream.close()
                # Do not retain admission locks or identities from recovery.
                self._release_leases()

    def request_stop(self):
        # Does not wait for either the Runtime or stdio lock. Helper sees this between events.
        if self._closed:
            return
        self._stop_path.touch()
        self._stopped.set()

    def quiesce(self):
        with self._lock:
            self._release_leases()
            return {**self._cleanup, "quiescent": True}

    def finish_resume(self):
        if self._cleanup.get("status") != "ok":
            raise RuntimeError("Native input cleanup UNKNOWN; recreate backend after host recovery")
        self._stop_path.unlink(missing_ok=True)
        self._stopped.clear()

    def close(self):
        self.request_stop()
        with self._lock:
            if self._closed:
                return
            try:
                super().close()
            finally:
                self._release_leases()
                self._closed = True
                self._control.cleanup()


def configured_computer_backend(allowed_apps, native_targets=None):
    """Host-only configuration; no native enablement or target qualifications in model schemas."""
    if native_targets is None:
        return AXBackend(MacOSAXAdapter(allowed_apps))
    targets = json.loads(Path(native_targets).read_text(encoding="utf-8"))
    return LocalNativeBackend(allowed_apps, enabled=True, targets=targets)
