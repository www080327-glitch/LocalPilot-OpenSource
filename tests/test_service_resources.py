"""Actual authenticated HTTP; scripted inference, zero paid/model load calls."""
from dataclasses import replace
import json
import threading
import unittest
from urllib.error import HTTPError

from localpilot_service.security import Principal
from localpilot_service.sdk import Client
from tests import test_agent_service as fixtures
from tests.test_runtime_api import StreamBackend, answer, call


class ResourceControlTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.AgentServiceTests(methodName="test_client_isolation_and_operator_binding")
        self.fixture.setUp()

    def tearDown(self):self.fixture.tearDown()

    def test_route_model_manager_survives_switch_to_cloud_backend(self):
        from unittest.mock import Mock
        from types import SimpleNamespace
        f=self.fixture;task=f.codex.submit("one",idempotency_key="handoff-resource");f.service.wait(task["id"])
        internal=f.service._task(task["id"]);manager=Mock();manager.status.return_value={"model_process_alive":False}
        f.server.model_hosts={internal.model:manager}
        internal.service_metadata["control_ticket"]="known-ticket"
        self.assertIs(f.server.resources.manager(internal),manager)
        f.codex.request("/localpilot/v1/inference/heartbeat",{"task_id":task["id"],"ticket_id":"known-ticket"})
        manager.heartbeat.assert_called_once_with(task["id"],"known-ticket")
        self.assertFalse(f.codex.status(task["id"])["model_resource"]["model_process_alive"])

    def test_drain_preserves_paid_current_reply_and_no_followup(self):
        f=self.fixture;backend=StreamBackend();f.backend=backend
        task=f.codex.submit("public streaming question",idempotency_key="drain")
        self.assertTrue(backend.first.wait(2))
        result=f.codex.request("/localpilot/v1/inference/stop",{"task_id":task["id"],"drain_response":True})
        self.assertTrue(result["drain_current_response"])
        backend.release.set();f.service.wait(task["id"])
        final=f.codex.status(task["id"])
        self.assertEqual(final["status"],"cancelled")
        self.assertIn("hello 世界",final["result"]["text"])
        self.assertEqual(len(backend.requests),1)

    def test_stop_cannot_cancel_other_client(self):
        f=self.fixture;task=f.codex.submit("one",idempotency_key="one");f.service.wait(task["id"])
        with self.assertRaises(HTTPError) as caught:
            f.dsh.request("/localpilot/v1/inference/stop",{"task_id":task["id"]})
        self.assertEqual(caught.exception.code,404);caught.exception.close()

    def test_global_stop_fences_delayed_submit(self):
        f=self.fixture
        f.codex.request("/localpilot/v1/inference/stop",{})
        req=f.codex._request("/localpilot/v1/tasks",{"input":"late"},key="late")
        req.add_header("X-LocalPilot-Client-Generation","0")
        with self.assertRaises(HTTPError) as caught:f.codex.opener.open(req)
        self.assertEqual(caught.exception.code,409);caught.exception.close()
        self.assertEqual(len(f.service.tasks),0)

    def test_resource_operator_is_not_tool_operator(self):
        f=self.fixture
        f.access.principals["resource"]=Principal("resource","x"*32,operator=True,
            scopes=frozenset({"read","resource_control"}),approval_for=("codex",))
        f.backend.steps[:]=[answer(None,call("apply_patch",{"changes":[{"path":"no.txt","operation":"create","content":"x"}]}))]
        task=f.codex.submit("write",idempotency_key="write");f.service.wait(task["id"])
        task=f.codex.status(task["id"])
        operator=Client(f.url,token="x"*32)
        with self.assertRaises(HTTPError) as caught:
            operator.request("/localpilot/v1/tasks/"+task["id"]+"/cloud/approve",{"action_id":task["required_action"]["id"]})
        self.assertEqual(caught.exception.code,403);caught.exception.close()
        self.assertFalse((f.workspace/"no.txt").exists())

    def test_memory_ticket_is_subject_key_and_scope_bound(self):
        f=self.fixture
        f.access.principals["resource"]=Principal("resource","x"*32,operator=True,
            scopes=frozenset({"resource_control"}),approval_for=("codex",))
        resource=f.server.resources
        grant=resource.memory_consent(f.principals[0],f.access.principals["resource"],"memory_ticket_123456","one")
        self.assertEqual(grant["scope"],"model_memory_gate_only")
        self.assertNotIn("token",json.dumps(grant))
        with self.assertRaises(Exception):resource.memory_consent(f.principals[1],f.access.principals["resource"],"memory_ticket_123456","one")
        with self.assertRaises(Exception):resource.memory_consent(f.principals[0],f.access.principals["resource"],"memory_ticket_123456","changed")

    def test_urgent_stop_remains_available_after_rate_limit(self):
        f=self.fixture
        p=replace(f.principals[0],requests_per_minute=1)
        f.access.principals[p.subject]=p
        f.codex.request("/healthz")
        stopped=f.codex.request("/localpilot/v1/inference/stop",{})
        self.assertEqual(stopped["status"],"stopping")
