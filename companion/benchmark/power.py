"""Real daemon residence tests. Checkpoints are nested in the same continuous run."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import platform
import sys
import time

from companion.cli import client, start, stop
from companion.config import Config


def snapshot(config, elapsed):
    import psutil
    state = client(config, {"command":"status"})
    worker_pid = state["model"]["worker_pid"]
    worker_cpu = None
    if worker_pid:
        try:
            worker_cpu = sum(psutil.Process(worker_pid).cpu_times()[:2])
        except psutil.Error:
            pass
    root = Path(config.data_dir)
    sizes = {p.name:p.stat().st_size for p in root.glob("memory.sqlite3*")}
    return {"elapsed_seconds":elapsed, "status":state, "worker_cpu_seconds":worker_cpu,
            "sqlite_bytes":sizes, "notices":len(client(config, {"command":"notices"})["notices"])}


def summarize(samples):
    first, last = samples[0], samples[-1]
    duration = last["elapsed_seconds"]-first["elapsed_seconds"]
    rss = [s["status"]["service_rss_bytes"] for s in samples]
    workers = [s["status"]["model"]["worker_rss_bytes"] or 0 for s in samples]
    worker_cpu = 0.0
    for a,b in zip(samples,samples[1:]):
        if a["status"]["model"]["worker_pid"] and a["status"]["model"]["worker_pid"] == b["status"]["model"]["worker_pid"] and a["worker_cpu_seconds"] is not None and b["worker_cpu_seconds"] is not None:
            worker_cpu += max(0,b["worker_cpu_seconds"]-a["worker_cpu_seconds"])
    # Last-half slope exposes sustained drift without calling allocator peak RSS.
    settled = samples[len(samples)//2:]
    xs = [s["elapsed_seconds"] for s in settled]
    ys = [s["status"]["service_rss_bytes"] for s in settled]
    mx, my = sum(xs)/len(xs), sum(ys)/len(ys)
    denom = sum((x-mx)**2 for x in xs)
    slope = sum((x-mx)*(y-my) for x,y in zip(xs,ys))/denom if denom else 0
    return {"duration_seconds":duration,
      "service_cpu_percent_one_core":100*(last["status"]["service_cpu_seconds"]-first["status"]["service_cpu_seconds"])/duration,
      "sampled_worker_cpu_percent_one_core_lower_bound":100*worker_cpu/duration,
      "service_rss_first_bytes":rss[0], "service_rss_last_bytes":rss[-1], "service_rss_peak_sampled_bytes":max(rss),
      "worker_rss_last_bytes":workers[-1], "worker_rss_peak_sampled_bytes":max(workers),
      "service_last_half_growth_bytes_per_hour":slope*3600,
      "model_invocations":last["status"]["model"]["inferences"]-first["status"]["model"]["inferences"],
      "model_wakeups":last["status"]["model"]["model_wakes_total"]-first["status"]["model"]["model_wakes_total"],
      "loop_wakeups":last["status"]["loop_wakeups"]-first["status"]["loop_wakeups"],
      "notification_count_delta":last["notices"]-first["notices"],
      "pending_files_max":max(s["status"]["pending_files"] for s in samples),
      "memory_records_delta":last["status"]["memory_count"]-first["status"]["memory_count"],
      "database_bytes_first":sum(first["sqlite_bytes"].values()), "database_bytes_last":sum(last["sqlite_bytes"].values()),
      "energy_watts":None, "energy_status":"UNKNOWN: no reliable unprivileged process power measurement",
      "no_obvious_service_growth":slope*3600 < 32*1024*1024,
      "idle_memory":rss[-1], "model_resident_memory":workers[-1],
      "errors":[s["status"]["last_error"] for s in samples if s["status"]["last_error"]]}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model-path',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--seconds',type=float,default=3600)
    p.add_argument('--sample-seconds',type=float,default=60)
    args=p.parse_args()
    if args.seconds < 10 or not 1 <= args.sample_seconds <= 60:
        p.error('duration >= 10 and sample interval 1..60 required')
    out=Path(args.output).resolve();out.parent.mkdir(parents=True,exist_ok=True)
    base=Path(__file__).resolve().parents[1]/'.data'/('power-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    base.mkdir(parents=True)
    evidence={'schema_version':1,'started_utc':datetime.now(timezone.utc).isoformat(),
              'requested_seconds':args.seconds,'sample_seconds':args.sample_seconds,
              'hardware':platform.platform(),'python':sys.version,
              'interference':'four services measured concurrently; other desktop applications uncontrolled',
              'workload':'one content change per 120s; identical touch burst per 180s; batches of 12 files at 1200s and 2400s',
              'arms':{}, 'status':'running','base_dir':str(base),
              'source_sha256':{str(p.relative_to(Path(__file__).resolve().parents[1])):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).resolve().parents[1].rglob('*.py') if not any(x in p.parts for x in ('.venv','.data','build'))}}
    configs={}
    try:
        for mode in ('eco','responsive'):
            for activity in ('idle','events'):
                name=mode+'_'+activity
                docs=base/name/'documents';docs.mkdir(parents=True)
                (docs/'project.txt').write_text('项目：星河\n预算：15万\n待办：整理材料\n')
                raw=asdict(Config()) | {'data_dir':str(base/name/'state'),'watch_dirs':[str(docs)],
                    'mode':mode,'model_path':str(Path(args.model_path).expanduser()),
                    'dnd':activity=='idle','notifications':False,'quiet_start_hour':0,'quiet_end_hour':0}
                filename=base/name/'config.json';filename.write_text(json.dumps(raw,ensure_ascii=False,indent=2))
                config=Config.load(filename);configs[name]=config
                initial=start(config,filename)
                warmup=client(config,{'command':'ask','text':'请用一句简短的话问候我。'})
                if warmup.get('model',{}).get('backend') != 'mlx' or warmup['status'] not in {'ok','truncated'}:
                    raise RuntimeError('Real MLX warmup failed: '+name)
                evidence['arms'][name]={'config':raw,'warmup':warmup,'samples':[], 'generated_changes':0}
        began=time.monotonic();sample_at=0;changed_at=120;touched_at=180;batches=set()
        while True:
            elapsed=time.monotonic()-began
            if elapsed>=changed_at and changed_at<args.seconds:
                for name,config in configs.items():
                    if name.endswith('_events'):
                        docs=Path(config.watch_dirs[0]);file=docs/'project.txt'
                        file.write_text(f'项目：星河\n预算：15万\n待办：整理材料\n测试事件序号：{int(changed_at//120)}\n')
                        evidence['arms'][name]['generated_changes']+=1
                changed_at+=120
            if elapsed>=touched_at and touched_at<args.seconds:
                for name,config in configs.items():
                    if name.endswith('_events'):
                        for _ in range(8): (Path(config.watch_dirs[0])/'project.txt').touch()
                touched_at+=180
            for batch_at in (1200,2400):
                if elapsed>=batch_at and batch_at not in batches and batch_at<=args.seconds:
                    for name,config in configs.items():
                        if name.endswith('_events'):
                            for i in range(12):
                                (Path(config.watch_dirs[0])/f'batch-{batch_at}-{i}.txt').write_text(f'普通批量文件 {i}\n')
                                evidence['arms'][name]['generated_changes']+=1
                    batches.add(batch_at)
            if elapsed>=sample_at or elapsed>=args.seconds:
                for name,config in configs.items():
                    snap=snapshot(config,elapsed)
                    evidence['arms'][name]['samples'].append(snap)
                    evidence['arms'][name]['summary']=summarize(evidence['arms'][name]['samples']) if len(evidence['arms'][name]['samples'])>1 else None
                evidence['elapsed_seconds']=elapsed
                out.write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
                print(json.dumps({'elapsed_seconds':round(elapsed),'samples':len(next(iter(evidence['arms'].values()))['samples'])}),flush=True)
                sample_at+=args.sample_seconds
            if elapsed>=args.seconds:
                break
            time.sleep(min(1,args.seconds-elapsed))
        evidence['status']='completed'
        for arm in evidence['arms'].values():
            for checkpoint in (1800,3600):
                prefix=[s for s in arm['samples'] if s['elapsed_seconds']<=checkpoint+args.sample_seconds]
                arm[f'checkpoint_{checkpoint}_seconds']=summarize(prefix) if evidence['elapsed_seconds']>=checkpoint else None
    except BaseException as exc:
        evidence['status']='failed';evidence['error']=f'{type(exc).__name__}: {exc}'
        raise
    finally:
        evidence['stops']={}
        for name,config in configs.items():
            try:evidence['stops'][name]=stop(config)
            except Exception as exc:evidence['stops'][name]={'error':str(exc)}
        out.write_text(json.dumps(evidence,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
