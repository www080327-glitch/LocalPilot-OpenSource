"""Real TLS/SSE protocol fixtures, not OpenAI inference or agent quality scores."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from agent.backends import Message
from agent.cloud_credentials import CloudCredentialError
from agent.local_http import LocalBackendError
from agent.persistence import backend_identity
from agent.policy import DataPolicy
from localpilot_api.service import APIError
from localpilot_service.backend_contract import ServiceOpenAIBackend, ServiceOpenAICloudBackend
from localpilot_service.deployment import build
from localpilot_service.route_backends import build_backend
from localpilot_service.routing import select_route
from localpilot_service.sdk import Client
from tests.test_local_http_backend import MockServer, completion, sse, tool_call


class OpenAICloudConfigurationTests(unittest.TestCase):
    def test_explicit_kind_defaults_and_legacy_identity(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-not-a-real-key"}):
            backend = build_backend({"kind": "openai", "model": "operator-selected-model"}, DataPolicy())
        self.assertIsInstance(backend, ServiceOpenAICloudBackend)
        self.assertEqual(backend.base_url, "https://api.openai.com/v1")
        self.assertFalse(backend.is_local)
        self.assertTrue(backend.include_stream_usage)
        self.assertEqual(backend.profile.service_location, "remote")
        self.assertEqual(backend_identity(backend)["provider"], "openai")
        self.assertNotIn("fixture-not-a-real-key", json.dumps(backend_identity(backend)))
        legacy = ServiceOpenAIBackend(base_url="http://127.0.0.1:9/v1", model="fixture")
        self.assertEqual(legacy.service_contract, {"generation_parameters": {}, "timeout": 30})
        self.assertEqual(legacy._payload([Message("user", "hi")], None, 32)["max_tokens"], 32)
        self.assertNotIn("max_completion_tokens", legacy._payload([], None, 32))

    def test_missing_key_plain_http_and_local_template_rejected(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with self.assertRaisesRegex(CloudCredentialError, "missing_credentials"):
                build_backend({"kind": "openai", "model": "fixture"}, DataPolicy())
        for options in ({"base_url": "http://127.0.0.1:9/v1"},
                        {"chat_template_kwargs": {"enable_thinking": False}}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                ServiceOpenAICloudBackend(model="fixture", api_key="fixture", **options)

    def test_five_mode_source_filter_recognizes_openai(self):
        routes = {"openai": "remote", "local": "local"}
        catalog = {"remote": {"adapter": "openai", "model": "cloud-model", "cloud_egress": "LOCAL_ONLY"},
                   "local": {"adapter": "local-openai", "model": "local-model", "cloud_egress": "LOCAL_ONLY"}}
        for source, expected in (("local_only", "local"), ("local_first", "local"),
                                 ("balanced", "openai"), ("cloud_first", "openai"),
                                 ("cloud_only", "openai")):
            with self.subTest(source=source):
                chosen, decision = select_route(routes, catalog, routing_preferences={
                    "version": "1.0", "source": source, "objective": "balanced"})
                self.assertEqual(chosen, expected)
                self.assertFalse(decision["backend_fallback"])
        with self.assertRaises(APIError) as rejected:
            select_route(routes, catalog, explicit="openai", routing_preferences={
                "version": "1.0", "source": "local_only", "objective": "quality"})
        self.assertEqual(rejected.exception.code, "model_source_forbidden")


@unittest.skipUnless(shutil.which("openssl"), "Local TLS fixture requires openssl")
class OpenAICloudFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cert_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.cert_dir.cleanup)
        cls.certificate = Path(cls.cert_dir.name) / "fixture.pem"
        cls.key = Path(cls.cert_dir.name) / "fixture-key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-keyout", str(cls.key), "-out", str(cls.certificate), "-subj", "/CN=127.0.0.1",
                        "-addext", "subjectAltName=IP:127.0.0.1"], check=True, capture_output=True)

    def setUp(self):
        self.model = MockServer()
        self.model.http.shutdown()
        self.model.thread.join()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.certificate, self.key)
        self.model.http.socket = context.wrap_socket(self.model.http.socket, server_side=True)
        self.model.thread = threading.Thread(target=self.model.http.serve_forever, daemon=True)
        self.model.thread.start()
        self.model.base_url = self.model.base_url.replace("http://", "https://", 1)
        self.addCleanup(self.model.close)
        environment = patch.dict(os.environ, {"SSL_CERT_FILE": str(self.certificate),
            "OPENAI_API_KEY": "fixture-not-a-real-key", "LP_OPENAI_CLIENT": "o" * 32,
            "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"})
        environment.start()
        self.addCleanup(environment.stop)

    def backend(self, **options):
        return build_backend({"kind": "openai", "model": "mock-local",
                              "base_url": self.model.base_url, **options}, DataPolicy())


class OpenAICloudTransportTests(OpenAICloudFixture):
    def test_json_tool_call_and_sse_report_reasoning_usage(self):
        backend = self.backend(capabilities={"reasoning": True}, reasoning_efforts=["low"])
        self.model.add(completion(calls=[tool_call("read_file", {"path": "fact.txt"})]))
        reply = backend.request([Message("user", "Read the fact")], max_tokens=128, thinking="low")
        self.assertEqual(reply.message.tool_calls[0].name, "read_file")
        usage = {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19,
                 "prompt_tokens_details": {"cached_tokens": 4},
                 "completion_tokens_details": {"reasoning_tokens": 5}}
        self.model.add(sse({"model": "mock-local", "choices": [{"index": 0,
            "delta": {"content": "FIXTURE"}, "finish_reason": "stop"}]},
            {"choices": [], "usage": usage}), content_type="text/event-stream")
        chunks = list(backend.stream([Message("user", "Reply")], max_tokens=128, thinking="low"))
        self.assertEqual(chunks[-1].response.message.content, "FIXTURE")
        self.assertEqual(chunks[-1].response.usage["completion_tokens_details"], {"reasoning_tokens": 5})
        self.assertEqual(chunks[-1].response.usage["prompt_cache_hit_tokens"], 4)
        for body in self.model.requests:
            self.assertEqual(body["max_completion_tokens"], 128)
            self.assertEqual(body["reasoning_effort"], "low")
            self.assertNotIn("max_tokens", body)
            self.assertNotIn("temperature", body)
            self.assertNotIn("chat_template_kwargs", body)
        self.assertEqual(self.model.requests[-1]["stream_options"], {"include_usage": True})
        self.assertEqual(self.model.headers, [("/v1/chat/completions", "Bearer fixture-not-a-real-key")] * 2)

    def test_task_uses_product_tools_and_restores_without_replay(self):
        self.model.add(completion(calls=[tool_call("read_file", {"path": "fact.txt"})]))
        self.model.add(completion("PUBLIC-FIXTURE-FACT"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "fact.txt").write_text("PUBLIC-FIXTURE-FACT")
            config = {"schema_version": 1, "port": 0, "data_dir": str(root / "data"),
                "clients": [{"subject": "fixture", "token_env": "LP_OPENAI_CLIENT"}],
                "routes": {"localpilot": {"workspace": str(workspace), "permissions": "approve-mutations",
                    "capabilities": {"read": True, "write": False, "execute": False, "read_only": True},
                    "backend": {"kind": "openai", "model": "mock-local", "base_url": self.model.base_url,
                                "capabilities": {"streaming": False}},
                    "cloud_egress": "CLOUD_ALLOWED", "budgets": {"max_output_tokens": 128}}}}
            path = root / "service.json"
            path.write_text(json.dumps(config))
            path.chmod(0o600)
            servers = []
            try:
                server = build(path)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                servers.append((server, thread))
                thread.start()
                client = Client(f"http://127.0.0.1:{server.server_port}", token="o" * 32)
                task = client.submit("Read fact.txt", idempotency_key="openai-fixture")
                server.service.wait(task["id"])
                final = client.status(task["id"])
                self.assertEqual(final["status"], "completed", final.get("error"))
                self.assertEqual(final["tools"][0]["payload"]["result"], "PUBLIC-FIXTURE-FACT")
                self.assertFalse(final["service"]["route_decision"]["backend_fallback"])
                server.service.suspend()
                server.shutdown()
                thread.join(2)
                restored = build(path)
                thread = threading.Thread(target=restored.serve_forever, daemon=True)
                servers.append((restored, thread))
                thread.start()
                client = Client(f"http://127.0.0.1:{restored.server_port}", token="o" * 32)
                self.assertEqual(client.submit("Read fact.txt", idempotency_key="openai-fixture")["id"], task["id"])
                self.assertEqual(len(self.model.requests), 2)
                self.assertTrue(all(row["max_completion_tokens"] == 128 for row in self.model.requests))
            finally:
                for server, thread in reversed(servers):
                    if thread.is_alive():
                        server.shutdown()
                    thread.join(2)
                    if not server.service.closed:
                        server.service.shutdown()
                    server.server_close()
                    server.access.close()

    def test_http_failure_and_redirect_keep_original_request(self):
        self.model.add({"error": {"message": "fixture-not-a-real-key"}}, status=401)
        backend = self.backend()
        with self.assertRaises(LocalBackendError) as failed:
            backend.request([Message("user", "fixture")], max_tokens=32)
        self.assertEqual(failed.exception.status_code, 401)
        self.assertNotIn("fixture-not-a-real-key", str(failed.exception))
        self.model.redirect_url = "https://127.0.0.1:9/never-follow"
        self.model.add({}, status=307)
        with self.assertRaisesRegex(LocalBackendError, "redirect refused"):
            backend.request([Message("user", "fixture")], max_tokens=32)
        self.assertEqual(len(self.model.requests), 2)

    def test_explicit_cloud_transport_inherits_https_proxy(self):
        connect_paths = []

        class Proxy(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_CONNECT(self):
                connect_paths.append(self.path)
                self.send_error(502, "fixture proxy refusal")

        proxy = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
        thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {"https_proxy": f"http://127.0.0.1:{proxy.server_port}",
                                         "NO_PROXY": "", "no_proxy": ""}):
                backend = self.backend(timeout=2)
                with self.assertRaises(LocalBackendError):
                    backend.request([Message("user", "fixture")], max_tokens=32)
            self.assertEqual(connect_paths, [f"127.0.0.1:{self.model.http.server_port}"])
            self.assertEqual(self.model.requests, [])
        finally:
            proxy.shutdown()
            proxy.server_close()
            thread.join(2)
