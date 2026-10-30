"""Pure routing rules for the runtime; these rules do not authorize execution."""

from dataclasses import dataclass
from enum import Enum


class RoutingPolicy(str, Enum):
    LOCAL_ONLY = "local-only"
    LOCAL_FIRST = "local-first"
    BALANCED = "balanced"
    CLOUD_FIRST = "cloud-first"
    CLOUD_ONLY = "cloud-only"


# Guidance added after the stable base prompt. These strings describe product
# posture; the session's host policy and permission checks remain authoritative.
ROUTING_OVERLAYS = {
    RoutingPolicy.LOCAL_ONLY: "Routing guidance: use the local model only; never send task data to cloud.",
    RoutingPolicy.LOCAL_FIRST: "Routing guidance: prefer eligible local processing; use cloud only after local failure and approval where required.",
    RoutingPolicy.BALANCED: "Routing guidance: choose by task complexity; local is suitable for simple tasks when eligible.",
    RoutingPolicy.CLOUD_FIRST: "Routing guidance: prefer cloud; use local only for very simple tasks when eligible.",
    RoutingPolicy.CLOUD_ONLY: "Routing guidance: use cloud only; do not route work to local.",
}


def parse_policy(value):
    """Parse a policy name, accepting the older underscore spelling too."""
    if isinstance(value, RoutingPolicy):
        return value
    normalized = str(value).strip().lower().replace("_", "-")
    try:
        return RoutingPolicy(normalized)
    except ValueError as error:
        raise ValueError(f"Unknown routing policy: {value}") from error


@dataclass(frozen=True)
class EligibilityConfig:
    excluded_size_classes: tuple = ("4B", "9B")
    min_context: int = 65536

    def __post_init__(self):
        if not isinstance(self.excluded_size_classes, tuple) or any(
            not isinstance(value, str) or not value for value in self.excluded_size_classes
        ):
            raise ValueError("excluded_size_classes must be a tuple of non-empty strings")
        if isinstance(self.min_context, bool) or not isinstance(self.min_context, int) or self.min_context <= 0:
            raise ValueError("min_context must be a positive integer")


def local_main_eligible(backend, config=EligibilityConfig()):
    """Return whether a local backend passes the configured product heuristic."""
    if backend is None:
        return False
    if getattr(backend, "is_local", None) is not True:
        return False
    health_check = getattr(backend, "health_check", None)
    if not callable(health_check):
        return False
    try:
        if not health_check():
            return False
    except Exception:
        return False
    info = getattr(backend, "model_info", None)
    size_class = getattr(info, "size_class", None)
    context = getattr(info, "effective_context", None)
    if size_class is None or context is None:
        return False
    if size_class in config.excluded_size_classes:
        return False
    return not isinstance(context, bool) and isinstance(context, int) and context >= config.min_context


class FallbackReason(str, Enum):
    LOCAL_BACKEND_FAILURE = "local_backend_failure"
    MODEL_CAPABILITY_ESCALATION = "model_capability_escalation"


@dataclass(frozen=True)
class ModelSwitchRequest:
    from_model: str
    to_model: str
    reason: str
    scope: str = "turn"
    task_complexity: str = "complex"
    requires_user_confirmation: bool = True
    data_boundary_change: tuple = ()


def switch_allowed(policy, current, target, task_complexity, local_eligible,
                   switches, max_switches=1):
    """Return (allowed, reason) for a model change; no provider is invoked."""
    policy = parse_policy(policy)
    current = str(current).strip().lower()
    target = str(target).strip().lower()
    if current not in {"local", "cloud"} or target not in {"local", "cloud"}:
        return False, "invalid_target"
    if current == target:
        return False, "same_target"
    if switches >= max_switches:
        return False, "switch_limit_reached"
    if target == "local" and not local_eligible:
        return False, "local_ineligible"
    simple = str(task_complexity).lower() in {"simple", "very_simple"}
    very_simple = str(task_complexity).lower() == "very_simple"
    if policy == RoutingPolicy.LOCAL_ONLY and target == "cloud":
        return False, "policy_forbids_cloud"
    if policy == RoutingPolicy.CLOUD_ONLY and target == "local":
        return False, "policy_forbids_local"
    if current == "local" and target == "cloud":
        if policy in {RoutingPolicy.BALANCED, RoutingPolicy.CLOUD_FIRST}:
            return True, FallbackReason.MODEL_CAPABILITY_ESCALATION.value
        if policy == RoutingPolicy.LOCAL_FIRST:
            return True, FallbackReason.MODEL_CAPABILITY_ESCALATION.value
        return False, "policy_forbids_switch"
    if current == "cloud" and target == "local":
        if policy == RoutingPolicy.BALANCED and simple:
            return True, "policy_allows_local_for_simple_task"
        if policy == RoutingPolicy.CLOUD_FIRST and very_simple:
            return True, "policy_allows_local_for_very_simple_task"
        return False, "policy_forbids_switch"
    return False, "policy_forbids_switch"
