"""Read-only physical-state recorder. User changes lock/display/lid/sleep manually."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import subprocess
import time

from .build import FIXTURE_ID
from .macos import MacOSAXAdapter
from .power import AwakeLease


def sample(adapter, app, previous_wall=None, window_title=None):
    wall = time.time()
    environment = adapter.environment()
    # Probe reads AX directly even when the production Runtime would pause.
    # This establishes what this OS/app exposes, never a supported locked write.
    tree = adapter.inspect_tree(app, window_title=window_title, max_nodes=128, max_depth=12)
    connection = "UNKNOWN"
    try:
        with socket.create_connection(("learn.chatgpt.com", 443), timeout=1):
            connection = "tcp_connected"
    except OSError as exc:
        connection = type(exc).__name__
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "app": app, "window_title": window_title,
        "wall_gap_seconds": None if previous_wall is None else wall - previous_wall,
        "wall": wall, "environment": environment, "ax_status": tree.get("status"), "ax_error": tree.get("error"),
        "nodes": len(tree.get("nodes", [])), "fixture_input": next((n.get("value") for n in tree.get("nodes", []) if n.get("identifier") == "lp.fixture.input"), None),
        "network": connection, "local_compute_tick": time.process_time(), "writes": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", default=FIXTURE_ID)
    parser.add_argument("--window-title", help="Observe only an exact test window title")
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument("--output", required=True)
    parser.add_argument("--keep-awake", action="store_true", help="Opt-in idle system sleep assertion; does not prevent forced sleep or guarantee lid-closed operation")
    args = parser.parse_args()
    if not 1 <= args.duration <= 3600 or not 0.2 <= args.interval <= 10:
        parser.error("duration 1..3600, interval 0.2..10 required")
    adapter = MacOSAXAdapter([args.app])
    start = time.time()
    previous = None
    last_status = None
    print("只读探针已启动；请手动切换状态并记录时间。不会锁屏、唤醒显示器或修改电源设置。", flush=True)
    try:
        with AwakeLease(args.keep_awake), Path(args.output).open("w", encoding="utf-8") as stream:
            while time.time() - start < args.duration:
                try:
                    record = sample(adapter, args.app, previous, args.window_title)
                    previous = record["wall"]
                except Exception as exc:
                    record = {"timestamp": datetime.now(timezone.utc).isoformat(), "error": type(exc).__name__, "message": str(exc), "writes": 0}
                    # Recreate a timed-out read-only transport; never retry writes.
                    adapter.close()
                    adapter = MacOSAXAdapter([args.app])
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
                environment = record.get("environment") or {}
                status = (record.get("ax_status"), record.get("ax_error"), record.get("nodes"), environment.get("trusted"), environment.get("locked"))
                if status != last_status:
                    detail = "AX=" + str(status[0]) + "，节点=" + str(status[2]) + "，权限=" + str(status[3])
                    if environment.get("locked") is True:
                        print("检测到锁屏，继续只读记录：" + detail + "；当前窗口不可读时无需重开，手动解锁后再观察。", flush=True)
                    else:
                        print("当前只读状态：" + detail + ("；测试窗口可读。" if status[0] == "ok" and status[2] else "；先检查测试窗口或把此提示告诉我。"), flush=True)
                    last_status = status
                time.sleep(args.interval)
    finally:
        adapter.close()
    print("探针已停止：" + args.output, flush=True)


if __name__ == "__main__":
    main()
