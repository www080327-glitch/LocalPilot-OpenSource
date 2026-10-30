"""Explicit opt-in user LaunchAgent, never installed by ordinary service start."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys

LABEL = "io.localpilot.companion.v0"


def plist(config_filename, data_dir):
    return {"Label":LABEL, "ProgramArguments":[sys.executable, "-m", "companion", "--config", str(Path(config_filename).absolute()), "run"], "WorkingDirectory":str(Path(__file__).resolve().parents[2]), "RunAtLoad":True, "KeepAlive":False, "ProcessType":"Background", "StandardOutPath":str(Path(data_dir)/"launchd.stdout.log"), "StandardErrorPath":str(Path(data_dir)/"launchd.stderr.log"), "EnvironmentVariables":{"PYTHONUNBUFFERED":"1"}}


def manage(action, config_filename, private, confirmed=False):
    destination = Path.home()/"Library/LaunchAgents"/(LABEL+".plist")
    domain = f"gui/{os.getuid()}"
    if action == "render":
        target = private.file("launchagent.preview.plist")
        private.write(target.name, plistlib.dumps(plist(config_filename, private.root)).decode())
        return {"status":"preview", "path":str(target), "installed":False}
    if action == "status":
        p = subprocess.run(["/bin/launchctl", "print", domain+"/"+LABEL], capture_output=True, text=True, timeout=5)
        return {"status":"loaded" if p.returncode == 0 else "not_loaded", "installed":destination.exists(), "path":str(destination)}
    if not confirmed:
        return {"status":"confirmation_required", "reason":"This permanently changes your user login startup item. Re-run with --confirm."}
    if action == "install":
        if destination.exists():
            raise ValueError("Existing startup item preserved; uninstall it explicitly first")
        if any(p.is_symlink() for p in (destination, *destination.parents)):
            raise ValueError("Symlink startup path refused")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as out:
            out.write(plistlib.dumps(plist(config_filename, private.root)))
        destination.chmod(0o600)
        p = subprocess.run(["/bin/launchctl", "bootstrap", domain, str(destination)], capture_output=True, text=True, timeout=10)
        if p.returncode:
            destination.unlink()
            return {"status":"unavailable", "error":p.stderr.strip(), "installed":False}
        return {"status":"installed", "path":str(destination)}
    if action == "uninstall":
        if destination.exists():
            data = plistlib.loads(destination.read_bytes())
            if data.get("Label") != LABEL or data.get("ProgramArguments", [])[1:3] != ["-m", "companion"]:
                raise ValueError("Unrecognized startup item preserved")
        p = subprocess.run(["/bin/launchctl", "bootout", domain+"/"+LABEL], capture_output=True, text=True, timeout=10)
        if p.returncode:
            still_loaded = subprocess.run(["/bin/launchctl", "print", domain+"/"+LABEL], capture_output=True, text=True, timeout=5)
            if still_loaded.returncode == 0:
                return {"status":"unavailable", "error":"LaunchAgent is still loaded; plist preserved", "detail":p.stderr.strip()}
        destination.unlink(missing_ok=True)
        return {"status":"uninstalled", "bootout_returncode":p.returncode, "memory_preserved":True}
    raise ValueError("Unknown launchd action")
