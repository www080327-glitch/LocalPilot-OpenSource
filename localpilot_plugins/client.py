"""Synchronous bounded bridge to one disposable SDK worker per server."""
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import threading
import time

from .security import MAX_FRAME


class TransportFailure(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class MCPClient:
    def __init__(self, config, credentials=None):
        self.config = config
        self.credentials = credentials or {}
        self.process = None
        self.lock = threading.Lock()
        self.cancelled = threading.Event()
        self.buffer = b""
        self.directory = None
        self.catalog = None
        self.cancel_at = None
        self.authorization_check = None
        self.watch_stop = threading.Event()

    def connect(self):
        self.close()
        if self.cancelled.is_set():
            raise TransportFailure('cancelled')
        self.cancel_at = None
        self.directory = tempfile.TemporaryDirectory(prefix="localpilot-plugin-")
        # Child SDK process has a private disposable cwd/HOME, explicit package
        # path and no inherited provider, operator, proxy or shell environment.
        package_root = str(Path(__file__).resolve().parent.parent)
        env = {"PATH": os.defpath, "HOME": self.directory.name, "LANG": "en_US.UTF-8",
               "PYTHONPATH": package_root, "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        self.process = subprocess.Popen([sys.executable, "-m", "localpilot_plugins.worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=self.directory.name, env=env, start_new_session=True, bufsize=0)
        self.watch_stop = threading.Event()
        threading.Thread(target=self._watch, args=(self.process, self.watch_stop), daemon=True).start()
        try:
            self._send({**self.config, "_credentials": self.credentials})
            reply = self._receive()
            if "catalog" not in reply:
                raise TransportFailure(reply.get("failure", "initialization_failed"))
            self.catalog = reply["catalog"]
            return self.catalog
        except BaseException:
            self.close()
            raise

    def _watch(self, owned_process, stop):
        """Idle workers must also obey revocation and memory bounds."""
        import psutil
        while not stop.wait(.1) and owned_process.poll() is None:
            try:
                process = psutil.Process(owned_process.pid)
                children = process.children(recursive=True)
                if sum(p.memory_info().rss for p in [process, *children]) > 512 * 1024 * 1024:
                    self.cancel()
                if self.authorization_check:
                    try:
                        self.authorization_check()
                    except Exception:
                        self.cancel()
                if self.cancelled.is_set() and time.monotonic() >= (self.cancel_at or 0) + .25:
                    for child in children:
                        try:
                            child.kill()
                        except psutil.NoSuchProcess:
                            pass
                    owned_process.kill()
                    return
            except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
                pass

    def _send(self, value):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode() + b"\n"
        if len(data) > MAX_FRAME:
            raise TransportFailure("request_limit")
        try:
            self.process.stdin.write(data)
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            raise TransportFailure("disconnected") from None

    def _receive(self):
        import psutil
        deadline = time.monotonic() + self.config["timeout"] + 1
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while True:
                if self.authorization_check:
                    try:
                        self.authorization_check()
                    except Exception:
                        self.cancel()
                if self.cancelled.is_set() and time.monotonic() >= (self.cancel_at or 0) + .25:
                    raise TransportFailure("cancelled")
                if time.monotonic() > deadline:
                    raise TransportFailure("timeout")
                try:
                    process = psutil.Process(self.process.pid)
                    memory = sum(p.memory_info().rss for p in [process, *process.children(recursive=True)] if p.is_running())
                    if memory > 512 * 1024 * 1024:
                        raise TransportFailure("memory_limit")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                if b"\n" in self.buffer:
                    line, self.buffer = self.buffer.split(b"\n", 1)
                    try:
                        return json.loads(line)
                    except (ValueError, RecursionError):
                        raise TransportFailure("invalid_worker_json") from None
                if not selector.select(.05):
                    continue
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise TransportFailure("disconnected")
                self.buffer += chunk
                if len(self.buffer) > MAX_FRAME:
                    raise TransportFailure("output_limit")

    def request(self, value):
        if not self.lock.acquire(blocking=False):
            raise TransportFailure("busy")
        try:
            if self.process is None or self.process.poll() is not None:
                self.connect()  # Fresh handshake; never replays a dispatched call.
            self._send(value)
            reply = self._receive()
            if reply.get("failure"):
                self.close()
            return reply
        except TransportFailure:
            self.close()
            raise
        finally:
            self.lock.release()

    def cancel(self):
        if self.cancelled.is_set():
            return
        self.cancel_at = time.monotonic()
        process = self.process
        if process and process.poll() is None:
            # Give the SDK an opportunity to send notifications/cancelled.
            try:
                os.kill(process.pid, signal.SIGUSR1)
            except ProcessLookupError:
                pass
        self.cancelled.set()

    def close(self):
        import psutil
        self.watch_stop.set()
        process, self.process = self.process, None
        if process is not None:
            try:
                children = psutil.Process(process.pid).children(recursive=True)
            except psutil.NoSuchProcess:
                children = []
            if process.poll() is None:
                if not self.lock.locked() and not self.cancelled.is_set():
                    try:
                        process.stdin.write(b'{"method":"close"}\n')
                        process.stdin.flush()
                        process.wait(timeout=.25)
                    except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                        pass
                try:
                    # SIGTERM permits the worker to exit even on hung child IO.
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            for stream in (process.stdin, process.stdout):
                stream.close()
        self.buffer = b""
        if self.directory is not None:
            self.directory.cleanup()
            self.directory = None
