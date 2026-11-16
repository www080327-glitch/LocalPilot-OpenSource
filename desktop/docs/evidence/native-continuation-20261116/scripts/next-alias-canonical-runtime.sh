#!/bin/bash
set -eu
cd /workspace/scratch/2a488f6eabf5/validation/polish-20261116/desktop/profile-resume-20261116
/usr/bin/python3 stop.py r19-a-alias
bash launch.sh r20-a-alias /workspace/scratch/2a488f6eabf5/validation/polish-20261116/desktop/native-final-profile-a-alias &
