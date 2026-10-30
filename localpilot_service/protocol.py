"""Additive, model-independent public compatibility manifest."""
import re

API_VERSION = "1.0"
CLIENT_CONTRACT_VERSION = "1.0"
CAPABILITIES = (
    "durable_tasks", "durable_idempotency", "sse_cursor", "operator_approval",
    "cancel", "safe_resume", "unknown_quarantine", "verification_dimensions",
    "model_registry", "explicit_cloud_egress", "resource_control_v1",
)
OPTIONAL_CAPABILITIES = ('omlx_thinking_toggle_v1', 'desktop_permissions_v3', 'task_low_power_consent_v1', 'task_outcome_v1', 'routing_preferences_v1', 'model_manager_read_v1','session_thinking_v1','model_resource_v1','pause_v1','lifecycle_suspend_v1','desktop_session_v1','desktop_session_idempotency_v1','desktop_profile_switch_v1','attachments_v1','attachments_v2','workspace_grants_v1','bounded_file_operations_v1')


def local_agent_constraints():
    from agent.routing import EligibilityConfig
    policy=EligibilityConfig()
    return {'version':1,'minimum_context':policy.min_context,'excluded_size_classes':list(policy.excluded_size_classes),'basis':'existing_core_eligibility_policy_not_a_quality_benchmark'}


def manifest():
    return {"agent_service_api": API_VERSION,
            "companion_client_contract": CLIENT_CONTRACT_VERSION,
            "api_supported": {"minimum": "1.0", "maximum_exclusive": "2.0"},
            "minimum_companion": "0.5.5rc1", "capabilities": list(CAPABILITIES + OPTIONAL_CAPABILITIES),
            "limits": {"task_input_json_utf8_bytes": 4096,"attachment_batch_bytes":2147483648,"attachment_metadata_bytes":8388608}, "local_agent_constraints":local_agent_constraints(), "model_health": "NOT_PROBED"}


def check(health):
    contract = health.get("compatibility", {})
    if not contract:
        if health.get("version") in {"4.9.1", "4.9.1rc2"}:
            return "legacy_audited_4.9.1"
        raise ValueError("API compatibility missing; minimum Core 4.9.1rc2, API 1.0")
    if not isinstance(contract, dict) or not all(isinstance(contract.get(k), str) and re.fullmatch(r"1\.\d+", contract[k]) for k in ("agent_service_api", "companion_client_contract")):
        raise ValueError("Incompatible API/Companion contract; require API 1.0 and client contract 1.0")
    caps = contract.get("capabilities", [])
    if not isinstance(caps, list) or not all(isinstance(c, str) for c in caps):
        raise ValueError("Malformed capability negotiation")
    missing = set(CAPABILITIES) - set(caps)
    if missing:
        raise ValueError("Missing service capabilities: " + ", ".join(sorted(missing)))
    return "compatible"
