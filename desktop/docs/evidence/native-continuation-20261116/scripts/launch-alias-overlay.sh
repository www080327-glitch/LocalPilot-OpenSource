#!/bin/bash
# Validation-only minimal overlay. WebKit helpers and D-Bus proxy plus bubblewrap standard private /dev; no host device tree bind.
set -eu
if [ "$#" -ne 2 ]; then
  printf '%s\n' 'usage: launch-owned-webview-minimal.sh ABSOLUTE_CANDIDATE_EXECUTABLE ABSOLUTE_MARKED_TEST_ROOT' >&2
  exit 2
fi
LP_WEBKIT_CANDIDATE="$1"
LP_WEBKIT_TEST_ROOT="$2"
case "$LP_WEBKIT_CANDIDATE" in /*) ;; *) printf '%s\n' 'Candidate path must be absolute' >&2; exit 2 ;; esac
case "$LP_WEBKIT_TEST_ROOT" in /*) ;; *) printf '%s\n' 'Test root must be absolute' >&2; exit 2 ;; esac
[ -x "$LP_WEBKIT_CANDIDATE" ] || { printf '%s\n' 'Reviewed candidate is not executable' >&2; exit 2; }
[ -f "$LP_WEBKIT_TEST_ROOT/test-owner.json" ] || { printf '%s\n' 'Prepare a private marked test root first; the APP validates its identity' >&2; exit 2; }
if [ "${WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS+x}" = x ]; then
  printf '%s\n' 'Refusing inherited WebKit sandbox-disable environment' >&2
  exit 2
fi
LP_X11_AUTH_FILE="/dev/shm/codex-orbit-desktop/Xauthority"
[ "${XAUTHORITY:-}" = "$LP_X11_AUTH_FILE" ] && [ -f "$LP_X11_AUTH_FILE" ] && [ -r "$LP_X11_AUTH_FILE" ] || { printf '%s\n' 'The existing reviewed X11 credential file is required' >&2; exit 2; }
mkdir -p "$LP_WEBKIT_TEST_ROOT/tmp" "$LP_WEBKIT_TEST_ROOT/runtime"
chmod 700 "$LP_WEBKIT_TEST_ROOT/tmp" "$LP_WEBKIT_TEST_ROOT/runtime"
LP_WEBKIT_WRITABLE_ROOT="$(realpath -- "$LP_WEBKIT_TEST_ROOT")"
exec /usr/bin/bwrap --unshare-user --unshare-pid --ro-bind / / --proc /proc --dev /dev --die-with-parent \
 --ro-bind "$LP_X11_AUTH_FILE" "$LP_X11_AUTH_FILE" \
 --overlay-src /usr/lib/x86_64-linux-gnu \
 --overlay-src /workspace/scratch/2a488f6eabf5/validation/polish-20261116/desktop/webkit-minimal-overlay-r4/layer/lib \
 --ro-overlay /usr/lib/x86_64-linux-gnu \
 --overlay-src /usr/bin \
 --overlay-src /workspace/scratch/2a488f6eabf5/validation/polish-20261116/desktop/webkit-minimal-overlay-r4/layer/bin \
 --ro-overlay /usr/bin \
 --bind "$LP_WEBKIT_WRITABLE_ROOT" "$LP_WEBKIT_WRITABLE_ROOT" \
 --setenv LP_INSTALL_TEST_ROOT "$LP_WEBKIT_TEST_ROOT" \
 --setenv TMPDIR "$LP_WEBKIT_TEST_ROOT/tmp" \
 --setenv XDG_RUNTIME_DIR "$LP_WEBKIT_TEST_ROOT/runtime" \
 -- "$LP_WEBKIT_CANDIDATE"
