"""Short real process failures and bounded-history stress, never a multi-day claim."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import time

import psutil

from companion.cli import client, start, stop
from companion.config import Config, PrivateData
from companion.memory import MemoryStore
from companion.runtime.process import service_record
from companion.runtime.service import Companion


def wait_exited(process, timeout=10):
    # An unreaped child of the daemon is already dead but psutil.wait may wait
    # for its PID to disappear. Do not mistake a zombie for a running model.
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return
        time.sleep(.05)
    raise TimeoutError("Owned process did not exit")


def run(output, model_path=""):
    out = Path(output).resolve()
    if out.exists():
        raise ValueError("Preserve previous evidence; choose new output")
    out.parent.mkdir(parents=True, exist_ok=True)
    base = Path(__file__).resolve().parents[1]/".data"/("stability-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    docs = base/"documents"; docs.mkdir(parents=True)
    file = docs/"work.txt"; file.write_text("项目：稳定\n预算：17万\n")
    config_file = base/"config.json"
    config_file.write_text(json.dumps(asdict(Config()) | {"data_dir":str(base/"state"), "watch_dirs":[str(docs)], "backend":"mlx" if model_path else "disabled", "model_path":model_path, "mode":"responsive", "dnd":True, "notifications":False}))
    config = Config.load(config_file)
    private = PrivateData(config.data_dir)
    report = {"status":"running", "base_dir":str(base), "started_utc":datetime.now(timezone.utc).isoformat(), "checks":{}, "model_kind":"real_cached_mlx" if model_path else "disabled", "not_run":["24h", "48h", "multi_day", "physical_sleep_wake", "login_restart", "human_feedback", "launchd_install_uninstall", "native_popup_ui"], "source_sha256":{str(p.relative_to(Path(__file__).resolve().parents[1])):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).resolve().parents[1].rglob("*.py") if not any(x in p.parts for x in (".data", ".venv", "build"))}}
    began = time.monotonic()
    obj = None
    try:
        start(config, config_file)
        initial = client(config, {"command":"ask", "text":"稳定预算多少"})
        original_ids = [r["id"] for r in initial["memories"] if r["type"] == "document"]
        client(config, {"command":"remember", "type":"preference", "text":"简短回复"})
        report["restart_stops"] = []
        for _ in range(3):
            report["restart_stops"].append(stop(config))
            start(config, config_file)
            answer = client(config, {"command":"ask", "text":"稳定预算多少"})
            assert [r["id"] for r in answer["memories"] if r["type"] == "document"] == original_ids
        report["checks"]["three_restarts_same_ids"] = True
        report["checks"]["dnd_no_restart_notices"] = client(config, {"command":"status"})["notification_count"] == 0
        if model_path:
            report["warmup"] = client(config, {"command":"ask", "text":"请用一句话向我问候。"})
            state = client(config, {"command":"status"})
            worker = psutil.Process(state["model"]["worker_pid"])
            worker.kill(); wait_exited(worker)
            report["after_worker_crash"] = client(config, {"command":"ask", "text":"请用一句话向我问候。"})
            report["checks"]["worker_crash_reload"] = report["after_worker_crash"].get("model", {}).get("cold") is True and report["after_worker_crash"]["status"] in {"ok", "truncated"}
            worker = psutil.Process(client(config, {"command":"status"})["model"]["worker_pid"])
        _, daemon = service_record(private)
        daemon.kill(); daemon.wait(timeout=10)
        if model_path:
            wait_exited(worker)
            report["checks"]["real_loaded_worker_exits_after_parent_sigkill"] = not worker.is_running() or worker.status() == psutil.STATUS_ZOMBIE
        try:
            client(config, {"command":"status"})
            report["checks"]["dead_runtime_is_stopped"] = False
        except FileNotFoundError:
            report["checks"]["dead_runtime_is_stopped"] = True
        report["crash_stop"] = stop(config)
        start(config, config_file)
        answer = client(config, {"command":"ask", "text":"稳定预算多少"})
        report["checks"]["crash_keeps_committed_memory"] = "17万" in answer["text"] and [r["id"] for r in answer["memories"] if r["type"] == "document"] == original_ids
        # Actual process suspension is separate from physical machine sleep.
        _, daemon = service_record(private)
        os.kill(daemon.pid, signal.SIGSTOP)
        try:
            file.write_text("项目：稳定\n预算：18万\n")
            (docs/"new.txt").write_text("暂停期间新来源：unique-v03")
            time.sleep(3)
        finally:
            os.kill(daemon.pid, signal.SIGCONT)
        time.sleep(3)
        report["after_process_resume"] = client(config, {"command":"ask", "text":"稳定预算多少"})
        report["checks"]["short_process_suspend_resume_current_value"] = "18万" in report["after_process_resume"]["text"] and "17万" not in report["after_process_resume"]["text"]
        report["stop_before_growth"] = stop(config)
        obj = Companion(config)
        grow = docs/"growth.txt"
        report["growth_samples"] = []
        for batch in range(20):
            for i in range(50):
                grow.write_text("项目：增长\n预算："+str(batch*50+i+1)+"万\n"+"归档原文\n"*200)
                obj.process_file(str(grow), "initial")
            obj.config.retention_recent_versions = 2
            obj.config.retention_metadata_limit = 5
            obj.config.history_record_limit = 25
            result = obj.retention()
            s = obj.store
            rows = [r for r in s.records(kinds=["document"]) if r["source_reference"] == str(grow)]
            report["growth_samples"].append({"revisions":(batch+1)*50, "retained_versions":len(rows), "retained_full":sum("index_text" in r["metadata"] for r in rows), "memory_count":s.db.execute("SELECT count(*) FROM memories").fetchone()[0], "conflicts":s.db.execute("SELECT count(*) FROM conflicts").fetchone()[0], "page_count":s.db.execute("PRAGMA page_count").fetchone()[0], "freelist_count":s.db.execute("PRAGMA freelist_count").fetchone()[0], "retention":result})
        report["checks"]["1000_revisions_bounded_retained_history"] = all(s["retained_versions"] == 6 and s["retained_full"] == 3 for s in report["growth_samples"])
        report["checks"]["growth_source_bytes_unchanged_by_retention"] = grow.read_text().startswith("项目：增长\n预算：1000万\n")
        report["db_integrity"] = obj.store.db.execute("PRAGMA integrity_check").fetchone()[0]
        report["checks"]["db_integrity"] = report["db_integrity"] == "ok"
        compact_ids = [r["id"] for r in obj.store.records(kinds=["document"]) if r["metadata"].get("retained")]
        obj.model.unload(); obj.store.close(); obj.channel.stop(); obj.lock.close(); obj = None
        db = MemoryStore(private.file("memory.sqlite3"))
        try:
            report["checks"]["compacted_fts_after_reopen"] = all(not db.db.execute("SELECT 1 FROM memory_fts WHERE id=?", (mid,)).fetchone() for mid in compact_ids)
        finally:
            db.close()
        report["elapsed_seconds"] = time.monotonic()-began
        report["status"] = "passed" if all(report["checks"].values()) else "failed"
    except BaseException as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if obj:
            obj.model.unload(); obj.store.close(); obj.channel.stop(); obj.lock.close()
        report["final_stop"] = stop(config)
        report["runtime_record_removed"] = not private.file("runtime.json").exists()
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "passed":
        raise AssertionError(report["checks"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-path", default="")
    args = parser.parse_args()
    report = run(args.output, args.model_path)
    print(json.dumps({"status":report["status"], "elapsed_seconds":report["elapsed_seconds"], "checks":report["checks"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
