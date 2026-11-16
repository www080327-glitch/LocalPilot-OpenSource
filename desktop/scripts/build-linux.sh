#!/bin/sh
set -eu
[ "$(uname -s)" = Linux ] || { echo 'Requires native Linux' >&2; exit 1; }
LP_GUI_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$LP_GUI_ROOT"
if [ "${LP_GUI_BUILD_LOCK_HELD:-0}" != 1 ]; then exec python3 scripts/build-locked.py "$@"; fi
export CARGO_BUILD_JOBS=1
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$HOME/.cache/localpilot-desktop/target}"
if [ "${LP_GUI_USE_INSTALLED_DEPS:-0}" != 1 ]; then
  [ ! -L node_modules ] || { echo 'Existing dependency link preserved; set LP_GUI_USE_INSTALLED_DEPS=1 after verifying it' >&2; exit 1; }
  npm ci
fi
python3 ../scripts/check-candidate-versions.py
python3 scripts/linux_backends.py check
npm run tauri -- icon public/icon.svg
LP_GUI_VERSION=$(node -p 'JSON.parse(require("fs").readFileSync("package.json")).version')
LP_GUI_RUN=$(date +%Y%m%d-%H%M%S)-$$
LP_GUI_OUTPUT="$LP_GUI_ROOT/release/linux-v$LP_GUI_VERSION/$LP_GUI_RUN"
if [ -n "${LP_GUI_TEST_CONFIG:-}" ]; then LP_GUI_OUTPUT="$LP_GUI_ROOT/release/linux-test-v$LP_GUI_VERSION/$LP_GUI_RUN"; fi
export LP_GUI_OUTPUT
python3 - <<'PY'
import json,os
from pathlib import Path
out=Path(os.environ['LP_GUI_OUTPUT']);out.mkdir(parents=True,exist_ok=False)
config=json.loads(Path('src-tauri/tauri.linux.conf.json').read_text())
manifest=json.loads(Path('src-tauri/bundled-backends/manifest.json').read_text())
config['bundle']['linux']['deb']['depends'] += [manifest['python_debian_dependency']]
if os.environ.get('LP_GUI_TEST_CONFIG'):
    test=json.loads(Path(os.environ['LP_GUI_TEST_CONFIG']).read_text())
    if test.get('identifier')!='io.localpilot.desktop.test':raise SystemExit('Select the existing isolated Test identity')
    config.update(productName='LocalPilot Test',identifier=test['identifier'],mainBinaryName='localpilot-desktop-test')
    config['app']['windows'][0]['title']='LocalPilot Test'
(out/'build-config.json').write_text(json.dumps(config,indent=2)+'\n')
PY
npm run tauri -- build --bundles deb --config "$LP_GUI_OUTPUT/build-config.json" -- --locked
python3 scripts/package-linux.py
printf '%s\n' "$LP_GUI_OUTPUT"
