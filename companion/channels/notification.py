import subprocess
import shutil
import sys

SCRIPT = '''on run argv
    display notification (item 1 of argv) with title "Companion V0"
end run
'''


def notify(message):
    if sys.platform.startswith('linux'):
        executable = shutil.which('notify-send')
        if not executable:
            return 'unavailable'
        try:
            p = subprocess.run([executable, '--app-name=LocalPilot Companion', '--', 'LocalPilot Companion', message[:300]],
                               text=True, capture_output=True, timeout=5)
            return 'submitted_visibility_unverified' if p.returncode == 0 else 'unavailable'
        except (OSError, subprocess.TimeoutExpired):
            return 'unavailable'
    if sys.platform != "darwin":
        return "unavailable_non_macos"
    try:
        p = subprocess.run(["/usr/bin/osascript", "-", message[:300]], input=SCRIPT, text=True, capture_output=True, timeout=5)
        return "submitted_visibility_unverified" if p.returncode == 0 else "unavailable"
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
