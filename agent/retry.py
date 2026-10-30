"""Retry only transient model-request failures; never retry tool actions."""

import errno
from http.client import IncompleteRead
import math
import random as random_module
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay: float = 0.5
    max_delay: float = 2.0
    jitter: float = 0.1

    def __post_init__(self):
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int) or not 1 <= self.max_attempts <= 10:
            raise ValueError("max_attempts must be an integer from 1 to 10")
        for value in (self.base_delay, self.max_delay, self.jitter):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 30:
                raise ValueError("Retry delays must be finite numbers from 0 to 30")


def is_transient_error(error):
    """Follow wrapped causes, but never treat a certificate failure as transient."""
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "retryable", None) is False:
            return False
        if isinstance(current, ssl.SSLCertVerificationError):
            return False
        if getattr(current, "retryable", None) is True:
            return True
        if isinstance(current, HTTPError):
            return current.code == 429 or current.code in (500, 502, 503, 504)
        status = getattr(current, "status_code", None)
        if isinstance(status, int):
            return status == 429 or status in (500, 502, 503, 504)
        if isinstance(current, URLError):
            reason = current.reason
            if isinstance(reason, str):
                lower = reason.lower()
                if "certificate" in lower or "cert verify" in lower:
                    return False
                return any(term in lower for term in (
                    "timed out", "timeout", "name resolution", "dns",
                    "connection reset", "connection refused", "network is unreachable",
                    "eof", "tls handshake",
                ))
            current = reason
            continue
        if isinstance(current, (TimeoutError, ConnectionError, EOFError, IncompleteRead, socket.gaierror, ssl.SSLError)):
            return True
        if isinstance(current, OSError) and current.errno in {
            errno.ECONNRESET, errno.ECONNABORTED, errno.EPIPE,
            errno.ETIMEDOUT, errno.ENETUNREACH, errno.EHOSTUNREACH,
        }:
            return True
        current = current.__cause__ or current.__context__
    return False


def call_with_retry(function, policy=None, on_retry=None, sleep=time.sleep,
                    random=random_module.random):
    """Call a request function again only before a result is exposed."""
    policy = policy or RetryPolicy()
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return function()
        except Exception as error:
            if attempt == policy.max_attempts or not is_transient_error(error):
                raise
            delay = min(policy.max_delay,
                        policy.base_delay * 2 ** (attempt - 1) + policy.jitter * random())
            if on_retry is not None:
                on_retry({"attempt": attempt, "delay": delay,
                          "error_type": type(error).__name__})
            sleep(delay)
