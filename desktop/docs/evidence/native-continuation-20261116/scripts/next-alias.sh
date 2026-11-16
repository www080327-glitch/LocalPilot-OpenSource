#!/bin/bash
set -eu
cd /workspace/scratch/2a488f6eabf5/validation/polish-20261116/desktop/profile-resume-20261116
/usr/bin/python3 stop.py r17-b-reopen
bash launch.sh r18-a-alias /workspace/scratch/2a488f6eabf5/validation/polish-20261116/desktop/native-final-profile-a-alias &
