"""Connection-close framing through the real API and authenticated facade."""
from http.client import HTTPConnection
import json
import unittest

from tests import test_agent_service as service_fixtures
from tests import test_runtime_api as api_fixtures


class ConnectionLifecycleTests(unittest.TestCase):
    def test_api_error_then_valid_request_on_the_same_client(self):
        fixture = api_fixtures.APITests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        client = HTTPConnection("127.0.0.1", fixture.server.server_port, timeout=3)
        self.addCleanup(client.close)
        headers = {"Authorization": "Bearer test-key", "Content-Type": "application/json"}
        for body in ({}, {"input": "a", "max_output_tokens": True}, {"input": "a", "temperature": 0}):
            client.request("POST", "/v1/responses", json.dumps(body), headers)
            with client.getresponse() as response:
                self.assertEqual(response.status, 400)
                self.assertEqual(response.getheader("Connection"), "close")
                self.assertTrue(json.loads(response.read())["error"]["message"])
            client.request("GET", "/v1/models", headers=headers)
            with client.getresponse() as response:
                self.assertEqual(response.status, 200)
                self.assertIsNone(response.getheader("Connection"))
                self.assertEqual(len(json.loads(response.read())["data"]), 2)
        self.assertEqual(fixture.backend.requests, [])

    def test_facade_announces_close_for_rejected_and_successful_responses(self):
        fixture = service_fixtures.AgentServiceTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        client = HTTPConnection("127.0.0.1", fixture.server.server_port, timeout=3)
        self.addCleanup(client.close)
        for token, expected in (("wrong", 401), ("c" * 32, 400)):
            client.request("POST", "/v1/responses", "{}",
                           {"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            with client.getresponse() as response:
                self.assertEqual(response.status, expected)
                self.assertEqual(response.getheader("Connection"), "close")
                self.assertTrue(json.loads(response.read())["error"]["message"])
            client.request("GET", "/healthz", headers={"Authorization": "Bearer " + "c" * 32})
            with client.getresponse() as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Connection"), "close")
                response.read()
        self.assertEqual(fixture.backend.requests, [])


if __name__ == "__main__":
    unittest.main()
