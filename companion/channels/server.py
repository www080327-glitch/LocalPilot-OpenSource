from concurrent.futures import Future
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import threading
from queue import Queue, Empty, Full
import time


class LocalChannel:
    def __init__(self, port, token, enqueue):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                future = None
                if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                    self.send_error(403)
                    return
                if self.path not in {"/command", "/pet-stream"} or self.headers.get("Origin"):
                    self.send_error(403)
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 32768:
                        raise ValueError("Invalid request size")
                    command = json.loads(self.rfile.read(size))
                    future = Future()
                    if self.path == "/pet-stream":
                        if not isinstance(command, dict) or command.get("command") != "pet_ask":
                            raise ValueError("Only pet_ask may stream")
                        deltas = Queue(maxsize=512)
                        def on_delta(text):
                            try: deltas.put_nowait(text)
                            except Full: pass  # Authoritative final response is never truncated.
                        command["_on_delta"] = on_delta
                        enqueue(command, future)
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        deadline = time.monotonic()+125
                        while not future.done() or not deltas.empty():
                            if time.monotonic() > deadline:
                                raise TimeoutError("Pet answer deadline reached")
                            try:
                                delta = deltas.get(timeout=.1)
                            except Empty:
                                continue
                            self.wfile.write(("data: "+json.dumps({"event":"draft", "text":delta}, ensure_ascii=False)+"\n\n").encode())
                            self.wfile.flush()
                        self.wfile.write(("data: "+json.dumps({"event":"final", "result":future.result()}, ensure_ascii=False)+"\n\n").encode())
                        self.wfile.flush()
                        self.close_connection = True
                        return
                    enqueue(command, future)
                    result = future.result(timeout=125)
                    content = json.dumps(result, ensure_ascii=False).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                except Exception as exc:
                    if future is not None:
                        future.cancel()  # A timed out queued command must not run later.
                    content = json.dumps({"status":"error", "error":str(exc)}).encode()
                    try:
                        self.send_response(400)
                        self.send_header("Content-Length", str(len(content)))
                        self.end_headers()
                        self.wfile.write(content)
                    except OSError:
                        pass

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval":1}, daemon=True)

    @property
    def port(self):
        return self.server.server_port

    def start(self):
        self.thread.start()

    def stop(self):
        if self.thread.is_alive():
            self.server.shutdown()
        self.server.server_close()
        if self.thread.ident is not None:
            self.thread.join(timeout=3)
