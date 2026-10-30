"""V0.4.1 safe process/resource and synthetic observation pipeline validation."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import time

from companion.benchmark.v04_runtime import (run as idle_run, make_config, start, stop,
    client, service_record, PrivateData, helper_process, wait_for, exited)
from companion.observers.native import build_native_helper
from companion.runtime.service import Companion
from companion.config import Config


def pipeline(base):
    docs=base/"pipeline-docs"; docs.mkdir()
    file=docs/"work.txt"; file.write_text("Synthetic project budget 17",encoding="utf-8")
    app=Companion(Config(data_dir=str(base/"pipeline-state"),watch_dirs=(str(docs),),backend="disabled",dnd=True,
        native_observation_enabled=True,native_ax_enabled=True,native_app_allowlist=("org.localpilot.synthetic",)))
    try:
        app.privacy.authorize(True)
        app.process_file(str(file),"initial")
        before=app.store.db.execute("SELECT count(*) FROM source_versions").fetchone()[0]
        timings=[]
        for i in range(1000):
            raw={"timestamp":1700000000+i,"source":"accessibility","kind":"ax.snapshot",
                 "object":{"bundle_id":"org.localpilot.synthetic"},
                 "evidence":{"read_status":"READ_SUCCESS_NONEMPTY","complete":True,"truncated":False,
                             "nodes":[{"id":0,"role":"AXWindow"}],"shared_core_version":"1.0.0"},"confidence":1}
            began=time.perf_counter(); app.enqueue_native(raw)
            _,queued,_=app.queue.get_nowait(); app.process_native(queued)
            timings.append((time.perf_counter()-began)*1000)
        # Permission denied and transient failure remain observations of failed
        # reads, never absence proofs. These are synthetic protocol outcomes.
        for i in range(10):
            app.enqueue_native({"timestamp":1700002000+i,"source":"accessibility","kind":"ax.snapshot",
                "object":{"bundle_id":"org.localpilot.synthetic"},"confidence":1,
                "evidence":{"read_status":"READ_FAILED","complete":False,"read_errors":[
                    {"attribute":"AXChildren","path":[0],"scope":"AXWindows","status":"READ_FAILED","error":-25204,
                     "structural":True,"reason":"AX_attribute_read_failed","retry_allowed":True,
                     "retry_class":"fresh_read_allowed_no_action_replay"}]}})
            _,queued,_=app.queue.get_nowait(); app.process_native(queued)
        for i in range(100): app.process_file(str(file),"modified")
        after=app.store.db.execute("SELECT count(*) FROM source_versions").fetchone()[0]
        totals=app.store.get("runtime_totals",{})
        return {"scope":"Synthetic protocol to actual privacy/SQLite; no actual AX provider failures, apps or model calls",
            "events":1010,"same_evidence_samples":1000,"pipeline_ms":{"median":statistics.median(timings),"p95":sorted(timings)[949],"max":max(timings)},
            "totals":totals,"merged_event_ratio":totals.get("native_merged_events",0)/1010,
            "incomplete_snapshot_ratio":totals.get("native_incomplete_snapshots",0)/1010,
            "document_cache_hits":totals.get("document_cache_hits",0),"document_versions_unchanged":before==after,
            "ax_snapshot_cache":"NOT_IMPLEMENTED; per-event fresh core snapshot and within-snapshot attribute memoization only",
            "database_integrity":app.store.db.execute("PRAGMA integrity_check").fetchone()[0],"model_calls":app.model.stats()["inferences"]}
    finally:
        app.native.stop(); app.observer.stop(); app.model.unload(); app.channel.stop(); app.store.close(); app.lock.close()


def crash_recovery(base):
    helper=build_native_helper(base/"recovery-helper")
    config,file,_=make_config(base,"reader-crash",helper)
    daemon=None; replacement=None
    try:
        start(config,file); client(config,{"command":"authorize_observation","confirmed":True})
        _,daemon=service_record(PrivateData(config.data_dir))
        original=wait_for(lambda:helper_process(daemon,helper))
        began=time.monotonic(); original.kill(); wait_for(lambda:exited(original))
        def replaced():
            client(config,{"command":"status"})  # Existing service wakeup, no AX polling.
            value=helper_process(daemon,helper)
            return value if value and value.pid!=original.pid else None
        replacement=wait_for(replaced,seconds=50)
        status=client(config,{"command":"status"})
        latency=time.monotonic()-began
        client(config,{"command":"pause_observation","paused":True})
        wait_for(lambda:exited(replacement))
        return {"status":"TESTED","scope":"Actual SIGKILL of only our empty-allowlist AX-disabled helper; status sampling wakes maintenance",
            "original_pid":original.pid,"replacement_pid":replacement.pid,"recovery_seconds":latency,
            "restart_attempts":status["totals"].get("native_helper_restart_attempts"),"helper_state":status["native_observer"]["state"],
            "pause_stops_replacement":exited(replacement),"app_switch_latency":"NOT_RUN; no real user app notifications induced"}
    finally:
        stop(config)


def run(output,seconds=300,sample_seconds=30):
    report=idle_run(output,seconds,sample_seconds,native=True,phase="final")
    base=Path(report["base_dir"])
    report["v041_pipeline"]=pipeline(base)
    report["v041_helper_crash_recovery"]=crash_recovery(base)
    Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True); parser.add_argument("--seconds",type=float,default=300)
    parser.add_argument("--sample-seconds",type=float,default=30)
    args=parser.parse_args(); report=run(args.output,args.seconds,args.sample_seconds)
    print(json.dumps({"status":report["status"],"resource_seconds":report["elapsed_seconds"],"crash_recovery":report["v041_helper_crash_recovery"]}))
