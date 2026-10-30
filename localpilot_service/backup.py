"""SQLite online snapshot and conservative restore to a new, private destination."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3


def copy_database(source, destination):
    source, destination = Path(source).expanduser(), Path(destination).expanduser()
    if source.is_symlink() or not source.is_file() or source.stat().st_mode & 0o077 or source.stat().st_uid != os.getuid():
        raise ValueError("Source must be an owner-only regular SQLite database")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600); os.close(fd)
    old = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    new = sqlite3.connect(destination)
    try:
        old.backup(new)
        if new.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup integrity check failed")
        new.commit()
    finally:
        old.close(); new.close()
    digest=hashlib.sha256()
    with destination.open('rb') as stream:
        while block:=stream.read(1024*1024):digest.update(block)
    return {"status": "ok", "destination": str(destination.resolve()), "sha256": digest.hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "restore"])
    parser.add_argument("source"); parser.add_argument("destination")
    args = parser.parse_args(argv)
    print(json.dumps(copy_database(args.source, args.destination)))


if __name__ == "__main__": main()
