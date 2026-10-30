"""Adopt the already running development batch, then run one frozen evaluation."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
E=ROOT/'docs/evidence/aic-final-20261029'
sys.path.insert(0,str(ROOT))
from benchmarks.aic_bfcl import power_guard


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--development-pid',type=int,required=True)
    args=parser.parse_args()
    os.environ['AIC_POWER_POLICY']='normal-ac'
    import psutil
    def owned(pid,run):
        try:
            process=psutil.Process(pid)
            command=process.cmdline()
            if process.status()==psutil.STATUS_ZOMBIE:return False
            if 'benchmarks.aic_local_study' not in command or run not in command:
                raise RuntimeError('Process ownership mismatch')
            if Path(process.cwd()).resolve()!=ROOT:raise RuntimeError('Unexpected process directory')
            return True
        except psutil.NoSuchProcess:return False
    def wait(pid,run,seconds):
        deadline=time.monotonic()+seconds
        while owned(pid,run):
            try:
                power_guard()
                if time.monotonic()>deadline:raise TimeoutError('Bounded stage deadline')
            except BaseException:
                if owned(pid,run):os.killpg(pid,signal.SIGINT)
                raise
            time.sleep(3)
    print('Adopt existing development; do not restart or duplicate it',flush=True)
    wait(args.development_pid,'bfcl-development-adapted2',3600)
    development=E/'bfcl-development-adapted2'
    status=json.loads((development/'driver-status.json').read_text())
    if not status.get('all_expected_instances_completed') or len(list(development.glob('*/result.json')))!=14:
        raise RuntimeError('Incomplete development; independent evaluation not launched')
    power_guard()
    print('Development complete; launch frozen three-instance evaluation',flush=True)
    command=[sys.executable,'-m','benchmarks.aic_local_study','--split','evaluation',
             '--manifest',str(E/'bfcl-protocol-qualified.json'),'--run','bfcl-evaluation-adapted2',
             '--ledger',str(ROOT/'.aic-runtime/cloud-ledger-adapted2.sqlite3')]
    with (E/'evaluation-adapted2.log').open('x') as log:
        child=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
        wait(child.pid,'bfcl-evaluation-adapted2',5400)
        code=child.wait()
    result={'development_complete':True,'evaluation_exit_code':code,
            'evaluation':json.loads((E/'bfcl-evaluation-adapted2/driver-status.json').read_text())}
    (E/'resumed-cycle-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
