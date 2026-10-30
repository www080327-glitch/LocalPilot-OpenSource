"""Deterministic consent/control tests; no paid requests or large model loads."""
from concurrent.futures import Future
from dataclasses import replace
import queue
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from companion.config import Config
from companion.runtime.inference_controls import InferenceControls
from companion.runtime.system_resources import ResourceMonitor, _signed_current


class Store:
    def __init__(self):self.data={"pending_escalation":{"user_request":"public question"}}
    def get(self,key,default=None):return self.data.get(key,default)
    def set(self,key,value):self.data[key]=value


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.state={"on_ac_power":True,"memory_available_bytes":40*1024**3,"system_cpu_percent":0,"battery_discharge_watts":None}
        config=Config(backend="disabled")
        provider=Mock(resource_control_version=1)
        provider.health.return_value={"status":"available"}
        provider._request.return_value={"models":[{"id":config.localpilot_analysis_route,"local_model_lifecycle":{
            "release_after_task":True,"control_surface_required":True,"minimum_available_bytes":28*1024**3}}, {"id":config.localpilot_cloud_analysis_route,"adapter":"deepseek","reasoning_only":True,"prompt_profile":"minimal_0"}]}
        provider.cancelled_submissions=set()
        self.app=SimpleNamespace(config=config,store=Store(),resources=ResourceMonitor(config,lambda:dict(self.state)),
            localpilot=provider,cloud_localpilot=provider,privacy=Mock(),review_digest=lambda raw:str(raw),
            command=Mock(return_value={"status":"running","task_id":"one"}),model=Mock(),monitor_task=Mock(),
            queue=queue.Queue())
        self.app.privacy.consent_id.return_value="scope"
        self.controls=InferenceControls(self.app);self.controls.ui_live=lambda:True

    def prepare(self,kind="local"):
        result=self.controls.prepare(kind);self.assertEqual(result["status"],"inference_prepared")
        ticket=result["control"]["id"];self.controls.ack(ticket);return ticket

    def test_two_options_default_off(self):
        self.assertEqual(self.controls.options(),{"allow_local_on_battery":False,"allow_automatic_cloud":False})

    def test_ac_auto_requires_presented_panel(self):
        ticket=self.controls.prepare()["control"]["id"]
        self.assertEqual(self.controls.start(ticket)["status"],"ui_required")
        self.controls.ack(ticket);self.controls.start(ticket)
        self.assertEqual(self.app.command.call_count,1)
        self.assertEqual(self.app.command.call_args.args[0]["resource_scopes"],[])

    def test_battery_off_waits_for_explicit_once_consent(self):
        self.state["on_ac_power"]=False;ticket=self.prepare()
        self.assertEqual(self.controls.start(ticket)["status"],"confirmation_required")
        self.app.command.assert_not_called()
        self.controls.start(ticket,True)
        self.assertEqual(self.app.command.call_args.args[0]["resource_scopes"],["battery"])
        self.assertFalse(self.controls.options()["allow_local_on_battery"])

    def test_battery_on_automatic_still_requires_panel_and_grants_no_memory(self):
        self.state["on_ac_power"]=False
        self.app.store.set("inference_options",{"allow_local_on_battery":True})
        self.controls.start(self.prepare())
        self.assertEqual(self.app.command.call_args.args[0]["resource_scopes"],["battery"])

    def test_low_memory_always_confirms_even_with_battery_automation(self):
        self.state["memory_available_bytes"]=10*1024**3
        self.app.store.set("inference_options",{"allow_local_on_battery":True})
        ticket=self.prepare();self.assertEqual(self.controls.start(ticket)["status"],"confirmation_required")
        self.controls.start(ticket,True)
        self.assertIn("memory",self.app.command.call_args.args[0]["resource_scopes"])

    def test_new_memory_reason_after_confirmation_needs_new_confirmation(self):
        self.state["on_ac_power"]=False;ticket=self.prepare()
        self.state["memory_available_bytes"]=10*1024**3
        self.assertEqual(self.controls.start(ticket,True)["status"],"confirmation_required")
        self.app.command.assert_not_called()

    def test_cloud_default_confirms_and_enabled_auto_still_shows_panel(self):
        ticket=self.prepare("cloud")
        self.assertEqual(self.controls.start(ticket)["status"],"confirmation_required")
        self.app.store.set("inference_options",{"allow_automatic_cloud":True})
        ticket=self.prepare("cloud");self.controls.start(ticket)
        self.assertTrue(self.app.command.call_args.args[0]["cloud_approved"])

    def test_no_owned_ui_never_starts(self):
        ticket=self.prepare();self.controls.ui_live=lambda:False
        self.assertEqual(self.controls.start(ticket,True)["status"],"ui_required")
        self.app.command.assert_not_called()

    def test_changed_context_cannot_use_old_confirmation(self):
        ticket=self.prepare();self.app.store.set("pending_escalation",{"user_request":"changed"})
        self.assertEqual(self.controls.start(ticket,True)["status"],"review_changed")

    def test_stop_before_start_has_zero_service_submission(self):
        ticket=self.prepare();future=Future();self.controls.stop_async(ticket,future)
        self.assertEqual(future.result()["status"],"stopping")
        item=self.app.queue.get(timeout=1);self.controls.stopped(item[1],item[2])
        self.assertEqual(self.controls.start(ticket,True)["status"],"stopped")
        self.app.command.assert_not_called();self.app.localpilot.emergency_stop.assert_not_called()

    def test_cloud_stop_uses_drain_and_returns_before_backend_stop(self):
        ticket=self.prepare("cloud");self.controls.start(ticket,True)
        gate=threading.Event()
        def wait(*args,**kwargs):gate.wait(2);return {"status":"stopping","tasks":[]}
        self.app.localpilot.emergency_stop.side_effect=wait
        future=Future();self.controls.stop_async(ticket,future)
        self.assertEqual(future.result(timeout=.2)["status"],"stopping")
        self.assertTrue(self.controls.stop_event.is_set());gate.set()
        self.app.queue.get(timeout=1)
        self.assertTrue(self.app.localpilot.emergency_stop.call_args.kwargs["drain"])

    def test_missing_release_contract_blocks_before_start(self):
        self.app.localpilot._request.return_value={"models":[]}
        self.assertEqual(self.controls.prepare()["status"],"unavailable")
        self.app.command.assert_not_called()


class MonitorTests(unittest.TestCase):
    def test_unknown_cache_does_not_erase_reported_token_counts(self):
        from companion.escalation.cache_usage import cache_usage
        result=cache_usage({"result":{"model_calls":[{"input_tokens":12,"output_tokens":3}]}})
        self.assertEqual(result["status"],"UNKNOWN")
        self.assertEqual(result["input_tokens"],12)
        self.assertIsNone(result["cache_hit_tokens"])

    def test_alerts_sustained_throttled_and_cpu_never_watts(self):
        config=replace(Config(),resource_alert_sustain_seconds=60)
        state={"memory_available_bytes":2*1024**3,"system_cpu_percent":95,"battery_discharge_watts":None}
        monitor=ResourceMonitor(config,lambda:state)
        self.assertEqual(monitor.poll(force=True,now=100),[])
        alerts=monitor.poll(force=True,now=161)
        self.assertEqual({a["kind"] for a in alerts},{"memory","cpu_load"})
        self.assertEqual(monitor.poll(force=True,now=162),[])
        self.assertNotIn("battery_discharge",monitor.since)

    def test_battery_hardware_high_discharge_alert(self):
        state={"memory_available_bytes":40*1024**3,"system_cpu_percent":2,"battery_discharge_watts":35}
        monitor=ResourceMonitor(Config(),lambda:state)
        monitor.poll(force=True,now=100)
        self.assertEqual(monitor.poll(force=True,now=161)[0]["kind"],"battery_discharge")
        self.assertEqual(_signed_current(2**64-2000),-2000)
