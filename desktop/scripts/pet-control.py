"""Recover only this explicitly identified LocalPilot pet through its private API."""
import argparse
import json
from pathlib import Path
import socket
import time

p = argparse.ArgumentParser()
p.add_argument("action", choices=["show", "hide", "inspect", "quit", "center", "anchor", "character"])
p.add_argument("--bundle-id", default="io.localpilot.deepseek.pet.native.test")
p.add_argument("--anchor", choices=["TOP_LEFT","TOP_RIGHT","LEFT_EDGE","RIGHT_EDGE","BOTTOM_LEFT","BOTTOM_RIGHT"])
p.add_argument("--character", choices=["deepseek","claude","gemini"])
a = p.parse_args()
command=a.action
if a.action=="anchor":
    if not a.anchor:p.error("anchor requires --anchor")
    command="anchor:"+a.anchor
if a.action=="character":
    if not a.character:p.error("character requires --character")
    command="character:"+a.character
if a.bundle_id not in {"io.localpilot.deepseek.pet.native.test", "io.localpilot.desktop", "io.localpilot.companion.pet.test"}:
    p.error("Select an explicit known LocalPilot identity")
root = Path.home() / "Library/Application Support" / a.bundle_id
report = root / "pet-window-diagnostics.json"
before = report.stat().st_mtime_ns if report.exists() else 0
with socket.socket(socket.AF_UNIX) as s:
    s.settimeout(2)
    s.connect(str(root / "pet-control.sock"))
    s.sendall(command.encode())
if a.action == "inspect":
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if report.exists() and report.stat().st_mtime_ns > before:
            print(json.dumps(json.loads(report.read_text()), indent=2, ensure_ascii=False))
            break
        time.sleep(.05)
    else:
        raise SystemExit("Pet did not return a fresh diagnostic snapshot")
else:
    print(json.dumps({"requested": a.action, "bundle_id": a.bundle_id}))
