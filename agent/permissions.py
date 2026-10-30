"""Host-owned permission vocabulary for tool calls."""

from dataclasses import dataclass
from enum import Enum


class PermissionMode(str, Enum):
    ASSIST_LOW = "assist-low-risk"
    ASSIST_HIGH = "assist-high-risk"
    WORKSPACE_AUTO = "workspace-auto"
    APPROVE_ALL = "approve-all"
    APPROVE_MUTATIONS = "approve-mutations"
    LOCAL_JUDGE_CONSERVATIVE = "local-judge-conservative"
    LOCAL_JUDGE_PERMISSIVE = "local-judge-permissive"
    FULL_PERMISSION = "full-permission"


@dataclass(frozen=True)
class ToolRiskMetadata:
    read_only: bool = False
    mutating: bool = True
    potentially_destructive: bool = False
    external_side_effect: bool = False
    requires_shell: bool = False
    network_access: bool = False
    requires_host_approval: bool = False


@dataclass(frozen=True)
class RiskAssessment:
    risk_level: str
    reason: str
    potential_impact: str
    recommended_action: str

    def __post_init__(self):
        if self.risk_level not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            raise ValueError("Invalid risk level")
        if self.recommended_action not in {"allow", "approval_required", "deny"}:
            raise ValueError("Invalid recommended action")
        if not isinstance(self.reason, str) or not isinstance(self.potential_impact, str):
            raise ValueError("Risk reason and impact must be strings")
