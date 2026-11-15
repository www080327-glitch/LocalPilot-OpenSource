"""Freeze a public Harbor study, launch its jobs, and audit every planned trial.

This is a result adapter, not a question set, grader, or LocalPilot agent adapter.
Harbor owns task execution and verification. Python 3.12+ is required for Harbor.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib


HARBOR_COMMIT = "ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4"
HARBOR_VERSION = "0.26.0"
TERMINAL_STATUSES = {"PASS", "FAIL", "ERROR"}
USAGE_FIELDS = ("n_input_tokens", "n_cache_tokens", "n_output_tokens", "cost_usd")


def main():
    args = arguments()
    if args.command == "freeze":
        study = freeze(args.spec, args.repository, args.output, args.task_prefix)
        print(json.dumps({"study_sha256": study["sha256"], "jobs": len(study["jobs"])}))
        return 0
    if args.command == "run":
        return run_job(args.study, args.arm, args.repeat, args.harbor_repository, args.python)
    report = audit(args.study)
    write_json(args.output, report)
    print(json.dumps({"audit_complete": report["audit_complete"], "output": str(args.output)}))
    return 0 if report["audit_complete"] else 2


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("freeze", help="Create a new study before running any models")
    p.add_argument("--spec", type=Path, required=True)
    p.add_argument("--repository", type=Path, required=True, help="Clean benchmark Git checkout")
    p.add_argument("--task-prefix", default="", help="Relative task directory within that checkout")
    p.add_argument("--output", type=Path, required=True, help="New directory; never overwritten")
    p = commands.add_parser("run", help="Run one frozen arm/repeat with official Harbor")
    p.add_argument("--study", type=Path, required=True)
    p.add_argument("--arm", required=True)
    p.add_argument("--repeat", type=int, required=True)
    p.add_argument("--harbor-repository", type=Path, required=True)
    p.add_argument("--python", default=sys.executable, help="Python with the pinned Harbor dependencies installed")
    p = commands.add_parser("audit", help="Import raw Harbor trial result.json files, including failures")
    p.add_argument("--study", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read_json(path):
    def nonfinite(value):
        raise ValueError(f"Non-finite JSON number: {value}")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=nonfinite)


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def git(repository, *args):
    return subprocess.check_output(["git", "-C", str(repository), *args], text=True).strip()


def relative_path(value):
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise ValueError(f"Expected a nonempty repository-relative path: {value!r}")
    return Path(value).as_posix()


def validate_spec(spec):
    if not isinstance(spec, dict):
        raise ValueError("Study specification must be an object")
    for key in ("benchmark", "repository_url", "purpose", "repeats", "arms", "comparison"):
        if key not in spec:
            raise ValueError(f"Missing study field: {key}")
    if not isinstance(spec["benchmark"], str) or not spec["benchmark"]:
        raise ValueError("benchmark must name a versioned upstream release")
    if not isinstance(spec["repository_url"], str) or not spec["repository_url"].startswith("https://"):
        raise ValueError("repository_url must be the public HTTPS Git repository URL")
    if spec["purpose"] not in {"smoke", "evaluation"}:
        raise ValueError("purpose must be smoke or evaluation")
    if type(spec["repeats"]) is not int or spec["repeats"] < 1:
        raise ValueError("repeats must be a positive integer")
    if not isinstance(spec["arms"], list) or len(spec["arms"]) < 2:
        raise ValueError("At least a candidate and reference arm are required")
    names = set()
    for arm in spec["arms"]:
        if not isinstance(arm, dict) or not isinstance(arm.get("id"), str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", arm["id"]):
            raise ValueError("Each arm requires a simple lowercase id")
        if arm["id"] in names:
            raise ValueError(f"Duplicate arm: {arm['id']}")
        names.add(arm["id"])
        if not isinstance(arm.get("revision"), str) or not arm["revision"]:
            raise ValueError("Each arm must declare its source/package revision")
        agent = arm.get("agent")
        if not isinstance(agent, dict) or bool(agent.get("name")) == bool(agent.get("import_path")):
            raise ValueError("Each agent must specify exactly one name or import_path")
        if not isinstance(agent.get("model_name"), str) or not agent["model_name"]:
            raise ValueError("Each arm must name its model explicitly")
        if agent.get("env"):
            raise ValueError("Keep credentials out of study files; use the agent's environment-variable support")
        if spec["purpose"] == "evaluation" and agent.get("name") in {"oracle", "nop"}:
            raise ValueError("Oracle/nop can only be used for a smoke study")
    comparison = spec["comparison"]
    if not isinstance(comparison, dict) or any(comparison.get(k) not in names for k in ("candidate", "baseline")):
        raise ValueError("comparison must name registered candidate and baseline arms")
    if comparison["candidate"] == comparison["baseline"]:
        raise ValueError("Candidate and baseline must be different arms")
    tasks = spec.get("tasks")
    if tasks is not None:
        if not isinstance(tasks, list) or not tasks:
            raise ValueError("tasks must be a nonempty explicit list, or omitted for all discovered tasks")
        spec["tasks"] = [relative_path(value) for value in tasks]
        if len(set(spec["tasks"])) != len(spec["tasks"]):
            raise ValueError("Duplicate task paths in specification")
    execution = spec.setdefault("execution", {})
    if not isinstance(execution, dict) or set(execution) - {"n_concurrent_trials", "timeout_multiplier"}:
        raise ValueError("execution supports n_concurrent_trials and timeout_multiplier; environment is Docker")
    execution.setdefault("n_concurrent_trials", 1)
    execution.setdefault("timeout_multiplier", 1.0)
    if type(execution["n_concurrent_trials"]) is not int or execution["n_concurrent_trials"] < 1:
        raise ValueError("n_concurrent_trials must be a positive integer")
    number(execution["timeout_multiplier"], "timeout_multiplier", positive=True)
    cleanup = spec.get('owned_docker_cache_cleanup')
    if cleanup is not None:
        if (not isinstance(cleanup, dict) or set(cleanup) != {'plan_path','plan_sha256'}
                or not isinstance(cleanup['plan_path'],str) or not Path(cleanup['plan_path']).is_absolute()
                or not isinstance(cleanup['plan_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',cleanup['plan_sha256'])
                or hashlib.sha256(Path(cleanup['plan_path']).read_bytes()).hexdigest() != cleanup['plan_sha256']
                or execution['n_concurrent_trials'] != 1):
            raise ValueError('An exact reviewed Docker cache plan and sequential execution are required')


def task_snapshot(repository, path):
    task = repository / path
    config = tomllib.loads((task / "task.toml").read_text(encoding="utf-8"))
    if config.get("steps") or not (task / "instruction.md").is_file():
        raise ValueError(f"Only single-step Harbor tasks are supported: {path}")
    name = config.get("task", {}).get("name", task.name)
    if not isinstance(name, str) or not name:
        raise ValueError(f"Invalid task name: {path}")
    files = []
    for item in git(repository, "ls-files", "--", path).splitlines():
        source = repository / item
        contents = os.readlink(source).encode() if source.is_symlink() else source.read_bytes()
        files.append({"path": item, "sha256": hashlib.sha256(contents).hexdigest(),
                      "kind": "symlink" if source.is_symlink() else "file"})
    if not files:
        raise ValueError(f"Task is not tracked by Git: {path}")
    return {"name": name, "path": path, "files": files, "files_sha256": digest(files)}


def freeze(spec_path, repository, output, task_prefix=""):
    spec = read_json(spec_path)
    validate_spec(spec)
    repository = repository.resolve(strict=True)
    prefix = relative_path(task_prefix) if task_prefix else "."
    available = sorted(p.parent.relative_to(repository).as_posix()
                       for p in (repository / prefix).rglob("task.toml") if ".git" not in p.parts)
    selected = sorted(spec.get("tasks", available))
    if not selected or set(selected) - set(available):
        raise ValueError("Selected tasks are absent from the checkout/prefix, or no tasks were found")
    if git(repository, "status", "--porcelain", "--untracked-files=all", "--", *selected):
        raise ValueError("Selected benchmark task directories must be clean, including untracked files")
    tasks = [task_snapshot(repository, path) for path in selected]
    if len({t["name"] for t in tasks}) != len(tasks):
        raise ValueError("Selected task names must be unique for unambiguous result matching")
    commit = git(repository, "rev-parse", "HEAD")
    study = {"schema_version": 1, "frozen_at": datetime.now(timezone.utc).isoformat(),
             "harbor_commit": HARBOR_COMMIT, "harbor_version": HARBOR_VERSION,
             "specification": spec, "benchmark_commit": commit,
             "selection": "all_tasks_in_checkout_prefix" if selected == available else "preregistered_subset",
             "available_task_paths": available, "tasks": tasks}
    study_id = digest(study)[:12]
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for directory in ("configs", "runs", "launches"):
        (output / directory).mkdir()
    study["jobs"] = []
    for arm in spec["arms"]:
        for repeat in range(1, spec["repeats"] + 1):
            name = f"lp-{study_id}-{arm['id']}-r{repeat}"
            config = {"job_name": name, "jobs_dir": str(output / "runs"), "n_attempts": 1,
                      "retry": {"max_retries": 0}, "environment": {"type": "docker"},
                      "verifier": {"disable": False}, "agents": [arm["agent"]],
                      "tasks": [{"path": t["path"], "git_url": spec["repository_url"],
                                 "git_commit_id": commit, "source": spec["benchmark"]} for t in tasks],
                      **spec["execution"]}
            config_path = output / "configs" / f"{name}.json"
            write_json(config_path, config)
            study["jobs"].append({"name": name, "arm": arm["id"], "repeat": repeat,
                                  "config_sha256": digest(config)})
    study["sha256"] = digest(study)
    write_json(output / "study.json", study)
    return study


def read_study(directory):
    study = read_json(directory / "study.json")
    if not isinstance(study, dict) or study.get("schema_version") != 1:
        raise ValueError("Unsupported frozen study schema")
    content = {key: value for key, value in study.items() if key != "sha256"}
    if study.get("sha256") != digest(content):
        raise ValueError("Frozen study changed; create a new study instead of editing it")
    for job in study["jobs"]:
        config = read_json(directory / "configs" / f"{job['name']}.json")
        if digest(config) != job["config_sha256"]:
            raise ValueError(f"Frozen job configuration changed: {job['name']}")
    return study


def run_job(directory, arm, repeat, harbor_repository, python):
    directory = directory.resolve(strict=True)
    study = read_study(directory)
    matches = [j for j in study["jobs"] if j["arm"] == arm and j["repeat"] == repeat]
    if len(matches) != 1:
        raise ValueError("Arm/repeat is not part of this frozen study")
    job = matches[0]
    harbor_repository = harbor_repository.resolve(strict=True)
    if git(harbor_repository, "rev-parse", "HEAD") != study["harbor_commit"]:
        raise ValueError(f"Harbor checkout must be pinned to {study['harbor_commit']}")
    if git(harbor_repository, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Harbor checkout has tracked modifications")
    if (directory / "runs" / job["name"]).exists():
        raise ValueError("Job already has results; do not replace an attempt with a retry")
    entry = "import sys; sys.path.insert(0, sys.argv.pop(1)); from harbor.cli.main import app; app()"
    command = [python, "-c", entry, str(harbor_repository / "src"), "run", "--config",
               str(directory / "configs" / f"{job['name']}.json")]
    cleanup = study['specification'].get('owned_docker_cache_cleanup')
    if cleanup:
        command.extend(['--plugin','scripts.harbor_owned_cache:OwnedDockerCachePlugin',
            '--plugin-kwarg','plan_path='+cleanup['plan_path'],
            '--plugin-kwarg','plan_sha256='+cleanup['plan_sha256']])
    receipt = {"study_sha256": study["sha256"], "job": job["name"],
               "harbor_commit": study["harbor_commit"], "started_at": datetime.now(timezone.utc).isoformat(),
               "owned_docker_cache_cleanup":cleanup}
    write_json(directory / "launches" / f"{job['name']}.json", receipt)
    with (directory / "launches" / f"{job['name']}.log").open("x") as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=False)
    write_json(directory / "launches" / f"{job['name']}.exit.json", {"exit_code": result.returncode,
               "finished_at": datetime.now(timezone.utc).isoformat()})
    print(json.dumps({"job": job["name"], "exit_code": result.returncode,
                      "note": "Exit code is not a benchmark score; run audit"}))
    return result.returncode


def number(value, label, positive=False):
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{label} must be a finite {'positive' if positive else 'nonnegative'} number")
    return value


def timestamp(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} is missing or is not a timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label} needs an explicit timezone")
    return parsed


def matching_fields(expected, actual, location):
    if not isinstance(actual, dict):
        raise ValueError(f"{location} must be an object")
    for key, value in expected.items():
        if isinstance(value, dict):
            matching_fields(value, actual.get(key), f"{location}.{key}")
        elif isinstance(value, list):
            items = actual.get(key)
            if not isinstance(items, list) or len(items) != len(value):
                raise ValueError(f"Frozen list differs: {location}.{key}")
            for index, (item, observed) in enumerate(zip(value, items)):
                if isinstance(item, dict):
                    matching_fields(item, observed, f"{location}.{key}[{index}]")
                elif item != observed:
                    raise ValueError(f"Frozen list item differs: {location}.{key}[{index}]")
        elif actual.get(key) != value:
            raise ValueError(f"Frozen field differs: {location}.{key}")


def normalize_trial(raw, study, job, task):
    if not isinstance(raw, dict) or type(raw.get("schema_version", 1)) is not int or raw.get("schema_version", 1) != 1:
        raise ValueError("Unsupported Harbor trial schema")
    for field in ("id", "trial_name", "task_checksum"):
        if not isinstance(raw.get(field), str) or not raw[field]:
            raise ValueError(f"Missing trial field: {field}")
    if raw.get("step_results"):
        raise ValueError("Multi-step results need a separate reviewed adapter")
    spec = study["specification"]
    arm = next(a for a in spec["arms"] if a["id"] == job["arm"])
    config = raw.get("config")
    matching_fields({"task": {"path": task["path"], "git_url": spec["repository_url"],
                              "git_commit_id": study["benchmark_commit"]},
                     "agent": arm["agent"], "environment": {"type": "docker"},
                     "timeout_multiplier": spec["execution"]["timeout_multiplier"]}, config, "config")
    agent_defaults = {"kwargs": {}, "env": {}, "skills": [], "mcp_servers": [], "extra_allowed_hosts": [],
                      "override_timeout_sec": None, "override_setup_timeout_sec": None, "max_timeout_sec": None,
                      "base_url": None, "model_api_key_name": None, "model_api_format": None,
                      "n_concurrent": None, "concurrency_group": None, "load_trajectory": None,
                      "skip_model_parsing": False, "resume_trajectory": False}
    for field, default in agent_defaults.items():
        if config["agent"].get(field, default) != arm["agent"].get(field, default):
            raise ValueError(f"Agent configuration changed after freeze: {field}")
    for field in ("agent_timeout_multiplier", "verifier_timeout_multiplier", "agent_setup_timeout_multiplier",
                  "environment_build_timeout_multiplier"):
        if config.get(field) is not None:
            raise ValueError(f"Unregistered timeout override: {field}")
    environment_defaults = {"import_path": None, "override_cpus": None, "override_memory_mb": None,
                            "override_storage_mb": None, "override_gpus": None, "override_tpu": None,
                            "mounts": None, "extra_docker_compose": [], "kwargs": {}, "env": {},
                            "extra_allowed_hosts": [], "cpu_enforcement_policy": "auto", "memory_enforcement_policy": "auto"}
    for field, default in environment_defaults.items():
        if config["environment"].get(field, default) != default:
            raise ValueError(f"Unregistered environment override: {field}")
    for field in ("install_only", "source_trial", "user_agent", "extra_instructions", "extra_instruction_paths", "override_error_policy"):
        if config.get(field):
            raise ValueError(f"Unsupported trial modification: {field}")
    verifier_config = config.get("verifier", {})
    if not isinstance(verifier_config, dict) or verifier_config.get("disable") or verifier_config.get("import_path") or verifier_config.get("kwargs"):
        raise ValueError("An enabled upstream verifier is required")
    if any(verifier_config.get(field) is not None for field in ("override_timeout_sec", "max_timeout_sec")) or verifier_config.get("env") or verifier_config.get("extra_allowed_hosts"):
        raise ValueError("Unregistered verifier configuration override")
    for phase in ("agent_execution", "verifier"):
        timing = raw.get(phase)
        if timing is not None:
            if not isinstance(timing, dict):
                raise ValueError(f"{phase} must be timing information")
            for key in ("started_at", "finished_at"):
                if timing.get(key) is not None:
                    timestamp(timing[key], f"{phase}.{key}")
    started = timestamp(raw.get("started_at"), "started_at")
    if started < timestamp(study["frozen_at"], "frozen_at"):
        raise ValueError("Trial predates preregistration")
    finished = timestamp(raw["finished_at"], "finished_at") if raw.get("finished_at") else None
    if finished is not None and finished < started:
        raise ValueError("Trial finished before it started")
    verifier = raw.get("verifier_result")
    reward = None
    if verifier is not None:
        if not isinstance(verifier, dict):
            raise ValueError("Malformed verifier_result")
        rewards = verifier.get("rewards")
        if rewards is not None and not isinstance(rewards, dict):
            raise ValueError("Malformed verifier rewards")
        if rewards:
            if set(rewards) != {"reward"} or type(rewards["reward"]) not in {int, float} or rewards["reward"] not in (0, 1):
                raise ValueError("This adapter supports exactly one binary reward named reward")
            reward = rewards["reward"]
    exception = raw.get("exception_info")
    if exception is not None and (not isinstance(exception, dict) or not isinstance(exception.get("exception_type"), str)):
        raise ValueError("Malformed exception_info")
    usage = raw.get("agent_result") or {}
    if not isinstance(usage, dict):
        raise ValueError("Malformed agent_result")
    usage_values = {}
    for field in USAGE_FIELDS:
        value = usage.get(field)
        if value is not None:
            number(value, field)
            if field != "cost_usd" and type(value) is not int:
                raise ValueError(f"{field} must be an integer")
        usage_values[field] = value
    if raw.get("reward_valid") is not None and type(raw["reward_valid"]) is not bool:
        raise ValueError("reward_valid must be boolean")
    if finished is None:
        status = "INCOMPLETE"
    elif exception is not None:
        status = "ERROR"
    elif reward is None or not (raw.get("agent_execution") or {}).get("finished_at") or not (raw.get("verifier") or {}).get("finished_at"):
        status = "INCOMPLETE"
    elif raw.get("reward_valid") is False:
        status = "ERROR"
    else:
        status = "PASS" if reward == 1 else "FAIL"
    info = raw.get("agent_info") or {}
    if not isinstance(info, dict):
        raise ValueError("agent_info must be an object")
    return {"trial_id": raw["id"], "trial_name": raw["trial_name"], "task_checksum": raw["task_checksum"],
            "status": status, "strict_success": status == "PASS", "verifier_reward": reward,
            "exception_type": exception["exception_type"] if exception else None,
            "started_at": raw["started_at"], "finished_at": raw.get("finished_at"),
            "wall_seconds": (finished - started).total_seconds() if finished else None,
            "reported_agent": info.get("name"), "reported_agent_version": info.get("version"),
            "reported_model": info.get("model_info"), **usage_values}


def audit(directory):
    directory = directory.resolve(strict=True)
    study = read_study(directory)
    tasks = {t["name"]: t for t in study["tasks"]}
    rows, issues, trial_ids = [], [], set()
    expected_jobs = {job["name"] for job in study["jobs"]}
    unexpected_jobs = sorted(p.name for p in (directory / "runs").iterdir() if p.name not in expected_jobs)
    issues.extend({"kind": "unexpected_job", "path": name} for name in unexpected_jobs)
    for job in study["jobs"]:
        records = {name: [] for name in tasks}
        job_dir = directory / "runs" / job["name"]
        if job_dir.exists():
            try:
                actual_config = read_json(job_dir / "config.json")
                expected_config = read_json(directory / "configs" / f"{job['name']}.json")
                matching_fields(expected_config, actual_config, "job.config")
                aggregate = read_json(job_dir / "result.json")
                if aggregate.get("n_total_trials") != len(tasks) or aggregate.get("stats", {}).get("n_retries") != 0:
                    raise ValueError("Job trial count differs or retry history is absent/nonzero")
                if not aggregate.get("finished_at"):
                    raise ValueError("Harbor job has not finished")
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                issues.append({"kind": "job_provenance", "job": job["name"], "reason": str(exc)})
        for path in sorted(job_dir.glob("*/result.json")):
            source = {"path": path.relative_to(directory).as_posix(),
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            raw = None
            try:
                raw = read_json(path)
                name = raw.get("task_name") if isinstance(raw, dict) else None
                if name not in tasks:
                    raise ValueError(f"Unregistered task_name: {name!r}")
                row = normalize_trial(raw, study, job, tasks[name])
                if row["trial_id"] in trial_ids:
                    raise ValueError("Trial id reused across files or repeats")
                trial_ids.add(row["trial_id"])
            except (OSError, ValueError, TypeError) as exc:
                issues.append({"kind": "invalid_trial", **source, "reason": str(exc)})
                if isinstance(raw, dict) and raw.get("task_name") in records:
                    records[raw["task_name"]].append({"status": "INVALID", "strict_success": False,
                                                      "sources": [source]})
                continue
            row["sources"] = [source]
            records[name].append(row)
        for name, trials in records.items():
            if not trials:
                row = {"status": "NOT_RUN", "strict_success": False, "sources": []}
            elif len(trials) > 1:
                row = {"status": "DUPLICATE", "strict_success": False,
                       "sources": [source for trial in trials for source in trial["sources"]]}
                issues.append({"kind": "duplicate_task", "job": job["name"], "task": name, "count": len(trials)})
            else:
                row = trials[0]
            rows.append({"arm": job["arm"], "repeat": job["repeat"], "task": name, **row})
    complete = not issues and all(row["status"] in TERMINAL_STATUSES for row in rows)
    arms = {arm["id"]: summarize([r for r in rows if r["arm"] == arm["id"]], len(tasks))
            for arm in study["specification"]["arms"]}
    comparison = paired_comparison(rows, study) if complete else {"status": "BLOCKED_INCOMPLETE_AUDIT"}
    return {"schema_version": 1, "study_sha256": study["sha256"], "purpose": study["specification"]["purpose"],
            "benchmark": study["specification"]["benchmark"], "benchmark_commit": study["benchmark_commit"],
            "harbor_commit": study["harbor_commit"], "selection": study["selection"],
            "audit_complete": complete, "official_leaderboard_result": False,
            "metric": "strict completion plus upstream binary verifier; errors and missing trials are not successes",
            "provenance_limit": "Checks supplied records and frozen inputs; does not certify model identity or independent execution",
            "arms": arms, "comparison": comparison, "issues": issues, "trials": rows}


def summarize(rows, task_count):
    by_task = {}
    for row in rows:
        by_task.setdefault(row["task"], []).append(row["strict_success"])
    result = {"planned_trials": len(rows), "statuses": dict(Counter(r["status"] for r in rows)),
              "strict_successes": sum(r["strict_success"] for r in rows),
              "strict_success_rate_all_planned": sum(r["strict_success"] for r in rows) / len(rows),
              "rate_is_lower_bound": any(r["status"] not in TERMINAL_STATUSES for r in rows),
              "all_repeats_success_rate": sum(all(v) for v in by_task.values()) / task_count,
              "any_repeat_success_rate": sum(any(v) for v in by_task.values()) / task_count}
    for field in (*USAGE_FIELDS, "wall_seconds"):
        known = [r[field] for r in rows if r.get(field) is not None]
        result[field] = {"known_sum": sum(known) if known else None, "reported_trials": len(known),
                         "missing_trials": len(rows) - len(known)}
    return result


def paired_comparison(rows, study):
    comparison = study["specification"]["comparison"]
    means = {}
    for arm in (comparison["candidate"], comparison["baseline"]):
        for task in study["tasks"]:
            outcomes = [r["strict_success"] for r in rows if r["arm"] == arm and r["task"] == task["name"]]
            means[arm, task["name"]] = sum(outcomes) / len(outcomes)
    differences = [{"task": task["name"], "candidate_rate": means[comparison["candidate"], task["name"]],
                    "baseline_rate": means[comparison["baseline"], task["name"]],
                    "difference": means[comparison["candidate"], task["name"]] - means[comparison["baseline"], task["name"]]}
                   for task in study["tasks"]]
    return {"status": "DESCRIPTIVE_PAIRED_COMPARISON", **comparison,
            "mean_difference": sum(row["difference"] for row in differences) / len(differences),
            "task_wins": sum(row["difference"] > 0 for row in differences),
            "task_ties": sum(row["difference"] == 0 for row in differences),
            "task_losses": sum(row["difference"] < 0 for row in differences),
            "noninferiority_established": False, "tasks": differences}


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"public_agent_eval: {exc}", file=sys.stderr)
        raise SystemExit(2)
