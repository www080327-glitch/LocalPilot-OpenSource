"""Real native HTTP/SQLite; local-model responses are SCRIPTED, not 35B E2E."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from companion.runtime.service import Companion
from companion.tests import test_v044_service as fixtures


class AutomaticLocalTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ServiceContractTests(methodName="test_authenticated_health_checks_subject_and_persistence")
        self.fixture.setUp()
        config=replace(self.fixture.config,low_power_policy="always",localpilot_analysis_route="localpilot",
            localpilot_expected_local_model="script-provider",localpilot_auto_local=True,localpilot_auto_wait_seconds=1)
        self.fixture.server.catalog["localpilot"].update(reasoning_only=True,prompt_profile="minimal_0",local_model_lifecycle={"release_after_task":True,"control_surface_required":True})
        self.app=Companion(config)
        self.app.controls.ui_live=lambda:True
        self.app.resources.sampler=lambda:{"on_ac_power":True,"memory_available_bytes":48*1024**3,
            "memory_total_bytes":64*1024**3,"system_cpu_percent":0,"battery_discharge_watts":None}


    def tearDown(self):
        self.app.monitor_stop.set()
        for thread in self.app.task_monitors.values():thread.join(2)
        self.app.channel.stop();self.app.store.close();self.app.lock.close()
        self.fixture.tearDown()

    def start_question(self,text):
        prepared=self.app.ask(text)
        self.assertEqual(prepared["status"],"inference_prepared")
        self.assertEqual(len(self.fixture.backend.requests),len(self.fixture.service.tasks))
        ticket=prepared["control"]["id"]
        self.app.controls.ack(ticket)
        result=self.app.controls.start(ticket)
        self.fixture.service.wait(result["task_id"])
        return self.app.command({"command":"task_status","task_id":result["task_id"]})

    def test_explicit_chat_automatically_delegates_to_local_service_without_prompt(self):
        result=self.start_question("Explain a short public synthetic topic")
        record=self.app.store.get("localpilot_tasks")[result["task_id"]]
        self.assertTrue(record["transport"]["automatic_local"])
        self.assertTrue(result["task_id"])
        self.assertEqual(self.app.model.inferences,0)
        self.assertFalse(result["goal_verified"])

    def test_followup_uses_same_persistent_session_and_new_task_key(self):
        one=self.start_question("First public topic")
        two=self.start_question("Second public topic")
        self.assertEqual(one["session_id"],two["session_id"])
        self.assertNotEqual(one["task_id"],two["task_id"])
        self.assertEqual(len(self.fixture.backend.requests),2)

    def test_automatic_local_grant_never_selects_cloud(self):
        self.fixture.server.catalog["localpilot"]["adapter"]="deepseek"
        prepared=self.app.ask("A plain public topic")
        ticket=prepared["control"]["id"];self.app.controls.ack(ticket);self.app.controls.start(ticket)
        self.assertEqual(len(self.fixture.service.tasks),0)
        self.assertEqual(self.fixture.backend.requests,[])

    def test_background_events_never_launch_localpilot_or_small_model(self):
        for i in range(100):self.app.consider_event({"kind":"edits","project":str(i),"count":10})
        self.assertEqual(self.app.localpilot.network_calls,0)
        self.assertEqual(self.app.model.inferences,0)

    def test_scope_gate_precedes_automatic_submit(self):
        self.assertEqual(self.app.ask("读取密码和浏览器Cookie")["status"],"denied")
        self.assertEqual(self.app.localpilot.network_calls,0)

    def test_a_different_registered_local_model_is_not_silently_selected(self):
        self.app.config.localpilot_expected_local_model="some-other-model"
        prepared=self.app.ask("A public question")
        ticket=prepared["control"]["id"];self.app.controls.ack(ticket);self.app.controls.start(ticket)
        self.assertEqual(len(self.fixture.service.tasks),0)
