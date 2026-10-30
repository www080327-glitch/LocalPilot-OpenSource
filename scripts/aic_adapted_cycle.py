"""One final, bounded tool-contract qualification; independent IDs are frozen."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];E=ROOT/'docs/evidence/aic-final-20261029'
sys.path.insert(0,str(ROOT));from benchmarks.aic_bfcl import power_guard
os.environ['AIC_POWER_POLICY']='normal-ac'
deadline=time.monotonic()+7200
while True:
    qualified=E/'core-tools-final.json'
    if qualified.exists():
        result=json.loads(qualified.read_text())
        if not result['successful']:raise RuntimeError('Current prompt/source regression is not qualified')
        try:power_guard();break
        except RuntimeError:pass
    if time.monotonic()>deadline:raise TimeoutError('AC readiness deadline; no local model launched')
    time.sleep(5)

stages=[
 ('local-cache2-retry',['-m','benchmarks.aic_cache_local','--output',str(E/'local-cache2')],2400),
 ('development-adapted2',['-m','benchmarks.aic_local_study','--split','development','--manifest',str(E/'bfcl-protocol-qualified.json'),
    '--run','bfcl-development-adapted2','--ledger',str(ROOT/'.aic-runtime/cloud-ledger-adapted2.sqlite3')],3600),
 ('evaluation-adapted2',['-m','benchmarks.aic_local_study','--split','evaluation','--manifest',str(E/'bfcl-protocol-qualified.json'),
    '--run','bfcl-evaluation-adapted2','--ledger',str(ROOT/'.aic-runtime/cloud-ledger-adapted2.sqlite3')],5400),
]
results=[]
for name,args,limit in stages:
    power_guard();print(name+' starting',flush=True)
    with (E/(name+'.log')).open('w') as log:
        child=subprocess.Popen([sys.executable,*args],cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
        try:code=child.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGINT)
            try:child.wait(timeout=60)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
            code=None
    results.append({'stage':name,'exit_code':code,'wall_ceiling_seconds':limit})
    (E/'adapted-cycle-stages.json').write_text(json.dumps(results,indent=2)+'\n')
    print(name+' finished: '+str(code),flush=True)
    if name=='development-adapted2':
        status=E/'bfcl-development-adapted2/driver-status.json'
        if not status.exists() or not json.loads(status.read_text()).get('all_expected_instances_completed'):
            raise RuntimeError('Development did not complete; independent evaluation not launched')
