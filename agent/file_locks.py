"""Cooperating LocalPilot writers share canonical-path locks across processes."""
from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
import os
from pathlib import Path

LOCK_DIRECTORY = Path.home() / "Library" / "Caches" / "LocalPilotFileLocks"


@contextmanager
def lock_paths(paths):
    # Lock stable names, never the replaced inode. Never unlink a lock file:
    # doing so would let a new writer lock a different inode for the same path.
    LOCK_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    with ExitStack() as stack:
        for path in sorted({str(Path(p).resolve()) for p in paths}):
            name = hashlib.sha256(path.encode()).hexdigest() + ".lock"
            fd = os.open(LOCK_DIRECTORY / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            stream = stack.enter_context(os.fdopen(fd, "r+"))
            fcntl.flock(stream, fcntl.LOCK_EX)
        yield
