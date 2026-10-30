"""Consumer-owned contract checks. No LocalPilot runtime dependency."""
import re
from companion import __version__

REQUIRED = {"durable_tasks", "durable_idempotency", "sse_cursor", "operator_approval",
            "cancel", "safe_resume", "unknown_quarantine", "verification_dimensions",
            "model_registry", "explicit_cloud_egress", "resource_control_v1"}


def version_key(value):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?", value) if isinstance(value, str) else None
    if not match:
        raise ValueError("Unknown version syntax")
    return (*map(int, match.group(1,2,3)), {"a":0,"b":1,"rc":2,None:3}[match[4]], int(match[5] or 0))


def incompatibility(health):
    contract = health.get("compatibility")
    if contract is None:
        return None if health.get("version") in {"4.9.1", "4.9.1rc2"} else "compatibility_missing_require_core_4_9_1rc2_api_1_0"
    if not isinstance(contract, dict) or not all(isinstance(contract.get(k), str) and re.fullmatch(r"1\.\d+", contract[k]) for k in ("agent_service_api", "companion_client_contract")):
        return "incompatible_api_require_1_0_client_contract_1_0"
    try:
        if version_key(contract.get("minimum_companion", "0.5.5rc1")) > version_key(__version__):
            return "consumer_upgrade_required_minimum_" + contract["minimum_companion"]
    except ValueError:
        return "invalid_minimum_companion_version"
    limits=contract.get("limits",{})
    if not isinstance(limits,dict) or type(limits.get("task_input_json_utf8_bytes",4096)) is not int or not 512 <= limits.get("task_input_json_utf8_bytes",4096) <= 1048576:
        return "invalid_task_input_limit_contract"
    capabilities = contract.get("capabilities")
    if not isinstance(capabilities, list) or not all(isinstance(c, str) for c in capabilities) or not REQUIRED.issubset(capabilities):
        return "missing_required_capabilities_require_core_4_9_2rc1"
    return None
