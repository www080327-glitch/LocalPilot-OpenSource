"""Small, provider-neutral local/cloud strategy and minimal-prompt settings."""

from dataclasses import dataclass


STRATEGIES = {"local_only", "local_first", "balanced", "cloud_first", "cloud_only"}
LOCAL_CONTEXT_NOTICE = (
    "尚未接通本地 Agent backend；路由输出只是配置建议，不能证明任务可完成。"
)


@dataclass(frozen=True)
class DataPolicy:
    """Trusted host policy; model text and routing preferences cannot relax it."""

    local_only: bool = False

    def check_backend(self, backend):
        if self.local_only and getattr(backend, "is_local", None) is not True:
            raise PermissionError("local_only forbids cloud or unclassified backends.")
        if self.local_only and (not getattr(backend, "is_loopback", True) or
                getattr(getattr(backend, "profile", None), "service_location", None) == "remote"):
            raise PermissionError("local_only forbids remote endpoints and declared remote tunnels.")

    def check_cloud_send(self):
        if self.local_only:
            raise PermissionError("local_only forbids sending data to a cloud backend.")


@dataclass(frozen=True)
class LocalRunConfig:
    strategy: str = "balanced"
    local_context_k: int = 32
    minimal_mode: bool = False
    local_primary_override: bool = False

    def __post_init__(self):
        if self.strategy not in STRATEGIES:
            raise ValueError(f"strategy must be one of {sorted(STRATEGIES)}")
        if self.local_context_k < 1:
            raise ValueError("local_context_k must be positive")

    def decision(self):
        """Describe routing posture; this does not execute or grant tools."""
        if self.strategy == "cloud_only":
            return {"primary": "cloud", "local_role": "disabled", "notice": None}
        if self.strategy == "cloud_first":
            return {"primary": "cloud", "local_role": "fallback", "notice": None}
        if self.strategy == "local_only":
            return {"primary": "local", "local_role": "primary", "notice": None}

        return {
            "primary": "local" if self.strategy == "local_first" or self.local_primary_override else "undecided",
            "local_role": "candidate",
            "notice": LOCAL_CONTEXT_NOTICE,
            "minimal_mode": self.minimal_mode,
        }
