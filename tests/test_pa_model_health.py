"""Real loopback discovery requests, with no model inference or process control."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError

from agent.deepseek import DeepSeekBackend
from agent.local_http import LocalHTTPBackend
from agent.omlx import OMLXBackend
from localpilot_service.backend_contract import ManagedLocalBackend
from localpilot_service.model_health import probe_model_health
from localpilot_api.service import TaskService
from localpilot_service.security import AccessPolicy, Principal
from localpilot_service.server import ServiceServer
from localpilot_service.sdk import Client


class ReadOnlyProvider:
    def __init__(self):
        self.responses = {"/v1/models": (200, {"data": [{"id": "fixture"}]})}
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.requests.append((self.command, self.path, self.headers.get("Authorization")))
                status, data = owner.responses.get(self.path, (404, {"error": "unavailable"}))
                body = data if isinstance(data, bytes) else json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                owner.requests.append((self.command, self.path, self.headers.get("Authorization")))
                self.send_error(405)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class ModelHealthTests(unittest.TestCase):
    def setUp(self):
        self.provider = ReadOnlyProvider()
        self.addCleanup(self.provider.close)

    def backend(self, cls=LocalHTTPBackend, **kwargs):
        return cls(base_url=self.provider.base_url, model="fixture", timeout=.2, **kwargs)

    def test_discovery_does_not_claim_loaded_inference_or_tool_qualification(self):
        self.provider.responses["/v1/models"] = (200, {
            "data": [{"id": "fixture", "loaded": True, "private": "provider-private"}],
            "api_key": "provider-secret",
        })
        observed = probe_model_health(self.backend(api_key="fixture-secret"))
        self.assertEqual(observed["status"], "OBSERVED")
        self.assertTrue(observed["endpoint_reachable"])
        self.assertEqual(observed["authentication"], "ACCEPTED")
        self.assertEqual(observed["authentication_scope"], "model_discovery_only")
        self.assertTrue(observed["model_listed"])
        self.assertIsNone(observed["model_loaded"])
        self.assertEqual(observed["inference"], "NOT_PROBED")
        self.assertEqual(observed["tool_execution"], "NOT_PROBED")
        self.assertEqual(self.provider.requests, [("GET", "/v1/models", "Bearer fixture-secret")])
        for private in ("fixture-secret", "provider-secret", "provider-private", self.provider.base_url):
            self.assertNotIn(private, json.dumps(observed))

    def test_anonymous_discovery_and_absent_configured_model(self):
        self.provider.responses["/v1/models"] = (200, {"data": [{"id": "other"}]})
        observed = probe_model_health(self.backend())
        self.assertEqual(observed["status"], "OBSERVED")
        self.assertEqual(observed["authentication"], "NOT_REQUIRED")
        self.assertFalse(observed["model_listed"])
        self.assertIsNone(observed["model_loaded"])
        self.assertEqual(observed["reason"], "model_not_listed")

    def test_authentication_failure_is_reachable_but_never_echoes_error_body(self):
        for code in (401, 403):
            with self.subTest(code=code):
                self.provider.responses["/v1/models"] = (code, {"error": "Bearer fixture-secret"})
                observed = probe_model_health(self.backend(api_key="fixture-secret"))
                self.assertEqual(observed["status"], "FAILED")
                self.assertTrue(observed["endpoint_reachable"])
                self.assertEqual(observed["authentication"], "REJECTED")
                self.assertEqual(observed["http_status"], code)
                self.assertIsNone(observed["model_listed"])
                self.assertNotIn("fixture-secret", json.dumps(observed))

    def test_provider_unavailable_response_does_not_imply_valid_credentials(self):
        self.provider.responses["/v1/models"] = (503, {"error": "provider-private"})
        observed = probe_model_health(self.backend(api_key="fixture-secret"))
        self.assertTrue(observed["endpoint_reachable"])
        self.assertEqual(observed["authentication"], "UNKNOWN")
        self.assertEqual(observed["http_status"], 503)
        self.assertIsNone(observed["model_listed"])
        self.assertNotIn("provider-private", json.dumps(observed))

    def test_closed_endpoint_does_not_become_online_from_configuration(self):
        backend = self.backend(api_key="fixture-secret")
        self.provider.close()
        observed = probe_model_health(backend)
        self.assertEqual(observed["status"], "FAILED")
        self.assertFalse(observed["endpoint_reachable"])
        self.assertEqual(observed["authentication"], "UNKNOWN")
        self.assertIsNone(observed["model_listed"])
        self.assertEqual(observed["reason"], "transport_unavailable")
        self.assertNotIn(self.provider.base_url, json.dumps(observed))

    def test_malformed_discovery_is_not_a_model_health_pass(self):
        for data in (b"not json", [], {"data": "fixture"}, {"data": [None]}, {"data": [{"id": 4}]}):
            with self.subTest(data=data):
                self.provider.responses["/v1/models"] = (200, data)
                observed = probe_model_health(self.backend())
                self.assertEqual(observed["status"], "FAILED")
                self.assertTrue(observed["endpoint_reachable"])
                self.assertEqual(observed["reason"], "invalid_model_discovery")
                self.assertIsNone(observed["model_listed"])

    def test_omlx_reports_loaded_and_loading_without_inference(self):
        self.provider.responses["/api/status"] = (200, {"loaded_models": ["fixture"]})
        for loaded, loading in ((False, False), (False, True), (True, False)):
            with self.subTest(loaded=loaded, loading=loading):
                self.provider.responses["/v1/models/status"] = (200, {"models": [
                    {"id": "fixture", "loaded": loaded, "is_loading": loading},
                ]})
                observed = probe_model_health(self.backend(OMLXBackend))
                self.assertEqual(observed["status"], "OBSERVED")
                self.assertEqual(observed["model_loaded"], loaded)
                self.assertEqual(observed["model_loading"], loading)
                self.assertEqual(observed["inference"], "NOT_PROBED")
                self.assertEqual(observed["tool_execution"], "NOT_PROBED")
        self.assertTrue(all(method == "GET" for method, _, _ in self.provider.requests))
        self.assertEqual({path for _, path, _ in self.provider.requests},
                         {"/v1/models", "/api/status", "/v1/models/status"})

    def test_omlx_missing_status_preserves_discovery_but_loaded_is_unknown(self):
        observed = probe_model_health(self.backend(OMLXBackend))
        self.assertEqual(observed["status"], "OBSERVED")
        self.assertTrue(observed["model_listed"])
        self.assertIsNone(observed["model_loaded"])
        self.assertEqual(observed["loaded_state_reason"], "omlx_status_unavailable")

    def test_omlx_missing_loaded_fields_are_unknown_not_unloaded(self):
        self.provider.responses["/api/status"] = (200, {})
        observed = probe_model_health(self.backend(OMLXBackend))
        self.assertTrue(observed["model_listed"])
        self.assertIsNone(observed["model_loaded"])
        self.assertEqual(observed["loaded_state_reason"], "omlx_loaded_state_unknown")
        self.provider.responses["/api/status"] = (200, {"loaded_models": []})
        observed = probe_model_health(self.backend(OMLXBackend))
        self.assertFalse(observed["model_loaded"])
        self.provider.responses["/api/status"] = (200, {"loaded_models": ["fixture"]})
        observed = probe_model_health(self.backend(OMLXBackend))
        self.assertTrue(observed["model_loaded"])

    def test_managed_backend_discovery_never_acquires_loading_lease(self):
        class Manager:
            token = "fixture-secret"

            def inference(self):
                raise AssertionError("A health probe must not acquire a model lease")

        observed = probe_model_health(self.backend(ManagedLocalBackend, manager=Manager()))
        self.assertTrue(observed["model_listed"])
        self.assertIsNone(observed["model_loaded"])
        self.assertEqual(len(self.provider.requests), 1)

    def test_deepseek_does_not_use_completion_transport_as_health_probe(self):
        backend = DeepSeekBackend(api_key="fixture-secret")
        with patch.object(backend, "_open", side_effect=AssertionError("No completion probe")) as wire:
            observed = probe_model_health(backend)
        wire.assert_not_called()
        self.assertEqual(observed["status"], "NOT_PROBED")
        self.assertIsNone(observed["endpoint_reachable"])
        self.assertIsNone(observed["model_listed"])
        self.assertEqual(observed["authentication"], "UNKNOWN")
        self.assertEqual(self.provider.requests, [])


class ModelHealthServiceTests(unittest.TestCase):
    def setUp(self):
        self.provider = ReadOnlyProvider()
        self.addCleanup(self.provider.close)

        def no_runtime(callback):
            self.fail("Model discovery must not create an AgentSession")

        self.service = TaskService({name: no_runtime for name in ("internal-local", "internal-secret", "internal-pending")})
        self.addCleanup(self.service.shutdown)
        routes = {"personal": "internal-local", "pending": "internal-pending"}
        self.access = AccessPolicy([
            Principal("reader", "r" * 32, scopes=frozenset({"read"}), routes=routes),
            Principal("submitter", "s" * 32, scopes=frozenset({"submit"}), routes=routes),
            Principal("other", "o" * 32, scopes=frozenset({"read"}), routes={"secret": "internal-secret"}),
        ])
        self.addCleanup(self.access.close)
        self.server = ServiceServer(("127.0.0.1", 0), self.service, access=self.access,
            catalog={"internal-local": {"deployment_status": "not_deployed"},
                     "internal-pending": {"deployment_status": "unavailable"}})
        self.server.inference_backends = {"internal-local": LocalHTTPBackend(
            base_url=self.provider.base_url, model="fixture", timeout=.2)}
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.reader = Client(self.url, token="r" * 32)

    def stop_server(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def test_read_scoped_discovery_does_not_promote_configured_model_to_ready(self):
        health = self.reader.request("/healthz")
        self.assertEqual(health["model_health"], "NOT_PROBED")
        self.assertEqual(self.provider.requests, [])
        result = self.reader.request("/localpilot/v1/model-health", {"model": "personal"})
        self.assertEqual(result["model"], "personal")
        self.assertEqual(result["status"], "OBSERVED")
        self.assertTrue(result["model_listed"])
        self.assertIsNone(result["model_loaded"])
        self.assertEqual(result["inference"], "NOT_PROBED")
        catalog = self.server.catalog["internal-local"]
        self.assertEqual(catalog["deployment_status"], "not_deployed")
        self.assertEqual(catalog["health_observation"], {k: v for k, v in result.items() if k != "model"})
        self.assertEqual(self.service.tasks, {})
        self.assertEqual(self.service.sessions, {})
        self.assertEqual(self.provider.requests, [("GET", "/v1/models", None)])

    def test_scope_route_identity_and_body_are_checked_before_provider_access(self):
        cases = [
            (self.reader, {"model": "internal-local"}, 404),
            (self.reader, {"model": "secret"}, 404),
            (self.reader, {"model": "unregistered"}, 404),
            (self.reader, {"model": "personal", "base_url": self.provider.base_url}, 400),
            (Client(self.url, token="s" * 32), {"model": "personal"}, 403),
        ]
        for client, body, code in cases:
            with self.subTest(body=body, code=code):
                with self.assertRaises(HTTPError) as caught:
                    client.request("/localpilot/v1/model-health", body)
                self.assertEqual(caught.exception.code, code)
                caught.exception.close()
        self.assertEqual(self.provider.requests, [])
        self.assertNotIn("health_observation", self.server.catalog["internal-local"])

    def test_registered_route_without_constructed_backend_is_not_probed(self):
        result = self.reader.request("/localpilot/v1/model-health", {"model": "pending"})
        self.assertEqual(result["model"], "pending")
        self.assertEqual(result["status"], "NOT_PROBED")
        self.assertIsNone(result["endpoint_reachable"])
        self.assertIsNone(result["model_loaded"])
        self.assertEqual(self.server.catalog["internal-pending"]["deployment_status"], "unavailable")
        self.assertEqual(self.provider.requests, [])


if __name__ == "__main__":
    unittest.main()
