"""Identify an owned service before signalling; dead records are recoverable."""
import fcntl
import json
import os

import psutil


def service_record(private):
    runtime = json.loads(private.file("runtime.json").read_text())
    try:
        process = psutil.Process(runtime["pid"])
        if process.status() == psutil.STATUS_ZOMBIE:
            raise psutil.NoSuchProcess(process.pid)
        if abs(process.create_time() - runtime["created"]) > .01:
            raise RuntimeError("Process identity mismatch; preserved")
        if not {"-m", "companion", "run"}.issubset(set(process.cmdline())):
            raise RuntimeError("Process identity mismatch; preserved")
    except psutil.NoSuchProcess:
        raise FileNotFoundError("Companion service has exited; runtime record is stale") from None
    return runtime, process


def remove_stale_record(private):
    # The service lock is authoritative even when the runtime JSON is damaged.
    with private.file("service.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        private.file("runtime.json").unlink(missing_ok=True)
        return True
