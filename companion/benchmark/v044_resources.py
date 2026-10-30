"""Short owned-process measurements; watts/GPU counters are never inferred."""
import argparse
from dataclasses import fields, asdict
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n")


def worker(args):
    sys.path.insert(0, str(args.source))
    from companion.config import Config
    from companion.observers.native import NativeObserver
    from companion.runtime.service import Companion
    raw = json.loads(args.config.read_text())
    config = Config(**{k:v for k,v in raw.items() if k in {f.name for f in fields(Config)}})
    if args.worker == "A":
        counts = {"events":0, "processing_ms":[]}
        def observe(event):
            began = time.perf_counter()
            counts["events"] += 1
            counts["processing_ms"].append((time.perf_counter()-began)*1000)
        native = NativeObserver(config, observe)
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        native.start()
        try:
            while True:
                time.sleep(30)
        except KeyboardInterrupt:
            pass
        finally:
            native.stop(); save(args.config.parent/"observer-summary.json", counts)
    elif args.worker == "load":
        app = Companion(config)
        cpu0 = time.process_time(); began = time.perf_counter()
        try:
            for index in range(200):
                app.consider_event({"kind":"edits", "project":f"synthetic-{index}", "count":6,
                    "same_document":True, "minutes":60, "hour":12})
            save(args.config.parent/"event-load.json", {"events":200,
                "elapsed_seconds":time.perf_counter()-began, "cpu_seconds":time.process_time()-cpu0,
                "model_attempts":app.model.inferences, "model_inference":"NOT_RUN_BACKEND_DISABLED",
                "memory_count":len(app.store.records(1000)), "source":str(args.source)})
        finally:
            app.store.close(); app.lock.close()
    else:
        app = Companion(config)
        app.privacy.authorize(confirmed=True)  # Only Finder metadata; AX disabled.
        app.run()


def run(output, seconds):
    import psutil
    from companion.config import Config
    from companion.cli import client
    out = output.resolve(); out.mkdir(parents=True, exist_ok=False)
    state = ROOT/"companion/.data"/("v044-resources-"+str(int(time.time())))
    state.mkdir(parents=True, mode=0o700)
    old = ROOT.parent/"LocalPilot-companion-v0.4.3"
    profiles = [("A",ROOT,"always"), ("B",ROOT,"always"), ("E",ROOT,"off"), ("V043",old,"off")]
    results = []
    for label,source,power in profiles:
        folder = state/label; folder.mkdir(mode=0o700)
        helper = (ROOT/"companion/.data/v044-native/NativeObserver" if source==ROOT else
                  old/"companion/.data/presence-native-release/NativeObserver")
        config = Config(data_dir=str(folder/"host"), backend="disabled", localpilot_endpoint="",
            low_power_policy=power, native_helper_path=str(helper), native_observation_enabled=True,
            native_ax_enabled=False, native_app_allowlist=("com.apple.finder",), quiet_start_hour=0, quiet_end_hour=0)
        raw = asdict(config)
        if source == old:
            for key in ("low_power_policy", "low_power_until", "lightweight_on_demand", "lightweight_max_weight_bytes", "localpilot_client_subject", "localpilot_analysis_route"):
                raw.pop(key, None)
        cfg = folder/"config.json"; save(cfg, raw)
        # Authorize only the metadata observer in this isolated test directory.
        # The source's normal CLI retains its process-identity validation.
        if label != "A":
            setup = "from companion.config import Config; from companion.runtime.service import Companion; import sys; a=Companion(Config.load(sys.argv[1])); a.privacy.authorize(confirmed=True); a.store.close(); a.lock.close()"
            subprocess.run([sys.executable,"-c",setup,str(cfg)],cwd=source,check=True,timeout=10)
        profile = label if label in {"A","B"} else "E"
        log = (folder/"worker.log").open("w")
        command = [sys.executable,__file__,"--worker",profile,"--source",str(source),"--config",str(cfg)] if label == "A" else [sys.executable,"-m","companion","--config",str(cfg),"run"]
        process = subprocess.Popen(command,
            cwd=source,stdout=log,stderr=log,env={k:v for k,v in os.environ.items() if not any(w in k.upper() for w in ("TOKEN","SECRET","API_KEY","PASSWORD"))})
        log.close(); rows=[]; previous={}; latest={}
        try:
            time.sleep(2)
            for index in range(seconds):
                if process.poll() is not None:
                    raise RuntimeError(f"Owned resource profile {label} exited")
                root = psutil.Process(process.pid)
                cpu=0; rss=0; live=[]
                for p in [root]+root.children(recursive=True):
                    try:
                        t=p.cpu_times(); value=t.user+t.system
                        if p.pid in previous:
                            cpu+=max(0,value-previous[p.pid])
                        previous[p.pid]=value; rss+=p.memory_info().rss;live.append(p.pid)
                    except psutil.Error:
                        pass
                rows.append({"at":time.monotonic(),"cpu_delta_seconds":cpu,"rss_bytes":rss,"owned_pids":live})
                if label!="A" and index in {0,seconds-1}:
                    latest=client(config,{"command":"status"},timeout=3)
                time.sleep(1)
        finally:
            if process.poll() is None:
                process.terminate(); process.wait(timeout=15)
        elapsed=rows[-1]["at"]-rows[0]["at"]
        result={"profile":label,"seconds":elapsed,"scope":"owned host + observer child only; sampled each second",
            "cpu_average_percent_one_core":100*sum(r["cpu_delta_seconds"] for r in rows[1:])/elapsed,
            "cpu_peak_sampled_percent_one_core":max(r["cpu_delta_seconds"] for r in rows[1:])*100,
            "rss_peak_sampled_bytes":max(r["rss_bytes"] for r in rows), "model_memory_bytes":0,
            "gpu_usage":None,"energy_watts":None,"energy_status":"NOT_MEASURED",
            "ax_read_ms":None,"ax_status":"NOT_RUN_METADATA_ONLY",
            "network_service_calls":latest.get("service_connection",{}).get("network_calls",0),
            "native_metrics":latest.get("native_observer",{}).get("metrics",{}),
            "event_processing":latest.get("native_ingestion",{}), "samples":rows, "owned_process_exited":process.poll() is not None}
        save(out/(label+".json"),result); results.append(result)
    for label,source,power in (("v043-event-load",old,"off"),("v044-event-load",ROOT,"always")):
        folder=state/label;folder.mkdir(mode=0o700)
        config=Config(data_dir=str(folder/"host"),backend="disabled",localpilot_endpoint="",low_power_policy=power,
            quiet_start_hour=0,quiet_end_hour=0,max_notices_per_day=1000)
        cfg=folder/"config.json";save(cfg,asdict(config))
        subprocess.run([sys.executable,__file__,"--worker","load","--source",str(source),"--config",str(cfg)],cwd=source,check=True,timeout=30)
        save(out/(label+".json"),json.loads((folder/"event-load.json").read_text()))
    save(out/"summary.json",{"status":"PASS_SHORT_SAMPLE", "profiles":[{k:v for k,v in r.items() if k!="samples"} for r in results],
        "limitations":["short samples are not battery or daily-use power evidence", "AX disabled: read latency NOT_RUN", "C uses the separate real cloud E2E measurements", "D is the separate cached 0.8B lifecycle sample"]})
    print(json.dumps({"output":str(out),"profiles":len(results),"status":"PASS_SHORT_SAMPLE"}))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker");parser.add_argument("--source",type=Path);parser.add_argument("--config",type=Path)
    parser.add_argument("--output",type=Path);parser.add_argument("--seconds",type=int,default=12)
    args=parser.parse_args()
    worker(args) if args.worker else run(args.output,args.seconds)
