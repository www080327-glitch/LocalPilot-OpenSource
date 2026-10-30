"""24h/48h/multi-day residence with append-only samples and bounded memory.

All event writes target new synthetic fixture files. Never accepts arbitrary watch dirs.
No desktop notification, GUI, auto-start installation, remote inference or Agent call.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time

from companion.cli import client, start, stop
from companion.config import Config
from companion.benchmark.power import snapshot


def sample(config, elapsed, previous=None):
    item = snapshot(config, elapsed)
    state = item["status"]
    state.pop("last_error", None) if not state.get("last_error") else None
    # Complete counts come from status, not the popup's last-20 display.
    item["notification_count"] = state["notification_count"]
    item["ignored_count"] = state["ignored_count"]
    item["accepted_help_count"] = state["accepted_help_count"]
    item["old_versions_retained"] = state["old_versions_retained"]
    item["pending_queue"] = state["queue_depth"]
    item["errors_total"] = state.get("totals", {}).get("errors", 0)
    item["cpu_percent_one_core"] = None
    if previous and elapsed > previous["elapsed_seconds"]:
        item["cpu_percent_one_core"] = 100 * max(0, state["service_cpu_seconds"] - previous["status"]["service_cpu_seconds"]) / (elapsed-previous["elapsed_seconds"])
    return item


def run(output, seconds=86400, sample_seconds=60, event_seconds=120, model_path="", mode="eco", activity="events"):
    if seconds < 5 or not 1 <= sample_seconds <= 60 or event_seconds < 2 or mode not in {"eco", "responsive"} or activity not in {"idle", "events"}:
        raise ValueError("Invalid endurance configuration")
    out = Path(output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    samples_file = out.with_suffix(".samples.jsonl")
    if out.exists() or samples_file.exists():
        raise ValueError("Preserve previous endurance evidence; choose new output")
    base = Path(__file__).resolve().parents[1] / ".data" / ("endurance-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    docs = base / "documents"
    docs.mkdir(parents=True)
    fixture = docs / "work.txt"
    fixture.write_text("项目：耐久合成项目\n预算：17万\n序号：0\n")
    raw = asdict(Config()) | {"data_dir":str(base / "state"),"watch_dirs":[str(docs)],
                             "backend":"mlx" if model_path else "disabled", "model_path":model_path,
                             "mode":mode,"notifications":False,"dnd":activity == "idle",
                             "quiet_start_hour":0,"quiet_end_hour":0}
    config_file = base / "config.json"
    config_file.write_text(json.dumps(raw, ensure_ascii=False, indent=2))
    config = Config.load(config_file)
    report = {"status":"running", "requested_seconds":seconds,"sample_seconds":sample_seconds,
              "mode":mode,"activity":activity,"model_kind":"real_cached_mlx" if model_path else "disabled",
              "started_utc":datetime.now(timezone.utc).isoformat(),"hardware":platform.platform(),
              "samples_file":str(samples_file),"base_dir":str(base),"sample_count":0,
              "duration_claim":"Only elapsed wall time counts; synthetic changes do not simulate days of residence.",
              "interference":"Other desktop work uncontrolled; CPU/RSS are process measurements, power is UNKNOWN.",
              "source_sha256":{str(p.relative_to(Path(__file__).resolve().parents[1])):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).resolve().parents[1].rglob("*.py") if not any(x in p.parts for x in (".venv", ".data", "build"))}}
    previous = None
    started = False
    try:
        report["initial"] = start(config, config_file)
        started = True
        if model_path:
            report["warmup"] = client(config, {"command":"ask","text":"请用一句话问候我。"})
            if report["warmup"]["status"] not in {"ok", "truncated"}:
                raise RuntimeError("Model warmup failed")
        began = time.monotonic()
        next_sample, next_event = 0, event_seconds
        with samples_file.open("x") as log:
            while True:
                elapsed = time.monotonic() - began
                if activity == "events" and elapsed >= next_event and elapsed < seconds:
                    fixture.write_text(f"项目：耐久合成项目\n预算：17万\n序号：{int(next_event//event_seconds)}\n")
                    next_event += event_seconds
                if elapsed >= next_sample or elapsed >= seconds:
                    item = sample(config, elapsed, previous)
                    log.write(json.dumps(item, ensure_ascii=False) + "\n")
                    log.flush()
                    report.update(sample_count=report["sample_count"]+1, elapsed_seconds=elapsed, latest=item)
                    previous = item
                    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
                    print(json.dumps({"elapsed_seconds":round(elapsed, 2),"sample_count":report["sample_count"]}), flush=True)
                    next_sample += sample_seconds
                if elapsed >= seconds:
                    break
                time.sleep(min(1, seconds-elapsed))
        report["retention"] = client(config, {"command":"retention"})
        report["final"] = client(config, {"command":"status"})
        report["status"] = "completed"
    except BaseException as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if started:
            try:
                report["stop"] = stop(config)
            except Exception as exc:
                report["stop"] = {"error":str(exc)}
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True)
    p.add_argument("--seconds", type=float, default=86400)
    p.add_argument("--sample-seconds", type=float, default=60)
    p.add_argument("--event-seconds", type=float, default=120)
    p.add_argument("--model-path", default="")
    p.add_argument("--mode", choices=["eco", "responsive"], default="eco")
    p.add_argument("--activity", choices=["idle", "events"], default="events")
    args = p.parse_args()
    run(args.output, args.seconds, args.sample_seconds, args.event_seconds, args.model_path, args.mode, args.activity)


if __name__ == "__main__":
    main()
