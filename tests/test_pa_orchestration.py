"""Real configured service, HTTP model transport and threaded workers; no model score."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from agent.persistence import PersistenceError
from localpilot_api.service import TaskRequest
from localpilot_service.deployment import build
from tests.test_local_http_backend import completion, tool_call


class ConfiguredOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.workspace = self.root / "work"
        self.workspace.mkdir()
        for name in ("left", "right"):
            (self.workspace / (name + ".txt")).write_text("Observed " + name)
        self.barrier = threading.Barrier(2, timeout=5)
        self.lock = threading.Lock()
        self.calls = []
        self.services = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def send_json(self, body):
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self.send_json({"data": [{"id": "fixture"}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                messages = body["messages"]
                task = next(m["content"] for m in messages if m["role"] == "user")
                with outer.lock:
                    outer.calls.append(body)
                results = [m for m in messages if m["role"] == "tool"]
                if task.startswith("child-"):
                    name = task.removeprefix("child-")
                    if not results:
                        outer.barrier.wait()
                        response = completion(calls=[tool_call("read_file", {"path": name + ".txt"}, "read-" + name)])
                    else:
                        response = completion("Observed " + name)
                elif not results:
                    response = completion("Received; checking both files.", calls=[
                        tool_call("delegate", {"task": "child-" + name, "backend_preference": "local",
                                              "read_only": True, "mode": "async",
                                              "budget": {"steps": 3, "tools": 2, "tokens": 100000}}, "spawn-" + name)
                        for name in ("left", "right")])
                elif not any(m.get("name") == "wait_children" for m in results) and len(results) == 2:
                    response = completion(calls=[tool_call("wait_children", {}, "collect")])
                else:
                    response = completion("Collected both file observations.")
                self.send_json(response)

        self.model = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.model.serve_forever, daemon=True)
        self.thread.start()
        self.env = patch.dict(os.environ, {"LP_PA_TEST_TOKEN": "p" * 32})
        self.env.start()

    def tearDown(self):
        for server in self.services:
            if not server.service.closed:
                server.service.shutdown(timeout=10)
            server.server_close()
            server.access.close()
        self.env.stop()
        self.model.shutdown()
        self.model.server_close()
        self.thread.join(2)
        self.tmp.cleanup()

    def configuration(self, **changes):
        value = {"schema_version": 1, "port": 0, "data_dir": str(self.root / "data"),
                 "clients": [{"subject": "pa-test", "token_env": "LP_PA_TEST_TOKEN"}],
                 "async_policy": {"max_running_per_session": 2, "max_model_requests": 4,
                                  "max_local_model_requests": 2},
                 "routes": {"localpilot": {"workspace": str(self.workspace), "engine": "v5",
                     "backend": {"kind": "local-openai", "model": "fixture", "context_budget": 32768,
                                 "base_url": f"http://127.0.0.1:{self.model.server_port}/v1",
                                 "capabilities": {"tool_calling": True, "streaming": False}},
                     "budgets": {"max_steps": 20, "max_tool_calls": 20, "max_token_units": 1000000,
                                 "max_worker_steps": 4, "max_worker_token_units": 100000}}}}
        value.update(changes)
        return value

    def service(self, config):
        path = self.root / "service.json"
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        server = build(path)
        self.services.append(server)
        return server

    def test_two_configured_workers_overlap_read_files_and_survive_restart(self):
        config = self.configuration()
        server = self.service(config)
        first = server.service.create_task(TaskRequest("Read both public files", idempotency_key="once"))
        final = server.service.wait(first["id"])
        self.assertEqual(final["status"], "completed", final.get("error"))
        self.assertEqual(len(final["subagents"]), 2)
        self.assertTrue(all(item["collected"] for item in final["subagents"]))
        reads = [item for item in final["tools"] if item["name"] == "read_file"]
        self.assertEqual(len(reads), 2)
        self.assertEqual({json.loads(item["arguments"])["path"] for item in reads}, {"left.txt", "right.txt"})
        runtime = server.service.sessions[first["session_id"]].runtime
        self.assertIs(runtime._scheduler, server.service.scheduler)
        self.assertEqual(server.catalog["localpilot"]["orchestration"]["mode"], "async_children")
        count = len(self.calls)
        server.service.suspend()
        restored = self.service(config)
        self.assertEqual(restored.service.task_snapshot(first["id"])["tools"], final["tools"])
        repeated = restored.service.create_task(TaskRequest("Read both public files", idempotency_key="once"))
        self.assertEqual(repeated["id"], first["id"])
        self.assertEqual(len(self.calls), count)

    def test_default_service_keeps_sync_schema(self):
        config = self.configuration()
        del config["async_policy"]
        server = self.service(config)
        session = server.service.create_session()
        runtime = server.service.sessions[session["id"]].runtime
        self.assertIsNone(server.service.scheduler)
        self.assertNotIn("child_status", [s["function"]["name"] for s in runtime._schemas()])

    def test_policy_change_does_not_silently_restore_old_session(self):
        config = self.configuration()
        server = self.service(config)
        server.service.create_session()
        server.service.suspend()
        config["async_policy"]["max_model_requests"] = 1
        with self.assertRaises(PersistenceError):
            self.service(config)

    def test_invalid_resource_limits_rejected_at_config_entry(self):
        for value in (None, [], {"max_running_children": 0}, {"unknown": 1}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.service(self.configuration(async_policy=value))


if __name__ == "__main__":
    unittest.main()
