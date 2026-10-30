"""Finite, owned Companion resource runs with recoverable wall-clock evidence.

Only the run's newly created documents and processes are changed. There is no
login item, sleep prevention, system permission, network or desktop action.
AX arms require the explicitly owned validation App descriptor. Notifications
are evaluated and recorded silently; this does not measure OS popup overhead.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sqlite3
import statistics
import subprocess
import sys
import time

import psutil

from companion.cli import client, start, stop
from companion.config import Config, PrivateData
from companion.runtime.process import service_record


ROOT = Path(__file__).resolve().parents[2]


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def process_sample(process):
    try:
        cpu = process.cpu_times()
        return {"pid":process.pid, "created":process.create_time(),
                "name":process.name(), "rss_bytes":process.memory_info().rss,
                "cpu_seconds":cpu.user+cpu.system}
    except psutil.Error:
        return None


def resource_sample(config, elapsed):
    state = client(config, {"command":"status"}, timeout=15)
    _, daemon = service_record(PrivateData(config.data_dir))
    owned = [process_sample(p) for p in [daemon]+daemon.children(recursive=True)]
    target=getattr(config,"native_controlled_target",None)
    target_alive=True
    if target:
        try:
            fixture_process=psutil.Process(target["pid"])
            target_alive=(abs(fixture_process.create_time()-target["launch_time"])<.1
                and fixture_process.ppid()==target["owner_pid"] and fixture_process.status()!=psutil.STATUS_ZOMBIE)
        except psutil.NoSuchProcess:
            target_alive=False
    return {"elapsed_seconds":elapsed, "wall_utc":datetime.now(timezone.utc).isoformat(),
            "status":state, "processes":[p for p in owned if p],
            "provider_health":{"model_loaded":state["model"].get("loaded",False),
                "ax_running":state["native_observer"].get("state")=="running",
                "controlled_target_alive":target_alive,
                "ax_snapshot_count":state["native_observer"].get("metrics",{}).get("snapshot_count",0)}}


def summary(samples):
    if len(samples) < 2:
        return {}
    first, last = samples[0], samples[-1]
    duration = last["elapsed_seconds"]-first["elapsed_seconds"]
    if duration <= 0:
        return {}
    cpu = 0
    identities = set()
    for a, b in zip(samples, samples[1:]):
        old = {(p["pid"],p["created"]):p for p in a["processes"]}
        for p in b["processes"]:
            identity = (p["pid"],p["created"])
            identities.add(identity)
            if identity in old:
                cpu += max(0, p["cpu_seconds"]-old[identity]["cpu_seconds"])
    states = [s["status"] for s in samples]
    totals = last["status"].get("totals", {})
    initial_totals = first["status"].get("totals", {})
    processed = totals.get("native_observations",0)-initial_totals.get("native_observations",0)
    merged = totals.get("native_merged_events",0)-initial_totals.get("native_merged_events",0)
    return {"actual_wall_seconds":duration,
            "service_cpu_percent_one_core":100*(states[-1]["service_cpu_seconds"]-states[0]["service_cpu_seconds"])/duration,
            "sampled_owned_tree_cpu_percent_one_core_lower_bound":100*cpu/duration,
            "service_rss_first_mib":states[0]["service_rss_bytes"]/2**20,
            "service_rss_last_mib":states[-1]["service_rss_bytes"]/2**20,
            "service_rss_peak_sampled_mib":max(s["service_rss_bytes"] for s in states)/2**20,
            "owned_tree_rss_peak_sampled_mib":max(sum(p["rss_bytes"] for p in s["processes"]) for s in samples)/2**20,
            "model_worker_rss_peak_sampled_mib":max(s["model"].get("worker_rss_bytes") or 0 for s in states)/2**20,
            "queue_depth_max":max(s["queue_depth"] for s in states),
            "native_processed_delta":processed, "native_merged_delta":merged,
            "event_rate_per_second":processed/duration,
            "dedupe_ratio":merged/processed if processed else None,
            "database_growth_bytes":states[-1]["db_bytes"]-states[0]["db_bytes"],
            "database_growth_bytes_per_hour":3600*(states[-1]["db_bytes"]-states[0]["db_bytes"])/duration,
            "model_inferences_delta":states[-1]["model"]["inferences"]-states[0]["model"]["inferences"],
            "notification_records_delta":states[-1]["notification_count"]-states[0]["notification_count"],
            "process_identities_seen":len(identities),
            "power_watts":None, "power_status":"UNKNOWN"}


def run(output, arm="A", seconds=300, sample_seconds=30, model_path="", helper="",
        controlled_target=None, event_seconds=60):
    if (arm not in "ABCD" or len(arm)!=1 or type(seconds) not in (int,float)
            or not math.isfinite(seconds) or not 5 <= seconds <= 172800
            or not 1 <= sample_seconds <= 60 or event_seconds < 2):
        raise ValueError("Use a finite 5s–48h run, 1–60s samples and bounded events")
    if arm != "A" and (not helper or not controlled_target):
        raise ValueError("AX arms require a fixed helper and owned controlled target")
    if arm in "CD" and not model_path:
        raise ValueError("Model arms require an existing local model")
    if not (ROOT/"validation/v042_guardian.py").is_file():
        raise ValueError("Run this qualification harness from the V0.4.2 repository with its cleanup guardian")
    os.umask(0o077)
    out = Path(output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = out.with_suffix(".samples.jsonl")
    if out.exists() or raw.exists():
        raise ValueError("Preserve evidence; choose a fresh output")
    base = ROOT/"companion"/".data"/("v042-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    documents = base/"documents"
    documents.mkdir(parents=True)
    fixture = documents/"work.txt"
    fixture.write_text("项目：V042受控验收\n预算：17万\n版本：0\n")
    target = controlled_target or {}
    values = asdict(Config()) | {"data_dir":str(base/"state"), "watch_dirs":[str(documents)],
        "backend":"mlx" if arm in "CD" else "disabled", "model_path":model_path,
        "mode":"responsive", "notifications":False, "dnd":arm != "D",
        "quiet_start_hour":0, "quiet_end_hour":0, "summarize_documents":False,
        "native_observation_enabled":arm != "A", "native_ax_enabled":arm != "A",
        "native_helper_path":helper, "native_app_allowlist":[target["bundle_id"]] if target else [],
        "native_content_app_allowlist":[target["bundle_id"]] if target else [],
        "localpilot_endpoint":"", "agent_endpoint":"", "max_output_tokens":160}
    if target:
        values["native_controlled_target"] = target
    filename = base/"config.json"
    atomic_json(filename,values)
    config = Config.load(filename)
    stopfile = base/"STOP"
    process = psutil.Process()
    report = {"status":"running", "arm":arm, "requested_seconds":seconds,
        "started_utc":datetime.now(timezone.utc).isoformat(), "base_dir":str(base),
        "config_file":str(filename), "stop_file":str(stopfile), "samples_file":str(raw),
        "controller":{"pid":os.getpid(), "created":process.create_time()},
        "sample_count":0, "crash_count":"UNKNOWN; only observed process exit/replacement is recorded",
        "observed_service_exits":0, "observed_service_restarts":0,
        "notification_mode":"silent_records; no OS notification display",
        "workload":"Owned App AX events; new fixture file changes every configured interval after first half (or throughout runs >=1h); D real model short calls every 120s",
        "scope":"Real OS/AX and file provider with controlled nonprivate content; user workflow value UNKNOWN",
        "source_sha256":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                          for suffix in ("*.py","*.swift","*.json") for p in (ROOT/"companion").rglob(suffix)
                          if not any(part in p.parts for part in (".data","evidence",".venv","build","__pycache__"))},
        "duration_claim":"Only continuous measured wall time counts; no sleep prevention or power changes"}
    samples, latencies = [], []
    model_calls=[]
    requested_stop = False
    def stop_signal(*_):
        nonlocal requested_stop
        requested_stop = True
    previous_handlers = {s:signal.signal(s,stop_signal) for s in (signal.SIGTERM,signal.SIGINT)}
    started = False
    guardian = None
    daemon = None
    began = time.monotonic()
    try:
        report["initial"] = start(config,filename)
        started = True
        runtime, daemon = service_record(PrivateData(config.data_dir))
        guardian = subprocess.Popen([sys.executable,str(ROOT/"validation/v042_guardian.py"),
            "--config",str(filename),"--owner-pid",str(os.getpid()),
            "--owner-created",str(process.create_time()),"--service-pid",str(daemon.pid),
            "--service-created",str(runtime["created"]),"--deadline",str(time.time()+seconds+180),
            "--receipt",str(base/"guardian.json")],stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        report["guardian"]={"pid":guardian.pid,"created":psutil.Process(guardian.pid).create_time(),
                            "receipt":str(base/"guardian.json")}
        guardian_ready=base/"guardian.ready.json"
        ready_deadline=time.monotonic()+10
        while not guardian_ready.exists() and time.monotonic()<ready_deadline:
            if guardian.poll() is not None:
                raise RuntimeError("Cleanup guardian exited before initialization")
            time.sleep(.05)
        if not guardian_ready.exists() or json.loads(guardian_ready.read_text()).get("pid")!=guardian.pid:
            raise RuntimeError("Cleanup guardian readiness was not verified")
        report["guardian"]["ready"]=True
        if arm != "A":
            report["authorization"] = client(config,{"command":"authorize_observation", "confirmed":True})
        if arm in "CD":
            report["warmup"] = client(config,{"command":"ask", "text":"请用一句话说明 SQLite 的用途。"})
            warmup=report["warmup"]
            if (warmup.get("model",{}).get("backend") != "mlx" or warmup.get("status")!="ok"
                    or warmup.get("model",{}).get("generation_tokens",0)<=0
                    or not client(config,{"command":"status"})["model"]["loaded"]):
                raise RuntimeError("Real completed MLX generation and resident worker are required")
        if arm != "A":
            ready_deadline=time.monotonic()+15
            while time.monotonic()<ready_deadline:
                state=client(config,{"command":"status"})
                if state["native_observer"].get("metrics",{}).get("snapshot_count",0)>0:
                    break
                time.sleep(.25)
            else:
                raise RuntimeError("Real AX provider produced no snapshot; resource arm is NOT_RUN")
        report["setup_seconds"] = time.monotonic()-began
        began = time.monotonic()
        began_wall = time.time()
        next_sample = 0
        next_event = event_seconds if seconds >=3600 else seconds/2
        next_model=120
        pending_change = None
        version = 0
        with raw.open("x") as log:
            while True:
                elapsed = time.time()-began_wall
                if stopfile.exists() or requested_stop:
                    report["status"] = "stopped_early"
                    break
                if arm=="D" and elapsed>=next_model and elapsed<seconds:
                    inference_began=time.perf_counter()
                    answer=client(config,{"command":"ask", "text":"用一句话说明只读权限是什么。"})
                    model_calls.append({"elapsed_seconds":elapsed,"call_seconds":time.perf_counter()-inference_began,
                        "status":answer.get("status"),"model":answer.get("model",{}),"text":answer.get("text","")})
                    next_model=elapsed+120
                if elapsed >= next_event and elapsed < seconds:
                    version += 1
                    fixture.write_text(f"项目：V042受控验收\n预算：17万\n版本：{version}\n")
                    pending_change = time.monotonic()
                    next_event = elapsed+event_seconds
                if pending_change is not None:
                    # Read only our own database, no status wakeup needed to measure FSEvents latency.
                    connection = sqlite3.connect(f"file:{config.data_dir}/memory.sqlite3?mode=ro", uri=True, timeout=1)
                    try:
                        row = connection.execute("SELECT digest FROM files WHERE path=?",(str(fixture),)).fetchone()
                        if row and row[0] == hashlib.sha256(fixture.read_bytes()).hexdigest():
                            latencies.append(time.monotonic()-pending_change)
                            pending_change = None
                    finally:
                        connection.close()
                if elapsed >= next_sample or elapsed >= seconds:
                    item = resource_sample(config,elapsed)
                    item["monotonic_elapsed_seconds"] = time.monotonic()-began
                    actual_pid=next((p for p in item["processes"] if p["pid"]==daemon.pid and abs(p["created"]-runtime["created"])<.01),None)
                    if actual_pid is None:
                        report["observed_service_restarts"]+=1
                        raise RuntimeError("Owned service identity changed during residence")
                    samples.append(item)
                    log.write(json.dumps(item,ensure_ascii=False)+"\n"); log.flush()
                    report.update(sample_count=len(samples),elapsed_seconds=elapsed,latest=item,
                                  summary=summary(samples))
                    atomic_json(out,report)
                    next_sample = elapsed+sample_seconds
                if elapsed >= seconds:
                    report["status"] = "completed"
                    break
                time.sleep(min(0.5,seconds-elapsed))
        report["elapsed_seconds"] = time.time()-began_wall
        report["monotonic_elapsed_seconds"] = time.monotonic()-began
        report["wall_monotonic_difference_seconds"]=report["elapsed_seconds"]-report["monotonic_elapsed_seconds"]
        report["duration_clock_status"]="CONSISTENT" if abs(report["wall_monotonic_difference_seconds"])<5 else "UNKNOWN_SLEEP_OR_CLOCK_CHANGE"
        report["ended_utc"] = datetime.now(timezone.utc).isoformat()
        report["summary"] = summary(samples)
        report["periodic_model_calls"]=model_calls
        report["idle_summary"] = summary([s for s in samples if s["elapsed_seconds"] <= seconds/2]) if seconds <3600 else None
        report["active_summary"] = summary([s for s in samples if s["elapsed_seconds"] >= seconds/2]) if seconds <3600 else None
        report["file_changes"] = version
        report["file_processing_latency_seconds"] = {"samples":latencies,
            "median":statistics.median(latencies) if latencies else None,
            "max":max(latencies) if latencies else None, "unprocessed_final_change":pending_change is not None}
        report["final"] = client(config,{"command":"status"})
        with sqlite3.connect(f"file:{config.data_dir}/memory.sqlite3?mode=ro",uri=True) as db:
            report["database_integrity"] = db.execute("PRAGMA integrity_check").fetchone()[0]
            report["memory_records"] = db.execute("SELECT count(*) FROM observation_events").fetchone()[0]
            report["last_active_decision"] = json.loads(db.execute("SELECT value FROM state WHERE key='last_active_decision'").fetchone()[0]) if db.execute("SELECT 1 FROM state WHERE key='last_active_decision'").fetchone() else None
        health=[s["provider_health"] for s in samples]
        providers_valid=report["status"]=="completed" and report["database_integrity"]=="ok"
        if arm in "CD" and not all(h["model_loaded"] for h in health):
            providers_valid=False
        if arm=="D" and any(c["status"]!="ok" or c["model"].get("generation_tokens",0)<=0 for c in model_calls):
            providers_valid=False
        report["resource_validation"]="PASS" if providers_valid else "PARTIAL"
        if arm!="A" and not all(h["ax_running"] and h["ax_snapshot_count"]>0 and h["controlled_target_alive"] for h in health):
            report["resource_validation"]="PARTIAL"
        qualified=(report["resource_validation"]=="PASS" and report["duration_clock_status"]=="CONSISTENT")
        report["residence_24h"] = ("PASS" if qualified else "PARTIAL") if report["status"]=="completed" and report["elapsed_seconds"]>=86400 else "NOT_RUN"
        report["residence_48h"] = ("PASS" if qualified else "PARTIAL") if report["status"]=="completed" and report["elapsed_seconds"]>=172800 else "NOT_RUN"
    except BaseException as exc:
        if daemon is not None and not psutil.pid_exists(daemon.pid):
            report["observed_service_exits"]+=1
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}",
                      elapsed_seconds=time.monotonic()-began, ended_utc=datetime.now(timezone.utc).isoformat())
        raise
    finally:
        if started:
            try:
                report["stop"] = stop(config)
            except Exception as exc:
                report["stop"] = {"status":"error", "error":str(exc)}
        if guardian is not None:
            try:
                guardian.wait(timeout=4)
            except subprocess.TimeoutExpired:
                # Preserve a finite guardian if service shutdown is still pending.
                report["guardian"]["still_running"]=True
        atomic_json(out,report)
        for sig, handler in previous_handlers.items():
            signal.signal(sig,handler)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    parser.add_argument("--arm",choices=list("ABCD"),default="A")
    parser.add_argument("--seconds",type=float,default=300)
    parser.add_argument("--sample-seconds",type=float,default=30)
    parser.add_argument("--event-seconds",type=float,default=60)
    parser.add_argument("--model-path",default="")
    parser.add_argument("--helper",default="")
    parser.add_argument("--controlled-target",default="")
    parser.add_argument("--owned-ax",action="store_true",help="Launch only the fixed offscreen validation App")
    args = parser.parse_args()
    target = json.loads(Path(args.controlled_target).read_text()) if args.controlled_target else None
    if args.owned_ax:
        if target or args.arm=="A":
            parser.error("Owned AX is only for B/C/D without an external descriptor")
        from validation.v042_ax import OwnedAXApp
        from companion.observers.native import build_native_helper
        base=ROOT/"companion/.data"/("v042-residence-target-"+str(time.time_ns()))
        with OwnedAXApp(base,seconds=args.seconds+240,interval=45) as owned:
            helper=args.helper or build_native_helper(base/"helper")
            result=run(args.output,args.arm,args.seconds,args.sample_seconds,args.model_path,helper,owned.descriptor,args.event_seconds)
            result["controlled_app_ready"]=owned.ready
        result["controlled_app_lifecycle"]=owned.lifecycle
        result["controlled_app_cleanup"]={"pid":owned.process.pid,"exited":owned.process.poll() is not None}
        if any(not e.get("window_offscreen") or e.get("activation_count",0) or e.get("key_window_count",0) for e in owned.lifecycle):
            result["resource_validation"]="FAIL"
        atomic_json(Path(args.output).resolve(),result)
    else:
        result = run(args.output,args.arm,args.seconds,args.sample_seconds,args.model_path,args.helper,target,args.event_seconds)
    print(json.dumps({"status":result["status"],"elapsed_seconds":result["elapsed_seconds"],"summary":result.get("summary")}))


if __name__ == "__main__":
    main()
