"""Bounded observation contract and consent boundary, independent of model output."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
import time

from .app_profiles import app_profile, window_qualified, summarize_observation, compact_nodes

SECRET = re.compile(r"(?i)(?:password|passwd|secret|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|authorization|cookie|密码|密钥|令牌)\s*[:=：]\s*\S+|(?:sk-[A-Za-z0-9_-]{8,})|(?:gh[pousr]_[A-Za-z0-9]{12,})|(?:Bearer\s+\S+)")
PRIVATE_KEYS = re.compile(r"(?i)(password|secret|token|cookie|keychain|credential|secure|input_value)")
PRIVATE_FILE = re.compile(r"(?i)(?:^|[/_.-])(?:credentials?|secrets?|passwords?|tokens?|cookies?|api[-_]?keys?|(?:access|refresh)[-_]?tokens?|id_rsa|id_ed25519)(?:$|[/_.-])|密码|口令|密钥|令牌|\.(?:pem|key|p12|pfx|env)$")


def redact_text(text):
    if not isinstance(text, str):
        raise ValueError("Observed text must be a string")
    if "-----BEGIN " in text and "PRIVATE KEY-----" in text:
        return "[REDACTED_PRIVATE_KEY]"
    return SECRET.sub("[REDACTED_SECRET]", text)


def bounded_text(text, max_bytes=2000):
    return redact_text(text).encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def sanitize(value, depth=0):
    if depth > 4:
        raise ValueError("Observation evidence too deeply nested")
    if isinstance(value, str):
        return redact_text(value[:4000])
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Nonfinite evidence")
        return value
    if isinstance(value, list):
        return [sanitize(v, depth+1) for v in value[:64]]
    if isinstance(value, dict):
        return {str(k)[:100]: sanitize(v, depth+1) for k, v in list(value.items())[:64] if not PRIVATE_KEYS.search(str(k))}
    raise ValueError("Observation evidence must be JSON data")


@dataclass(frozen=True)
class ObservationEvent:
    timestamp: float
    source: str
    kind: str
    object: dict
    evidence: dict
    confidence: float
    sensitivity: str
    dedupe_key: str
    source_reference: str = ""
    version_id: str = ""
    epistemic: str = "observed"
    important: bool = False

    @classmethod
    def create(cls, source, kind, object, evidence, *, timestamp=None, confidence=1.0,
               sensitivity="private", source_reference="", version_id="", important=False):
        now = time.time() if timestamp is None else timestamp
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError("Invalid observation timestamp")
        if not isinstance(source, str) or not source or len(source) > 80 or not isinstance(kind, str) or not kind or len(kind) > 80:
            raise ValueError("Invalid observation source/kind")
        if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Invalid observation confidence")
        if sensitivity not in {"public", "private", "sensitive"} or type(important) is not bool:
            raise ValueError("Invalid sensitivity/importance")
        if not isinstance(object, dict) or not isinstance(evidence, dict):
            raise ValueError("Observation object/evidence must be dictionaries")
        obj, proof = sanitize(object), sanitize(evidence)
        if len(json.dumps(obj, ensure_ascii=False).encode()) > 4096 or len(json.dumps(proof, ensure_ascii=False).encode()) > 8192:
            raise ValueError("Observation object/evidence exceeds memory byte budget")
        reference, version = redact_text(source_reference)[:2000], str(version_id)[:100]
        identity = [source, kind, obj, proof, reference, version]
        # Identical repeated native snapshots merge; source/version changes stay distinct.
        key = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        result = cls(float(now), source, kind, obj, proof, float(confidence), sensitivity, key,
                     reference, version, "observed", important)
        if len(json.dumps(asdict(result), ensure_ascii=False).encode()) > 32768:
            raise ValueError("Observation event exceeds byte budget")
        return result

    def to_dict(self):
        return asdict(self)


class ObservationPrivacy:
    def __init__(self, config, store, scope):
        self.config, self.store, self.scope = config, store, scope

    def scope_description(self):
        c = self.config
        value = {"files": list(c.watch_dirs), "excluded_directories": list(c.exclude_dirs),
                "native_enabled": c.native_observation_enabled, "allowed_apps": list(c.native_app_allowlist),
                "excluded_apps": list(c.native_app_exclusions), "ax_enabled": c.native_ax_enabled,
                "excluded_windows": list(getattr(c, "native_window_exclusions", ())),
                "content_apps": list(c.native_content_app_allowlist), "max_nodes": c.native_ax_max_nodes,
                "max_depth": c.native_ax_max_depth, "processing": "local", "isolation": "application_checks_and_separate_process; OS_SANDBOX_NOT_IMPLEMENTED"}
        target = getattr(c, "native_controlled_target", None)
        if getattr(c, "native_all_apps_enabled", False):
            value["all_apps"] = True
        if getattr(c, "native_all_apps_content_enabled", False):
            value["all_content"] = True
        titles = getattr(c, "native_content_window_allowlist", ())
        if titles:
            value["content_windows"] = list(titles)
        if target is not None:
            from companion.observers.native import controlled_target_descriptor
            value["controlled_target"] = controlled_target_descriptor(target)
        return value

    def consent_id(self):
        return hashlib.sha256(json.dumps(self.scope_description(), sort_keys=True).encode()).hexdigest()

    def authorize(self, confirmed=False):
        if confirmed is not True:
            return {"status": "approval_required", "scope": self.scope_description(), "consent_id": self.consent_id()}
        self.store.set("native_observation_consent", self.consent_id())
        self.store.set("observation_paused", False)
        return self.status()

    def native_allowed(self):
        consent = self.store.get("native_observation_consent")
        current = self.consent_id()
        # V0.4 had no window exclusions. The empty default preserves its exact
        # scope and read authorization; migrations never authorize new scope.
        if consent != current and not getattr(self.config, "native_window_exclusions", ()) and not getattr(self.config, "native_controlled_target", None):
            legacy = self.scope_description()
            legacy.pop("excluded_windows")
            if consent == hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest():
                self.store.set("native_observation_consent", current)
                consent = current
        return self.config.native_observation_enabled and not self.paused() and consent == current

    def paused(self):
        return self.store.get("observation_paused", False) or self.store.get("indexing_paused", False)

    def file_allowed(self, filename):
        return not self.paused() and self.scope.allowed(filename) and not PRIVATE_FILE.search(str(filename))

    def filter_native(self, raw):
        if not self.native_allowed() or not isinstance(raw, dict):
            return None
        obj = raw.get("object", {})
        if not isinstance(obj, dict):
            return None
        bundle = obj.get("bundle_id", "")
        if raw.get("source") not in {"nsworkspace", "accessibility", "session"}:
            return None
        from companion.observers.native import native_options, app_scope_allowed, content_scope_allowed
        options = native_options(self.config)
        if raw.get("source") != "session" and not app_scope_allowed(bundle, options):
            return None
        proof = raw.get("evidence", {})
        if not isinstance(proof, dict):
            return None
        target = getattr(self.config, "native_controlled_target", None)
        if target is not None and raw.get("source") != "session":
            from companion.observers.native import controlled_target_descriptor
            target = controlled_target_descriptor(target)
            if obj.get("pid") != target["pid"] or bundle != target["bundle_id"]:
                return None
        if raw.get("kind") == "ax.snapshot":
            if target is not None:
                from companion.observers.native import controlled_target_descriptor, controlled_target_digest
                target = controlled_target_descriptor(target)
                if (obj.get("pid") != target["pid"] or bundle != target["bundle_id"]
                        or proof.get("capture_scope") != "controlled_owned_application"
                        or proof.get("target_descriptor_sha256") != controlled_target_digest(target)):
                    return None
            elif (proof.get("capture_scope") in {"controlled_owned_application", "authorized_application_inspection"} or obj.get("capture_scope") in {"controlled_owned_application", "authorized_application_inspection"} or proof.get("target_descriptor_sha256")
                  or proof.get("read_scope") == "authorized_windows_filtered_private_inputs"):
                return None
        if proof.get("window_title") in getattr(self.config, "native_window_exclusions", ()):
            return None
        if raw.get("kind") == "ax.snapshot" and content_scope_allowed(bundle, options):
            title = proof.get("window_title")
            exact_titles = getattr(self.config, "native_content_window_allowlist", ())
            if title is not None and not window_qualified(title, exact_titles):
                return None
            if exact_titles and title is None:
                return None
        metadata_keys = {"role", "nodes", "node_count", "coverage", "state", "notification", "reason", "truncated",
                         "ax_permission", "lock_state", "session_state", "screen_state", "sleep_state", "read_errors", "unsupported_notifications", "ax_error",
                         "read_status", "complete", "structural_complete", "attributes_complete", "content_truncated", "read_error_count", "pruned_count", "shared_core_version", "window_coverage", "read_scope", "capture_scope", "target_descriptor_sha256", "profile_pruned_count", "window_references"}
        proof = {k:v for k,v in proof.items() if k in metadata_keys | {"window_title"}}
        obj = {k:v for k,v in obj.items() if k in {"bundle_id", "pid", "app", "window_id"}}
        original_count = len(proof.get("nodes", [])) if isinstance(proof.get("nodes"), list) else 0
        if isinstance(proof.get("nodes"), list):
            nodes, blocked, accepted_ids = [], set(), set()
            for node in proof["nodes"][:512]:
                if not isinstance(node, dict):
                    continue
                role, subrole = node.get("role"), node.get("subrole", "")
                node_id, parent = node.get("id"), node.get("parent")
                if type(node_id) is not int or not 0 <= node_id < 10000:
                    continue
                if node_id in accepted_ids or node_id in blocked:
                    blocked.add(node_id)
                    continue
                if parent is not None and (type(parent) is not int or parent >= node_id or parent < 0):
                    blocked.add(node_id)
                    continue
                if parent is not None and parent not in accepted_ids:
                    blocked.add(node_id)
                    continue
                profile = app_profile(bundle)
                if (not isinstance(role, str) or role in {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField", "AXSecureTextField", "AXUnknown"} | profile.denied_roles
                        or not re.fullmatch(r"AX[A-Za-z]{1,60}", role)
                        or not isinstance(subrole, str) or (subrole and not re.fullmatch(r"AX[A-Za-z]{1,60}", subrole))
                        or subrole in profile.denied_subroles or parent in blocked):
                    blocked.add(node_id)
                    continue
                clean = {k:v for k,v in node.items() if k in {"id", "parent", "role", "subrole"}}
                if isinstance(node.get("children_read_status"), str) and node["children_read_status"] in {"READ_SUCCESS_EMPTY", "READ_SUCCESS_NONEMPTY", "READ_FAILED", "READ_PARTIAL", "UNKNOWN"}:
                    clean["children_read_status"] = node["children_read_status"]
                if role == "AXStaticText" and isinstance(node.get("text"), str):
                    clean["text"] = node["text"]
                nodes.append(clean)
                accepted_ids.add(node_id)
            proof["nodes"] = nodes
        if raw.get("source") == "accessibility" and not self.config.native_ax_enabled:
            return None
        if raw.get("kind") == "ax.snapshot":
            states = {"READ_SUCCESS_EMPTY", "READ_SUCCESS_NONEMPTY", "READ_FAILED", "READ_PARTIAL", "UNKNOWN"}
            if not isinstance(proof.get("read_status"), str) or proof["read_status"] not in states:
                proof["read_status"], proof["complete"] = "UNKNOWN", False
            if proof["read_status"] in {"READ_FAILED", "READ_PARTIAL", "UNKNOWN"}:
                proof["complete"] = False
            if isinstance(proof.get("read_errors"), list):
                from companion.observers.native import _read_errors
                proof["read_errors"] = _read_errors(proof["read_errors"])
        if not content_scope_allowed(bundle, options):
            # Metadata does not include window titles or page/body text.
            obj = {k: v for k, v in obj.items() if k in {"bundle_id", "pid", "app", "window_id"}}
            proof = {k: v for k, v in proof.items() if k in metadata_keys}
            if isinstance(proof.get("nodes"), list):
                proof["nodes"] = [{k:v for k,v in node.items() if k in {"id", "parent", "role", "subrole", "children_read_status"}}
                                  for node in proof["nodes"] if isinstance(node, dict)]
        # Select before sanitize's 64-item JSON cap, preserving text ancestry.
        if isinstance(proof.get("nodes"), list):
            metadata_bytes = len(json.dumps(sanitize({k:v for k,v in proof.items() if k != "nodes"}), ensure_ascii=False).encode())
            proof["nodes"] = compact_nodes(proof["nodes"], max_bytes=max(0, 6400-metadata_bytes))
        proof = sanitize(proof)
        # Protocol identity records only refer to admitted windows. Do not trust
        # arbitrary identifier text, paths, or provider-specific identifier APIs.
        refs, window_ids = [], {n["id"] for n in proof.get("nodes", []) if n.get("role") == "AXWindow"}
        for ref in proof.get("window_references", [])[:8] if isinstance(proof.get("window_references"), list) else []:
            if (isinstance(ref, dict) and type(ref.get("node_id")) is int and ref["node_id"] in window_ids and isinstance(ref.get("reference"), str)
                    and re.fullmatch(r"[0-9a-f]{64}", ref["reference"]) and ref.get("identity_quality") == "EPHEMERAL_AX_REFERENCE"
                    and type(ref.get("launch_time")) in (int, float) and math.isfinite(ref["launch_time"]) and ref["launch_time"] > 0):
                refs.append({k:ref[k] for k in ("node_id", "reference", "identity_quality", "launch_time")})
        if raw.get("kind") == "ax.snapshot":
            proof["window_references"] = refs
        if isinstance(proof.get("nodes"), list):
            proof["nodes"] = proof["nodes"][:64]
            while len(json.dumps(proof, ensure_ascii=False).encode()) > 7600 and proof["nodes"]:
                proof["nodes"].pop()
                proof["truncated"] = True
            proof["node_count"] = len(proof["nodes"])
            if len(proof["nodes"]) < original_count:
                proof["truncated"] = True
                proof["complete"] = False
                proof["structural_complete"] = False
                if proof.get("read_status") in {"READ_SUCCESS_EMPTY", "READ_SUCCESS_NONEMPTY"}:
                    proof["read_status"] = "READ_PARTIAL"
        if raw.get("kind") == "ax.snapshot":
            profile = app_profile(bundle)
            proof["application_profile"] = profile.id
            proof["profile_version"] = 1
            proof["application_context"] = summarize_observation(bundle, proof.get("nodes", []), proof.get("window_title"), proof.get("read_status", "UNKNOWN"))
            while len(json.dumps(proof, ensure_ascii=False).encode()) > 8192 and proof.get("nodes"):
                proof["nodes"].pop()
                proof.update(node_count=len(proof["nodes"]), truncated=True, complete=False, structural_complete=False, read_status="READ_PARTIAL")
                proof["application_context"] = summarize_observation(bundle, proof["nodes"], proof.get("window_title"), proof["read_status"])
        if bundle:
            obj["content_authorized"] = content_scope_allowed(bundle, options)
            obj["acquisition_scope"] = self.consent_id()
            if target is not None and raw.get("kind") == "ax.snapshot":
                obj["capture_scope"] = "controlled_owned_application"
        return ObservationEvent.create(raw["source"], raw.get("kind", "state_changed"), obj, proof,
                                       timestamp=raw.get("timestamp"), confidence=raw.get("confidence", 1.0),
                                       sensitivity="private").to_dict()

    def status(self):
        return {"status": "paused" if self.paused() else "active", "scope": self.scope_description(),
                "native_consent": "granted" if self.native_allowed() else "MANUAL_REQUIRED" if self.config.native_observation_enabled else "disabled",
                "file_authorization": "explicit_configured_directories" if self.config.watch_dirs else "unconfigured",
                "retention_days": self.config.observation_ttl_days, "raw_retention_days": self.config.observation_raw_ttl_days,
                "cloud_transmission": "requires_per_task_approval", "os_read_only_isolation": "NOT_IMPLEMENTED"}
