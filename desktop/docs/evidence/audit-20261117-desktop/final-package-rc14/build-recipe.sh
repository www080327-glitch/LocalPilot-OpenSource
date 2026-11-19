#!/bin/bash
set -eu

# Build only the frozen published source; root explicitly authorized this single-worker build alongside the cloud-only validation jobs.
[ "$#" -eq 2 ] || { echo "usage: script FROZEN_CHECKOUT FULL_COMMIT_SHA" >&2; exit 2; }
export LP_PKG_SOURCE="$1"
LP_PKG_FROZEN="$2"
export LP_PKG_DEPENDENCIES=/workspace/scratch/2a488f6eabf5/LocalPilot-polish-final-20261116/desktop
LP_PKG_PYTHON=/workspace/scratch/2a488f6eabf5/LocalPilot-OpenSource/.venv/bin/python
mkdir -p /workspace/scratch/c0f3ec78c621/validation
export LP_PKG_RUN
LP_PKG_RUN=$(mktemp -d /workspace/scratch/c0f3ec78c621/validation/package-b31-b8-b32-XXXXXX)
printf '%s\n' "$LP_PKG_RUN"

source /workspace/scratch/2a488f6eabf5/validation/linux-20261116/desktop/toolchain/environment.sh
export PATH="/opt/codex/runtimes/codex-primary-runtime/dependencies/node/bin:$PATH"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export PIP_NO_INDEX=1 CARGO_NET_OFFLINE=true CARGO_BUILD_JOBS=1
cd "$LP_PKG_SOURCE"
[ "$(git rev-parse HEAD)" = "$LP_PKG_FROZEN" ] || { echo "Frozen source commit differs from HEAD" >&2; exit 2; }
git diff --check
"$LP_PKG_PYTHON" scripts/check-candidate-versions.py > "$LP_PKG_RUN/candidate-versions.json"

"$LP_PKG_PYTHON" - <<'PY'
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

root = Path(os.environ['LP_PKG_SOURCE'])
run = Path(os.environ['LP_PKG_RUN'])
stage = run / 'build-source'
subprocess.run(['git', 'worktree', 'add', '--detach', '--no-checkout', str(stage), 'HEAD'], cwd=root, check=True)
subprocess.run(['git', 'read-tree', 'HEAD'], cwd=stage, check=True)
paths = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root).split(b'\0')
files = {}
for encoded in sorted(set(paths)):
    if not encoded:
        continue
    relative = encoded.decode()
    source = root / relative
    if not source.is_file():
        continue
    if source.suffix.lower() in {'.db', '.sqlite', '.sqlite3', '.gguf', '.safetensors', '.pt', '.pth'}:
        continue
    destination = stage / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    files[relative] = hashlib.sha256(destination.read_bytes()).hexdigest()
snapshot = {'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
            'source_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root)),
            'files': files}
(run / 'SOURCE_SNAPSHOT.json').write_text(json.dumps(snapshot, indent=2) + '\n')
(run / 'wheels').mkdir()
dependencies = Path(os.environ['LP_PKG_DEPENDENCIES'])
locked_sha = hashlib.sha256((root / 'desktop/package-lock.json').read_bytes()).hexdigest()
if locked_sha != hashlib.sha256((dependencies / 'package-lock.json').read_bytes()).hexdigest():
    raise SystemExit('Frozen dependency lock differs from the verified installed frontend dependencies')
(stage / 'desktop/node_modules').symlink_to(dependencies / 'node_modules', target_is_directory=True)
previous = run / 'previous-target-artifacts'
previous.mkdir()
target = Path(os.environ['CARGO_TARGET_DIR'])
for source in sorted((target / 'release/bundle/deb').glob('*.deb')):
    shutil.copy2(source, previous / source.name)
for name in ('localpilot-desktop', 'localpilot-desktop-test'):
    source = target / 'release' / name
    if source.is_file():
        shutil.copy2(source, previous / name)
PY

"$LP_PKG_PYTHON" -m build --wheel --no-isolation --outdir "$LP_PKG_RUN/wheels" "$LP_PKG_RUN/build-source" > "$LP_PKG_RUN/wheel-core.log" 2>&1
"$LP_PKG_PYTHON" -m build --wheel --no-isolation --outdir "$LP_PKG_RUN/wheels" "$LP_PKG_RUN/build-source/companion" > "$LP_PKG_RUN/wheel-companion.log" 2>&1
"$LP_PKG_PYTHON" -m build --wheel --no-isolation --outdir "$LP_PKG_RUN/wheels" "$LP_PKG_RUN/build-source/suite" > "$LP_PKG_RUN/wheel-suite.log" 2>&1
"$LP_PKG_PYTHON" "$LP_PKG_RUN/build-source/scripts/build_channels_wheel.py" --no-isolation --out "$LP_PKG_RUN/wheels" > "$LP_PKG_RUN/wheel-channels.log" 2>&1

cd "$LP_PKG_RUN/build-source"
"$LP_PKG_PYTHON" desktop/scripts/linux_backends.py prepare \
  --python /usr/bin/python3.13 \
  --wheels "$LP_PKG_RUN/wheels" \
  --dependencies /workspace/scratch/2a488f6eabf5/validation/linux-20261116/desktop/dependencies \
  --dependency-lock desktop/runtime-dependencies-linux-x86_64-py313.json \
  --channel-runtime /workspace/scratch/2a488f6eabf5/validation/linux-20261116/runtime-inputs/node-v22.23.4-linux-x64.tar.gz \
  > "$LP_PKG_RUN/prepare-resources.log" 2>&1

"$LP_PKG_PYTHON" "$LP_PKG_SOURCE/desktop/scripts/linux_backends.py" check \
  --output "$LP_PKG_RUN/build-source/desktop/src-tauri/bundled-backends" \
  > "$LP_PKG_RUN/verify-resources-against-original-source.log" 2>&1
cp desktop/src-tauri/bundled-backends/verified-modules.json "$LP_PKG_RUN/VERIFIED_MODULES.json"

cd desktop
LP_GUI_USE_INSTALLED_DEPS=1 LP_GUI_TEST_CONFIG=src-tauri/tauri.test.conf.json npm run release:linux > "$LP_PKG_RUN/build-linux-test.log" 2>&1
tail -n 1 "$LP_PKG_RUN/build-linux-test.log" > "$LP_PKG_RUN/delivery-directory.txt"
"$LP_PKG_PYTHON" "$LP_PKG_SOURCE/desktop/scripts/linux_backends.py" check \
  --output "$LP_PKG_RUN/build-source/desktop/src-tauri/bundled-backends" \
  > "$LP_PKG_RUN/verify-resources-after-build.log" 2>&1
printf '%s\n' "Build logs and source snapshot: $LP_PKG_RUN"
cat "$LP_PKG_RUN/delivery-directory.txt"
