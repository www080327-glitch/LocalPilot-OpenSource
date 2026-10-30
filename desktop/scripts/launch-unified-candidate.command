#!/bin/sh
# Isolated engineering candidate; preserves the one daily installation.
set -eu
LP_CANDIDATE_APP=${1:-"$HOME/.cache/localpilot-desktop/target/release/bundle/macos/LocalPilot.app"}
LP_CANDIDATE_ROOT=${LP_CANDIDATE_HOME:-"$HOME/.local/share/localpilot-unified-candidate-20261025"}
LP_CANDIDATE_ID=$(/usr/bin/plutil -extract CFBundleIdentifier raw -o - "$LP_CANDIDATE_APP/Contents/Info.plist")
LP_CANDIDATE_VERSION=$(/usr/bin/plutil -extract CFBundleShortVersionString raw -o - "$LP_CANDIDATE_APP/Contents/Info.plist")
[ "$LP_CANDIDATE_ID" = io.localpilot.desktop.test ] && [ "$LP_CANDIDATE_VERSION" = 5.0.0-beta.3-dev.19-unified.7 ] || { echo 'Candidate identity differs; no application opened.' >&2; exit 1; }
/usr/bin/codesign --verify --deep --strict "$LP_CANDIDATE_APP"
umask 077
[ ! -L "$LP_CANDIDATE_ROOT" ] || { echo 'Candidate data must not be a symlink.' >&2; exit 1; }
mkdir -p "$LP_CANDIDATE_ROOT"
[ "$(/usr/bin/stat -f %u "$LP_CANDIDATE_ROOT")" = "$(/usr/bin/id -u)" ] || exit 1
if [ ! -e "$LP_CANDIDATE_ROOT/test-owner.json" ]; then
  printf '%s\n' '{"purpose":"LocalPilot installation E2E"}' > "$LP_CANDIDATE_ROOT/test-owner.json"
fi
[ "$(/usr/bin/plutil -extract purpose raw -o - "$LP_CANDIDATE_ROOT/test-owner.json")" = 'LocalPilot installation E2E' ] || exit 1
exec /usr/bin/open -g --env "LP_INSTALL_TEST_ROOT=$LP_CANDIDATE_ROOT" "$LP_CANDIDATE_APP"
