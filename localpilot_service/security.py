"""Host configured identities, bounded admission and content-free audit records."""
from dataclasses import dataclass, field
from collections import deque
import hmac
import json
import os
from pathlib import Path
import re
import stat
import threading
import time

from localpilot_api.service import APIError

SCOPES = {"submit", "read", "cancel", "control", "resource_control"}


def private_json(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 1048576:
            raise ValueError("Configuration must be an owner-only regular file, at most 1 MiB")
        return json.loads(os.read(fd, 1048577))
    finally:
        os.close(fd)


@dataclass(frozen=True)
class Principal:
    subject: str
    token: str = field(repr=False)
    scopes: frozenset = frozenset({"submit", "read", "cancel"})
    routes: dict = field(default_factory=lambda: {"localpilot": "localpilot"})
    approval_for: tuple = ()
    operator: bool = False
    requests_per_minute: int = 120
    max_active_tasks: int = 2
    max_connections: int = 8

    def __post_init__(self):
        if type(self.operator) is not bool:
            raise ValueError("operator must be a boolean, never a truthy string")
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", self.subject):
            raise ValueError("Invalid client subject")
        if not isinstance(self.token, str) or len(self.token) < 24 or any(ord(c) < 33 or ord(c) > 126 for c in self.token):
            raise ValueError("Client tokens require at least 24 visible ASCII characters")
        if not self.scopes <= SCOPES or (("control" in self.scopes or "resource_control" in self.scopes) and not self.operator):
            raise ValueError("Only explicitly configured operators may hold control scope")
        if not isinstance(self.routes, dict) or not all(isinstance(k, str) and isinstance(v, str) for k,v in self.routes.items()):
            raise ValueError("Client route map must contain strings")
        if not self.operator and self.approval_for:
            raise ValueError("Delegated approval subjects require an operator identity")
        if any(type(n) is not int or not 1 <= n <= 10000 for n in
               (self.requests_per_minute, self.max_active_tasks, self.max_connections)):
            raise ValueError("Client limits must be positive bounded integers")


class AccessPolicy:
    def __init__(self, principals, *, audit_path=None):
        self.principals = {p.subject: p for p in principals}
        if not self.principals or len(self.principals) != len(principals) or len({p.token for p in principals}) != len(principals):
            raise ValueError("Client subjects and tokens must be unique")
        if any(set(p.approval_for) - self.principals.keys() for p in principals):
            raise ValueError("Approval subjects must exist")
        self.lock = threading.RLock()
        self.times, self.connections = {}, {}
        self.audit_file = None
        if audit_path:
            fd = os.open(audit_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                os.close(fd)
                raise ValueError("Audit log must be owner-only")
            self.audit_file = os.fdopen(fd, "a", buffering=1)

    def authenticate(self, authorization):
        actual = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        found = None
        for principal in self.principals.values():
            if hmac.compare_digest(actual.encode(), principal.token.encode()):
                found = principal
        if not found:
            raise APIError("Invalid API token", "unauthorized", 401)
        return found

    def admit(self, principal, urgent=False):
        with self.lock:
            now = time.monotonic()
            times = self.times.setdefault(principal.subject, deque())
            while times and times[0] <= now - 60:
                times.popleft()
            if (not urgent and len(times) >= principal.requests_per_minute) or self.connections.get(principal.subject, 0) >= principal.max_connections+(1 if urgent else 0):
                raise APIError("Client request/connection limit reached", "rate_limited", 429)
            times.append(now)
            self.connections[principal.subject] = self.connections.get(principal.subject, 0) + 1

    def release(self, principal):
        with self.lock:
            self.connections[principal.subject] -= 1

    def audit(self, **record):
        with self.lock:
            if self.audit_file:
                self.audit_file.write(json.dumps({"time": time.time(), **record}, allow_nan=False) + "\n")
                self.audit_file.flush()

    def close(self):
        with self.lock:
            if self.audit_file:
                self.audit_file.close()
                self.audit_file=None
