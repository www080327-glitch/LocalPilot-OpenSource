"""Host-owned acceptance assertions; never registered as an Agent tool.

The assertion file lives outside every Agent write scope. On macOS it runs
read-only, without network, credentials or inherited Python configuration.
Other platforms fail closed until an equivalent executor is qualified.
"""
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

from .stabilization import HostVerification, file_version


class HostPythonAcceptance:
    def __init__(self, workspace, assertions, outputs, *, required_line=None, timeout=5):
        self.workspace = Path(workspace).resolve(strict=True)
        source = Path(assertions)
        if source.is_symlink():
            raise ValueError('Acceptance assertions cannot be a symlink')
        self.assertions = source.resolve(strict=True)
        if self.assertions.is_relative_to(self.workspace):
            raise ValueError('Host assertions must be outside the Agent workspace')
        if not 0 < timeout <= 30 or not outputs or len(outputs) > 32:
            raise ValueError('Acceptance requires bounded time and explicit outputs')
        if required_line is not None and (not isinstance(required_line, str) or '\n' in required_line or not required_line):
            raise ValueError('Delivery contract must be one nonempty line')
        for name in outputs:
            if Path(name).is_absolute() or '..' in Path(name).parts:
                raise ValueError('Acceptance outputs must stay within the workspace')
        self.outputs = tuple(outputs)
        self.required_line, self.timeout = required_line, timeout
        self.source_sha256 = self._source_hash()

    @property
    def identity(self):
        return {'schema': 1, 'assertions_sha256': self.source_sha256,
            'outputs': list(self.outputs), 'required_line': self.required_line, 'timeout': self.timeout}

    def _source_hash(self):
        if self.assertions.is_symlink():
            raise ValueError('Assertion identity changed')
        return hashlib.sha256(self.assertions.read_bytes()).hexdigest()

    def _versions(self):
        versions = {}
        for name in self.outputs:
            version = file_version(self.workspace, name)
            if not version:
                raise FileNotFoundError(name)
            versions[name] = version['sha256']
        return versions

    def __call__(self, root, result):
        if Path(root).resolve() != self.workspace:
            raise ValueError('Acceptance workspace identity mismatch')
        if sys.platform != 'darwin' or not Path('/usr/bin/sandbox-exec').exists():
            return HostVerification('not_run', 'host_assertions:executor_unavailable', {})
        if self._source_hash() != self.source_sha256:
            return HostVerification('blocked', 'host_assertions:identity_changed', {})
        try:
            versions = self._versions()
        except (OSError, ValueError):
            return HostVerification('failed', 'host_assertions:missing_output', {})
        quote = lambda p: json.dumps(str(p), ensure_ascii=False)
        runtime = Path(sys.base_prefix).resolve()
        profile = '\n'.join([
            '(version 1)', '(allow default)', '(deny network*)',
            '(deny file-read*)', '(deny file-write*)', '(deny process-info*)',
            '(allow process-info* (target self))', '(allow file-read-metadata)',
            '(allow file-read* (literal "/"))',
            *['(allow file-read* (subpath ' + quote(p) + '))' for p in
              ['/System', '/usr/lib', '/usr/share', '/private/var/db/dyld', runtime, self.workspace]],
            *['(allow file-read* (literal ' + quote(p) + '))' for p in
              [Path(sys.executable).resolve(), self.assertions, '/dev/null', '/dev/urandom', '/dev/random']],
        ])
        process = subprocess.Popen(['/usr/bin/sandbox-exec', '-p', profile,
            str(Path(sys.executable).resolve()), '-I', '-B', str(self.assertions), str(self.workspace)],
            cwd=self.workspace, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        deadline = time.monotonic() + self.timeout
        seen = 0
        status = 'unknown'
        try:
            with selectors.DefaultSelector() as selector:
                for stream in (process.stdout, process.stderr):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ)
                while selector.get_map() and time.monotonic() < deadline and seen <= 16000:
                    for key, _ in selector.select(.02):
                        chunk = os.read(key.fileobj.fileno(), 4096)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        seen += len(chunk)
                if not selector.get_map() and seen <= 16000:
                    process.wait(timeout=max(.001, deadline - time.monotonic()))
                    status = 'passed' if process.returncode == 0 else 'failed'
        except subprocess.TimeoutExpired:
            pass
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            process.stdout.close()
            process.stderr.close()
        try:
            if self._versions() != versions or self._source_hash() != self.source_sha256:
                status = 'unknown'
        except (OSError, ValueError):
            status = 'unknown'
        if result is not None and self.required_line is not None and self.required_line not in result.text.splitlines():
            status = 'failed'
        good = status == 'passed'
        # No assertion source, expected answers, stdout or stderr enter feedback.
        return HostVerification(status, 'host_assertions:code_and_delivery', versions, good, good, True)

    def execution_check(self, root, projection):
        return self(root, None)
