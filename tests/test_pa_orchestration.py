"""Real configured service, HTTP model transport and threaded workers; no model score."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from copy import deepcopy
from pathlib import Path
import shutil
import ssl
import subprocess
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
        self.model_names = ['fixture']
        self.worker_routes = {name: {'backend_preference':'local'} for name in ('left', 'right')}
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
                self.send_json({"data": [{"id": name} for name in outer.model_names]})

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
                        tool_call("delegate", {"task": "child-" + name, **outer.worker_routes[name],
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

    def test_new_async_route_preserves_existing_synchronous_session(self):
        config = self.configuration()
        limits = config.pop('async_policy')
        server = self.service(config)
        sid = server.service.create_session()['id']
        configuration_sha = server.service.sessions[sid].runtime._persistence_config
        server.service.suspend()
        config['async_policy'] = limits
        config['routes']['localpilot']['orchestration_mode'] = 'sync'
        config['routes']['collaborator'] = deepcopy(config['routes']['localpilot'])
        config['routes']['collaborator']['orchestration_mode'] = 'async'
        restored = self.service(config)
        old = restored.service.sessions[sid].runtime
        self.assertEqual(old._persistence_config, configuration_sha)
        self.assertIsNone(old.async_policy)
        new_sid = restored.service.create_session('collaborator')['id']
        new = restored.service.sessions[new_sid].runtime
        self.assertIs(new._scheduler, restored.service.scheduler)
        self.assertIn('wait_children', [s['function']['name'] for s in new._schemas()])
        self.assertNotIn('wait_children', [s['function']['name'] for s in old._schemas()])

    @unittest.skipUnless(shutil.which('openssl'), 'A local TLS fixture requires openssl')
    def test_different_local_and_cloud_workers_use_real_transports_and_preserve_identity(self):
        certificate, key = self.root/'fixture.pem', self.root/'fixture-key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                        '-keyout',str(key),'-out',str(certificate),'-subj','/CN=127.0.0.1',
                        '-addext','subjectAltName=IP:127.0.0.1'], check=True, capture_output=True)
        tls = ThreadingHTTPServer(('127.0.0.1', 0), self.model.RequestHandlerClass)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, key)
        tls.socket = context.wrap_socket(tls.socket, server_side=True)
        thread = threading.Thread(target=tls.serve_forever, daemon=True)
        thread.start()
        try:
            self.model_names += ['worker-local', 'worker-cloud']
            self.worker_routes = {
                'left': {'backend_preference':'local', 'backend_id':'route:local-worker'},
                'right': {'backend_preference':'cloud', 'backend_id':'route:cloud-worker'}}
            config = self.configuration()
            primary = config['routes']['localpilot']
            for name in ('local-worker','cloud-worker'):
                config['routes'][name] = deepcopy(primary)
                config['routes'][name]['orchestration_mode'] = 'sync'
            config['routes']['local-worker']['backend']['model'] = 'worker-local'
            config['routes']['cloud-worker']['backend'].update(kind='remote-openai', model='worker-cloud',
                base_url=f'https://127.0.0.1:{tls.server_port}/v1', api_key_env='LP_CLOUD_FIXTURE_TOKEN')
            primary.update(cloud_egress='CLOUD_ALLOWED', cooperation={
                'routes':['local-worker','cloud-worker'], 'optimizer':{'mode':'local-first'}})
            with patch.dict(os.environ, {'SSL_CERT_FILE':str(certificate), 'LP_CLOUD_FIXTURE_TOKEN':'fixture-only'}):
                server = self.service(config)
                sid = server.service.create_session(desktop_options={
                    'permission_mode':'full', 'agent_profile':'standard', 'prompt_revision':2, 'scope_revision':3})['id']
                task = server.service.create_task(TaskRequest('Read both public files', session_id=sid,
                                                             idempotency_key='mixed-workers'))
                final = server.service.wait(task['id'])
                self.assertEqual(final['status'], 'completed', final.get('error'))
                records = server.service.sessions[sid].runtime.subagents
                self.assertEqual({r['configured_model'] for r in records}, {'worker-local','worker-cloud'})
                self.assertEqual({r['backend'] for r in records}, {'local','cloud'})
                self.assertTrue(all(r['receipts'] and r['collected'] for r in records))
                self.assertEqual({body['model'] for body in self.calls}, {'fixture','worker-local','worker-cloud'})
                mix = server.service.sessions[sid].runtime.hybrid.summary()['source_mix']
                self.assertEqual(mix['by_source']['cloud']['dispatched_requests'], 2)
                self.assertAlmostEqual(mix['by_source']['cloud']['request_share'], 2 / len(self.calls))
                self.assertAlmostEqual(sum(row['token_share'] for row in mix['by_source'].values()), 1)
                requests = len(self.calls)
                server.service.suspend()
                restored = self.service(config)
                self.assertEqual(restored.service.sessions[sid].runtime.subagents, records)
                self.assertEqual(restored.service.create_task(TaskRequest('Read both public files', session_id=sid,
                    idempotency_key='mixed-workers'))['id'], task['id'])
                self.assertEqual(len(self.calls), requests)
        finally:
            tls.shutdown()
            tls.server_close()
            thread.join(2)

    def test_invalid_resource_limits_rejected_at_config_entry(self):
        for value in (None, [], {"max_running_children": 0}, {"unknown": 1}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.service(self.configuration(async_policy=value))


if __name__ == "__main__":
    unittest.main()
