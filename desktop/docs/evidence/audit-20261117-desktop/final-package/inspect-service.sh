#!/bin/bash
set -eu
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
unset PYTHONHOME PYTHONPATH
exec /workspace/scratch/c0f3ec78c621/validation/package-b27-b8-b32-Azb7vG/native-smoke/profile-e/client/modules/bundle-9e492311f5d49615e283/runtime/bin/python /workspace/scratch/c0f3ec78c621/validation/package-b27-b8-b32-Azb7vG/native-smoke/inspect-service.py
