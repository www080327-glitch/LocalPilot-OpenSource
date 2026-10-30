"""Bounded CLI resource heartbeat. Uses public API only; never executes tools."""
import argparse,json,os,time
from pathlib import Path
from urllib.error import HTTPError,URLError
from .sdk import Client
from .security import private_json


def run(home, record_path):
    from .cli import lock,save
    import psutil
    with lock(home,'control-'+record_path.stem+'.lock'):
        record=private_json(record_path)
        token=os.environ.get('LOCALPILOT_HEARTBEAT_TOKEN')
        if not token:raise ValueError('Ordinary client credential unavailable')
        client=Client(record['url'],token=token,timeout=10)
        record.update(pid=os.getpid(),created=psutil.Process().create_time(),state='monitoring')
        save(record_path,record)
        deadline=time.monotonic()+max(0,min(3630,record['expires_at']-time.time()))
        failures=0;next_status=0
        while time.monotonic()<deadline:
            try:
                if time.monotonic()>=next_status:
                    task=client.status(record['task_id'])
                    if task.get('quiescent') and task.get('status') in {'completed','incomplete','failed','cancelled','timed_out'}:
                        record.update(state='finished',task_status=task['status']);save(record_path,record);return 0
                    next_status=time.monotonic()+16
                client.request('/localpilot/v1/inference/heartbeat',{'task_id':record['task_id'],'ticket_id':record['ticket']})
                failures=0
            except (HTTPError,URLError,OSError,ValueError):
                failures+=1
                if failures>=3:
                    record.update(state='connection_lost');save(record_path,record);return 1
            time.sleep(8)
        record.update(state='deadline_elapsed');save(record_path,record);return 0


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--home',required=True);parser.add_argument('--record',required=True)
    args=parser.parse_args();home=Path(args.home).resolve();record=Path(args.record).resolve()
    if record.parent!=home:parser.error('Controller record must be inside its private data directory')
    try:return run(home,record)
    except (ValueError,OSError):return 2


if __name__=='__main__':raise SystemExit(main())
