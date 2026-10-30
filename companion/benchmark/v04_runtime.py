"""Owned V0.4 real process controls and short resource sampling.

Only creates private synthetic fixtures and its own service/helper/optional cached
model workers. Native tests use an empty app allowlist and AX disabled, so no app
content, TCC prompt, input, system settings or existing work session is touched.
Short suspension and synthetic files never represent physical sleep or 24h/48h.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import sqlite3
import time

import psutil

from companion.cli import client, start, stop
from companion.config import Config, PrivateData
from companion.observers.native import build_native_helper
from companion.runtime.process import service_record


ROOT = Path(__file__).resolve().parents[1]


def manifest():
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for extension in ("*.py", "*.swift") for path in ROOT.rglob(extension)
            if not any(part in path.parts for part in (".data", ".venv", "build", "__pycache__"))}


def wait_for(predicate, seconds=12):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except (FileNotFoundError, OSError, psutil.Error):
            pass
        time.sleep(.2)
    raise TimeoutError("Owned fixture condition did not become true")


def exited(process):
    try:
        return not process.is_running() or process.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def helper_process(daemon, binary):
    if not binary:
        return None
    for child in daemon.children():
        try:
            if child.exe() == binary:
                return child
        except psutil.Error:
            pass
    return None


def process_sample(process):
    if process is None:
        return None
    try:
        cpu = process.cpu_times()
        return {"pid": process.pid, "created": process.create_time(), "rss_bytes": process.memory_info().rss,
                "cpu_seconds": cpu.user+cpu.system, "threads": process.num_threads(), "state": process.status()}
    except psutil.Error:
        return None


def make_config(base, label, helper="", model_path=""):
    group = base / label
    docs = group / "documents"
    docs.mkdir(parents=True)
    fixture = docs / "work.txt"
    fixture.write_text("项目：V04合成\n预算：17万\n", encoding="utf-8")
    raw = asdict(Config()) | {"data_dir": str(group/"state"), "watch_dirs": [str(docs)],
           "backend": "mlx" if model_path else "disabled", "model_path": model_path, "mode": "eco",
           "eco_unload_seconds": 5 if model_path else 120, "notifications": False, "dnd": True,
           "quiet_start_hour": 0, "quiet_end_hour": 0, "native_observation_enabled": bool(helper),
           "native_helper_path": helper, "native_app_allowlist": [], "native_app_exclusions": [],
           "native_content_app_allowlist": [], "native_ax_enabled": False,
           "localpilot_endpoint": "", "agent_endpoint": "", "summarize_documents": False}
    file = group / "config.json"
    file.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return Config.load(file), file, fixture


def doc_rows(config):
    return [row for row in client(config, {"command": "retrieve", "text": "V04合成预算"})["memories"] if row["type"] == "document"]


def observation_ids(config):
    return sorted(row["id"] for row in client(config, {"command": "observations"})["observations"] if row["source"] == "file_observer")


def controls(config, file, fixture, helper):
    checks, detail = {}, {}
    private = PrivateData(config.data_dir)
    detail["initial"] = start(config, file)
    if helper:
        detail["consent"] = client(config, {"command": "authorize_observation", "confirmed": True})
        wait_for(lambda: client(config, {"command": "status"})["native_observer"]["state"] == "running")
    wait_for(lambda: bool(doc_rows(config)))
    initial = client(config, {"command": "status"})
    first_ids = [row["id"] for row in doc_rows(config)]
    fixture.write_text("项目：V04合成\n预算：19万\n", encoding="utf-8")
    wait_for(lambda: client(config, {"command": "status"})["observed_events"] > initial["observed_events"])
    updated = client(config, {"command": "ask", "text": "V04合成预算多少"})
    checks["real_file_event_indexed"] = "19万" in updated.get("text", "") and [row["id"] for row in updated["memories"] if row["type"] == "document"] != first_ids
    detail["observer_type"] = initial["observer"]
    detail["after_file_event"] = updated

    client(config, {"command": "pause_observation", "paused": True})
    paused = client(config, {"command": "status"})
    fixture.write_text("项目：V04合成\n预算：23万\n", encoding="utf-8")
    extra = fixture.parent / "paused-new.txt"
    extra.write_text("暂停期间新文件 v04-paused-marker\n", encoding="utf-8")
    time.sleep(3)
    still_paused = client(config, {"command": "status"})
    checks["pause_stops_file_capture"] = still_paused["observed_events"] == paused["observed_events"] and still_paused["privacy"]["status"] == "paused"
    client(config, {"command": "pause_observation", "paused": False})
    wait_for(lambda: client(config, {"command": "status"})["observed_events"] > paused["observed_events"])
    resumed = client(config, {"command": "retrieve", "text": "v04-paused-marker"})
    checks["resume_reconciles_missed_new_file"] = any(row["source_reference"] == str(extra) for row in resumed["memories"])
    checks["resume_has_current_document"] = "23万" in client(config, {"command": "ask", "text": "V04合成预算多少"})["text"]

    docs_before = [row["id"] for row in doc_rows(config)]
    obs_before = observation_ids(config)
    detail["restart_stop"] = stop(config)
    start(config, file)
    checks["restart_preserves_document_versions"] = [row["id"] for row in doc_rows(config)] == docs_before
    checks["restart_preserves_committed_observation_ids"] = observation_ids(config) == obs_before
    # Existing events are not re-added by unchanged document startup scans.
    detail["observation_ids_before_crash"] = obs_before

    _, daemon = service_record(private)
    child = wait_for(lambda: helper_process(daemon, helper)) if helper else None
    detail["owned_helper_before_crash"] = process_sample(child)
    daemon.kill()
    wait_for(lambda: exited(daemon))
    if child is not None:
        wait_for(lambda: exited(child), seconds=12)
        checks["native_helper_exits_after_parent_sigkill"] = exited(child)
    detail["crash_stop"] = stop(config)
    start(config, file)
    checks["sigkill_preserves_committed_observations"] = observation_ids(config) == obs_before
    checks["sigkill_preserves_source_versions"] = [row["id"] for row in doc_rows(config)] == docs_before

    _, daemon = service_record(private)
    before_suspend = client(config, {"command": "status"})
    os.kill(daemon.pid, signal.SIGSTOP)
    try:
        fixture.write_text("项目：V04合成\n预算：29万\n", encoding="utf-8")
        time.sleep(3)
    finally:
        os.kill(daemon.pid, signal.SIGCONT)
    wait_for(lambda: client(config, {"command": "status"})["observed_events"] > before_suspend["observed_events"])
    after_suspend = client(config, {"command": "ask", "text": "V04合成预算多少"})
    checks["short_sigstop_sigcont_current_file"] = "29万" in after_suspend["text"]
    detail["suspension_scope"] = "3-second actual service process suspension; physical sleep and >180s scheduling-gap recovery NOT_RUN"

    if config.model_path:
        detail["model_controls"] = model_controls(config)
        checks["owned_cached_model_controls"] = all(detail["model_controls"]["checks"].values())
    _, final_daemon = service_record(private)
    final_helper = helper_process(final_daemon, helper) if helper else None
    before_clear_hash = hashlib.sha256(fixture.read_bytes()).hexdigest()
    detail["clear"] = client(config, {"command": "clear", "confirmation": "DELETE_COMPANION_MEMORY"})
    state = client(config, {"command": "status"})
    checks["clear_removes_both_memory_layers"] = state["memory_count"] == 0 and state["observations"]["records"] == 0 and state["privacy"]["status"] == "paused"
    checks["read_only_source_preserved_by_clear"] = hashlib.sha256(fixture.read_bytes()).hexdigest() == before_clear_hash
    detail["final_stop"] = stop(config)
    checks["owned_control_service_exited"] = exited(final_daemon)
    if final_helper is not None:
        checks["clear_stops_owned_native_helper"] = exited(final_helper)
    with sqlite3.connect(private.file("memory.sqlite3")) as db:
        detail["integrity_check"] = db.execute("PRAGMA integrity_check").fetchone()[0]
    checks["database_integrity"] = detail["integrity_check"] == "ok"
    checks["runtime_removed"] = not private.file("runtime.json").exists()
    return {"checks": checks, "details": detail}


def model_controls(config):
    report = {"checks": {}, "scope": "cached model only; test eco timeout=5s, not production120s; no response quality/latency speedup claim"}
    question = {"command": "ask", "text": "请用一句话向我问候。"}
    report["cold"] = client(config, question)
    cold = client(config, {"command": "status"})
    report["warm"] = client(config, question)
    warm = client(config, {"command": "status"})
    report["cold_state"], report["warm_state"] = cold["model"], warm["model"]
    worker = psutil.Process(warm["model"]["worker_pid"])
    worker.kill(); wait_for(lambda: exited(worker))
    report["after_worker_crash"] = client(config, question)
    crash = client(config, {"command": "status"})
    report["checks"]["worker_crash_reload"] = bool(crash["model"].get("worker_pid") and crash["model"]["worker_pid"] != worker.pid)
    wait_for(lambda: not client(config, {"command": "status"})["model"]["loaded"], seconds=40)
    report["checks"]["eco_unloads_owned_worker"] = True
    report["after_eco_reload"] = client(config, question)
    reload_state = client(config, {"command": "status"})
    report["checks"]["after_eco_reload"] = bool(reload_state["model"]["loaded"])
    private = PrivateData(config.data_dir)
    _, daemon = service_record(private)
    worker = psutil.Process(reload_state["model"]["worker_pid"])
    daemon.kill(); wait_for(lambda: exited(daemon)); wait_for(lambda: exited(worker), seconds=12)
    report["checks"]["loaded_worker_exits_after_parent_sigkill"] = exited(worker)
    # Caller needs a running service to complete clear/status controls.
    stop(config)
    start(config, Path(config.data_dir).parent/"config.json")
    return report


def resource_group(config, file, helper, seconds, sample_seconds, samples_file):
    start(config, file)
    if helper:
        client(config, {"command": "authorize_observation", "confirmed": True})
    _, daemon = service_record(PrivateData(config.data_dir))
    native = wait_for(lambda: helper_process(daemon, helper)) if helper else None
    initial = None
    previous = None
    began, next_sample = time.monotonic(), 0.0
    count = 0
    latest = None
    with samples_file.open("x", encoding="utf-8") as stream:
        while True:
            elapsed = time.monotonic()-began
            if elapsed >= next_sample or elapsed >= seconds:
                state = client(config, {"command": "status"})
                item = {"elapsed_seconds": elapsed, "service": process_sample(daemon), "native_helper": process_sample(native), "status": state, "cpu_percent_one_core": {}, "watts": "UNKNOWN"}
                if previous:
                    duration = elapsed-previous["elapsed_seconds"]
                    for key in ("service", "native_helper"):
                        old, new = previous.get(key), item.get(key)
                        item["cpu_percent_one_core"][key] = 100*max(0, new["cpu_seconds"]-old["cpu_seconds"])/duration if old and new and old["pid"] == new["pid"] else None
                stream.write(json.dumps(item, ensure_ascii=False)+"\n"); stream.flush()
                initial = item if initial is None else initial
                previous, latest, count = item, item, count+1
                print(json.dumps({"group": samples_file.stem, "elapsed_seconds": round(elapsed, 2), "samples": count}), flush=True)
                next_sample += sample_seconds
            if elapsed >= seconds:
                break
            time.sleep(min(.5, seconds-elapsed))
    result = {"elapsed_seconds": latest["elapsed_seconds"], "sample_count": count, "samples_file": str(samples_file), "initial": initial, "final": latest, "average_cpu_percent_one_core": {},
              "scope": "actual short idle elapsed time; sampling wakes service; other desktop load uncontrolled; power UNKNOWN"}
    for key in ("service", "native_helper"):
        old, new = initial.get(key), latest.get(key)
        result["average_cpu_percent_one_core"][key] = 100*max(0, new["cpu_seconds"]-old["cpu_seconds"])/latest["elapsed_seconds"] if old and new else None
    result["stop"] = stop(config)
    result["owned_processes_exited"] = {"service": exited(daemon), "native_helper": exited(native) if native else None}
    return result


def run(output, seconds=300, sample_seconds=30, native=False, model_path="", phase="final"):
    if seconds < 2 or not 1 <= sample_seconds <= 60 or sample_seconds > seconds:
        raise ValueError("Invalid actual resource sample duration")
    out = Path(output).resolve()
    if out.exists():
        raise ValueError("Preserve previous evidence; use a new output")
    out.parent.mkdir(parents=True, exist_ok=True)
    base = ROOT/".data"/("v04-runtime-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    base.mkdir(parents=True, mode=0o700)
    before_manifest = manifest()
    report = {"status": "running", "phase": phase, "started_utc": datetime.now(timezone.utc).isoformat(), "base_dir": str(base), "python": os.sys.executable,
              "platform": platform.platform(), "source_manifest": before_manifest, "resource_groups": {}, "native_scope": "empty app/content allowlist, AX=false, system metadata only" if native else "default native off",
              "model_scope": "existing cached MLX" if model_path else "disabled", "power_watts": "UNKNOWN",
              "not_run": ["physical_sleep_wake", "24h", "48h", "multi_day", "real_user_feedback", "TCC_prompt", "launchd_login", "other_app_AX_content", "power_meter", "full_crash_window_matrix"]}
    owned_configs = []
    began = time.monotonic()
    try:
        helper = build_native_helper(base/"helper") if native else ""
        control_config, control_file, fixture = make_config(base, "controls", helper, model_path)
        owned_configs.append(control_config)
        report["controls"] = controls(control_config, control_file, fixture, helper)
        for label, binary in (("idle-defaultoff", ""), *(([("idle-native-emptyallowlist", helper)]) if native else [])):
            config, file, _ = make_config(base, label, binary)
            owned_configs.append(config)
            samples = out.with_name(out.stem+"-"+label+".samples.jsonl")
            if samples.exists():
                raise ValueError("Preserve previous raw samples")
            report["resource_groups"][label] = resource_group(config, file, binary, seconds, sample_seconds, samples)
        clean = all(group["owned_processes_exited"]["service"] and group["owned_processes_exited"]["native_helper"] is not False for group in report["resource_groups"].values())
        report["status"] = "passed" if all(report["controls"]["checks"].values()) and clean else "failed"
    except BaseException as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        report["cleanup"] = []
        for config in owned_configs:
            try:
                report["cleanup"].append({"data_dir": config.data_dir, "stop": stop(config)})
            except Exception as exc:
                report["cleanup"].append({"data_dir": config.data_dir, "error": str(exc)})
        report["elapsed_seconds"] = time.monotonic()-began
        report["source_unchanged"] = manifest() == before_manifest
        if phase == "final" and not report["source_unchanged"] and report["status"] == "passed":
            report["status"] = "source_changed_requires_rerun"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seconds", type=float, default=300)
    parser.add_argument("--sample-seconds", type=float, default=30)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--model-path", default="")
    parser.add_argument("--phase", choices=["smoke", "final"], default="final")
    args = parser.parse_args()
    report = run(args.output, args.seconds, args.sample_seconds, args.native, args.model_path, args.phase)
    print(json.dumps({"status": report["status"], "elapsed_seconds": report["elapsed_seconds"], "source_unchanged": report["source_unchanged"]}, ensure_ascii=False))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
