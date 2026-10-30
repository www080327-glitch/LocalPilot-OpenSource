#!/bin/zsh
set -eu
COMPANION_TRIAL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$COMPANION_TRIAL_ROOT"
COMPANION_TRIAL_PY="/Users/localpilot-user/Desktop/aic竞赛/LocalPilot-companion-v0/companion/.venv/bin/python"
COMPANION_TRIAL_CONFIG="$COMPANION_TRIAL_ROOT/companion/.data/daily-trial/config.json"
"$COMPANION_TRIAL_PY" -m companion.runtime.daily_trial start --companion-config "$COMPANION_TRIAL_CONFIG"
