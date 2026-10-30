from dataclasses import dataclass, fields
from pathlib import Path
import json
import os
import re
import secrets


def path(value):
    return Path(os.path.abspath(os.path.expanduser(value)))


SENSITIVE = {".ssh", ".gnupg", ".aws", ".azure", ".config", ".git", ".venv", "node_modules", "Keychains", "Cookies", "Login Data"}


@dataclass
class Config:
    data_dir: str = "~/Library/Application Support/LocalPilotCompanion"
    watch_dirs: tuple = ()
    exclude_dirs: tuple = ()
    mode: str = "eco"
    eco_unload_seconds: float = 120
    backend: str = "mlx"
    model_path: str = ""
    model_context_tokens: int = 8192
    max_output_tokens: int = 160
    model_routing_enabled: bool = True
    tier2_model_path: str = ""
    tier2_context_tokens: int = 8192
    tier2_max_output_tokens: int = 320
    tier2_unload_seconds: float = 60
    proactive_level: str = "normal"
    proactive_delivery: str = "silent"
    retrieval_records: int = 5
    retrieval_chars: int = 4000
    retrieval_backend: str = "bm25"
    relevance_threshold: float = 0.9
    max_file_bytes: int = 16 * 1024 * 1024
    max_document_chars: int = 40000
    max_scan_files: int = 5000
    summarize_documents: bool = False
    notifications: bool = False
    dnd: bool = False
    quiet_start_hour: int = 22
    quiet_end_hour: int = 8
    cooldown_seconds: float = 1800
    type_cooldown_seconds: float = 14400
    max_notices_per_day: int = 4
    project_activity_seconds: float = 600
    active_sustained_minutes: float = 45
    break_reminder_opt_in: bool = False
    project_aliases: dict = None
    retention_recent_versions: int = 3
    retention_full_ttl_days: float = 30
    retention_metadata_limit: int = 100
    retention_interval_seconds: float = 3600
    history_record_limit: int = 10000
    http_schema_supported: bool = False
    structured_repairs: int = 1
    agent_endpoint: str = ""
    agent_model: str = ""
    agent_allow_remote: bool = False
    agent_host_local_only: bool = False
    agent_api_key_env: str = ""
    http_model_endpoint: str = ""
    http_model_name: str = ""
    http_model_api_key_env: str = ""
    http_model_host_local_only: bool = False
    port: int = 0
    native_observation_enabled: bool = False
    native_all_apps_enabled: bool = False
    native_all_apps_content_enabled: bool = False
    native_helper_path: str = ""
    native_app_allowlist: tuple = ()
    native_app_exclusions: tuple = ()
    native_window_exclusions: tuple = ()
    native_ax_enabled: bool = False
    native_content_app_allowlist: tuple = ()
    native_content_window_allowlist: tuple = ()
    native_ax_max_nodes: int = 80
    native_ax_max_depth: int = 5
    # Explicit validation-only owned process; absent preserves foreground scope.
    native_controlled_target: dict = None
    observation_ttl_days: float = 30
    observation_raw_ttl_days: float = 7
    observation_record_limit: int = 10000
    low_power_policy: str = "always"
    desktop_control_enabled: bool = False
    low_power_until: str = "09:00"
    lightweight_on_demand: bool = True
    lightweight_max_weight_bytes: int = 1500000000
    localpilot_client_subject: str = "companion"
    localpilot_analysis_route: str = "companion-reasoning"
    localpilot_auto_local: bool = True
    localpilot_expected_local_model: str = "Qwen3.6-35B-A3B-4bit"
    localpilot_auto_wait_seconds: float = 8
    allow_local_on_battery: bool = False
    allow_automatic_cloud: bool = False
    localpilot_cloud_analysis_route: str = "companion-cloud-reasoning"
    localpilot_resource_key_env: str = "LOCALPILOT_COMPANION_RESOURCE_TOKEN"
    local_model_min_available_bytes: int = 28*1024**3
    resource_sample_seconds: float = 30
    resource_alert_sustain_seconds: float = 60
    resource_alert_cooldown_seconds: float = 900
    resource_memory_alert_bytes: int = 8*1024**3
    resource_discharge_alert_watts: float = 25
    resource_cpu_alert_percent: float = 85
    localpilot_endpoint: str = "http://127.0.0.1:8765"
    localpilot_route: str = "localpilot"
    localpilot_api_key_env: str = "LOCALPILOT_COMPANION_TOKEN"
    localpilot_allow_remote: bool = False
    localpilot_host_local_only: bool = True
    localpilot_allow_cloud: bool = False
    localpilot_timeout_seconds: float = 15
    localpilot_task_timeout_seconds: float = 120
    localpilot_max_context_chars: int = 16000

    @classmethod
    def load(cls, filename):
        raw = json.loads(Path(filename).read_text()) if filename else {}
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown config keys: {sorted(unknown)}")
        c = cls(**raw)
        from companion.runtime.power import LowPowerPolicy
        LowPowerPolicy(c)
        if type(c.allow_local_on_battery) is not bool or type(c.allow_automatic_cloud) is not bool:
            raise ValueError("Inference automation options must be boolean")
        for name in ("resource_sample_seconds","resource_alert_sustain_seconds","resource_alert_cooldown_seconds","resource_discharge_alert_watts","resource_cpu_alert_percent"):
            value=getattr(c,name)
            if type(value) not in (int,float) or not 0<value<=86400:
                raise ValueError("Invalid resource telemetry threshold")
        if (type(c.resource_memory_alert_bytes) is not int or c.resource_memory_alert_bytes<=0 or
                type(c.local_model_min_available_bytes) is not int or c.resource_cpu_alert_percent>100 or
                c.resource_sample_seconds<10 or not 4*1024**3<=c.local_model_min_available_bytes<=64*1024**3):
            raise ValueError("Invalid memory wall or sampling interval")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",c.localpilot_resource_key_env):
            raise ValueError("Invalid resource credential reference")
        if type(c.desktop_control_enabled) is not bool or type(c.localpilot_auto_local) is not bool or not isinstance(c.localpilot_expected_local_model,str):
            raise ValueError("Invalid automatic local routing configuration")
        if type(c.localpilot_auto_wait_seconds) not in (int,float) or not 1<=c.localpilot_auto_wait_seconds<=15:
            raise ValueError("Local inference observation budget must be 1..15 seconds")
        if type(c.lightweight_on_demand) is not bool or type(c.lightweight_max_weight_bytes) is not int or not 1 <= c.lightweight_max_weight_bytes <= 1500000000:
            raise ValueError("Invalid lightweight lifecycle policy")
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", c.localpilot_client_subject) or c.localpilot_client_subject.lower() == "operator" or "OPERATOR" in c.localpilot_api_key_env.upper():
            raise ValueError("Companion requires its ordinary scoped identity")
        if type(c.native_all_apps_enabled) is not bool or type(c.native_all_apps_content_enabled) is not bool:
            raise ValueError("All-app observation switches must be boolean")
        if c.native_all_apps_content_enabled and not c.native_all_apps_enabled:
            raise ValueError("All-app content requires all-app metadata scope")
        if c.native_controlled_target is not None and (c.native_all_apps_enabled or c.native_all_apps_content_enabled):
            raise ValueError("Controlled validation target cannot widen to all apps")
        if type(c.model_routing_enabled) is not bool:
            raise ValueError("model_routing_enabled must be boolean")
        if c.proactive_level not in {"off", "low", "normal"} or c.proactive_delivery not in {"silent", "enabled"}:
            raise ValueError("Invalid proactive settings")
        if not isinstance(c.tier2_model_path, str):
            raise ValueError("tier2_model_path must be a local path")
        if (type(c.tier2_context_tokens) is not int or not 512 <= c.tier2_context_tokens <= 32768
                or type(c.tier2_max_output_tokens) is not int or not 1 <= c.tier2_max_output_tokens <= 2048
                or c.tier2_context_tokens <= c.tier2_max_output_tokens + 256):
            raise ValueError("Invalid tier2 context/output budget")
        import math
        if type(c.tier2_unload_seconds) not in (int, float) or not math.isfinite(c.tier2_unload_seconds) or not 1 <= c.tier2_unload_seconds <= 3600:
            raise ValueError("Invalid tier2 unload interval")
        if c.retrieval_backend not in {"lexical", "bm25"} or type(c.relevance_threshold) not in (int,float) or not 0 <= c.relevance_threshold <= 1:
            raise ValueError("Invalid retrieval backend/relevance threshold")
        if c.mode not in {"eco", "responsive"} or c.backend not in {"mlx", "local-http", "omlx", "disabled"}:
            raise ValueError("Invalid mode/backend")
        for key in ("summarize_documents", "notifications", "dnd", "agent_allow_remote", "agent_host_local_only", "http_model_host_local_only", "http_schema_supported", "break_reminder_opt_in", "native_observation_enabled", "native_ax_enabled", "localpilot_allow_remote", "localpilot_host_local_only", "localpilot_allow_cloud"):
            if type(getattr(c,key)) is not bool:
                raise ValueError(f"{key} must be boolean")
        for key in ("max_file_bytes", "max_document_chars", "max_scan_files", "retrieval_records", "retrieval_chars", "model_context_tokens", "max_output_tokens", "max_notices_per_day"):
            if not isinstance(getattr(c, key), int) or getattr(c, key) <= 0:
                raise ValueError(f"{key} must be a positive integer")
        for key in ("cooldown_seconds", "type_cooldown_seconds", "eco_unload_seconds", "project_activity_seconds"):
            if getattr(c, key) <= 0:
                raise ValueError(f"{key} must be positive")
        for key in ("retention_recent_versions", "retention_metadata_limit", "history_record_limit"):
            if type(getattr(c, key)) is not int or getattr(c, key) < 1:
                raise ValueError(f"{key} must be a positive integer")
        if c.retention_metadata_limit < c.retention_recent_versions:
            raise ValueError("Metadata limit must retain recent versions")
        import math
        for key in ("retention_full_ttl_days", "retention_interval_seconds", "active_sustained_minutes"):
            value = getattr(c, key)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} must be finite and positive")
        if type(c.structured_repairs) is not int or c.structured_repairs not in (0, 1):
            raise ValueError("structured_repairs must be 0 or 1")
        c.project_aliases = c.project_aliases or {}
        if not isinstance(c.project_aliases, dict) or len(c.project_aliases) > 100 or any(
                not isinstance(k, str) or not isinstance(v, str) or not 2 <= len(k) <= 80 or not 2 <= len(v) <= 80
                for k, v in c.project_aliases.items()):
            raise ValueError("Invalid explicit project alias mapping")
        if not 0 <= c.quiet_start_hour < 24 or not 0 <= c.quiet_end_hour < 24 or not 0 <= c.port <= 65535:
            raise ValueError("Invalid hour/port")
        if c.model_context_tokens <= c.max_output_tokens + 256:
            raise ValueError("Context budget is too small")
        for key in ("agent_api_key_env", "http_model_api_key_env"):
            if getattr(c,key) and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", getattr(c,key)):
                raise ValueError("API key environment variable name is invalid")
        for key in ("native_app_allowlist", "native_app_exclusions", "native_content_app_allowlist"):
            values = getattr(c, key)
            if not isinstance(values, (tuple, list)) or len(values) > 100 or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+", v) for v in values):
                raise ValueError(f"{key} must contain bounded bundle identifiers")
            setattr(c, key, tuple(values))
        if not set(c.native_content_app_allowlist) <= set(c.native_app_allowlist):
            raise ValueError("Native content apps must be explicitly allowed")
        if c.native_controlled_target is not None:
            from companion.observers.native import controlled_target_descriptor
            c.native_controlled_target = controlled_target_descriptor(c.native_controlled_target)
            if set(c.native_app_allowlist) != {c.native_controlled_target["bundle_id"]}:
                raise ValueError("Controlled observation permits only its owned validation app")
        values = c.native_window_exclusions
        if (not isinstance(values, (tuple, list)) or len(values) > 100
                or any(not isinstance(v, str) or not v or len(v) > 300
                       or len(v.encode("utf-8")) > 1200
                       or any(ord(ch) < 32 for ch in v) for v in values)):
            raise ValueError("Native window exclusions must be bounded exact titles")
        c.native_window_exclusions = tuple(dict.fromkeys(values))
        values = c.native_content_window_allowlist
        if (not isinstance(values, (tuple, list)) or len(values) > 100
                or any(not isinstance(v, str) or not v or len(v) > 300
                       or len(v.encode("utf-8")) > 1200 or any(ord(ch) < 32 for ch in v) for v in values)):
            raise ValueError("Native content windows must be bounded exact titles")
        c.native_content_window_allowlist = tuple(dict.fromkeys(values))
        for key, maximum in (("native_ax_max_nodes", 512), ("native_ax_max_depth", 16), ("observation_record_limit", 100000), ("localpilot_max_context_chars", 32000)):
            if type(getattr(c, key)) is not int or not 1 <= getattr(c, key) <= maximum:
                raise ValueError(f"Invalid {key}")
        for key in ("observation_ttl_days", "observation_raw_ttl_days", "localpilot_timeout_seconds", "localpilot_task_timeout_seconds"):
            value = getattr(c, key)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} must be finite and positive")
        if c.observation_raw_ttl_days > c.observation_ttl_days:
            raise ValueError("Raw observation retention exceeds event retention")
        if c.localpilot_timeout_seconds > 120 or c.localpilot_task_timeout_seconds > 3600:
            raise ValueError("LocalPilot timeout exceeds bounded limit")
        if c.localpilot_api_key_env and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", c.localpilot_api_key_env):
            raise ValueError("Invalid LocalPilot API key environment name")
        if not c.localpilot_api_key_env or c.localpilot_max_context_chars < 512:
            raise ValueError("LocalPilot requires an API key environment name and at least 512 context characters")
        if c.localpilot_endpoint:
            from companion.escalation.provider import validate_endpoint
            validate_endpoint(c.localpilot_endpoint, c.localpilot_allow_remote)
        c.data_dir = str(path(c.data_dir))
        c.watch_dirs = tuple(str(path(p)) for p in c.watch_dirs)
        c.exclude_dirs = tuple(str(path(p)) for p in c.exclude_dirs)
        state = path(c.data_dir)
        for root in map(path, c.watch_dirs):
            if not root.is_dir() or root in (Path("/"), Path.home()) or any(p.is_symlink() for p in (root,*root.parents)):
                raise ValueError(f"Choose a specific, existing directory: {root}")
            if any(p in SENSITIVE for p in root.parts) or Path.home() / "Library" == root or (Path.home() / "Library") in root.parents:
                raise ValueError(f"Sensitive directory refused: {root}")
            if root == state or root in state.parents or state in root.parents:
                raise ValueError("Data directory must be separate from observed directories")
        return c


class PrivateData:
    """Every Companion-owned write must stay inside this private directory."""
    def __init__(self, root):
        self.root = path(root)
        if any(p.is_symlink() for p in (self.root, *self.root.parents)):
            raise ValueError("Symlink data directory refused")
        marker = self.root / ".companion-data-owner"
        if self.root.exists() and any(self.root.iterdir()):
            if marker.is_symlink() or not marker.is_file() or marker.read_text() != "localpilot-companion-v0\n":
                raise ValueError("Existing non-Companion data directory preserved; choose an empty private directory")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.stat().st_uid != os.getuid():
            raise ValueError("Data directory must belong to current user")
        self.root.chmod(0o700)
        if not marker.exists():
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd,"w") as out:
                out.write("localpilot-companion-v0\n")

    def file(self, name):
        p = self.root / name
        if p.parent != self.root or p.is_symlink():
            raise ValueError("Invalid private filename")
        return p

    def write(self, name, content):
        p = self.file(name)
        temporary = self.file(".write-" + secrets.token_hex(12))
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w") as out:
                out.write(content)
                out.flush()
                os.fsync(out.fileno())
            self.file(name)  # Recheck the destination before atomic publication.
            os.replace(temporary, p)
        finally:
            temporary.unlink(missing_ok=True)
        return p
