#!/bin/bash
set -eu
source /workspace/scratch/2a488f6eabf5/validation/linux-20261116/desktop/toolchain/environment.sh
cd /workspace/scratch/c0f3ec78c621/validation/native-audit-20261117/build-source/desktop
export LP_GUI_USE_INSTALLED_DEPS=1
export LP_GUI_TEST_CONFIG=src-tauri/tauri.test.conf.json
bash scripts/build-linux.sh
