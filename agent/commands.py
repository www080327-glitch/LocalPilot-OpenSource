"""Bounded subprocess execution using argv, never a generated Python exec."""

import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import time

from .safety import PermissionGateway

SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def _executable(program):
    # Never resolve a model-provided name using the workspace or inherited PATH.
    if program in {"python", "python3", sys.executable}:
        return sys.executable
    found = shutil.which(Path(program).name, path=SYSTEM_PATH)
    if not found:
        raise ValueError("Program is not available in the trusted system PATH.")
    if "/" in program and (not Path(program).is_absolute() or Path(program).resolve() != Path(found).resolve()):
        raise ValueError("Executable paths must match a trusted system program.")
    return found


def _kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def execute(workspace_root, argv, timeout=10, output_limit=16000, *, gateway=None):
    gateway = gateway or PermissionGateway(workspace_root)
    if Path(workspace_root).resolve() != gateway.root:
        raise ValueError("Gateway workspace does not match tool workspace.")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= gateway.max_timeout:
        raise ValueError(f"timeout must be positive and at most {gateway.max_timeout}")
    if isinstance(output_limit, bool) or not isinstance(output_limit, int) or not 1 <= output_limit <= gateway.max_output_bytes:
        raise ValueError(f"output_limit must be between 1 and {gateway.max_output_bytes}")
    decision = gateway.command_decision(argv)
    if decision["status"] != "allowed":
        return {**decision, "request": {"argv": list(argv), "timeout": timeout, "output_limit": output_limit}}
    if os.name != "posix":
        raise RuntimeError("Command execution V0 requires POSIX process groups.")
    executable = _executable(argv[0])
    env = {"PATH": SYSTEM_PATH, "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8",
           "PYTHONDONTWRITEBYTECODE": "1", "GIT_PAGER": "cat",
           "GIT_EXTERNAL_DIFF": "", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    command = [executable, *argv[1:]]
    if Path(executable).resolve() == Path(sys.executable).resolve():
        # Environment is rebuilt above; disable user site-packages.
        command.insert(1, "-s")
    if Path(argv[0]).name == "git":
        git_options = ["--no-pager", "-c", "core.fsmonitor=false", "-c", "diff.external=", "-c", "core.pager=cat"]
        diff_options = ["--no-ext-diff", "--no-textconv"] if argv[1] in {"diff", "show", "log"} else []
        # Insert before user '--' path separators so helper-disabling flags apply.
        command = [executable, *git_options, argv[1], *diff_options, *argv[2:]]
    process = subprocess.Popen(command, cwd=gateway.root, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    output = {"stdout": bytearray(), "stderr": bytearray()}
    total_bytes = 0
    truncated = False
    timed_out = False
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    room = max(0, output_limit - sum(len(part) for part in output.values()))
                    output[key.data].extend(chunk[:room])
                    total_bytes += len(chunk)
                    truncated = truncated or len(chunk) > room
            if not timed_out:
                try:
                    process.wait(timeout=max(0.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    timed_out = True
    finally:
        # Also clean up ordinary descendants that still hold a pipe open.
        _kill_group(process)
        process.wait()
        process.stdout.close()
        process.stderr.close()
    result = {
        "status": "timeout" if timed_out else ("ok" if process.returncode == 0 else "nonzero_exit"),
        "exit_code": process.returncode, "stdout": output["stdout"].decode("utf-8", errors="replace"),
        "stderr": output["stderr"].decode("utf-8", errors="replace"), "truncated": truncated,
        "output_bytes_seen": total_bytes, "timeout_seconds": timeout,
        "risk_summary": decision["risk_summary"],
    }
    gateway.record({"operation": "execute", "status": result["status"], "exit_code": result["exit_code"],
                    "output_bytes_seen": total_bytes, "truncated": truncated})
    return result


run_command = execute  # Host-side compatibility alias, no seventh model-visible tool.
