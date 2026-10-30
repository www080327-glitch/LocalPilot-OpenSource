"""Bounded stdio transport to our public-AX Swift helper (not Codex private IPC)."""
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import threading
import time

from .build import BUILD


class MacOSAXAdapter:
    def __init__(self, allowed_apps, *, binary=None, timeout=8):
        if sys.platform != "darwin":
            raise RuntimeError("macOS is required")
        self.allowed_apps = frozenset(allowed_apps)
        binary = Path(binary or BUILD / "axbridge")
        if not binary.is_file():
            raise RuntimeError("Run python3 -m computer.build first.")
        self.timeout = timeout
        self.lock = threading.Lock()
        self.process = subprocess.Popen([str(binary), *sorted(self.allowed_apps)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def request(self, **request):
        with self.lock:
            if self.process.poll() is not None:
                raise RuntimeError("AX helper is closed; recreate adapter and observe before retrying.")
            raw = json.dumps(request, ensure_ascii=False).encode() + b"\n"
            if len(raw) > 32768:
                raise ValueError("AX request exceeds bound")
            self.process.stdin.write(raw)
            self.process.stdin.flush()
            deadline = time.monotonic() + self.timeout
            response = bytearray()
            while not response.endswith(b"\n"):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self.selector.select(remaining):
                    self.close(force=True)
                    outcome = "action outcome UNKNOWN; no automatic replay" if request.get("op") in {"action", "native_text", "cu_focus", "cu_text", "cu_shortcut", "cu_click", "cu_double_click", "cu_select"} else "read failed; no action dispatched"
                    raise TimeoutError("AX helper timeout; " + outcome)
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk or len(response) + len(chunk) > 2_000_000:
                    self.close(force=True)
                    raise RuntimeError("Invalid or oversized AX helper response")
                response.extend(chunk)
                if b"\n" in response[:-1]:
                    self.close(force=True)
                    raise RuntimeError("Unexpected AX helper response frames")
            try:
                return json.loads(response)
            except (ValueError, UnicodeError):
                self.close(force=True)
                raise RuntimeError("Invalid AX helper JSON response") from None

    def environment(self):
        return self.request(op="environment")["environment"]

    def inspect_apps(self):
        return self.request(op="inspect_apps")

    def inspect_tree(self, app, **bounds):
        return self.request(op="inspect_tree", app=app, **bounds)

    def action(self, app, handle, kind, **args):
        return self.request(op="action", app=app, handle=handle, kind=kind, **args)

    def close(self, *, force=False):
        self.selector.close()
        if self.process.poll() is None and not force:
            # A healthy stdio helper exits cooperatively on EOF. Forceful
            # timeout/error shutdown remains immediate and never replays input.
            try:self.process.stdin.close()
            except OSError:pass
            try:self.process.wait(timeout=.5)
            except subprocess.TimeoutExpired:pass
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill();self.process.wait()
        for pipe in (self.process.stdin,self.process.stdout):
            pipe.close()
