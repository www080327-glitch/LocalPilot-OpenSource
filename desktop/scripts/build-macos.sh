#!/bin/sh
# One shared disposable build slot; immutable delivery folders contain archives only.
set -eu
[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] || { echo 'Requires macOS arm64' >&2; exit 1; }
LP_GUI_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$LP_GUI_ROOT"
if [ "${LP_GUI_BUILD_LOCK_HELD:-0}" != 1 ]; then exec python3 scripts/build-locked.py "$@"; fi
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-1}"
# Keep compiler diagnostics/panic locations out of the maintainer's home path.
# Preserve existing flags, including encoded flags containing spaces.
CARGO_ENCODED_RUSTFLAGS=$(python3 - <<'LP_FLAGS'
import os,shlex
from pathlib import Path
existing=os.environ.get('CARGO_ENCODED_RUSTFLAGS')
flags=existing.split('\x1f') if existing else shlex.split(os.environ.get('RUSTFLAGS',''))
flags.append('--remap-path-prefix='+str(Path.home())+'=/LocalPilotBuild')
print('\x1f'.join(flags),end='')
LP_FLAGS
)
export CARGO_ENCODED_RUSTFLAGS
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$HOME/.cache/localpilot-desktop/target}"
LP_GUI_PRODUCT_NAME=$(python3 - <<'LP_PY'
import json,os
from pathlib import Path
name=json.loads(Path('src-tauri/tauri.conf.json').read_text())['productName']
if os.environ.get('LP_GUI_TEST_CONFIG'):
    name=json.loads(Path(os.environ['LP_GUI_TEST_CONFIG']).read_text()).get('productName',name)
if not name or '/' in name or '\\' in name:raise SystemExit('Invalid application name')
print(name)
LP_PY
)
export LP_GUI_BUILD_APP="$CARGO_TARGET_DIR/release/bundle/macos/$LP_GUI_PRODUCT_NAME.app"
python3 - <<'PY'
import os,subprocess
p=os.environ['LP_GUI_BUILD_APP']+'/'
if p in subprocess.check_output(['ps','-axo','command='],text=True):
    raise SystemExit('The build slot is in use. Stop its GUI and Core explicitly before building.')
PY
if [ "${LP_GUI_USE_INSTALLED_DEPS:-0}" != 1 ]; then
  [ ! -L node_modules ] || { echo 'Dependency link preserved: use LP_GUI_USE_INSTALLED_DEPS=1 after verifying installed dependencies' >&2; exit 1; }
  npm ci
fi
LP_GUI_VERSION=$(node -p 'JSON.parse(require("fs").readFileSync("package.json")).version')
LP_GUI_RUN=$(date +%Y%m%d-%H%M%S)-$$
LP_GUI_OUTPUT="$LP_GUI_ROOT/release/v$LP_GUI_VERSION/$LP_GUI_RUN"
if [ -n "${LP_GUI_TEST_CONFIG:-}" ]; then
  [ -f "$LP_GUI_TEST_CONFIG" ] || { echo 'Explicit test configuration is missing' >&2; exit 1; }
  LP_GUI_OUTPUT="$LP_GUI_ROOT/release/test-v$LP_GUI_VERSION/$LP_GUI_RUN"
fi
python3 ../scripts/check-candidate-versions.py
python3 scripts/check-bundled-backends.py
[ ! -e "$LP_GUI_OUTPUT" ] || { echo 'Existing output preserved' >&2; exit 1; }
if [ -n "${LP_GUI_TEST_CONFIG:-}" ]; then
  npm run tauri -- build --bundles app --config "$LP_GUI_TEST_CONFIG"
else
  npm run tauri -- build --bundles app
fi
# C dependencies can retain host paths in Mach-O debug symbols even when Rust
# source locations are remapped. Strip only this newly generated ad-hoc APP.
if /usr/bin/codesign -dvv "$LP_GUI_BUILD_APP" 2>&1 | /usr/bin/grep -q 'Signature=adhoc'; then
  /usr/bin/strip -S "$LP_GUI_BUILD_APP/Contents/MacOS/localpilot-desktop"
  /usr/bin/codesign --force --sign - --preserve-metadata=identifier,entitlements,flags,runtime "$LP_GUI_BUILD_APP/Contents/MacOS/localpilot-desktop"
  /usr/bin/codesign --force --sign - --preserve-metadata=identifier,entitlements,flags,runtime "$LP_GUI_BUILD_APP"
fi
mkdir -p "$LP_GUI_OUTPUT"
/usr/bin/xattr -rd com.apple.FinderInfo "$LP_GUI_BUILD_APP" 2>/dev/null || true
/usr/bin/xattr -rd com.apple.ResourceFork "$LP_GUI_BUILD_APP" 2>/dev/null || true
/usr/bin/codesign --verify --deep --strict "$LP_GUI_BUILD_APP"
python3 scripts/archive-app.py "$LP_GUI_BUILD_APP" "$LP_GUI_OUTPUT/LocalPilot-$LP_GUI_VERSION-arm64.app.zip"
# Staging is newly generated disposable data; no retained build or installation is removed.
LP_GUI_PACKAGE_OUTPUT="$LP_GUI_OUTPUT" LP_GUI_PACKAGE_APP="$LP_GUI_BUILD_APP" LP_GUI_PACKAGE_VERSION="$LP_GUI_VERSION" python3 scripts/package-release.py
printf '%s\n' "$LP_GUI_OUTPUT"
