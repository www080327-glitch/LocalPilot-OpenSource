#!/bin/bash
set -eu
cd <PREVIOUS_WORKSPACE>/LocalPilot-polish-final-20261116
source <PREVIOUS_WORKSPACE>/validation/linux-20261116/desktop/toolchain/environment.sh
export PYTHONPATH="$PWD/suite"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export LOCALPILOT_WORKER_BUDGET_LEGACY_SOURCE=<PREVIOUS_WORKSPACE>/LocalPilot-polish-20261116
python - <<'PY'
import subprocess,time,json,pathlib,re,sys,os
out=pathlib.Path('<WORKSPACE>/validation/final-regression')
py='<PREVIOUS_WORKSPACE>/LocalPilot-OpenSource/.venv/bin/python'
source=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
runs=[]
for name,args in [('core',['discover','-s','tests','-t','.','-v']),('suite',['discover','-s','suite/tests','-t','suite','-v']),('companion',['discover','-s','companion/tests','-t','.','-v'])]:
 command=[py,'-m','unittest',*args]
 started=time.monotonic()
 with (out/(name+'-final-r1.log')).open('w') as log:
  result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
 text=(out/(name+'-final-r1.log')).read_text()
 row={'name':name,'command':command,'source_commit':source,'returncode':result.returncode,'wall_seconds':round(time.monotonic()-started,3),'summary':text[-1300:]}
 runs.append(row)
 (out/'RUN_SUMMARY.json').write_text(json.dumps({'source_commit':source,'runs':runs},indent=2)+'\n')
 print(json.dumps(row),flush=True)
raise SystemExit(any(row['returncode'] for row in runs))
PY
