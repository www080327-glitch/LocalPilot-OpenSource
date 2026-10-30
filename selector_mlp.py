"""Experimental two-affine-layer throughput regressor; standard library only."""

import json
import math
from pathlib import Path
import random
from statistics import mean, pstdev


FEATURES = ["memory_budget_gib", "artifact_gb_catalog", "parameters_b", "active_parameters_b", "context_k"]


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def features(model, context_k, memory_gb):
    values = [memory_gb - 3.0, model["artifact_gb"], model["parameters_b"],
              model["active_parameters_b"], context_k]
    if not all(finite(v) and v > 0 for v in values):
        raise ValueError("invalid_mlp_features")
    return values


def model_identity(model):
    return [model[k] for k in ("repo_id", "revision", "quantization", "backend")]


def forward(network, values):
    x = [(v - m) / s for v, m, s in zip(values, network["mean"], network["scale"])]
    h = [math.tanh(sum(w * v for w, v in zip(row, x)) + b)
         for row, b in zip(network["w1"], network["b1"])]
    return sum(w * v for w, v in zip(network["w2"], h)) + network["b2"], x, h


def train(samples, *, seed=17, epochs=400, hidden_units=8, l2=0.0):
    """Fit X -> tanh(8) -> log(decode TPS); no evaluation rows or rule labels."""
    if len(samples) < 2 or not 1 <= epochs <= 10000:
        raise ValueError("insufficient_training_data_or_invalid_epochs")
    if (type(hidden_units) is not int or not 1 <= hidden_units <= 32
            or not finite(l2) or not 0 <= l2 <= 10):
        raise ValueError("invalid_mlp_capacity_or_regularization")
    xs, ys = zip(*samples)
    if any(len(x) != len(FEATURES) or not all(finite(v) for v in x) for x in xs) or not all(finite(y) for y in ys):
        raise ValueError("invalid_training_data")
    rng = random.Random(seed)
    network = {"mean": [mean(c) for c in zip(*xs)], "scale": [pstdev(c) or 1.0 for c in zip(*xs)],
               "target_mean": mean(ys), "target_scale": pstdev(ys) or 1.0,
               "w1": [[rng.uniform(-0.2, 0.2) for _ in FEATURES] for _ in range(hidden_units)],
               "b1": [0.0] * hidden_units, "w2": [rng.uniform(-0.2, 0.2) for _ in range(hidden_units)], "b2": 0.0}
    for _ in range(epochs):
        dw1, db1, dw2, db2 = [[0.0] * len(FEATURES) for _ in range(hidden_units)], [0.0] * hidden_units, [0.0] * hidden_units, 0.0
        for values, target in samples:
            prediction, x, h = forward(network, values)
            error = prediction - (target - network["target_mean"]) / network["target_scale"]
            gradient = 2 * error / len(samples)
            db2 += gradient
            for j in range(hidden_units):
                dw2[j] += gradient * h[j]
                hidden = gradient * network["w2"][j] * (1 - h[j] ** 2)
                db1[j] += hidden
                for k in range(len(FEATURES)):
                    dw1[j][k] += hidden * x[k]
        for j in range(hidden_units):
            network["w2"][j] -= 0.03 * (dw2[j] + l2 * network["w2"][j])
            network["b1"][j] -= 0.03 * db1[j]
            for k in range(len(FEATURES)):
                network["w1"][j][k] -= 0.03 * (dw1[j][k] + l2 * network["w1"][j][k])
        network["b2"] -= 0.03 * db2
    return network


def load(path):
    if Path(path).stat().st_size > 1_000_000:
        raise ValueError("mlp_artifact_too_large")
    artifact = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(artifact, dict):
        raise ValueError("invalid_mlp_artifact")
    if (artifact["schema_version"] != 1 or artifact["features"] != FEATURES
            or artifact["target"] != "log_decode_tps" or artifact["performance_validated"] is not False):
        raise ValueError("unsupported_mlp_artifact")
    n = artifact["network"]
    if (not isinstance(n, dict) or not isinstance(n.get("w1"), list)
            or not isinstance(artifact.get("hardware_scope"), list)
            or not isinstance(artifact.get("model_scope"), list)
            or not isinstance(artifact.get("context_range"), list)
            or len(artifact["context_range"]) != 2
            or any(type(v) is not int or v <= 0 for v in artifact["context_range"])
            or artifact["context_range"][0] > artifact["context_range"][1]):
        raise ValueError("invalid_mlp_scope")
    width = len(n["w1"])
    vectors = [(n["mean"], len(FEATURES)), (n["scale"], len(FEATURES)),
               (n["b1"], width), (n["w2"], width), *[(row, len(FEATURES)) for row in n["w1"]]]
    if (not 1 <= width <= 64 or any(not isinstance(v, list) or len(v) != size or not all(finite(x) for x in v) for v, size in vectors)
            or not all(s > 0 for s in n["scale"]) or not finite(n["b2"])
            or not finite(n["target_mean"]) or not finite(n["target_scale"]) or n["target_scale"] <= 0):
        raise ValueError("invalid_mlp_network")
    return artifact


def rank(options, memory_gb, host, path):
    artifact = load(path)
    if host not in artifact["hardware_scope"]:
        raise ValueError("mlp_hardware_out_of_scope")
    scored = []
    for option in options:
        if (model_identity(option["model"]) not in artifact["model_scope"]
                or not artifact["context_range"][0] <= option["context_k"] <= artifact["context_range"][1]):
            raise ValueError("mlp_candidate_out_of_scope")
        y, _, _ = forward(artifact["network"], features(option["model"], option["context_k"], memory_gb))
        log_tps = y * artifact["network"]["target_scale"] + artifact["network"]["target_mean"]
        if not finite(log_tps) or abs(log_tps) > 50:
            raise ValueError("invalid_mlp_prediction")
        scored.append((log_tps, option))
    score, selected = max(scored, key=lambda item: item[0])
    return selected, math.exp(score)
