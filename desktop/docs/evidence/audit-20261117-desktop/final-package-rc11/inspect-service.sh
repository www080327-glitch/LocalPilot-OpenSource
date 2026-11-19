#!/bin/bash
set -eu
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
unset PYTHONHOME PYTHONPATH
exec /workspace/scratch/c0f3ec78c621/native-rc11-g/client/modules/bundle-b8a776f2092763174dbb/runtime/bin/python /workspace/scratch/c0f3ec78c621/validation/package-b28-b8-b32-DtZ0R2/native-smoke/inspect-service.py
