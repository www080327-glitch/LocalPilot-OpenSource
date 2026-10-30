"""Build and own a passive macOS menu bar process without modifying system state."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from companion.config import PrivateData


def sources():
    root = Path(__file__).resolve().parent
    return [root / name for name in ("CompanionClient.swift", "CompanionBanner.swift", "InferenceControlWindow.swift", "SystemNotifications.swift", "MenuBarController.swift", "main.swift")]


def source_digest():
    digest = hashlib.sha256()
    for source in sources():
        digest.update(source.name.encode())
        digest.update(source.read_bytes())
    digest.update((Path(__file__).parent / "CompanionUI.entitlements").read_bytes())
    return digest.hexdigest()


def build_ui(destination, signing_identity="-"):
    if sys.platform != "darwin":
        raise RuntimeError("Companion native UI requires macOS")
    contents = PrivateData(Path(destination) / "Contents")
    macos = PrivateData(contents.root / "MacOS")
    binary = macos.file("CompanionUI")
    manifest = contents.file("source.json")
    digest = source_digest()
    from companion import __version__
    instance = hashlib.sha256(str(Path(destination).resolve().parent).encode()).hexdigest()[:12]
    bundle_identifier = "io.localpilot.companion.ui." + instance
    try:
        state = json.loads(manifest.read_text())
        fresh = binary.is_file() and state.get("source_sha256") == digest and state.get("signing_identity") == signing_identity and state.get("bundle_identifier") == bundle_identifier and state.get("version") == __version__
    except (OSError, ValueError):
        fresh = False
    contents.write("Info.plist", plistlib.dumps({
        "CFBundleName": "AI Companion", "CFBundleDisplayName": "AI Companion " + __version__,
        "CFBundleIdentifier": bundle_identifier, "CFBundleVersion": "0.5.5",
        "CFBundleShortVersionString": "0.5.5", "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "CompanionUI", "NSHighResolutionCapable": True,
        "LSUIElement": True, "CompanionTimeSensitiveNotifications": signing_identity != "-",
    }).decode())
    if not fresh:
        temporary = macos.file("CompanionUI.building")
        try:
            subprocess.run(["/usr/bin/swiftc", "-O", *map(str, sources()), "-o", str(temporary)],
                           check=True, timeout=120, capture_output=True, text=True)
            # Restricted notification entitlement needs a genuine authorized
            # signing/profile combination. An ad-hoc trial must remain runnable.
            entitlement = Path(__file__).parent / "CompanionUI.entitlements"
            if signing_identity == "-":
                entitlement = contents.write("Local.entitlements", plistlib.dumps({}).decode())
            subprocess.run(["/usr/bin/codesign", "--force", "--sign", signing_identity, "--identifier", bundle_identifier, "--timestamp=none", "--entitlements",
                            str(entitlement), str(temporary)],
                           check=True, timeout=30, capture_output=True, text=True)
            os.chmod(temporary, 0o700)
            os.replace(temporary, binary)
            contents.write("source.json", json.dumps({"source_sha256": digest,
                "version": __version__, "bundle_identifier":bundle_identifier, "signing_identity":signing_identity, "time_sensitive_capability":signing_identity!="-", "signing": "ad-hoc trial without restricted entitlement; authorized distribution profile still required for time-sensitive delivery"}))
        finally:
            temporary.unlink(missing_ok=True)
    return binary


def _owned_process(record, private, token):
    import psutil
    process = psutil.Process(record["pid"])
    expected = str(private.root / "CompanionUI.app/Contents/MacOS/CompanionUI")
    runtime = str(private.file("runtime.json"))
    if (record.get("token") != token or type(record.get("created")) not in (int, float)
            or abs(process.create_time() - record["created"]) > .01
            or record.get("executable") != expected or process.exe() != expected
            or process.cmdline() not in ([expected, runtime], [expected, runtime, "--show"])):
        raise RuntimeError("UI process identity mismatch; preserved")
    return process


def launch_ui(config, show=False):
    from companion.cli import client
    from companion.runtime.process import service_record
    import psutil
    private = PrivateData(config.data_dir)
    client(config, {"command": "status"}, timeout=5)
    runtime, _ = service_record(private)
    try:
        record = json.loads(private.file("ui.json").read_text())
        process = _owned_process(record, private, runtime["token"])
        if not show:
            return {"status": "ui_already_running", "pid": process.pid, "panel": "passive_menu_bar"}
        process.terminate()
        process.wait(timeout=3)
        private.file("ui.json").unlink(missing_ok=True)
    except (OSError, ValueError, KeyError, psutil.Error, RuntimeError):
        pass
    binary = build_ui(private.file("CompanionUI.app"))
    argv = [str(binary), str(private.file("runtime.json"))] + (["--show"] if show else [])
    if not private.file("ui.log").exists():private.write("ui.log", "")
    with private.file("ui.log").open("a") as log:
        process = subprocess.Popen(argv, start_new_session=True, stdout=log, stderr=log)
    if process.poll() is not None:raise RuntimeError("Companion UI exited before runtime registration; inspect private ui.log")
    created = psutil.Process(process.pid).create_time()
    private.write("ui.json", json.dumps({"pid": process.pid, "created": created,
        "token": runtime["token"], "executable": str(binary)}))
    return {"status": "ui_started", "pid": process.pid, "panel": "opened_on_start" if show else "closed_until_menu_click"}


def stop_ui(private, token):
    """Signal only the exact UI attached to this Host; do not touch other sessions."""
    import psutil
    try:
        record = json.loads(private.file("ui.json").read_text())
        process = _owned_process(record, private, token)
        process.terminate()
        process.wait(timeout=3)
        private.file("ui.json").unlink(missing_ok=True)
        return {"status": "ui_stopped"}
    except psutil.NoSuchProcess:
        private.file("ui.json").unlink(missing_ok=True)
        return {"status": "ui_exited"}
    except (OSError, ValueError, KeyError, RuntimeError, psutil.Error):
        return {"status": "ui_not_signalled", "reason": "missing or unmatched owned process"}
