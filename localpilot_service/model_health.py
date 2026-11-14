"""Read-only provider observations; discovery never qualifies inference or tools."""

import json
from http.client import HTTPException
from urllib.error import URLError

from agent.local_http import LocalBackendError, LocalHTTPBackend
from agent.omlx import OMLXBackend


def probe_model_health(backend):
    """Observe an already configured backend without acquiring a model lease.

    ACCEPTED means the discovery request with configured credentials succeeded.
    A public discovery endpoint cannot verify those credentials for inference.
    """
    result = {
        "status": "NOT_PROBED", "endpoint_reachable": None,
        "authentication": "UNKNOWN", "authentication_scope": "model_discovery_only",
        "model_listed": None, "model_loaded": None,
        "inference": "NOT_PROBED", "tool_execution": "NOT_PROBED",
        "evidence_kind": "READ_ONLY_PROVIDER_DISCOVERY",
        "reason": "unsupported_read_only_probe",
    }
    if not isinstance(backend, LocalHTTPBackend):
        return result

    try:
        with backend._open("/models") as response:
            result.update(endpoint_reachable=True,
                          authentication="ACCEPTED" if backend._api_key else "NOT_REQUIRED")
            data = json.load(response)
        models = _model_ids(data)
    except LocalBackendError as error:
        _record_transport_error(result, error)
        return result
    except (OSError, HTTPException):
        result.update(status="FAILED", reason="transport_unavailable")
        if result["endpoint_reachable"] is None:
            result["endpoint_reachable"] = False
        return result
    except (ValueError, TypeError, KeyError):
        result.update(status="FAILED", reason="invalid_model_discovery")
        return result

    listed = backend.model in models
    result.update(status="OBSERVED", model_listed=listed,
                  reason="model_listed" if listed else "model_not_listed")
    if isinstance(backend, OMLXBackend) and listed:
        _observe_omlx_loaded(backend, result)
    return result


def _model_ids(data):
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ValueError("Invalid discovery envelope")
    models = data["data"]
    if any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in models):
        raise ValueError("Invalid model identity")
    return {row["id"] for row in models}


def _record_transport_error(result, error):
    result.update(status="FAILED", reason="endpoint_unverified")
    code = error.status_code
    if code is not None:
        result.update(endpoint_reachable=True, http_status=code,
                      reason="discovery_http_error")
        if code in {401, 403}:
            result.update(authentication="REJECTED", reason="authentication_rejected")
    elif isinstance(error.__cause__, (URLError, OSError)):
        result.update(endpoint_reachable=False, reason="transport_unavailable")


def _observe_omlx_loaded(backend, result):
    try:
        observation = backend.inspect_service()
        row = next((item for item in observation["models"] if item["id"] == backend.model), None)
    except (LocalBackendError, OSError, HTTPException, ValueError, KeyError, TypeError, AttributeError):
        result["loaded_state_reason"] = "omlx_status_unavailable"
        return
    if row is not None and type(row.get("loaded")) is bool:
        result.update(model_loaded=row["loaded"],
                      loaded_state_reason="omlx_reported_loaded_state",
                      model_loading=row.get("deployment_status") == "loading")
    else:
        result["loaded_state_reason"] = "omlx_loaded_state_unknown"
