import subprocess
import sys

SCRIPT = '''on run argv
    display notification (item 1 of argv) with title "Companion V0"
end run
'''


def notify(message):
    if sys.platform != "darwin":
        return "unavailable_non_macos"
    try:
        p = subprocess.run(["/usr/bin/osascript", "-", message[:300]], input=SCRIPT, text=True, capture_output=True, timeout=5)
        return "submitted_visibility_unverified" if p.returncode == 0 else "unavailable"
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
