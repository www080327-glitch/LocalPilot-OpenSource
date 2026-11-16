#!/bin/bash
set -eu
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
unset PYTHONHOME PYTHONPATH
exec /workspace/scratch/c0f3ec78c621/native-rc13-i/client/modules/bundle-295f77018b216b1877d3/runtime/bin/python /workspace/scratch/c0f3ec78c621/validation/package-b30-b8-b32-WdAimn/native-smoke/inspect-service.py
