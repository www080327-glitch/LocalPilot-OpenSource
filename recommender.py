"""Explainable memory-gated model recommendations with explicit provenance."""

import json
import math
from copy import deepcopy
from pathlib import Path
from statistics import median

from catalog import CONTEXT_LENGTHS, MODELS

MODEL_CONTEXT_PREFERENCES = {
    "model": "capability_first",
    "slight_model": "slight_capability_first",
    "balanced": "balanced",
    "slight_context": "slight_context_first",
    "context": "context_first",
}
VALID_CONTEXT_PREFERENCES = set(MODEL_CONTEXT_PREFERENCES) | set(MODEL_CONTEXT_PREFERENCES.values())
VALID_PERFORMANCE_PREFERENCES = {"quality", "speed", "efficiency", "balanced"}
SYSTEM_RESERVE_GB = 3.0
PROFILE_PATH = Path(__file__).parent / "benchmarks" / "mlx_profiles.json"
if not PROFILE_PATH.is_file():
    PROFILE_PATH = Path(__file__).parent / "localpilot_service" / "data" / "mlx_profiles.json"
MLP_PATH = Path(__file__).parent / "localpilot_service" / "data" / "selector_mlp.json"

def load_profiles(path=PROFILE_PATH):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"host": {}, "models": {}}


def _model_context_preference(value):
    return MODEL_CONTEXT_PREFERENCES.get(value, value)


def _standard_context_at_most(limit_k, model_max_tokens):
    max_k = min(limit_k, model_max_tokens // 1024)
    return max((tier for tier in CONTEXT_LENGTHS if tier <= max_k), default=None)


def memory_estimate(model, context_k, profiles=None, *, backend_version=None):
    """A conservative MLX admission estimate, never a measured total-memory claim.

    Reserve = 20% of the largest observed RSS/allocator/artifact + 1 GiB.
    A separate system reserve remains in recommend(). Margins are heuristics,
    not a calibrated OOM guarantee. Observations retain their exact identity.
    """
    profiles = profiles if profiles is not None else load_profiles()
    weight = float(model.get("artifact_gb") or model["parameters_b"] * 0.5)
    candidates = []
    for point in profiles.get("measurements", []):
        key = point["identity"]
        if any(key.get(field) != expected for field, expected in (
            ("repo_id", model["repo_id"]), ("model_revision", model["revision"]),
            ("quantization", model["quantization"]), ("backend", model["backend"]))):
            continue
        if backend_version is not None and key.get("backend_version") != backend_version:
            continue
        metrics = point["metrics"]
        allocator = metrics.get("mlx_peak_memory_gb")
        rss = metrics.get("peak_process_rss_gb")
        if key.get("context_k") is None or (allocator is None and rss is None):
            continue
        if allocator is None:
            # RSS is only a lower bound; never let fallback undercut a high RSS.
            observed_base = max(rss, weight * 1.12 + 0.8 + key["context_k"] * 0.20)
        else:
            observed_base = max(weight, allocator, rss or 0)
        candidates.append((key["context_k"], observed_base, point))
    source_points = []
    if candidates:
        # For unmeasured short inputs use a measured upper context, not a smaller
        # artifact formula that could undercut the observed allocation.
        upper = [item for item in candidates if item[0] >= context_k]
        if upper:
            tier = min(item[0] for item in upper)
            eligible = [item for item in upper if item[0] == tier]
            basis = "observed_context" if tier == context_k else "observed_upper_context"
            base = max(item[1] for item in eligible)
            source_points = [item[2] for item in eligible]
        else:
            tier = max(item[0] for item in candidates)
            eligible = [item for item in candidates if item[0] == tier]
            # Explicit unvalidated extrapolation, never an interpolation measurement.
            base = max(item[1] for item in eligible) + (context_k - tier) * 0.20
            source_points = [item[2] for item in eligible]
            basis = "heuristic_extrapolation"
    else:
        base = weight * 1.12 + 0.8 + context_k * 0.20
        basis = "heuristic_artifact_fallback"
    if any(point["metrics"].get("mlx_peak_memory_gb") is None for point in source_points):
        basis = "heuristic_rss_lower_bound"
    envelope = round(base * 1.20 + 1.0, 2)
    return {
        "admission_envelope_gib": envelope, "provenance": "estimated",
        "basis": basis, "measurement_ids": [p["measurement_id"] for p in source_points],
        "observations": source_points,
        "explanation": "Estimated MLX envelope: 1.20 × max(observed allocator, RSS, artifact) + 1 GiB; "
                       "no RSS+allocator sum. Transfer/output growth and missing identity are unvalidated. "
                       + basis,
    }


def estimate_memory_gb(model, context_k, profiles=None, device_memory_gb=None, device_host=None,
                       *, backend_version=None):
    """Compatibility wrapper. Device transfer is always an estimate."""
    estimate = memory_estimate(model, context_k, profiles, backend_version=backend_version)
    return estimate["admission_envelope_gib"], "estimated", estimate["explanation"]


def _active_parameters_b(model):
    # Dense models activate all weights; MoE speed uses active, not total, size.
    return float(model.get("active_parameters_b", model["parameters_b"]))


def _observed_decode_tps(model, context_k, profiles, chip, memory_gb):
    if not chip:
        return None, None, None
    samples = {}
    for point in profiles.get("measurements", []):
        key = point.get("identity", {})
        if any(key.get(field) != model[field_name] for field, field_name in (
            ("repo_id", "repo_id"), ("model_revision", "revision"),
            ("quantization", "quantization"), ("backend", "backend"))):
            continue
        host = key.get("hardware", {})
        measured_context = key.get("context_k")
        if (not isinstance(measured_context, int) or measured_context < context_k
                or host.get("chip") != chip or host.get("memory_gb") != memory_gb):
            continue
        value = point.get("metrics", {}).get("decode_tps_median")
        if (point.get("metric_provenance", {}).get("latency") == "measured"
                and isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and value > 0):
            samples.setdefault(measured_context, []).append(value)
    if not samples:
        return None, None, None
    nearest_context = min(samples)
    basis = "observed_decode_tps" if nearest_context == context_k else "observed_upper_context_proxy"
    return median(samples[nearest_context]), basis, nearest_context


def _add_speed_evidence(options, profiles, chip, memory_gb):
    observed_scales = []
    for option in options:
        tps, basis, observed_context = _observed_decode_tps(
            option["model"], option["context_k"], profiles, chip, memory_gb)
        option["observed_decode_tps"] = tps
        option["speed_observation_context_k"] = observed_context
        option["speed_basis"] = basis or "heuristic_active_parameters"
        if tps is not None:
            observed_scales.append(tps * _active_parameters_b(option["model"]))
            option["metric_provenance"]["latency"] = ("measured_same_host_context_decode" if
                basis == "observed_decode_tps" else "estimated_from_observed_upper_context")
    # Anchor unobserved active-parameter proxies to this host's observations
    # so a measured candidate and an unmeasured one share a scale.
    scale = median(observed_scales) if observed_scales else 1.0
    for option in options:
        option["speed_tps_for_ranking"] = (option["observed_decode_tps"] if
            option["observed_decode_tps"] is not None else
            scale / _active_parameters_b(option["model"]))


def _score(option, performance, context_preference):
    context_preference = _model_context_preference(context_preference)
    weights = {
        "capability_first": (6, 1),
        "slight_capability_first": (4, 2),
        "balanced": (2, 2),
        "slight_context_first": (1, 4),
        "context_first": (1, 6),
    }
    capability_weight, context_weight = weights[context_preference]
    model_rank = option["model"]["capability_rank"] - 1
    context_rank = CONTEXT_LENGTHS.index(option["context_k"])
    model_score = model_rank * capability_weight
    context_score = context_rank * context_weight
    if performance == "quality":
        performance_score = model_rank * 1.5
    elif performance == "speed":
        performance_score = 2.5 * math.log(option["speed_tps_for_ranking"])
    elif performance == "efficiency":
        performance_score = 2.5 * math.log(option["speed_tps_for_ranking"]) - context_rank * 0.15
    else:
        performance_score = model_rank * 0.25
    return model_score + context_score + performance_score


def feasible_candidates(memory_gb, context_k, *, profiles=None, os_name="macOS", arch="arm64", chip=None,
                        minimum_context_k=None, excluded_size_classes=()):
    """Apply the original MLX admission rules before any ranking."""
    if minimum_context_k is not None and (minimum_context_k not in CONTEXT_LENGTHS or minimum_context_k > context_k):
        raise ValueError('minimum_context_k must be a supported tier at most context_k')
    if not isinstance(excluded_size_classes, (tuple, list)) or any(not isinstance(v, str) for v in excluded_size_classes):
        raise ValueError('Invalid excluded model classes')
    if context_k not in CONTEXT_LENGTHS:
        raise ValueError("invalid context tier")
    if os_name != "macOS" or arch not in {"arm64", "aarch64"} or memory_gb is None or memory_gb <= 0:
        return []
    profiles = profiles if profiles is not None else load_profiles()
    device_host = {"os": os_name, "arch": arch, "chip": chip}
    feasible = []
    memory_budget = max(0.0, memory_gb - SYSTEM_RESERVE_GB)
    for model in MODELS:
        if f"{model['parameters_b']}B" in excluded_size_classes:continue
        tier = _standard_context_at_most(context_k, model["max_context_tokens"] - 1024)
        while tier is not None and (minimum_context_k is None or tier>=minimum_context_k):
            required, provenance, estimate_reason = estimate_memory_gb(
                model, tier, profiles, device_memory_gb=memory_gb, device_host=device_host
            )
            if required <= memory_budget:
                feasible.append({
                    "model": model,
                    "model_id": model["repo_id"],
                    "quantization": model["quantization"],
                    "bits": model["bits"],
                    "backend": model["backend"],
                    "context_k": tier,
                    "context_length": tier * 1024,
                    "reserved_output_tokens": 1024,
                    "estimated_peak_memory_gb": required,
                    "system_reserve_gb": SYSTEM_RESERVE_GB,
                    "data_source": provenance,  # Memory estimate only; not a quality score.
                    "admission_envelope_gib": required,
                    "metric_provenance": {"memory": "estimated", "latency": "unknown",
                                          "capability_quality": "unknown", "compatibility": "unknown"},
                    "memory_evidence": memory_estimate(model, tier, profiles),
                    "ranking_provenance": "heuristic_subjective_product_ordering",
                    "estimate_reason": estimate_reason,
                    "requested_context_k": context_k,
                })
                break
            lower_tier = [value for value in CONTEXT_LENGTHS if value < tier]
            tier = lower_tier[-1] if lower_tier else None
    if not feasible:
        return []

    _add_speed_evidence(feasible, profiles, chip, memory_gb)
    return feasible


def recommend(
    memory_gb,
    preference="balanced",
    context_k=32,
    model_context="balanced",
    *,
    os_name="macOS",
    arch="arm64",
    chip=None,
    profiles=None,
    minimum_context_k=None,
    excluded_size_classes=(),
    selector="rules",
    mlp_path=None,
    available_memory_gb=None,
    allowed_model_ids=None,
):
    """Recommend a 4-bit MLX configuration; never infer support from chip name."""
    if minimum_context_k is not None and (minimum_context_k not in CONTEXT_LENGTHS or minimum_context_k>context_k):
        raise ValueError('minimum_context_k must be a supported tier at most context_k')
    if not isinstance(excluded_size_classes,(tuple,list)) or any(not isinstance(v,str) for v in excluded_size_classes):raise ValueError('Invalid excluded model classes')
    if preference not in VALID_PERFORMANCE_PREFERENCES:
        raise ValueError("preference must be quality, speed, efficiency, or balanced")
    if context_k not in CONTEXT_LENGTHS:
        raise ValueError(f"context_k must be one of {CONTEXT_LENGTHS}")
    if model_context not in VALID_CONTEXT_PREFERENCES:
        raise ValueError("invalid capability/context preference")
    if selector not in {"rules", "mlp", "auto"}:
        raise ValueError("selector must be rules, mlp or auto")
    if available_memory_gb is not None and (type(available_memory_gb) not in (int, float)
            or not math.isfinite(available_memory_gb) or available_memory_gb < 0):
        raise ValueError("available memory must be finite and nonnegative")
    if allowed_model_ids is not None and (not isinstance(allowed_model_ids, (list, tuple))
            or any(not isinstance(v, str) for v in allowed_model_ids)):
        raise ValueError("allowed_model_ids must be an explicit model allowlist")
    if os_name != "macOS":
        return {"status": "unsupported", "reason": "Only macOS is in the current platform scope."}
    if arch not in {"arm64", "aarch64"}:
        return {"status": "deferred", "reason": "Intel Mac support is deferred; MLX requires Apple Silicon."}
    if memory_gb is None or memory_gb <= 0:
        return None

    feasible = feasible_candidates(memory_gb, context_k, profiles=profiles, os_name=os_name, arch=arch, chip=chip,
                                   minimum_context_k=minimum_context_k, excluded_size_classes=excluded_size_classes)
    feasible = [o for o in feasible
                if (available_memory_gb is None or o["admission_envelope_gib"] <= available_memory_gb)
                and (allowed_model_ids is None or o["model_id"] in allowed_model_ids)]
    if not feasible:
        return None

    result = max(feasible, key=lambda option: _score(option, preference, model_context))
    if preference in {"speed", "efficiency"}:
        result["ranking_provenance"] = result["speed_basis"] + "_and_subjective_capability_ordering"
        speed_reason = {
            "observed_decode_tps": "同设备、同上下文的已有解码观测",
            "observed_upper_context_proxy": "同设备、更长上下文的解码观测作为速度参考",
            "heuristic_active_parameters": "活跃参数量估算（尚无可用的速度观测）",
        }[result["speed_basis"]]
        choice_reason = f"综合模型能力、{speed_reason}和上下文容量。"
    else:
        result["ranking_provenance"] = "heuristic_subjective_product_ordering"
        choice_reason = "综合模型能力和上下文容量。"
    reasons = ["按估算内存余量筛选后，" + choice_reason,
               "模型能力排序是主观估计，实际 Agent 表现仍需验证。"]
    if result["context_k"] < context_k:
        cause = ("为输出预留空间" if result["model"]["max_context_tokens"] <
                 context_k * 1024 + result["reserved_output_tokens"] else "按估算内存余量")
        reasons.append(f"{cause}，上下文从要求的 {context_k}K 调整为 {result['context_k']}K。")
    result["status"] = "recommended"
    result["reason"] = " ".join(reasons)
    if selector in {"mlp", "auto"}:
        try:
            # The shipped network predicts throughput, not task quality. Do not
            # silently reinterpret quality, efficiency or context objectives.
            if preference != "speed" or _model_context_preference(model_context) != "balanced" or not chip:
                raise ValueError("mlp_requires_speed_balanced_host_and_artifact")
            from selector_mlp import rank
            selected, predicted_tps = rank(deepcopy(feasible), memory_gb,
                {"os": os_name, "arch": arch, "chip": chip, "memory_gb": memory_gb},
                mlp_path if mlp_path is not None else MLP_PATH)
            # Resolve to the canonical admitted candidate. A corrupt/plugin
            # result must never inject a new model, context or resource policy.
            admitted = next((o for o in feasible if o == selected), None)
            if admitted is None or type(predicted_tps) not in (int, float) or not math.isfinite(predicted_tps) or predicted_tps <= 0:
                raise ValueError("mlp_output_not_admitted")
            selected = admitted
            result = dict(selected, status="recommended", selector_used="mlp", selector_requested="mlp",
                          ranking_provenance="experimental_mlp_predicted_decode_tps",
                          mlp_predicted_decode_tps=predicted_tps,
                          reason="实验 MLP 按预测解码吞吐量排序；效果未独立验证，内存仍为估算准入。")
            if result["context_k"] < context_k:
                result["reason"] += f" 上下文从 {context_k}K 调整为 {result['context_k']}K。"
        except Exception:
            result = dict(result, selector_requested=selector, selector_used="rules",
                          selector_fallback="mlp_unavailable_invalid_or_out_of_scope")
        result["selector_requested"] = selector
        if selector == "auto" and result.get("selector_used") == "rules":
            result["selector_fallback_reason"] = ("task_quality_calibration_missing" if preference != "speed"
                else "unsupported_context_objective" if _model_context_preference(model_context) != "balanced"
                else "artifact_or_hardware_scope_or_prediction_invalid")
    return result


def recommend_primary(*args, local_allowed=True, **kwargs):
    """Product entry point: attempt the bundled MLP inside its declared scope.

    Returns a proposal only. Download/load, source choice, cloud consent and
    execution permissions remain with their existing host controllers.
    """
    if type(local_allowed) is not bool:
        raise ValueError("local_allowed must be a host boolean")
    if not local_allowed:
        return None
    kwargs.setdefault("selector", "auto")
    return recommend(*args, **kwargs)
