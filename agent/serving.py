"""Operator claims and scoped observations; never controls Runtime permissions."""

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path


VERIFICATION_CHECKS = ("health_models", "basic_chat", "streaming", "tool_calling", "reasoning")


@dataclass
class ServingProfile:
    base_url: str
    model: str
    configured_context: int
    engine: str = "UNKNOWN"
    engine_version: str = "UNKNOWN"
    model_revision: str = "UNKNOWN"
    hardware: str = "UNKNOWN"
    device: str = "UNKNOWN"
    # A loopback address may be an SSH tunnel. Location is an operator claim.
    service_location: str = "unknown"
    configured_capabilities: dict = field(default_factory=dict)
    request_options: dict = field(default_factory=dict)
    verification: dict | None = field(default=None, repr=False)

    def identity(self):
        return {"transport": "openai_chat_completions", "base_url": self.base_url,
                "model": self.model, "configured_context": self.configured_context,
                "engine": self.engine, "engine_version": self.engine_version,
                "model_revision": self.model_revision, "hardware": self.hardware,
                "device": self.device, "service_location": self.service_location,
                "configured_capabilities": deepcopy(self.configured_capabilities),
                "request_options": deepcopy(self.request_options)}

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.identity(), sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()

    def attach_verification(self, report):
        if (not isinstance(report, dict) or report.get("schema_version") != 1 or
                report.get("profile_fingerprint") != self.fingerprint):
            raise ValueError("Verification report does not match this serving profile/configuration")
        checks = report.get("checks")
        if not isinstance(checks, dict) or set(checks) - set(VERIFICATION_CHECKS) or any(
            not isinstance(check, dict) or check.get("status") not in {"verified", "unsupported", "unknown"}
            or check.get("outcome") not in {"passed", "failed", "skipped"}
            or (check.get("status") == "verified" and check.get("outcome") != "passed")
            for check in checks.values()
        ):
            raise ValueError("Malformed verification report")
        self.verification = deepcopy(report)

    def snapshot(self):
        matched = bool(self.verification and self.verification.get("profile_fingerprint") == self.fingerprint)
        checks = self.verification.get("checks", {}) if matched else {}
        names = {"health_models", "basic_chat", "streaming", "tool_calling", "reasoning",
                 "parallel_tool_calls", "context", "prefix_caching"}
        capabilities = {}
        for name in sorted(names):
            configured = self.configured_capabilities.get(name)
            observation = checks.get(name)
            capabilities[name] = {
                "configured": configured,
                "status": observation["status"] if observation else
                          "configured" if configured is not None else "unknown",
                "source": "verification_report" if observation else "operator_config" if configured is not None else "unknown",
                "observation": deepcopy(observation),
            }
        return {"schema_version": 1, **self.identity(), "fingerprint": self.fingerprint,
                "provenance": {"metadata": "operator_config_not_device_measurement",
                               "configuration": "operator_config_or_legacy_defaults",
                               "context": "configured_estimate_not_verified_limit"},
                "capabilities": capabilities,
                "verification_state": "matched_historical" if matched else "stale" if self.verification else "not_run",
                "verification": deepcopy(self.verification)}


def add_serving_arguments(parser):
    parser.add_argument("--serving-profile", help="JSON operator configuration; contains no API key or verification claims.")
    parser.add_argument("--local-base-url", help="OpenAI-compatible API root, e.g. http://127.0.0.1:1234/v1.")
    parser.add_argument("--local-model", help="Exact model ID returned by /models.")
    parser.add_argument("--local-context", type=int, help="Configured admission estimate, not a verified context limit (default: 131072).")
    parser.add_argument("--local-size-class", help="Configured routing size class (default: unknown).")
    parser.add_argument("--local-timeout", type=float, help="HTTP timeout in seconds (default: 30).")
    parser.add_argument("--local-no-think", action="store_true", help="Request enable_thinking=false using chat_template_kwargs.")
    parser.add_argument("--local-stream-usage", action="store_true", help="Request optional SSE usage metadata.")
    parser.add_argument("--allow-remote-local-endpoint", action="store_true", help="Explicitly permit a non-loopback endpoint; data may leave this host.")
    parser.add_argument("--local-api-key-env", help="Name of environment variable containing the Bearer key (default: LOCALPILOT_LOCAL_API_KEY).")
    parser.add_argument("--backend-status", action="store_true", help="Show profile and last verification offline; no network or inference.")
    parser.add_argument("--backend-verification", help="Read a matching historical verification JSON report; does not grant permissions.")
    parser.add_argument("--backend-verify", action="store_true", help="Explicit short smoke requests to an already running configured service; no tools executed.")
    parser.add_argument("--backend-checks", default="health_models,basic_chat,streaming,tool_calling,reasoning", help="Comma-separated smoke checks; health/models always checked first.")
    parser.add_argument("--backend-report", help="New output stem for verification .json and .md files (never overwrites).")
    parser.add_argument("--verification-evidence", choices=("unclassified-service", "scripted-tested", "real-model-tested"), default="unclassified-service", help="Operator-declared evidence kind; API responses alone cannot prove a real model.")


def configured_backend(args, recommendation=None):
    """Same adapter for legacy flags and optional JSON; explicit flags win."""
    from .backends import LocalBackend, ModelInfo
    from .local_http import LocalHTTPBackend
    config = {}
    if args.serving_profile:
        config = json.loads(Path(args.serving_profile).expanduser().read_text(encoding="utf-8"))
        allowed = {"base_url", "model", "configured_context", "size_class", "timeout",
                   "engine", "engine_version", "model_revision", "hardware", "device",
                   "service_location", "capabilities", "chat_template_kwargs",
                   "include_stream_usage", "reasoning_replay", "reasoning_efforts", "api_key_env"}
        if not isinstance(config, dict) or set(config) - allowed:
            raise ValueError("Serving profile must contain only supported operator configuration fields")
    base_url = args.local_base_url or config.get("base_url")
    selected = args.local_model or config.get("model") or (recommendation or {}).get("model_id")
    if not base_url:
        if config or args.backend_verify:
            raise ValueError("A configured base_url and model are required")
        local = LocalBackend()
        if recommendation:
            local.model_info = ModelInfo(selected, f"{recommendation['model']['parameters_b']:g}B", recommendation["context_length"])
        return local
    if not selected:
        raise ValueError("Set --local-model with --local-base-url when no recommendation is supplied.")
    capabilities = config.get("capabilities", {})
    if not isinstance(capabilities, dict) or set(capabilities) - {"streaming", "tool_calling", "reasoning"} or any(type(v) is not bool for v in capabilities.values()):
        raise ValueError("Profile capabilities must be boolean streaming/tool_calling/reasoning declarations")
    key_env = args.local_api_key_env or config.get("api_key_env", "LOCALPILOT_LOCAL_API_KEY")
    if not isinstance(key_env, str) or not key_env or not key_env.isidentifier():
        raise ValueError("api_key_env must be an environment variable name")
    if (args.local_api_key_env or "api_key_env" in config) and not os.environ.get(key_env):
        raise ValueError("Configured backend API key environment variable is empty")
    context = args.local_context if args.local_context is not None else config.get("configured_context", 131072)
    size = args.local_size_class or config.get("size_class", "unknown")
    if recommendation and not args.local_model and not config.get("model"):
        if args.local_context is None:
            context = recommendation["context_length"]
        if args.local_size_class is None:
            size = f"{recommendation['model']['parameters_b']:g}B"
    kwargs = deepcopy(config.get("chat_template_kwargs", {}))
    if not isinstance(kwargs, dict):
        raise ValueError("chat_template_kwargs must be an object")
    if args.local_no_think:
        kwargs["enable_thinking"] = False
    backend = LocalHTTPBackend(base_url=base_url, model=selected,
        effective_context=context, size_class=size,
        timeout=args.local_timeout if args.local_timeout is not None else config.get("timeout", 30),
        allow_remote=args.allow_remote_local_endpoint, api_key=os.environ.get(key_env),
        supports_tool_calling=capabilities.get("tool_calling", True),
        supports_streaming=capabilities.get("streaming", True),
        supports_reasoning=capabilities.get("reasoning"),
        chat_template_kwargs=kwargs,
        include_stream_usage=args.local_stream_usage or config.get("include_stream_usage", False),
        reasoning_replay=config.get("reasoning_replay", False),
        reasoning_efforts=config.get("reasoning_efforts", ()),
        **{name: config[name] for name in ("engine", "engine_version", "model_revision", "hardware", "device", "service_location") if name in config})
    if args.backend_verification:
        backend.profile.attach_verification(json.loads(Path(args.backend_verification).expanduser().read_text(encoding="utf-8")))
    return backend
