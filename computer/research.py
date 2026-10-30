"""Read-only, bounded local bundle/process/TCC inspection. Never connects to private IPC."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import plistlib
import re
import subprocess


def capture(argv, timeout=45):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr[:1500]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"returncode": None, "error": type(exc).__name__}


def plist(path):
    data = plistlib.loads(path.read_bytes())
    return {k: data.get(k) for k in ("CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleVersion",
            "CFBundleExecutable", "LSUIElement", "LSBackgroundOnly")}


def collect():
    app = Path("/Applications/ChatGPT.app")
    installed = app / "Contents/Resources/cua_node/lib/node_modules/@oai/sky/Codex Computer Use.app"
    active = Path.home() / ".codex/computer-use/Codex Computer Use.app"
    bundles = [app, installed, active]
    bundles += sorted(installed.glob("Contents/SharedSupport/*.app"))
    bundles += list(installed.glob("Contents/SharedSupport/*Installer.app/Contents/Resources/*.bundle"))
    auth = Path("/Library/Security/SecurityAgentPlugins/CodexComputerUseAuthorizationPlugin.bundle")
    if auth.exists():
        bundles.append(auth)
    metadata = []
    selected_symbols = []
    selected_strings = []
    for bundle in bundles:
        info = bundle / "Contents/Info.plist"
        if not info.is_file():
            continue
        record = {"path": str(bundle), "plist": plist(info)}
        binary = bundle / "Contents/MacOS" / record["plist"]["CFBundleExecutable"]
        if binary.is_file():
            record["binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
            record["signature"] = capture(["codesign", "-dv", str(bundle)])
            record["entitlements"] = capture(["codesign", "-d", "--entitlements", ":-", str(bundle)])
            record["linked_frameworks"] = capture(["otool", "-L", str(binary)])
            if bundle == active:
                symbols = capture(["nm", "-u", str(binary)], timeout=60)
                selected_symbols = [line.strip() for line in symbols.get("stdout", "").splitlines()
                    if re.search(r'AXUI|AXIs|CGS|CGSession|IOPM|NSXPC|SecCode|SecTask|xpc_', line)]
                strings = capture(["strings", str(binary)], timeout=60)
                terms = ("ComputerUseCursor", "SoftwareCursorStyle", "VirtualCursor", "SyntheticAppFocusEnforcer",
                    "SystemFocusStealPreventer", "LockScreenAutoUnlockCoordinator", "LockScreenPhysicalInputMonitor",
                    "LockScreenGuardian", "LockScreenLoginAuthorization", "ApplicationBelievesItHasFocus",
                    "computerUseCursorLocation", "CGEventPostToPid", "CGEventTapCreate", "SLSPostEventRecordTo",
                    "SLPSPostEventRecordTo", "SKY_CUA", "IPCJSONRPC")
                selected_strings = sorted(set(line for line in strings.get("stdout", "").splitlines()
                    if len(line) < 200 and any(term.lower() in line.lower() for term in terms)))[:100]
        metadata.append(record)
    processes = capture(["ps", "-axo", "pid,ppid,comm"])
    selected_processes = [line for line in processes.get("stdout", "").splitlines()
        if any(s in line for s in ("SkyComputerUse", "CUALockScreen", "/ChatGPT", "/WindowServer", "/loginwindow"))]
    service_pids = [line.split()[0] for line in selected_processes if "SkyComputerUseService" in line]
    ipc = [capture(["lsof", "-n", "-a", "-p", pid, "-U"]) for pid in service_pids]
    tcc = Path.home() / "Library/Application Support/com.apple.TCC/TCC.db"
    query = "SELECT service,client,auth_value FROM access WHERE client IN ('com.openai.codex','com.openai.sky.CUAService') AND service IN ('kTCCServiceAccessibility','kTCCServiceScreenCapture');"
    tcc_result = capture(["sqlite3", "-readonly", str(tcc), query])
    mechanisms = {}
    for rule in ("system.login.console", "system.login.screensaver"):
        raw = capture(["security", "authorizationdb", "read", rule])
        mechanisms[rule] = {"returncode": raw.get("returncode"), "matching_lines": [l.strip() for l in raw.get("stdout", "").splitlines()
            if any(term in l for term in ("Codex", "authenticate", "mechanism", "screensaver", "loginwindow"))]}
    root = app / "Contents/Resources/cua_node/lib/node_modules/@oai/sky/dist/project/cua/sky_js/src/targets/mac"
    wrappers = {name: {"path": str(root / name), "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest()}
                for name in ("native-pipe.js", "native-pipe.d.ts", "client.d.ts", "set_value.js", "computer-use-policy.js") if (root / name).exists()}
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "evidence": "OBSERVED_read_only_local_install",
        "os": capture(["sw_vers"]), "bundles": metadata, "selected_imports": selected_symbols,
        "selected_component_strings": selected_strings, "processes": selected_processes, "unix_sockets": ipc,
        "tcc_selected_rows": tcc_result, "authorization_rules": mechanisms, "wrapper_files": wrappers,
        "power_settings": capture(["pmset", "-g"]), "private_ipc_requests": 0,
        "security_changes": 0, "clean_service_off_on_experiment": "NOT_RUN_shared_service_already_running"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="docs/evidence/computer-use-v2/local-install.json")
    args = parser.parse_args()
    report = collect()
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print("Read-only local installation evidence: " + args.output)


if __name__ == "__main__":
    main()
