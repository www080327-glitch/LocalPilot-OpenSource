#!/bin/bash
set -eu
source /workspace/scratch/2a488f6eabf5/validation/linux-20261116/desktop/toolchain/environment.sh
exec /usr/bin/python3 /workspace/scratch/2a488f6eabf5/validation/polish-20261116/desktop/profile-resume-20261116/launch.py "$@"
