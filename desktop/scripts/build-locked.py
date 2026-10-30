"""Serialize all worktrees' Desktop packaging without a stale lock directory."""
import fcntl
import os
from pathlib import Path
import subprocess
import sys

path=Path.home()/'.cache/localpilot-desktop/build.lock'
path.parent.mkdir(parents=True,exist_ok=True)
with path.open('a') as lock:
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('Another Desktop build is active; wait for its delivery receipt.')
    raise SystemExit(subprocess.call([str(Path(__file__).with_name('build-macos.sh')),*sys.argv[1:]],env={**os.environ,'LP_GUI_BUILD_LOCK_HELD':'1'}))
