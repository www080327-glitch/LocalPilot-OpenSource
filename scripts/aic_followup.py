"""Bounded sequential follow-up stages; never overlaps owned model services."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];E=ROOT/'docs/evidence/aic-final-20261029'
status=E/'bfcl-evaluation-final1/local-unloaded.json'
deadline=time.monotonic()+7200
while not status.exists():
    if time.monotonic()>deadline:raise TimeoutError('Evaluation completion deadline; no follow-up model launched')
    time.sleep(2)

stages=[
 ('cache-local',['-m','benchmarks.aic_cache_local','--output',str(E/'local-cache1')],2400),
 ('selector-quality',['-m','benchmarks.aic_selector_quality','--output',str(E/'selector-quality1'),'--manifest',str(E/'bfcl-protocol-evaluation.json')],3600),
 ('cache-delayed',['-m','benchmarks.aic_cache_delayed','--output',str(E/'cloud-cache-delayed.json')],120),
]
results=[]
for name,args,limit in stages:
    print(name+' starting',flush=True)
    with (E/(name+'-followup.log')).open('w') as log:
        child=subprocess.Popen([sys.executable,*args],cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
        try:code=child.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGINT)
            try:child.wait(timeout=60)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
            code=None
    results.append({'stage':name,'exit_code':code,'wall_ceiling_seconds':limit})
    (E/'followup-stages.json').write_text(json.dumps(results,indent=2)+'\n')
    print(name+' finished: '+str(code),flush=True)
