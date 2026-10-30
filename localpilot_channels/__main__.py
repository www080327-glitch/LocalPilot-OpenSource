import argparse
import json
import signal
import threading
from .security import private_json

from .adapter import Adapter
from .server import make_server


def main():
    parser = argparse.ArgumentParser(description='Loopback QQ/WeChat facade for official LocalPilot Agent service')
    parser.add_argument('--config', required=True, help='JSON with environment variable NAMES, never credential values')
    parser.add_argument('--state-dir', required=True, help='New private directory outside all repositories and task workspaces')
    parser.add_argument('--port', type=int, default=8003)
    parser.add_argument('--task-timeout-seconds', type=int, help='Task deadline including manual approvals (maximum 3600)')
    args = parser.parse_args()
    adapter = None
    try:
        adapter = Adapter(private_json(args.config), args.state_dir,
                          task_timeout_seconds=args.task_timeout_seconds)
        server = make_server(adapter, port=args.port)
    except Exception:
        if adapter is not None:
            adapter.close()
        parser.exit(2, 'CHANNEL_CONFIGURATION_OR_STATE_INVALID\n')
    print('Official LocalPilot channel adapter listening on 127.0.0.1:' + str(server.server_port), flush=True)
    stopping = threading.Event()
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, lambda *_: stopping.set())
    server.timeout = 0.2
    try:
        while not stopping.is_set():
            server.handle_request()
    finally:
        server.server_close()  # Joins bounded in-flight requests before SQLite closes.
        adapter.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
