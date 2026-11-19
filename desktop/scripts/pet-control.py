"""Send commands to an existing LocalPilot pet using its private control socket."""
import argparse
import json
import os
from pathlib import Path
import socket
import stat
import time


LEGACY_IDS = (
    "io.localpilot.deepseek.pet.native.test",
    "io.localpilot.desktop",
    "io.localpilot.companion.pet.test",
)


def main():
    args, command = command_line()
    if args.test_root is not None:
        root = test_client(args.test_root)
        identity = {"test_root": str(args.test_root)}
    else:
        bundle_id = args.bundle_id or LEGACY_IDS[0]
        root = Path.home() / "Library/Application Support" / bundle_id
        identity = {"bundle_id": bundle_id}

    reports = {"inspect": ("pet-window-diagnostics.json", 3),
               "measure_animation": ("pet-animation-probe.json", 12)}
    report = None
    if command in reports:
        name, timeout = reports[command]
        report = root / name
        before = report_stamp(report)
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(2)
        client.connect(str(root / "pet-control.sock"))
        client.sendall(command.encode())
    if report is None:
        print(json.dumps({"requested": args.action, **identity}))
    else:
        print(json.dumps(fresh_report(report, before, timeout), indent=2, ensure_ascii=False))


def command_line():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["show", "hide", "inspect", "quit", "center",
                                          "anchor", "character", "measure_animation"])
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--bundle-id", choices=LEGACY_IDS, help="Existing macOS pet identity")
    destination.add_argument("--test-root", type=Path,
                             help="Absolute LP_INSTALL_TEST_ROOT used by the running Test APP")
    parser.add_argument("--anchor", choices=["TOP_LEFT", "TOP_RIGHT", "LEFT_EDGE", "RIGHT_EDGE",
                                              "BOTTOM_LEFT", "BOTTOM_RIGHT"])
    parser.add_argument("--character", choices=["deepseek", "claude", "gemini"])
    args = parser.parse_args()
    command = args.action
    if command in ("anchor", "character"):
        value = getattr(args, command)
        if not value:
            parser.error(f"{command} requires --{command}")
        command = f"{command}:{value}"
    if command == "measure_animation" and args.test_root is None:
        parser.error("measure_animation requires --test-root")
    return args, command


def test_client(root):
    marker = root / "test-owner.json"
    if not root.is_absolute():
        raise ValueError("--test-root requires an absolute installation test root")
    info = marker.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError("test-owner.json must be a private file owned by the current user")
    owner = json.loads(marker.read_text())
    if not isinstance(owner, dict) or owner.get("purpose") != "LocalPilot installation E2E":
        raise ValueError("test-owner.json does not identify a LocalPilot installation test root")
    return root.resolve() / "client"


def report_stamp(path):
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    # The native writer renames a fresh file over the prior report on each sample.
    return info.st_ino, info.st_mtime_ns


def fresh_report(path, before, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = report_stamp(path)
        if current is not None and current != before:
            return json.loads(path.read_text())
        time.sleep(0.05)
    raise TimeoutError(f"No fresh {path.name} received within {timeout} seconds")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
