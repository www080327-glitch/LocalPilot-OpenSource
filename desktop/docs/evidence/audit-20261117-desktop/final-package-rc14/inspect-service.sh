#!/bin/bash
set -eu
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
unset PYTHONHOME PYTHONPATH
exec '/workspace/scratch/c0f3ec78c621/native-rc14-k/client/modules/bundle-cdf295c7d9b19837d0c8/runtime/bin/python' '/workspace/scratch/c0f3ec78c621/validation/package-b31-b8-b32-LtvhM6/native-smoke/inspect-service.py'
