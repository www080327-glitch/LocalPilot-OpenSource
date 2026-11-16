#!/bin/bash
set -eu
cd /workspace/scratch/c0f3ec78c621/validation/audit-20261117
[ ! -e build-rc14-native.log ] && [ ! -e build-rc14-native-exit.json ]
exec /workspace/scratch/2a488f6eabf5/LocalPilot-OpenSource/.venv/bin/python -B run_qualification_job.py build-rc14-native-job.json
