import argparse
import json
import os
from pathlib import Path
import signal
import plistlib
import subprocess
import sys
import time
from urllib.request import ProxyHandler, Request, build_opener

from companion.config import Config, PrivateData
from companion.runtime.process import service_record, remove_stale_record

_started_processes = {}


def reap_started(config):
    process = _started_processes.get(config.data_dir)
    if process is not None and process.poll() is not None:
        del _started_processes[config.data_dir]


def client(config, command, timeout=125):
    private = PrivateData(config.data_dir)
    runtime, _ = service_record(private)
    req = Request(f"http://127.0.0.1:{int(runtime['port'])}/command", data=json.dumps(command, ensure_ascii=False).encode(), headers={"Content-Type":"application/json", "Authorization":"Bearer " + runtime["token"]})
    with build_opener(ProxyHandler({})).open(req, timeout=timeout) as response:
        return json.load(response)


def start(config, filename):
    reap_started(config)
    try:
        return client(config, {"command":"status"}, timeout=2)
    except Exception:
        pass
    private = PrivateData(config.data_dir)
    with open(private.file("service.log"), "a") as log:
        process = subprocess.Popen([sys.executable, "-m", "companion", "--config", str(Path(filename).absolute()), "run"], stdout=log, stderr=log, env={k:v for k,v in os.environ.items() if "DEEPSEEK" not in k.upper() and "OPERATOR" not in k.upper()}, start_new_session=True, cwd=str(Path(__file__).resolve().parent.parent))
        _started_processes[config.data_dir] = process
    for _ in range(40):
        if process.poll() is not None:
            reap_started(config)
            raise RuntimeError("Companion did not start; inspect service.log")
        try:
            return client(config, {"command":"status"}, timeout=1)
        except Exception:
            time.sleep(0.2)
    return {"status":"starting", "pid":process.pid}


def stop(config):
    private = PrivateData(config.data_dir)
    try:
        import psutil
        runtime, p = service_record(private)
        os.kill(p.pid, signal.SIGTERM)
        try:
            p.wait(timeout=10)
        except psutil.TimeoutExpired:
            return {"status":"stopping", "pid":p.pid}
        remove_stale_record(private)
        return {"status":"stopped"}
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status":"stopped", "stale_record_removed":True} if remove_stale_record(private) else {"status":"unavailable", "reason":"Service lock is held; runtime record preserved"}
    finally:
        reap_started(config)


def popup(config):
    if sys.platform != "darwin":
        raise RuntimeError("Native popup requires macOS")
    private = PrivateData(config.data_dir)
    client(config, {"command":"status"}, timeout=5)
    import psutil
    try:
        record = json.loads(private.file("popup.json").read_text())
        runtime = json.loads(private.file("runtime.json").read_text())
        existing = psutil.Process(record["pid"])
        expected = str(private.root/"CompanionPopup.app/Contents/MacOS/CompanionPopup")
        if record.get("token") == runtime["token"] and existing.exe() == expected:
            return {"status":"popup_already_open", "pid":existing.pid}
    except (OSError, ValueError, KeyError, psutil.Error):
        pass
    source = Path(__file__).parent/"channels/Popup.swift"
    app = private.file("CompanionPopup.app")
    contents = PrivateData(app/"Contents")
    macos = PrivateData(contents.root/"MacOS")
    from companion import __version__
    contents.write("Info.plist", plistlib.dumps({"CFBundleName":"Companion "+__version__, "CFBundleDisplayName":"Companion "+__version__, "CFBundleIdentifier":"io.localpilot.companion.popup", "CFBundleVersion":"0.5.5", "CFBundlePackageType":"APPL", "CFBundleExecutable":"CompanionPopup", "NSHighResolutionCapable":True}).decode())
    binary = macos.file("CompanionPopup")
    if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
        subprocess.run(["/usr/bin/swiftc", str(source), "-o", str(binary)], check=True, timeout=120)
    p = subprocess.Popen([str(binary), str(private.file("runtime.json"))], start_new_session=True)
    return {"status":"popup_opened", "pid":p.pid}


def main():
    from companion import __version__
    parser = argparse.ArgumentParser(description=f"Companion {__version__} — independent local read-only assistant")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("run", "start", "stop", "status", "popup", "ui", "ui-build", "ui-snapshot", "recent-memories", "reminders", "notices", "index", "retention", "privacy", "native-build", "escalation-status"):
        action = sub.add_parser(name)
        if name == "ui":
            action.add_argument("--show", action="store_true")
    for name in ("ask", "retrieve", "escalate"):
        sub.add_parser(name).add_argument("text")
    dnd = sub.add_parser("dnd")
    dnd.add_argument("value", choices=["on", "off"])
    remember = sub.add_parser("remember")
    remember.add_argument("type", choices=["user_fact", "preference"])
    remember.add_argument("text")
    remember.add_argument("--fact-key", default="")
    remember.add_argument("--expires-days", type=float)
    sub.add_parser("forget").add_argument("id")
    sub.add_parser("clear-memory").add_argument("--confirm", action="store_true")
    notice = sub.add_parser("respond")
    notice.add_argument("id")
    notice.add_argument("response", choices=["ignore", "not_needed", "reply", "help", "useful", "mute", "more"])
    notice.add_argument("--text", default="")
    for name in ("submit-escalation", "retry-submission"):
        action = sub.add_parser(name)
        action.add_argument("--approve", action="store_true")
        action.add_argument("--allow-cloud", action="store_true")
        action.add_argument("--session-id")
        action.add_argument("--conversation-id", default=None)
        action.add_argument("--review-digest")
    sub.add_parser("authorize-observation").add_argument("--confirm", action="store_true")
    sub.add_parser("observe").add_argument("value", choices=["pause", "resume"])
    obs = sub.add_parser("observations")
    obs.add_argument("text", nargs="?", default="")
    sub.add_parser("forget-observation").add_argument("id")
    exclusions = sub.add_parser("exclude-apps")
    exclusions.add_argument("apps", nargs="*")
    proactive = sub.add_parser("proactive")
    proactive.add_argument("--level", choices=["off", "low", "normal"])
    proactive.add_argument("--delivery", choices=["silent", "enabled"])
    reminder = sub.add_parser("set-reminder")
    reminder.add_argument("text")
    reminder.add_argument("--due-at", required=True, type=float)
    reminder.add_argument("--confirm", action="store_true")
    sub.add_parser("delete-reminder").add_argument("id")
    sub.add_parser("localpilot-health").add_argument("--allow-cloud", action="store_true")
    for name in ("task-status", "task-cancel", "task-events"):
        action = sub.add_parser(name)
        action.add_argument("task_id")
        action.add_argument("--allow-cloud", action="store_true")
        if name == "task-cancel":
            action.add_argument("--approve", action="store_true")
        if name == "task-events":
            action.add_argument("--after", type=int, default=0)
    launch = sub.add_parser("launchd")
    launch.add_argument("operation", choices=["render", "install", "uninstall", "status"])
    launch.add_argument("--confirm", action="store_true")
    smoke = sub.add_parser("model-smoke")
    smoke.add_argument("--prompt", default="用一句中文向用户问早上好。")
    args = parser.parse_args()
    try:
        config = Config.load(args.config)
        if args.action == "run":
            from companion.runtime import Companion
            Companion(config).run()
            return
        if args.action == "start":
            result = start(config, args.config)
        elif args.action == "stop":
            result = stop(config)
        elif args.action == "popup":
            result = popup(config)
        elif args.action in {"ui", "ui-build"}:
            from companion.ui.build import build_ui, launch_ui
            result = launch_ui(config, show=args.show) if args.action == "ui" else {"status":"ok", "app":str(build_ui(PrivateData(config.data_dir).file("CompanionUI.app")))}
        elif args.action == "native-build":
            from companion.observers.native import build_native_helper
            result = {"status":"ok", "helper":str(build_native_helper(PrivateData(config.data_dir).file("native")))}
        elif args.action == "launchd":
            from companion.runtime.launchd import manage
            result = manage(args.operation, args.config, PrivateData(config.data_dir), args.confirm)
        elif args.action == "model-smoke":
            from companion.model import ModelManager
            from companion.runtime.service import SYSTEM
            model = ModelManager(config)
            try:
                result = model.complete([{"role":"system", "content":SYSTEM}, {"role":"user", "content":args.prompt}])
            finally:
                model.unload()
        else:
            command = {"command": args.action}
            if args.action in {"ask", "retrieve", "escalate"}:
                command["text"] = args.text
            elif args.action in {"ui-snapshot", "recent-memories", "delete-reminder"}:
                command = {"command":args.action.replace("-", "_")}
                if args.action == "delete-reminder":
                    command["id"] = args.id
            elif args.action == "exclude-apps":
                command = {"command":"set_app_exclusions", "apps":args.apps}
            elif args.action == "proactive":
                command = {"command":"proactive_settings"} | {k:v for k,v in (("level", args.level), ("delivery", args.delivery)) if v is not None}
            elif args.action == "set-reminder":
                command = {"command":"set_reminder", "text":args.text, "due_at":args.due_at, "confirmed":args.confirm}
            elif args.action == "dnd":
                command["enabled"] = args.value == "on"
            elif args.action == "remember":
                command.update(type=args.type, text=args.text, fact_key=args.fact_key, expires_days=args.expires_days)
            elif args.action == "forget":
                command["id"] = args.id
            elif args.action == "clear-memory":
                command = {"command":"clear", "confirmation":"DELETE_COMPANION_MEMORY" if args.confirm else ""}
            elif args.action == "respond":
                command = {"command":"notice_action", "id":args.id, "action":args.response, "text":args.text}
            elif args.action in {"submit-escalation", "retry-submission"}:
                command = {"command":"submit_escalation", "approved":args.approve, "cloud_approved":args.allow_cloud,
                           "session_id":args.session_id, **({"conversation_id":args.conversation_id} if args.conversation_id else {}), "retry":args.action == "retry-submission",
                           "expected_digest":args.review_digest}
                if args.approve and not args.review_digest:
                    command["expected_digest"] = client(config, {"command":"escalation_status"}).get("review_digest")
            elif args.action == "authorize-observation":
                command = {"command":"authorize_observation", "confirmed":args.confirm}
            elif args.action == "observe":
                command = {"command":"pause_observation", "paused":args.value == "pause"}
            elif args.action == "observations":
                command["text"] = args.text
            elif args.action == "forget-observation":
                command = {"command":"forget_observation", "id":args.id}
            elif args.action == "localpilot-health":
                command = {"command":"localpilot_health", "cloud_approved":args.allow_cloud}
            elif args.action == "escalation-status":
                command = {"command":"escalation_status"}
            elif args.action in {"task-status", "task-cancel", "task-events"}:
                command = {"command":args.action.replace("-", "_"), "task_id":args.task_id, "cloud_approved":args.allow_cloud}
                if args.action == "task-cancel":
                    command["approved"] = args.approve
                if args.action == "task-events":
                    command["after"] = args.after
            try:
                result = client(config, command)
            except FileNotFoundError:
                if args.action != "status":
                    raise
                result = {"status":"stopped"}
        if args.json or "text" not in result:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result["text"])
            for memory in result.get("memories", []):
                print(f"  来源：{memory['source_reference'] or memory['type']} [{memory['epistemic']}]")
        if result.get("status") in {"error", "unavailable", "truncated"}:
            sys.exit(1)
    except Exception as exc:
        print(f"Companion: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
