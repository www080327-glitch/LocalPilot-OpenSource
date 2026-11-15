"""Exercise the importer with on-disk Harbor-shaped fixtures, never model scores."""

from copy import deepcopy
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from scripts.public_agent_eval import HARBOR_COMMIT, HARBOR_VERSION, audit, freeze, read_json, read_study


class PublicAgentEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repository = self.root / "upstream"
        self.repository.mkdir()
        for name in ("alpha", "beta"):
            task = self.repository / name
            (task / "tests").mkdir(parents=True)
            (task / "task.toml").write_text('version = "1.0"\n')
            (task / "instruction.md").write_text("Parser fixture, not a model capability task.\n")
            (task / "tests" / "test.sh").write_text("#!/bin/sh\nexit 0\n")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
        self.spec = {"benchmark": "fixture-not-a-benchmark@1", "repository_url": "https://example.invalid/fixture.git",
                     "purpose": "smoke", "repeats": 2,
                     "arms": [{"id": name, "revision": "unit-test-fixture",
                               "agent": {"name": agent, "model_name": "fixture/model", "kwargs": {}}}
                              for name, agent in (("localpilot", "codex"), ("reference", "mini-swe-agent"))],
                     "comparison": {"candidate": "localpilot", "baseline": "reference"}}
        self.spec_path = self.root / "spec.json"
        self.spec_path.write_text(json.dumps(self.spec))
        self.study_dir = self.root / "frozen"
        self.study = freeze(self.spec_path, self.repository, self.study_dir)
        self.paths = {}

    def git(self, *arguments):
        return subprocess.check_output(["git", "-C", str(self.repository), *arguments], text=True).strip()

    def populate(self):
        start = datetime.fromisoformat(self.study["frozen_at"]) + timedelta(seconds=1)
        end = start + timedelta(seconds=2)
        for job in self.study["jobs"]:
            directory = self.study_dir / "runs" / job["name"]
            directory.mkdir()
            job_config = read_json(self.study_dir / "configs" / f"{job['name']}.json")
            # Pydantic adds defaults to the configuration Harbor copies into each job.
            job_config["agents"][0]["skills"] = []
            (directory / "config.json").write_text(json.dumps(job_config))
            (directory / "result.json").write_text(json.dumps({"n_total_trials": 2,
                  "finished_at": end.isoformat(), "stats": {"n_retries": 0}}))
            for task in job_config["tasks"]:
                name = Path(task["path"]).name
                path = directory / f"{name}__{uuid4().hex[:8]}" / "result.json"
                path.parent.mkdir()
                raw = {"schema_version": 1, "id": str(uuid4()), "trial_name": path.parent.name,
                       "task_name": name, "task_checksum": "fixture-checksum", "trial_uri": str(path.parent),
                       "task_id": deepcopy(task), "config": {"task": deepcopy(task),
                           "agent": deepcopy(job_config["agents"][0]), "environment": {"type": "docker"},
                           "verifier": {"disable": False}, "timeout_multiplier": 1.0},
                       "agent_info": {"name": job_config["agents"][0]["name"], "version": "fixture",
                                      "model_info": {"name": "model", "provider": "fixture"}},
                       "started_at": start.isoformat(), "finished_at": end.isoformat(),
                       "agent_execution": {"started_at": start.isoformat(), "finished_at": end.isoformat()},
                       "verifier": {"started_at": start.isoformat(), "finished_at": end.isoformat()},
                       "agent_result": {"n_input_tokens": 10, "n_cache_tokens": 4, "n_output_tokens": 2, "cost_usd": None},
                       "verifier_result": {"rewards": {"reward": 1}}, "exception_info": None, "reward_valid": True}
                path.write_text(json.dumps(raw))
                self.paths[job["arm"], job["repeat"], name] = path

    def edit(self, key, mutate):
        path = self.paths[key]
        raw = read_json(path)
        mutate(raw)
        path.write_text(json.dumps(raw))

    def test_freeze_hashes_tracked_tasks_and_generates_no_retry_jobs(self):
        self.assertEqual(read_study(self.study_dir), self.study)
        self.assertEqual(self.study["benchmark_commit"], self.git("rev-parse", "HEAD"))
        self.assertEqual(self.study["selection"], "all_tasks_in_checkout_prefix")
        self.assertEqual(len(self.study["jobs"]), 4)
        self.assertEqual(len(self.study["tasks"][0]["files"]), 3)
        config = read_json(next((self.study_dir / "configs").glob("*.json")))
        self.assertEqual(config["n_attempts"], 1)
        self.assertEqual(config["retry"]["max_retries"], 0)
        self.assertEqual(config["tasks"][0]["git_commit_id"], self.study["benchmark_commit"])

    def test_empty_run_keeps_all_planned_cells_and_blocks_comparison(self):
        result = audit(self.study_dir)
        self.assertFalse(result["audit_complete"])
        self.assertEqual(len(result["trials"]), 8)
        self.assertEqual(result["arms"]["localpilot"]["statuses"], {"NOT_RUN": 4})
        self.assertTrue(result["arms"]["localpilot"]["rate_is_lower_bound"])
        self.assertEqual(result["comparison"]["status"], "BLOCKED_INCOMPLETE_AUDIT")

    def test_complete_fixture_is_descriptive_and_cost_missing_is_not_zero(self):
        self.populate()
        result = audit(self.study_dir)
        self.assertTrue(result["audit_complete"])
        self.assertFalse(result["official_leaderboard_result"])
        self.assertEqual(result["comparison"]["task_ties"], 2)
        self.assertFalse(result["comparison"]["noninferiority_established"])
        self.assertIsNone(result["arms"]["localpilot"]["cost_usd"]["known_sum"])
        self.assertEqual(result["arms"]["localpilot"]["cost_usd"]["missing_trials"], 4)
        self.assertEqual(result["arms"]["localpilot"]["n_input_tokens"]["known_sum"], 40)

    def test_exception_after_reward_one_counts_failure_and_is_retained(self):
        self.populate()
        self.edit(("localpilot", 1, "alpha"), lambda r: r.update(exception_info={"exception_type": "AgentTimeoutError"}))
        self.edit(("localpilot", 2, "alpha"), lambda r: r.update(verifier_result={"rewards": {"reward": 0}}))
        result = audit(self.study_dir)
        self.assertTrue(result["audit_complete"])
        self.assertEqual(result["arms"]["localpilot"]["strict_successes"], 2)
        self.assertEqual(result["comparison"]["mean_difference"], -0.5)
        self.assertEqual(result["comparison"]["task_losses"], 1)
        error = next(r for r in result["trials"] if r["status"] == "ERROR")
        self.assertEqual(error["verifier_reward"], 1)
        self.assertFalse(error["strict_success"])

    def test_official_nullable_reward_retains_errors_and_incomplete_trials(self):
        self.populate()
        self.edit(("localpilot", 1, "alpha"), lambda r: r.update(
            verifier_result={"rewards": None}, exception_info={"exception_type": "AgentTimeoutError"}))
        result = audit(self.study_dir)
        self.assertTrue(result["audit_complete"])
        self.assertEqual(result["arms"]["localpilot"]["statuses"]["ERROR"], 1)
        self.edit(("localpilot", 2, "alpha"), lambda r: r.update(verifier_result={"rewards": {}}))
        result = audit(self.study_dir)
        self.assertFalse(result["audit_complete"])
        self.assertEqual(result["arms"]["localpilot"]["statuses"]["INCOMPLETE"], 1)

    def test_duplicate_never_selects_the_successful_attempt(self):
        self.populate()
        original = self.paths["localpilot", 1, "alpha"]
        duplicate = original.parent.parent / "alpha__extra" / "result.json"
        duplicate.parent.mkdir()
        raw = read_json(original)
        raw["id"] = str(uuid4())
        raw["trial_name"] = "alpha__extra"
        raw["verifier_result"]["rewards"]["reward"] = 0
        duplicate.write_text(json.dumps(raw))
        result = audit(self.study_dir)
        self.assertFalse(result["audit_complete"])
        duplicate_row = next(r for r in result["trials"] if r["status"] == "DUPLICATE")
        self.assertEqual(len(duplicate_row["sources"]), 2)
        self.assertEqual(result["arms"]["localpilot"]["planned_trials"], 4)

    def test_missing_trial_remains_in_denominator(self):
        self.populate()
        self.paths["localpilot", 1, "alpha"].unlink()
        result = audit(self.study_dir)
        self.assertEqual(result["arms"]["localpilot"]["strict_success_rate_all_planned"], 0.75)
        self.assertFalse(result["audit_complete"])

    def test_binary_reward_type_and_nonfinite_values_are_not_coerced(self):
        self.populate()
        for reward in ("1", True, 0.5, float("nan")):
            with self.subTest(reward=reward):
                self.edit(("localpilot", 1, "alpha"), lambda r: r.update(verifier_result={"rewards": {"reward": reward}}))
                result = audit(self.study_dir)
                self.assertFalse(result["audit_complete"])
                self.assertTrue(result["issues"])

    def test_frozen_config_and_verifier_modifications_are_rejected(self):
        self.populate()
        changes = [lambda r: r["config"]["task"].update(git_commit_id="f" * 40),
                   lambda r: r["config"]["agent"].update(model_name="another/model"),
                   lambda r: r["config"]["verifier"].update(disable=True),
                   lambda r: r["config"].update(source_trial={"action": "regrade"}),
                   lambda r: r.update(step_results=[{"step_name": "unexpected"}])]
        path = self.paths["localpilot", 1, "alpha"]
        original = path.read_text()
        for change in changes:
            with self.subTest(change=change):
                path.write_text(original)
                self.edit(("localpilot", 1, "alpha"), change)
                self.assertFalse(audit(self.study_dir)["audit_complete"])

    def test_reused_trial_id_is_detected_across_repeats(self):
        self.populate()
        first = read_json(self.paths["localpilot", 1, "alpha"])["id"]
        self.edit(("localpilot", 2, "alpha"), lambda r: r.update(id=first))
        result = audit(self.study_dir)
        self.assertFalse(result["audit_complete"])
        self.assertTrue(any("reused" in i.get("reason", "") for i in result["issues"]))

    def test_post_freeze_budget_and_context_overrides_are_not_defaults(self):
        self.populate()
        changes = [lambda r: r["config"]["agent"].update(kwargs={"max_steps": 10000}),
                   lambda r: r["config"]["agent"].update(override_timeout_sec=99999),
                   lambda r: r["config"]["agent"].update(load_trajectory="earlier-success.jsonl"),
                   lambda r: r["config"].update(agent_timeout_multiplier=10),
                   lambda r: r["config"]["verifier"].update(override_timeout_sec=99999),
                   lambda r: r["config"]["environment"].update(override_gpus=8)]
        path = self.paths["localpilot", 1, "alpha"]
        original = path.read_text()
        for change in changes:
            with self.subTest(change=change):
                path.write_text(original)
                self.edit(("localpilot", 1, "alpha"), change)
                self.assertFalse(audit(self.study_dir)["audit_complete"])

    def test_unexpected_task_is_reported_and_expected_task_is_still_missing(self):
        self.populate()
        self.edit(("localpilot", 1, "alpha"), lambda r: r.update(task_name="cherry-picked-task"))
        result = audit(self.study_dir)
        self.assertFalse(result["audit_complete"])
        self.assertEqual(result["arms"]["localpilot"]["statuses"]["NOT_RUN"], 1)

    def test_harbor_job_retry_history_and_actual_config_are_checked(self):
        self.populate()
        job_dir = self.paths["localpilot", 1, "alpha"].parent.parent
        aggregate = read_json(job_dir / "result.json")
        aggregate["stats"]["n_retries"] = 1
        (job_dir / "result.json").write_text(json.dumps(aggregate))
        self.assertFalse(audit(self.study_dir)["audit_complete"])
        aggregate["stats"]["n_retries"] = 0
        (job_dir / "result.json").write_text(json.dumps(aggregate))
        config = read_json(job_dir / "config.json")
        config["n_attempts"] = 4
        (job_dir / "config.json").write_text(json.dumps(config))
        self.assertFalse(audit(self.study_dir)["audit_complete"])

    def test_incomplete_execution_cannot_pass_on_reward_alone(self):
        self.populate()
        self.edit(("localpilot", 1, "alpha"), lambda r: r.update(agent_execution={"finished_at": None}))
        result = audit(self.study_dir)
        self.assertFalse(result["audit_complete"])
        self.assertEqual(result["arms"]["localpilot"]["statuses"]["INCOMPLETE"], 1)

    def test_a_trial_before_freeze_is_not_preregistered(self):
        self.populate()
        self.edit(("localpilot", 1, "alpha"), lambda r: r.update(started_at="2020-01-01T00:00:00+00:00"))
        self.assertFalse(audit(self.study_dir)["audit_complete"])

    def test_frozen_files_are_not_silently_overwritten_or_modified(self):
        with self.assertRaises(FileExistsError):
            freeze(self.spec_path, self.repository, self.study_dir)
        config = next((self.study_dir / "configs").glob("*.json"))
        raw = read_json(config)
        raw["n_attempts"] = 10
        config.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError, "configuration changed"):
            audit(self.study_dir)

    def test_dirty_tasks_and_duplicate_selection_refuse_freeze(self):
        (self.repository / "alpha" / "instruction.md").write_text("changed")
        with self.assertRaisesRegex(ValueError, "must be clean"):
            freeze(self.spec_path, self.repository, self.root / "dirty")
        self.spec["tasks"] = ["alpha", "alpha"]
        self.spec_path.write_text(json.dumps(self.spec))
        with self.assertRaisesRegex(ValueError, "Duplicate task"):
            freeze(self.spec_path, self.repository, self.root / "duplicate")

    def test_subset_label_and_multistep_rejection_are_explicit(self):
        self.spec["tasks"] = ["alpha"]
        self.spec_path.write_text(json.dumps(self.spec))
        subset = freeze(self.spec_path, self.repository, self.root / "subset")
        self.assertEqual(subset["selection"], "preregistered_subset")
        (self.repository / "alpha" / "task.toml").write_text('[[steps]]\nname = "step1"\n')
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "multistep")
        with self.assertRaisesRegex(ValueError, "Only single-step"):
            freeze(self.spec_path, self.repository, self.root / "multistep")

    def test_cli_writes_an_incomplete_report_and_exits_two(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "public_agent_eval.py"
        output = self.root / "audit.json"
        result = subprocess.run([sys.executable, str(script), "audit", "--study", str(self.study_dir),
                                 "--output", str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(read_json(output)["audit_complete"])
        self.assertEqual(len(read_json(output)["trials"]), 8)

    @unittest.skipUnless(os.environ.get("LOCALPILOT_HARBOR_CONTRACT") == "1",
                         "Optional contract check requires the pinned Harbor checkout and schema dependencies")
    def test_official_harbor_schema_roundtrip(self):
        import importlib.metadata
        import inspect
        from harbor.models.job.config import JobConfig
        from harbor.models.job.result import JobResult, JobStats
        from harbor.models.trial.result import TrialResult

        source = Path(inspect.getfile(JobConfig)).resolve().parents[4]
        commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        self.assertEqual(commit, HARBOR_COMMIT)
        self.assertEqual(importlib.metadata.version("harbor"), HARBOR_VERSION)
        self.populate()
        for job in self.study["jobs"]:
            directory = self.study_dir / "runs" / job["name"]
            config = JobConfig.model_validate(read_json(directory / "config.json"))
            (directory / "config.json").write_text(config.model_dump_json(indent=2))
            trials = []
            for path in directory.glob("*/result.json"):
                trial = TrialResult.model_validate(read_json(path))
                trials.append(trial)
                path.write_text(trial.model_dump_json(indent=2))
            result = JobResult(id=uuid4(), started_at=trials[0].started_at, finished_at=trials[0].finished_at,
                               n_total_trials=2, stats=JobStats.from_trial_results(trials, n_total_trials=2))
            (directory / "result.json").write_text(result.model_dump_json(indent=2))
        report = audit(self.study_dir)
        self.assertTrue(report["audit_complete"], report["issues"])
        self.assertEqual(report["comparison"]["task_ties"], 2)


if __name__ == "__main__":
    unittest.main()
