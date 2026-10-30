"""Prototype checks; test mutations are fixtures, never extra benchmark evidence."""

from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
from statistics import mean
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from benchmarks import mlx_context
from benchmarks.selector_eval import audit, evaluate, group, hardware_group, main, model_for, prototype, split
from recommender import feasible_candidates, recommend
from selector_mlp import features, forward, rank


class SelectorMLPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = json.loads(Path("benchmarks/mlx_profiles.json").read_text(encoding="utf-8"))
        cls.artifact, cls.training, cls.evaluation, cls.summary = prototype(cls.profile)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.model_path = self.root / "model.json"
        self.model_path.write_text(json.dumps(self.artifact), encoding="utf-8")

    def select(self, **extra):
        return recommend(64, "speed", 32, chip="Apple M1 Max", selector="mlp", mlp_path=self.model_path, **extra)

    def test_216_default_rule_results_match_pre_change_snapshot(self):
        rows = [recommend(ram, pref, ctx, trade, chip="Apple M1 Max")
                for ram in (8, 16, 24, 32, 48, 64)
                for pref in ("quality", "speed", "efficiency", "balanced")
                for ctx in (32, 128, 256) for trade in ("balanced", "capability_first", "context_first")]
        self.assertEqual(hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                         "8bde30039b4801a03b4305f3c3c6ded9cd39fbcfdd4506d8869cd803db25fa5f")

    def test_mlp_only_receives_admitted_candidates_and_respects_output_headroom(self):
        with patch("selector_mlp.rank", wraps=rank) as ranking:
            result = self.select()
        self.assertEqual(result["selector_used"], "mlp")
        options = ranking.call_args.args[0]
        self.assertIn(result["model_id"], [o["model_id"] for o in options])
        for ram in (8, 16, 32, 64):
            options = feasible_candidates(ram, 128)
            for option in options:
                self.assertLessEqual(option["admission_envelope_gib"] + option["system_reserve_gb"], ram)
                self.assertLessEqual(option["context_length"] + option["reserved_output_tokens"], option["model"]["max_context_tokens"])
        self.assertEqual(feasible_candidates(1, 128), [])
        with patch("selector_mlp.rank", side_effect=AssertionError("must not run")):
            self.assertIsNone(recommend(1, "speed", selector="mlp", mlp_path=self.model_path))
            self.assertEqual(recommend(64, os_name="Linux", selector="mlp")["status"], "unsupported")

    def test_official_minimum_context_and_excluded_models_remain_hard_constraints(self):
        with patch("selector_mlp.rank", wraps=rank) as ranking:
            result = recommend(64, "speed", 128, chip="Apple M1 Max", selector="mlp", mlp_path=self.model_path,
                               minimum_context_k=128, excluded_size_classes=("4B",))
        self.assertEqual(result["selector_used"], "mlp")
        self.assertGreaterEqual(result["context_k"], 128)
        self.assertNotEqual(result["model"]["parameters_b"], 4)
        self.assertTrue(all(o["context_k"] >= 128 and o["model"]["parameters_b"] != 4
                            for o in ranking.call_args.args[0]))
        with patch("selector_mlp.rank", side_effect=AssertionError("must not rank rejected options")):
            self.assertIsNone(recommend(64, "speed", 256, chip="Apple M1 Max", selector="mlp",
                                        mlp_path=self.model_path, minimum_context_k=256))

    def test_feature_and_forward_math(self):
        self.assertEqual(features({"artifact_gb": 2.0, "parameters_b": 4, "active_parameters_b": 3}, 32, 64),
                         [61.0, 2.0, 4, 3, 32])
        network = {"mean": [0] * 5, "scale": [1] * 5, "w1": [[0] * 5], "b1": [0], "w2": [2], "b2": 0.5}
        score, _, _ = forward(network, [1, 2, 3, 4, 5])
        self.assertEqual(score, 0.5)
        with self.assertRaises(ValueError):
            features({"artifact_gb": float("nan"), "parameters_b": 4, "active_parameters_b": 3}, 32, 64)

    def test_missing_invalid_or_nonfinite_model_safely_returns_unchanged_rule_choice(self):
        baseline = recommend(64, "speed", 32, chip="Apple M1 Max")
        invalid = ["broken", [], {**self.artifact, "context_range": []}]
        for field, value in [("scale", [0] * 5), ("w2", [float("nan")] * 8), ("w1", [[]]), ("b2", float("inf"))]:
            artifact = deepcopy(self.artifact)
            artifact["network"][field] = value
            invalid.append(artifact)
        for artifact in invalid:
            self.model_path.write_text(json.dumps(artifact), encoding="utf-8")
            result = self.select()
            self.assertEqual(result.pop("selector_used"), "rules")
            result.pop("selector_requested")
            result.pop("selector_fallback")
            self.assertEqual(result, baseline)
        self.model_path.unlink()
        self.assertEqual(self.select()["selector_used"], "rules")

    def test_unavailable_mlp_module_falls_back_to_unchanged_rules(self):
        baseline = recommend(64, "speed", 32, chip="Apple M1 Max")
        for module in (None, ModuleType("selector_mlp")):
            with self.subTest(module_missing=module is None), patch.dict("sys.modules", {"selector_mlp": module}):
                self.assertEqual(recommend(64, "speed", 32, chip="Apple M1 Max"), baseline)
                result = self.select()
                self.assertEqual(result.pop("selector_requested"), "mlp")
                self.assertEqual(result.pop("selector_used"), "rules")
                self.assertEqual(result.pop("selector_fallback"), "mlp_unavailable_invalid_or_out_of_scope")
                self.assertEqual(result, baseline)

    def test_unknown_hardware_model_features_and_non_speed_preferences_fall_back(self):
        self.assertEqual(recommend(64, "speed", chip="other", selector="mlp", mlp_path=self.model_path)["selector_used"], "rules")
        self.assertEqual(recommend(64, "quality", chip="Apple M1 Max", selector="mlp", mlp_path=self.model_path)["selector_used"], "rules")
        self.assertEqual(recommend(64, "speed", selector="mlp", mlp_path=self.model_path)["selector_used"], "rules")
        import recommender
        models = deepcopy(recommender.MODELS)
        models[0].pop("active_parameters_b")
        with patch.object(recommender, "MODELS", models):
            self.assertEqual(self.select()["selector_used"], "rules")

    def test_audit_retains_failures_and_reports_incomplete_identity(self):
        rows, summary = audit(self.profile)
        self.assertEqual(len(rows), 33)
        self.assertEqual(summary["retained_failure_count"], 17)
        self.assertEqual(len(summary["hardware"]), 1)
        self.assertEqual(summary["unknown_identity_fields"]["cache_mode"], 33)
        malformed = deepcopy(self.profile)
        malformed["measurements"][0]["metrics"]["decode_tps_median"] = -1
        malformed["measurements"][1]["measurement_id"] = []
        valid, result = audit(malformed)
        self.assertEqual(len(valid), 31)
        self.assertEqual(len(result["invalid_rows"]), 2)
        self.assertEqual(result["retained_failure_count"], 17)
        with self.assertRaisesRegex(ValueError, "schema_2"):
            audit({"schema_version": 1, "measurements": []})

    def test_group_split_and_normalization_use_only_training_rows(self):
        self.assertFalse({group(r) for r in self.training} & {group(r) for r in self.evaluation})
        self.assertFalse(set(self.artifact["training_ids"]) & set(self.artifact["evaluation_ids"]))
        self.assertEqual(self.artifact["network"]["mean"], [mean(c) for c in zip(*[
            features(model_for(r), r["identity"]["context_k"], r["identity"]["hardware"]["memory_gb"])
            for r in self.training])])
        altered = deepcopy(self.profile)
        for row in altered["measurements"]:
            if row["measurement_id"] in self.artifact["evaluation_ids"]:
                row["metrics"]["decode_tps_median"] *= 100
        altered_model, _, _, _ = prototype(altered)
        self.assertEqual(altered_model["network"], self.artifact["network"])

    def test_multiple_hardware_groups_never_cross_the_holdout_split(self):
        rows = deepcopy(self.training[:4])
        other = deepcopy(rows)
        for row in other:
            row["identity"]["hardware"]["chip"] = "synthetic-other-device"
        training, evaluation = split(rows + other, 17)
        self.assertFalse({hardware_group(r) for r in training} & {hardware_group(r) for r in evaluation})
        self.assertTrue(training and evaluation)

    def test_evaluation_is_repeatable_and_reports_actual_metrics_and_limits(self):
        first = evaluate(self.profile, self.model_path, self.artifact, self.training, self.evaluation, self.summary)
        second = evaluate(self.profile, self.model_path, self.artifact, self.training, self.evaluation, self.summary)
        self.assertEqual(first, second)
        self.assertFalse(first["independent_effectiveness_validated"])
        self.assertEqual(first["split"], "single_hardware_context_group_holdout")
        self.assertEqual(first["task_quality"]["status"], "not_available")
        self.assertEqual(first["training_rows"] + first["evaluation_rows"], 33)
        for case in first["cases"]:
            candidate_keys = {(c["model_id"], c["context_k"]) for c in case["same_feasible_candidates"]}
            for method in ("rules", "mlp"):
                choice = case[method]
                if choice:
                    self.assertIn((choice["model_id"], choice["context_k"]), candidate_keys)
                    self.assertTrue(choice["fits_estimated_budget"])
                    for observation in choice["observations"]:
                        self.assertIn("decode_tps_median", observation["metrics"])
                        self.assertIn("ttft_seconds_median", observation["metrics"])
        self.assertTrue(first["limitations"])

    def test_cli_is_reproducible_and_never_overwrites_inputs_or_outputs(self):
        reports, models = [], []
        for index in range(2):
            model, report = self.root / f"m{index}.json", self.root / f"r{index}.json"
            with redirect_stdout(io.StringIO()):
                main(["--output-model", str(model), "--output-report", str(report)])
            models.append(model.read_bytes())
            reports.append(report.read_bytes())
        self.assertEqual(models[0], models[1])
        self.assertEqual(reports[0], reports[1])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--output-model", str(model), "--output-report", str(report)])
        self.assertEqual(report.read_bytes(), reports[-1])


class RepeatCollectorTests(unittest.TestCase):
    def test_output_budget_reaches_worker_command(self):
        with patch.object(mlx_context, "_existing_snapshot", return_value="cached-model"), \
             patch.object(mlx_context.shutil, "disk_usage", return_value=Mock(free=100 * 1024**3)), \
             patch.object(mlx_context, "_software_metadata", return_value={}), \
             patch.object(mlx_context, "_power_metadata", return_value={}), \
             patch.object(mlx_context, "_system_memory", return_value={}), \
             patch.object(mlx_context.subprocess, "Popen") as popen:
            popen.return_value.poll.return_value = 0
            popen.return_value.returncode = 0
            popen.return_value.communicate.return_value = ('{"status":"ok"}', '')
            result = mlx_context._run_one(mlx_context.MODELS[0], 32, 1, {"max_new_tokens": 128})
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("--max-new-tokens") + 1], "128")
        self.assertEqual(result["max_new_tokens"], 128)

    def test_repeats_keep_failed_rows_and_record_output_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new.jsonl"
            def run(model, context, repeat, metadata, **kwargs):
                return {"model_id": model["id"], "context_k": context, "repeat": repeat,
                        "max_new_tokens": metadata["max_new_tokens"], "status": "failed" if repeat == 1 else "ok"}
            with patch.object(mlx_context, "_hardware_metadata", return_value={"platform_status": "supported"}), \
                 patch.object(mlx_context, "_abort_reason", return_value=None), \
                 patch.object(mlx_context, "_run_one", side_effect=run), redirect_stdout(io.StringIO()):
                self.assertEqual(mlx_context.main(["--model", "qwen3.5-4b", "--model", "qwen3.6-35b-a3b",
                    "--context-k", "32", "--repeat-small", "2", "--repeat-large", "3",
                    "--max-new-tokens", "128", "--output", str(output)]), 0)
            rows = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual(len(rows), 5)
            self.assertEqual(sum(r["status"] == "failed" for r in rows), 2)
            self.assertTrue(all(r["max_new_tokens"] == 128 for r in rows))

    def test_invalid_repeat_counts_stop_before_hardware_probe(self):
        with patch.object(mlx_context, "_hardware_metadata", side_effect=AssertionError), \
             redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            mlx_context.main(["--repeat-small", "0"])


if __name__ == "__main__":
    unittest.main()
