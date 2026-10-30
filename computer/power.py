"""Opt-in idle-system-sleep assertion with a bounded process lifetime; no display wake."""
import os
import subprocess
import sys


class AwakeLease:
    def __init__(self, enabled=False):
        self.enabled = enabled
        self.process = None

    def __enter__(self):
        if self.enabled:
            if sys.platform != "darwin":
                raise RuntimeError("Awake lease requires macOS")
            # -i prevents idle SYSTEM sleep. No -d (display assertion), -u
            # (user activity/display wake), or -s (broader system assertion).
            self.process = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return self

    def __exit__(self, *exc):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
