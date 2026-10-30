"""Opt-in, bounded native observations; this is not an OS read-only sandbox.

Only a locally built, source-and-binary-hash checked helper is launched. The
protocol has no app actions, shell commands, document reads or arbitrary paths.
"""
from datetime import datetime
from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading

from .app_profiles import app_profile, window_qualified, summarize_observation

SOURCE = Path(__file__).with_name("NativeObserver.swift")
SHARED_CORE = SOURCE.with_name("shared_ax")
SHARED_FILES = ("AXReadCore.swift", "AXSystemProvider.swift")
SHARED_MANIFEST = SHARED_CORE / "manifest.json"
READ_STATES = {"READ_SUCCESS_EMPTY", "READ_SUCCESS_NONEMPTY", "READ_FAILED", "READ_PARTIAL", "UNKNOWN"}
MAX_LINE_BYTES = 128 * 1024
APP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,199}\Z")
SECRET = re.compile(
    r"password|passwd|passphrase|cookie|keychain|credential|"
    r"(?:access|refresh|login|auth|bearer)[ _-]*token|api[ _-]*key|"
    r"authorization\s*:|bearer\s+\S+|sk-[A-Za-z0-9_-]{12,}|"
    r"-----BEGIN[^\n]*PRIVATE KEY|密码|口令|密钥|令牌", re.I)
INPUT_ROLES = {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField", "AXSecureTextField"}
BLOCKED_APPS = {"com.apple.keychainaccess", "com.agilebits.onepassword-osx",
                "com.1password.1password", "com.bitwarden.desktop", "io.localpilot.companion.ui"}
APP_KINDS = {"app.launched", "app.terminated", "app.activated", "app.deactivated",
             "app.hidden", "app.unhidden", "ax.snapshot"}
SYSTEM_KINDS = {"system.will_sleep", "system.did_wake", "system.screens_sleep",
                "system.screens_wake", "session.became_active", "session.resigned_active",
                "workspace.space_changed", "observation.status"}


def _digest(path):
    value = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _safe_path(path):
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlink helper paths are refused")
    if path.stat().st_uid != os.getuid():
        raise ValueError("Helper must belong to the current user")
    if path.stat().st_mode & 0o022:
        raise ValueError("Helper and manifest must not be group/world writable")
    return path


def helper_environment():
    """Do not copy API tokens, proxy settings or the caller's arbitrary env."""
    return {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8",
            "LC_ALL": "en_US.UTF-8", "TMPDIR": "/tmp"}


class HelperRebuildRequired(ValueError):
    """The fixed packaged source or its compatible compiled helper is absent."""


def shared_core_manifest():
    """Verify the pinned release; no sibling checkout or runtime download needed."""
    try:
        if SHARED_MANIFEST.is_symlink() or SHARED_MANIFEST.stat().st_size > 16384:
            raise HelperRebuildRequired("Invalid packaged AX read core manifest")
        value = json.loads(SHARED_MANIFEST.read_text())
        if not isinstance(value, dict):
            raise HelperRebuildRequired("Invalid packaged AX read core manifest object")
        sources = value.get("sources", {})
        if (not isinstance(value.get("version"), str) or not value["version"]
                or not isinstance(sources, dict) or set(sources) != set(SHARED_FILES)):
            raise HelperRebuildRequired("Packaged AX read core contract mismatch")
        for name in SHARED_FILES:
            path = SHARED_CORE / name
            if path.is_symlink() or not path.is_file() or sources[name] != _digest(path):
                raise HelperRebuildRequired("Packaged AX read core source mismatch")
        return {"version": value["version"], "sources": sources,
                "manifest_sha256": _digest(SHARED_MANIFEST)}
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise HelperRebuildRequired("Packaged AX read core unavailable; rebuild or reinstall") from exc


def build_native_helper(output_dir):
    """Explicit development build; source is fixed, no observer-triggered build.

    Hash validation protects against accidental config substitution. A process
    with this user's file-write rights can replace the source/binary/manifest;
    this is not code-signature enforcement or a security boundary against it.
    """
    if sys.platform != "darwin":
        raise RuntimeError("Native helper requires macOS")
    core = shared_core_manifest()
    root = Path(os.path.abspath(output_dir))
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("Symlink build paths are refused")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _safe_path(root)
    binary, manifest = root / "NativeObserver", root / "NativeObserver.manifest.json"
    if binary.is_symlink() or manifest.is_symlink():
        raise ValueError("Symlink build outputs are refused")
    # Swift's multi-file executable requires a main.swift entry point. The
    # temporary copy is byte identical to the fixed, manifest-bound source.
    with tempfile.TemporaryDirectory(prefix="observer-build-", dir=root) as temporary:
        main = Path(temporary) / "main.swift"
        main.write_bytes(SOURCE.read_bytes())
        subprocess.run(["/usr/bin/xcrun", "swiftc", *(str(SHARED_CORE / n) for n in SHARED_FILES),
                        str(main), "-o", str(binary)], check=True, timeout=120,
                       env=helper_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    binary.chmod(0o700)
    value = {"protocol": 2, "profile": "observer", "shared_core": core,
             "source_sha256": _digest(SOURCE),
             "binary_sha256": _digest(binary)}
    fd = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)
    manifest.chmod(0o600)
    return str(binary)


def trusted_helper(path):
    binary = _safe_path(path)
    if binary.name != "NativeObserver" or not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError("Use the fixed Companion native helper build")
    # A writable parent could replace the checked binary between check and exec.
    _safe_path(binary.parent)
    manifest = _safe_path(binary.with_name("NativeObserver.manifest.json"))
    if not manifest.is_file() or manifest.stat().st_size > 16384:
        raise ValueError("Invalid helper manifest")
    value = json.loads(manifest.read_text())
    if not isinstance(value, dict):
        raise ValueError("Invalid helper manifest object")
    if value.get("protocol") != 2:
        raise HelperRebuildRequired("Observer helper protocol changed; rebuild the fixed helper")
    core = shared_core_manifest()
    if (value.get("profile") != "observer" or value.get("shared_core") != core
            or value.get("source_sha256") != _digest(SOURCE)
            or value.get("binary_sha256") != _digest(binary)):
        raise ValueError("Helper source/binary mismatch; rebuild the fixed helper")
    return str(binary)


def _ids(values):
    if not isinstance(values, (tuple, list)) or len(values) > 100:
        raise ValueError("Native application list must be bounded")
    if any(not isinstance(v, str) or not APP_ID.fullmatch(v) for v in values):
        raise ValueError("Native application lists require bundle identifiers")
    return list(dict.fromkeys(values))


def controlled_target_descriptor(value):
    """Validation scope identity. Configuration never launches/activates apps."""
    keys = {"pid", "bundle_id", "bundle_url", "launch_time", "owner_pid"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("Controlled target requires a complete fixed descriptor")
    if any(type(value[k]) is not int or value[k] <= 0 for k in ("pid", "owner_pid")):
        raise ValueError("Controlled target requires positive process identities")
    bundle = value["bundle_id"]
    if not isinstance(bundle, str) or not APP_ID.fullmatch(bundle) or not bundle.startswith("org.localpilot.companion.validation."):
        raise ValueError("Controlled target is restricted to owned validation apps")
    launch = value["launch_time"]
    if type(launch) not in (int, float) or not math.isfinite(launch) or launch <= 0:
        raise ValueError("Controlled target requires a finite launch time")
    location = value["bundle_url"]
    if not isinstance(location, str) or len(location) > 2000 or any(ord(c) < 32 for c in location) or not location.startswith("/") or not location.endswith(".app"):
        raise ValueError("Controlled target requires an absolute app bundle path")
    if os.path.abspath(location) != location:
        raise ValueError("Controlled app path must be canonical")
    return {k: value[k] for k in sorted(keys)}


def controlled_target_digest(value):
    value = controlled_target_descriptor(value)
    identity = "\n".join((str(value["pid"]), value["bundle_id"], value["bundle_url"],
                          format(value["launch_time"], ".6f"), str(value["owner_pid"])))
    return hashlib.sha256(identity.encode()).hexdigest()


def verify_controlled_target(value):
    """Bind to this harness's live, owned, source-qualified validation process.

    A matching bundle name alone is insufficient. This fixed-source check is
    validation provenance, not a sandbox against this user's file-write rights.
    """
    import psutil
    value = controlled_target_descriptor(value)
    bundle = _safe_path(value["bundle_url"])
    manifest = _safe_path(bundle / "Contents" / "v042-controlled-app.json")
    binary = _safe_path(bundle / "Contents" / "MacOS" / "CompanionAXValidation")
    source = SOURCE.parents[2] / "validation" / "v042_ax_app.swift"
    if manifest.stat().st_size > 16384 or not source.is_file():
        raise ValueError("Owned validation app provenance unavailable")
    provenance = json.loads(manifest.read_text())
    if (not isinstance(provenance, dict) or provenance.get("source_sha256") != _digest(source)
            or provenance.get("binary_sha256") != _digest(binary)):
        raise ValueError("Owned validation app source/binary provenance mismatch")
    try:
        process = psutil.Process(value["pid"])
        if (process.uids().real != os.getuid() or process.ppid() != value["owner_pid"]
                or process.exe() != str(binary) or abs(process.create_time() - value["launch_time"]) > 0.1
                or not psutil.pid_exists(value["owner_pid"])):
            raise ValueError("Owned validation app lifetime or parent mismatch")
    except psutil.Error as exc:
        raise ValueError("Owned validation process unavailable") from exc
    return value


def native_options(config):
    allowed = _ids(getattr(config, "native_app_allowlist", ()))
    excluded = _ids(getattr(config, "native_app_exclusions", ()))
    content = _ids(getattr(config, "native_content_app_allowlist", ()))
    if not set(content).issubset(allowed):
        raise ValueError("Content apps must also be on the native application allowlist")
    nodes, depth = getattr(config, "native_ax_max_nodes", 80), getattr(config, "native_ax_max_depth", 5)
    if type(nodes) is not int or not 1 <= nodes <= 512 or type(depth) is not int or not 1 <= depth <= 16:
        raise ValueError("Invalid bounded AX traversal")
    ax = getattr(config, "native_ax_enabled", False)
    if type(ax) is not bool:
        raise ValueError("native_ax_enabled must be boolean")
    windows = getattr(config, "native_window_exclusions", ())
    if (not isinstance(windows, (tuple, list)) or len(windows) > 100
            or any(not isinstance(v, str) or not v or len(v) > 300
                   or len(v.encode("utf-8")) > 1200 or any(ord(c) < 32 for c in v) for v in windows)):
        raise ValueError("Native window exclusions require bounded exact titles")
    result = {"low_power": getattr(config, "low_power_policy", "always") != "off", "allowlist": allowed, "exclusions": excluded, "content_allowlist": content,
            "window_exclusions": list(dict.fromkeys(windows)),
            "ax_enabled": ax, "max_nodes": nodes, "max_depth": depth,
            "parent_pid": os.getpid()}
    all_apps = getattr(config, "native_all_apps_enabled", False)
    all_content = getattr(config, "native_all_apps_content_enabled", False)
    if type(all_apps) is not bool or type(all_content) is not bool or all_content and not all_apps:
        raise ValueError("Invalid all-app read scope")
    if all_apps:
        result["all_apps"] = True
    if all_content:
        result["all_content"] = True
    titles = getattr(config, "native_content_window_allowlist", ())
    if (not isinstance(titles, (tuple, list)) or len(titles) > 100
            or any(not isinstance(v, str) or not v or not window_qualified(v) or len(v.encode("utf-8")) > 1200 for v in titles)):
        raise ValueError("Native content window allowlist requires safe bounded exact titles")
    result["content_window_allowlist"] = list(dict.fromkeys(titles))
    target = getattr(config, "native_controlled_target", None)
    if target is not None:
        if all_apps or all_content:
            raise ValueError("Owned validation scope cannot become all-app scope")
        target = controlled_target_descriptor(target)
        if set(allowed) != {target["bundle_id"]}:
            raise ValueError("Controlled scope requires exactly its owned application")
        result["controlled_target"] = target
        result["target_descriptor_sha256"] = controlled_target_digest(target)
    return result


def app_scope_allowed(bundle, options):
    return (isinstance(bundle, str) and re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+", bundle) is not None
            and (options.get("all_apps") is True or bundle in options.get("allowlist", []))
            and bundle not in options.get("exclusions", []) and bundle.lower() not in BLOCKED_APPS and not SECRET.search(bundle))


def content_scope_allowed(bundle, options):
    return app_scope_allowed(bundle, options) and options.get("ax_enabled") is True and (options.get("all_content") is True or bundle in options.get("content_allowlist", []))


def _safe_text(value, limit=300):
    if not isinstance(value, str) or SECRET.search(value):
        return None
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        return None
    return value[:limit]


def _read_errors(values):
    """Errors carry structural coordinates and categories, never copied AX data."""
    result = []
    for error in values[:32]:
        if not isinstance(error, dict):
            continue
        clean = {}
        for key in ("attribute", "status", "category", "scope", "root_attribute", "reason", "retry_class"):
            value = error.get(key)
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", value):
                clean[key] = value
        if type(error.get("error")) is int and -100000 <= error["error"] <= 100000:
            clean["error"] = error["error"]
        for key in ("retryable", "retry_allowed", "structural"):
            if type(error.get(key)) is bool:
                clean[key] = error[key]
        path = error.get("path")
        if isinstance(path, list) and len(path) <= 22 and all(type(p) is int and 0 <= p < 10000 for p in path):
            clean["path"] = path
        if clean:
            result.append(clean)
        if len(result) >= 16:
            break
    while len(json.dumps(result).encode()) > 3000:
        result.pop()
    return result


def filter_native_event(event, options):
    """Defence in depth before callbacks, memory, logs or model inputs.

    The real helper never copies input values. This validator additionally
    drops unexpected protocol keys and refuses input/secure fixture subtrees.
    Arbitrary secret identification remains incomplete; content is opt-in.
    """
    if not isinstance(event, dict):
        return None
    source = event.get("source")
    if not isinstance(source, str) or source not in {"macos.workspace", "macos.ax", "macos.observer"}:
        return None
    kind = event.get("kind")
    if not isinstance(kind, str) or kind not in APP_KINDS | SYSTEM_KINDS:
        return None
    obj = event.get("object", {})
    if not isinstance(obj, dict):
        return None
    bundle = obj.get("bundle_id", "")
    if not isinstance(bundle, str):
        return None
    if kind in APP_KINDS:
        if not app_scope_allowed(bundle, options):
            return None
        target = options.get("controlled_target")
        if target and (bundle != target["bundle_id"] or obj.get("pid") != target["pid"]):
            return None
    timestamp = event.get("timestamp")
    try:
        if not isinstance(timestamp, str) or len(timestamp) > 40:
            return None
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
    except ValueError:
        return None
    result_obj = {"bundle_id": bundle} if kind in APP_KINDS else {"type": "system"}
    if kind in APP_KINDS and type(obj.get("pid")) is int and obj["pid"] > 0:
        result_obj["pid"] = obj["pid"]
    evidence = event.get("evidence", {})
    if not isinstance(evidence, dict):
        return None
    controlled = options.get("controlled_target")
    if kind == "ax.snapshot":
        inspection = options.get("inspection_target")
        if inspection:
            if (bundle != inspection["bundle_id"] or obj.get("pid") != inspection["pid"]
                    or evidence.get("capture_scope") != "authorized_application_inspection"):
                return None
            result_obj["capture_scope"] = "authorized_application_inspection"
        elif controlled:
            if (bundle != controlled["bundle_id"] or obj.get("pid") != controlled["pid"]
                    or evidence.get("capture_scope") != "controlled_owned_application"
                    or evidence.get("target_descriptor_sha256") != options["target_descriptor_sha256"]):
                return None
            result_obj["capture_scope"] = "controlled_owned_application"
        elif (evidence.get("capture_scope") in {"controlled_owned_application", "authorized_application_inspection"} or obj.get("capture_scope") in {"controlled_owned_application", "authorized_application_inspection"} or evidence.get("target_descriptor_sha256")
              or evidence.get("read_scope") == "authorized_windows_filtered_private_inputs"):
            return None
    if evidence.get("window_title") in options.get("window_exclusions", ()):
        return None
    content_enabled = content_scope_allowed(bundle, options)
    if kind == "ax.snapshot" and content_enabled:
        title = evidence.get("window_title")
        if title is not None and not window_qualified(title, options.get("content_window_allowlist", ())):
            return None
        if options.get("content_window_allowlist") and title is None:
            return None
    safe = {}
    for key in ("notification", "reason", "coverage", "ax_permission", "lock_state", "session_state", "screen_state", "sleep_state", "fixture_origin", "self_ax_role", "read_status", "shared_core_version", "window_coverage", "read_scope", "capture_scope", "target_descriptor_sha256"):
        value = _safe_text(evidence.get(key), 160)
        if value is not None:
            safe[key] = value
    for key in ("node_count", "read_errors", "unsupported_notifications", "ax_error"):
        value = evidence.get(key)
        if type(value) is int and 0 <= value <= 100000:
            safe[key] = value
    for key in ("truncated", "content_truncated", "self_process_only", "complete", "structural_complete", "attributes_complete"):
        if type(evidence.get(key)) is bool:
            safe[key] = evidence[key]
    if kind == "ax.snapshot":
        if safe.get("read_status") not in READ_STATES:
            safe["read_status"], safe["complete"] = "UNKNOWN", False
        if safe["read_status"] in {"READ_FAILED", "READ_PARTIAL", "UNKNOWN"}:
            safe["complete"] = False
        raw_errors = evidence.get("read_errors")
        if isinstance(raw_errors, list):
            safe["read_errors"] = _read_errors(raw_errors)
        for key in ("read_error_count", "pruned_count", "profile_pruned_count", "notification_count", "coalesced_notifications", "snapshot_count"):
            if type(evidence.get(key)) is int and 0 <= evidence[key] <= 100000000:
                safe[key] = evidence[key]
        if type(evidence.get("elapsed_ms")) in (int, float) and 0 <= evidence["elapsed_ms"] <= 120000:
            safe["elapsed_ms"] = evidence["elapsed_ms"]
    if content_enabled:
        title = _safe_text(evidence.get("window_title"))
        if title is not None:
            safe["window_title"] = title
    tree = evidence.get("nodes")
    profile = app_profile(bundle)
    if options["ax_enabled"] and isinstance(tree, list):
        nodes = []
        blocked = set()
        accepted_ids = set()
        text_remaining = 4000
        for index, node in enumerate(tree[:options["max_nodes"]]):
            if not isinstance(node, dict):
                continue
            role, subrole = node.get("role"), node.get("subrole", "")
            node_id, parent = node.get("id", index), node.get("parent")
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
            if (not isinstance(role, str) or not isinstance(subrole, str)
                    or role in INPUT_ROLES | profile.denied_roles or role == "AXUnknown" or subrole in profile.denied_subroles or parent in blocked
                    or SECRET.search(str(subrole))):
                blocked.add(node_id)
                continue
            if not isinstance(role, str) or not re.fullmatch(r"AX[A-Za-z]{1,60}", role):
                blocked.add(node_id)
                continue
            clean = {"id": node_id, "role": role}
            if parent is not None:
                clean["parent"] = parent
            if subrole and not re.fullmatch(r"AX[A-Za-z]{1,60}", subrole):
                blocked.add(node_id)
                continue
            if isinstance(subrole, str) and re.fullmatch(r"AX[A-Za-z]{1,60}", subrole):
                clean["subrole"] = subrole
            if isinstance(node.get("children_read_status"), str) and node["children_read_status"] in READ_STATES:
                clean["children_read_status"] = node["children_read_status"]
            if content_enabled and role == "AXStaticText":
                text = _safe_text(node.get("text"), min(500, text_remaining))
                if text is not None:
                    clean["text"] = text
                    text_remaining -= len(text)
            nodes.append(clean)
            accepted_ids.add(node_id)
        safe["nodes"] = nodes
        safe["node_count"] = len(nodes)
        if len(tree) > len(nodes):
            safe["truncated"] = True
            safe["complete"] = False
            safe["structural_complete"] = False
            if safe.get("read_status") in {"READ_SUCCESS_EMPTY", "READ_SUCCESS_NONEMPTY"}:
                safe["read_status"] = "READ_PARTIAL"
    if kind == "ax.snapshot":
        safe["application_profile"] = profile.id
        safe["profile_version"] = 1
        safe["application_context"] = summarize_observation(bundle, safe.get("nodes", []), safe.get("window_title"), safe.get("read_status", "UNKNOWN"))
        references = []
        window_ids = {n["id"] for n in safe.get("nodes", []) if n["role"] == "AXWindow"}
        for value in evidence.get("window_references", [])[:8] if isinstance(evidence.get("window_references"), list) else []:
            if (isinstance(value, dict) and type(value.get("node_id")) is int and value["node_id"] in window_ids
                    and isinstance(value.get("reference"), str) and re.fullmatch(r"[0-9a-f]{64}", value["reference"])
                    and value.get("identity_quality") == "EPHEMERAL_AX_REFERENCE"
                    and type(value.get("launch_time")) in (int, float) and math.isfinite(value["launch_time"]) and value["launch_time"] > 0):
                references.append({k:value[k] for k in ("node_id", "reference", "identity_quality", "launch_time")})
        safe["window_references"] = references
    # Compute identity from the accepted evidence, never from rejected values.
    identity = json.dumps([event["source"], kind, result_obj, safe], sort_keys=True, ensure_ascii=False)
    source = "accessibility" if event["source"] == "macos.ax" else "nsworkspace" if kind in APP_KINDS else "session"
    return {"timestamp": parsed.timestamp(), "source": source,
            "kind": kind, "object": result_obj, "evidence": safe,
            "confidence": 1.0 if kind != "ax.snapshot" else 0.8,
            "sensitivity": "private",
            "dedupe_key": hashlib.sha256(identity.encode()).hexdigest()}


def inspect_native_application(config, bundle_id, pid, *, confirmed=False, timeout=5):
    """Explicit ordinary-app compatibility read, no launch/activation or storage.

    The foreground listener does not acquire this broader scope. Returned
    inspection events are rejected by its normal transport/privacy boundary.
    Caller must present current user permission; AX/TCC is never prompted.
    """
    if confirmed is not True:
        return {"status": "MANUAL_REQUIRED", "reason": "explicit_application_read_confirmation_required"}
    if sys.platform != "darwin":
        return {"status": "NOT_RUN", "reason": "macOS_required"}
    options = native_options(config)
    if (options.get("controlled_target") or options["allowlist"] != [bundle_id]
            or bundle_id in options["exclusions"] or bundle_id.lower() in BLOCKED_APPS or not options["ax_enabled"]):
        raise ValueError("Inspection requires one explicitly authorized ordinary application")
    if type(pid) is not int or pid <= 0 or type(timeout) not in (int, float) or not 0 < timeout <= 15:
        raise ValueError("Inspection requires bounded process and timeout")
    import psutil
    process = psutil.Process(pid)
    if process.uids().real != os.getuid():
        raise ValueError("Inspection target must belong to the current user")
    options["inspection_target"] = {"bundle_id": bundle_id, "pid": pid, "launch_time": process.create_time()}
    options["explicit_application_read"] = True
    binary = trusted_helper(config.native_helper_path)
    result = subprocess.run([binary, "--inspect-application"], input=json.dumps(options).encode(),
                            capture_output=True, env=helper_environment(), timeout=timeout, check=False)
    if result.returncode:
        return {"status": "UNKNOWN", "reason": "target_unavailable_or_changed", "events": []}
    if len(result.stdout) > MAX_LINE_BYTES * 2:
        return {"status": "UNKNOWN", "reason": "inspection_output_exceeded_budget", "events": []}
    events, audit = [], []
    for line in result.stdout.splitlines():
        if len(line) > MAX_LINE_BYTES:
            continue
        raw = json.loads(line)
        trace = raw.get("evidence", {}).get("getter_trace", [])
        if isinstance(trace, list):
            input_ids = {v.get("node") for v in trace if isinstance(v, dict) and v.get("attribute") == "AXRole" and v.get("role") in INPUT_ROLES}
            audit.append({"getter_count": len(trace), "input_nodes": len(input_ids),
                          "input_nonrole_getters": sum(1 for v in trace if isinstance(v, dict) and v.get("node") in input_ids and v.get("attribute") != "AXRole")})
        event = filter_native_event(raw, options)
        if event is not None:
            events.append(event)
    if any(e["evidence"].get("ax_permission") == "MANUAL_REQUIRED" for e in events):
        return {"status": "MANUAL_REQUIRED", "reason": "Accessibility_not_granted", "events": events}
    snapshots = [e for e in events if e["kind"] == "ax.snapshot"]
    # Even a successful supported tree does not establish whole-app coverage.
    return {"status": "PARTIAL" if snapshots else "UNKNOWN", "events": events, "read_audit": audit,
            "reason": "authorized_read_only_application_inspection" if snapshots else "no_qualified_snapshot"}


class NativeObserver:
    def __init__(self, config, callback):
        self.config, self.callback = config, callback
        self.options = native_options(config)
        self.process = None
        self.thread = None
        self._state = "disabled"
        self._reason = "native observation is opt-in"
        self._paused = False
        self._accepted = self._rejected = 0
        self._permission = "UNKNOWN" if self.options["ax_enabled"] else "disabled"
        self._metrics = {}
        self._metrics_lock = threading.Lock()
        self._recent_read_ms = deque(maxlen=256)

    def status(self):
        with self._metrics_lock:
            metrics = {k: dict(v) if isinstance(v, dict) else v for k, v in self._metrics.items()}
            metrics["recent_read_ms"] = [dict(v) for v in self._recent_read_ms]
        return {"state": self._state, "reason": self._reason, "ax_permission": self._permission,
                "lock_state": "UNKNOWN", "isolation": "PARTIAL_APPLICATION_ONLY",
                "os_read_only_sandbox": False, "accepted_events": self._accepted,
                "rejected_events": self._rejected, "metadata_only": not (self.options["ax_enabled"] and (self.options["content_allowlist"] or self.options.get("all_content"))),
                "allowlist": list(self.options["allowlist"]), "profile": "observer",
                "window_exclusion_count": len(self.options["window_exclusions"]),
                "helper_protocol": 2, "metrics": metrics}

    def start(self):
        if not getattr(self.config, "native_observation_enabled", False):
            return self.status()
        if self._paused:
            self._state = "paused"
            return self.status()
        if self.process is not None and self.process.poll() is None:
            return self.status()
        if sys.platform != "darwin":
            self._state, self._reason = "unavailable", "macOS required"
            return self.status()
        path = getattr(self.config, "native_helper_path", "")
        if not path:
            self._state, self._reason = "MANUAL_REQUIRED", "build and configure the fixed native helper"
            return self.status()
        try:
            executable = trusted_helper(path)
            if self.options.get("controlled_target"):
                verify_controlled_target(self.options["controlled_target"])
            if self.process is not None:
                self.stop()
            mode = "--controlled-listen" if self.options.get("controlled_target") else "--listen"
            self.process = subprocess.Popen([executable, mode], stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                            env=helper_environment(), close_fds=True)
            self.process.stdin.write((json.dumps(self.options) + "\n").encode())
            self.process.stdin.close()
            self._state, self._reason = "running", "event-driven helper with bounded 5-minute foreground refresh; no TCC prompt"
            self.thread = threading.Thread(target=self._read, args=(self.process,), daemon=True)
            self.thread.start()
        except HelperRebuildRequired:
            self._state, self._reason = "MANUAL_REQUIRED", "AX core/helper unavailable or incompatible; rebuild the fixed helper"
            self.stop()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._state, self._reason = "error", type(exc).__name__ + ": helper unavailable or untrusted"
            self.stop()
        return self.status()

    def _read(self, process):
        try:
            while True:
                line = process.stdout.readline(MAX_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_LINE_BYTES:
                    self._state, self._reason = "error", "native protocol line exceeded budget"
                    process.terminate()
                    break
                try:
                    event = filter_native_event(json.loads(line), self.options)
                except (ValueError, UnicodeDecodeError, RecursionError):
                    event = None
                if event is None:
                    self._rejected += 1
                    continue
                if self._paused:
                    continue
                with self._metrics_lock:
                    if event["kind"] == "ax.snapshot":
                        characters = sum(len(n.get("text", "")) for n in event["evidence"].get("nodes", [])
                                         if isinstance(n, dict) and n.get("role") == "AXStaticText")
                        self._metrics["last_static_text_chars"] = characters
                        self._metrics["static_text_snapshots"] = self._metrics.get("static_text_snapshots", 0) + int(characters > 0)
                        elapsed = event["evidence"].get("elapsed_ms")
                        state = event["evidence"].get("read_status", "UNKNOWN")
                        self._metrics["read_count"] = self._metrics.get("read_count", 0) + 1
                        if type(elapsed) in (int, float):
                            self._metrics["total_read_ms"] = self._metrics.get("total_read_ms", 0.0) + elapsed
                            self._metrics["max_read_ms"] = max(self._metrics.get("max_read_ms", 0.0), elapsed)
                            self._recent_read_ms.append({"read_index": self._metrics["read_count"],
                                "snapshot_count": event["evidence"].get("snapshot_count", 0),
                                "elapsed_ms": elapsed, "read_status": state})
                        counts = self._metrics.setdefault("read_state_counts", {})
                        counts[state] = counts.get(state, 0) + 1
                    for key in ("elapsed_ms", "notification_count", "coalesced_notifications", "snapshot_count"):
                        if key in event["evidence"]:
                            self._metrics[key] = event["evidence"][key]
                            del event["evidence"][key]
                self._accepted += 1
                if event["kind"] == "observation.status":
                    self._permission = event["evidence"].get("ax_permission", self._permission)
                try:
                    self.callback(event)
                except Exception:
                    self._state, self._reason = "error", "native callback failed"
                    process.terminate()
                    break
        finally:
            process.stdout.close()
            # Reap only the owned helper; its death never dispatches actions.
            if process.poll() is not None:
                process.wait()
            if self.process is process and self._state == "running":
                self._state, self._reason = "stopped", "native helper exited"

    def stop(self):
        process = self.process
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            if self.thread is not None and self.thread is not threading.current_thread():
                self.thread.join(timeout=2)
            if process.stdout and not process.stdout.closed:
                process.stdout.close()
            self.process = None
        if self._state not in {"error", "MANUAL_REQUIRED", "unavailable", "disabled"}:
            self._state, self._reason = "stopped", "native helper stopped"

    def pause(self):
        self._paused = True
        self.stop()
        self._state, self._reason = "paused", "observation paused"

    def resume(self):
        self._paused = False
        return self.start()
