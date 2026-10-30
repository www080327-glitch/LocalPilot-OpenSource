"""Independent regressions for V0.4 authorization, recovery and async ingestion.

All providers are offline fixtures. Existing service fixture setup is reused;
the test class does not inherit or re-export its original test methods.
"""
from copy import deepcopy
from dataclasses import asdict
import json
from queue import Empty
import threading
import unittest
from unittest.mock import Mock, patch

import companion.tests.test_v04_service as service_fixtures
from companion.escalation.localpilot import result_memory, task_view
from companion.escalation.service_v491 import LocalPilotProvider
from companion.escalation.provider import EscalationRequest, OpenAICompatibleProvider
from companion.observers.events import ObservationEvent


def escalation(text="Task A", memories=None, recent=None, local_only=True):
    return EscalationRequest(text, "manual", "complex", memories or [], [], recent or [],
                             {"local_only": local_only}, "Prepared, not executed")


def view(status="completed", text="Mock task result", quiet=True):
    return task_view({"id":"resp_fixture", "session_id":"sess_fixture", "object":"localpilot.task",
                      "status":status, "quiescent":quiet, "last_event_id":3,
                      "result":{"text":text,"verification_status":"not_run"},
                      "required_action":{"type":"approval","id":"approval_fixture"} if status=="requires_approval" else None})


class ProviderFixture:
    result_memory = staticmethod(result_memory)

    def __init__(self, result=None):
        self.result = result or view()
        self.calls = []
        self.release = threading.Event()
        self.entered = threading.Event()
        self.block_stream = False

    def available(self):
        return True

    def submit(self, request, approved=False, **kwargs):
        if approved is not True:
            return {"status":"approval_required", "phase":"suggested"}
        self.calls.append(("submit", asdict(request), kwargs))
        return deepcopy(self.result)

    def status(self, task_id, **kwargs):
        self.calls.append(("status", task_id, kwargs))
        return deepcopy(self.result)

    def stream(self, task_id, **kwargs):
        self.calls.append(("stream", task_id, kwargs))
        self.entered.set()
        if self.block_stream:
            self.release.wait(2)
        yield {"task_status":deepcopy(self.result),"last_event_id":3}

    def approve(self, *args, **kwargs):
        raise AssertionError("Monitor must never approve tools")

    def cancel(self, *args, **kwargs):
        raise AssertionError("Monitor must never cancel tasks")


class AuthorizationV04Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = service_fixtures.ServiceV04Tests(methodName="test_default_no_native_capture")
        self.fixture.setUp()
        self.app, self.config, self.docs = self.fixture.app, self.fixture.config, self.fixture.docs
        self.config.localpilot_endpoint = "http://127.0.0.1:18765"
        self.config.localpilot_host_local_only = True
        self.provider = ProviderFixture()
        self.app.localpilot = self.provider

    def tearDown(self):
        self.app.monitor_stop.set()
        self.provider.release.set()
        for thread in self.app.task_monitors.values():
            thread.join(3)
        self.fixture.tearDown()

    def prepare(self, request=None):
        self.app.prepare_escalation(request or escalation())
        return self.app.command({"command":"escalation_status"})["review_digest"]

    def approve(self, digest, **kwargs):
        return self.app.command({"command":"submit_escalation", "approved":True,
                                 "expected_digest":digest, **kwargs})

    def attach(self):
        self.app.store.set("localpilot_tasks", {"resp_fixture":{"endpoint":self.config.localpilot_endpoint}})

    def test_stale_preview_cannot_authorize_replacement_task(self):
        digest_a = self.prepare(escalation("Task A"))
        digest_b = self.prepare(escalation("Task B"))
        self.assertNotEqual(digest_a, digest_b)
        result = self.approve(digest_a)
        self.assertEqual(result["status"], "approval_required")
        self.assertEqual(self.provider.calls, [])
        with patch.object(self.app, "monitor_task"):
            result = self.approve(digest_b)
        self.assertEqual(result["task_id"], "resp_fixture")
        self.assertEqual(self.provider.calls[0][1]["user_request"], "Task B")

    def test_missing_review_digest_and_nonboolean_approval_do_not_send(self):
        digest = self.prepare()
        self.assertEqual(self.approve(None)["status"], "approval_required")
        for grant in (1, "true", {"approved":True}):
            result = self.app.command({"command":"submit_escalation", "approved":grant,"expected_digest":digest})
            self.assertEqual(result["status"], "approval_required")
        self.assertFalse(self.provider.calls)

    def unknown(self, session_id="sess_original"):
        self.provider.result = {"status":"submission_unknown", "phase":"unknown", "task_execution":"unknown"}
        digest = self.prepare()
        result = self.approve(digest, session_id=session_id)
        self.assertEqual(result["status"], "submission_unknown")
        return digest, deepcopy(self.app.store.get("pending_localpilot_submission"))

    def test_unknown_intent_prevents_replacement_and_requires_explicit_retry(self):
        digest, intent = self.unknown()
        self.assertEqual(self.app.prepare_escalation(escalation("Replacement"))["status"], "recovery_required")
        self.assertEqual(self.app.store.get("pending_escalation")["user_request"], "Task A")
        self.assertEqual(self.approve(digest,session_id="sess_original")["status"], "recovery_required")
        self.assertEqual(len(self.provider.calls), 1)
        self.provider.result = view()
        with patch.object(self.app, "monitor_task"):
            result = self.approve(digest,retry=True,session_id="sess_original")
        self.assertEqual(result["task_id"], "resp_fixture")
        self.assertEqual(self.provider.calls[-1][2]["submission_id"], intent["submission_id"])
        self.assertEqual(self.provider.calls[-1][1], self.provider.calls[0][1])

    def test_unknown_retry_rejects_changed_transport_session_or_scope(self):
        digest, intent = self.unknown()
        self.assertEqual(self.approve(digest,retry=True,session_id="sess_other")["status"], "recovery_required")
        self.config.localpilot_task_timeout_seconds += 1
        self.assertEqual(self.approve(digest,retry=True,session_id="sess_original")["status"], "recovery_required")
        self.config.localpilot_task_timeout_seconds -= 1
        self.config.native_app_exclusions = ("com.example.new",)
        self.assertEqual(self.approve(digest,retry=True,session_id="sess_original")["status"], "recovery_required")
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.app.store.get("pending_localpilot_submission")["submission_id"],intent["submission_id"])

    def test_unknown_retry_rejects_changed_effective_payload_after_file_filter(self):
        file=self.docs/"reference.txt"; file.write_text("approved reference")
        req=escalation(); req.relevant_files=[str(file)]
        self.provider.result={"status":"submission_unknown","phase":"unknown","task_execution":"unknown"}
        digest=self.prepare(req)
        self.approve(digest)
        file.unlink()
        result=self.approve(digest,retry=True)
        self.assertEqual(result["status"],"recovery_required")
        self.assertEqual(len(self.provider.calls),1)

    def test_changed_document_version_revokes_pending_approval(self):
        file = self.docs/"work.txt"; file.write_text("项目：测试\n预算：17万")
        self.app.process_file(str(file), "initial")
        records = self.app.retrieve("预算")
        self.assertTrue(any(r["type"]=="document" for r in records))
        digest = self.prepare(escalation(memories=records))
        file.write_text("项目：测试\n预算：18万")
        result = self.approve(digest)
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(self.provider.calls)
        self.assertIsNone(self.app.store.get("pending_escalation"))

    def test_native_permission_exclusion_revokes_pending_context(self):
        self.fixture.consent(content=True)
        self.app.process_native(self.fixture.native())
        record = self.app.observation_memory.records()[0]
        digest = self.prepare(escalation(recent=[record | {"observation_id":record["id"]}]))
        self.config.native_app_exclusions = ("com.example.fixture",)
        result = self.approve(digest)
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(self.provider.calls)

    def test_loopback_unknown_host_policy_does_not_grant_cloud_permission(self):
        self.config.localpilot_host_local_only = False
        self.app.localpilot = LocalPilotProvider(self.config)
        self.app.localpilot.opener = Mock()
        digest = self.prepare()
        result = self.approve(digest,cloud_approved=True)
        self.assertEqual(result["error"]["code"], "cloud_disabled")
        self.app.localpilot.opener.open.assert_not_called()
        self.assertIsNone(self.app.store.get("pending_localpilot_submission"))

    def test_legacy_remote_needs_cloud_grant_and_filters_private_context(self):
        self.config.agent_endpoint="https://example.com/v1"; self.config.agent_model="fixture"
        self.config.agent_allow_remote=True
        legacy = OpenAICompatibleProvider(self.config)
        private = {"id":"private-observation","sensitivity":"private","text":"private marker"}
        sensitive = {"id":"sensitive-observation","sensitivity":"sensitive","text":"never export"}
        req = escalation(recent=[private,sensitive],local_only=False)
        with patch("companion.escalation.provider.request_chat",return_value={"text":"MOCK_ONLY"}) as network:
            self.assertEqual(legacy.submit(req,approved=True)["status"], "approval_required")
            network.assert_not_called()
            result = legacy.submit(req,approved=True,cloud_approved=True)
            self.assertEqual(result["status"],"submitted")
            serialized = network.call_args.args[2][-1]["content"]
            self.assertNotIn("private marker",serialized)
            self.assertNotIn("never export",serialized)

    def test_legacy_loopback_unknown_host_never_calls_network(self):
        self.config.agent_endpoint="http://127.0.0.1:18765/v1"; self.config.agent_model="fixture"
        self.config.agent_host_local_only=False
        legacy = OpenAICompatibleProvider(self.config)
        with patch("companion.escalation.provider.request_chat") as network:
            result=legacy.submit(escalation(),approved=True,cloud_approved=True)
            self.assertEqual(result["status"],"unavailable")
            network.assert_not_called()

    def test_forget_document_purges_error_events_and_workflow(self):
        file=self.docs/"work.txt"; file.write_text("项目：测试\nError: private-work-error-marker")
        self.app.process_file(str(file),"initial")
        record=next(r for r in self.app.store.records() if r["type"]=="document")
        self.assertIn("private-work-error-marker",json.dumps(self.app.store.records()))
        self.app.workflow.events.append({"id":"prior"})
        self.app.command({"command":"forget","id":record["id"]})
        self.assertNotIn("private-work-error-marker",json.dumps(self.app.store.records()))
        self.assertFalse(self.app.events)
        self.assertFalse(self.app.workflow.events)
        self.assertFalse(self.app.observation_memory.records())
        self.assertTrue(file.exists())

    def test_forget_observation_resets_deleted_source_signals(self):
        self.fixture.consent(content=True); self.app.process_native(self.fixture.native())
        record=self.app.observation_memory.records()[0]
        self.app.workflow.events.append({"id":record["id"]})
        self.app.command({"command":"forget_observation","id":record["id"]})
        self.assertFalse(self.app.workflow.events)
        self.assertIsNone(self.app.observation_memory.get(record["id"]))

    def test_deep_tool_task_uses_summary_without_raw_contract_recursion(self):
        self.provider.result=view("requires_approval")
        self.provider.result["task"]["output"]=[{"tool_calls":[{"function":{"name":"apply_patch","arguments":"{}"}}]}]
        digest=self.prepare()
        with patch.object(self.app,"monitor_task"):
            returned=self.approve(digest)
        self.assertEqual(returned["status"],"requires_approval")
        self.assertIn("task",returned)
        record=self.app.store.get("localpilot_tasks")["resp_fixture"]
        self.assertNotIn("task",record["result"])
        self.assertEqual(record["result"]["required_action"]["id"],"approval_fixture")

    def test_long_chinese_result_stores_with_byte_budget_and_preserves_status(self):
        self.provider.result=view(text="中文结果"*1000)
        self.attach()
        result=self.app.command({"command":"task_status","task_id":"resp_fixture"})
        self.assertEqual(result["status"],"completed")
        self.assertEqual(result["memory_write"],"stored")
        record=self.app.observation_memory.records()[0]
        self.assertLessEqual(len(json.dumps(record["evidence"],ensure_ascii=False).encode()),8192)
        self.assertEqual(record["evidence_epistemic"],"reported_unverified_text")

    def test_long_english_result_fits_summary_character_limit(self):
        self.provider.result=view(text="Ordinary result. "*250)
        self.attach()
        result=self.app.command({"command":"task_status","task_id":"resp_fixture"})
        self.assertEqual(result["status"],"completed")
        self.assertEqual(result["memory_write"],"stored")

    def test_result_memory_write_failure_never_masks_task_status(self):
        self.attach()
        with patch.object(self.app.observation_memory,"add",side_effect=ValueError("fixture memory failure")):
            result=self.app.command({"command":"task_status","task_id":"resp_fixture"})
        self.assertEqual(result["status"],"completed")
        self.assertEqual(result["memory_write"],"failed")

    def test_repeated_same_task_result_does_not_increment_occurrences(self):
        self.attach()
        for _ in range(3):
            self.app.command({"command":"task_status","task_id":"resp_fixture"})
        record=self.app.observation_memory.records()[0]
        self.assertEqual(record["occurrences"],1)
        self.assertEqual(self.app.observation_memory.status()["records"],1)

    def test_monitor_reads_only_and_defers_sqlite_to_service_queue(self):
        self.attach()
        with patch.object(self.app.observation_memory,"add",wraps=self.app.observation_memory.add) as add:
            self.app.monitor_task("resp_fixture",cloud_approved=False)
            self.app.task_monitors["resp_fixture"].join(3)
            add.assert_not_called()
            item=self.app.queue.get_nowait()
            self.assertEqual(item[0],"task_update")
            self.app.receive_task_update(item[1],item[2])
            self.assertEqual(add.call_count,1)
        self.assertEqual([c[0] for c in self.provider.calls],["status", "stream"])
        self.assertFalse(self.provider.calls[0][2]["cloud_approved"])

    def test_monitor_pending_approval_does_not_run_or_create_result_memory(self):
        self.provider.result=view("requires_approval")
        self.attach(); self.app.monitor_task("resp_fixture")
        item=self.app.queue.get(timeout=1)
        self.app.monitor_stop.set()
        self.app.task_monitors["resp_fixture"].join(3)
        self.app.receive_task_update(item[1],item[2])
        self.assertTrue(all(c[0] in {"stream","status"} for c in self.provider.calls))
        self.assertEqual(self.app.observation_memory.status()["records"],0)
        self.assertEqual(self.app.store.get("localpilot_tasks")["resp_fixture"]["last_status"]["status"],"requires_approval")

    def test_clear_discards_queued_late_result_and_keeps_observation_paused(self):
        self.attach(); self.app.monitor_task("resp_fixture")
        self.app.task_monitors["resp_fixture"].join(3)
        item=self.app.queue.get_nowait()
        self.app.command({"command":"remember","type":"user_fact","text":"prior fact"})
        self.app.command({"command":"clear","confirmation":"DELETE_COMPANION_MEMORY"})
        self.app.receive_task_update(item[1],item[2])
        self.assertEqual(self.app.observation_memory.status()["records"],0)
        self.assertEqual(self.app.store.records(),[])
        self.assertTrue(self.app.privacy.paused())
        self.assertTrue(self.app.store.get("indexing_paused"))
        self.assertFalse(self.app.store.get("localpilot_tasks"))

    def test_clear_while_monitor_is_reading_prevents_late_delivery(self):
        self.provider.block_stream=True; self.attach(); self.app.monitor_task("resp_fixture")
        self.assertTrue(self.provider.entered.wait(1))
        self.app.command({"command":"clear","confirmation":"DELETE_COMPANION_MEMORY"})
        self.provider.release.set(); self.app.task_monitors["resp_fixture"].join(3)
        with self.assertRaises(Empty): self.app.queue.get_nowait()
        self.assertEqual(self.app.observation_memory.status()["records"],0)

    def test_monitor_limit_is_two_threads_and_stop_does_not_authorize_tasks(self):
        self.provider.block_stream=True
        for task_id in ("resp_one","resp_two","resp_three"):
            self.app.monitor_task(task_id)
        self.assertEqual(set(self.app.task_monitors),{"resp_one","resp_two"})
        self.app.monitor_stop.set(); self.provider.release.set()
        for thread in self.app.task_monitors.values(): thread.join(3)
        self.assertTrue(all(call[0] in {"status", "stream"} for call in self.provider.calls))

    def test_clear_transaction_rolls_back_old_and_new_tables_on_failure(self):
        self.app.command({"command":"remember","type":"user_fact","text":"keep if rollback"})
        event=ObservationEvent.create("session","fixture",{}, {"state":"awake"})
        self.app.observation_memory.add(event.to_dict())
        before=self.app.observation_memory.status()["records"]
        self.app.store.db.execute("CREATE TRIGGER fixture_clear_abort BEFORE DELETE ON observation_events BEGIN SELECT RAISE(ABORT,'fixture rollback'); END")
        self.app.store.db.commit()
        with self.assertRaises(Exception):
            self.app.command({"command":"clear","confirmation":"DELETE_COMPANION_MEMORY"})
        self.assertEqual(self.app.observation_memory.status()["records"],before)
        self.assertEqual(len(self.app.store.records()),1)
        self.assertFalse(self.app.store.get("indexing_paused",False))
        self.app.store.db.execute("DROP TRIGGER fixture_clear_abort"); self.app.store.db.commit()


if __name__ == "__main__":
    unittest.main()
