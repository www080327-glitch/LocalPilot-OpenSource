#!/bin/bash
set -eu
umask 077
cd /workspace/scratch/c0f3ec78c621/validation/audit-20261117
/workspace/scratch/2a488f6eabf5/LocalPilot-OpenSource/.venv/bin/python - <<'PYCODE'
from pathlib import Path
import json,os,platform,time
value={'started_unix':time.time(),'wrapper_pid':os.getppid(),'python':platform.python_version(),'source_commit':'03535fe943f64f49e9e3d79e7949aca6c9ec9b87','pid_namespace':os.readlink('/proc/self/ns/pid'),'network_namespace':os.readlink('/proc/self/ns/net'),'network_configuration_changes':False}
with Path('cloud-soak-2h-r4-b28-native-surface.json').open('x') as stream:json.dump(value,stream,indent=2)
print(json.dumps(value),flush=True)
PYCODE
/workspace/scratch/2a488f6eabf5/LocalPilot-OpenSource/.venv/bin/python run_qualification_job.py cloud-soak-2h-r4-b28-native-job.json
