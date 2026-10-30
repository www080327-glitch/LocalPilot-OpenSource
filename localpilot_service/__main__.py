"""python -m localpilot_service --config /private/service.json"""
import argparse
import json
import signal
import threading
from pathlib import Path
from . import VERSION
from .deployment import build


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--check", action="store_true", help="Validate configuration and checkpoints without inference")
    args = parser.parse_args(argv)
    try:
        server = build(args.config)
    except (ValueError, OSError) as exc:
        parser.exit(2, json.dumps({"valid": False, "error": "configuration_invalid", "detail": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}) + "\n")
    if args.check:
        print(json.dumps({"valid": True, "version": VERSION, "model_health": "NOT_PROBED"}))
        server.service.suspend(); server.server_close(); server.access.close()
        return
    stopping=threading.Event()
    def stop(signum, frame):
        from .lifecycle import event
        event(Path(args.config).parent,'signal_received',signal=signum,name=signal.Signals(signum).name)
        if not stopping.is_set():
            stopping.set()
            # Do not inject an asynchronous exception into request/thread admission.
            # shutdown must run outside the serve_forever thread.
            threading.Thread(target=server.shutdown,name='localpilot-graceful-stop',daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(json.dumps({"version": VERSION, "host": server.server_address[0], "port": server.server_port,
                      "status": "ready", "model_health": "NOT_PROBED"}), flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        # Existing suspend refuses unsafe in-flight work. Drain/cancel if needed.
        if not server.service.closed:
            try:
                server.service.suspend()
            except Exception:
                server.service.shutdown()
        server.server_close(); server.access.close()
        for manager in set(getattr(server,"model_hosts",{}).values()):
            manager.close()


if __name__ == "__main__":
    main()
