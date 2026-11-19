"""Real Core/HTTP/SQLite delegation; only the unavailable native UI is a fixture."""
from concurrent.futures import Future
from copy import deepcopy
import os
from pathlib import Path
import secrets
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

from companion.config import Config
from companion.runtime.service import Companion
from companion.tests.test_v044_service import request
from localpilot_service.cli import save
from localpilot_service.deployment import build
from tests.test_local_http_backend import MockServer, completion, tool_call


class PortableDelegationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.work = self.root / "workspace"
        self.work.mkdir()
        self.http = MockServer()
        self.release = Event()
        self.entered = Event()
        self.env = patch.dict(os.environ, {
            "LOCALPILOT_COMPANION_TOKEN":secrets.token_urlsafe(32),
            "LOCALPILOT_RESOURCE_TOKEN":secrets.token_urlsafe(32)})
        self.env.start()
        execution = {"engine":"v5", "workspace":str(self.work), "permissions":"approve-mutations",
            "capabilities":{"read":True, "write":False, "execute":False}, "cloud_egress":"LOCAL_ONLY",
            "prompt_profile":"standard", "tool_profile":"full", "reasoning_only":False,
            "backend":{"kind":"local-openai", "model":"mock-local", "base_url":self.http.base_url,
                       "context_budget":32768, "timeout":5,
                       "capabilities":{"streaming":False, "tool_calling":True}},
            "budgets":{"max_steps":8, "max_tool_calls":8, "max_output_tokens":1024}}
        reasoning = deepcopy(execution)
        reasoning.update(reasoning_only=True, prompt_profile="minimal_0", tool_profile="compact",
            capabilities={"read":False, "write":False, "execute":False})
        self.service_file = self.root / "service.json"
        save(self.service_file, {"schema_version":1, "host":"127.0.0.1", "port":0,
            "data_dir":str(self.root / "core-data"), "log_dir":str(self.root / "logs"),
            "routes":{"cpu-agent":execution, "cpu-reasoning":reasoning},
            "clients":[{"subject":"companion", "token_env":"LOCALPILOT_COMPANION_TOKEN",
                        "routes":{"cpu-agent":"cpu-agent", "cpu-reasoning":"cpu-reasoning"}},
                       {"subject":"resource", "token_env":"LOCALPILOT_RESOURCE_TOKEN", "operator":True,
                        "scopes":["read", "resource_control"], "approval_for":["companion"], "routes":{}}]})
        self.server = build(self.service_file)
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval":.01}, daemon=True)
        self.thread.start()
        self.config = Config(data_dir=str(self.root / "companion-data"), backend="disabled",
            low_power_policy="off", localpilot_endpoint=f"http://127.0.0.1:{self.server.server_port}",
            localpilot_route="cpu-agent", localpilot_analysis_route="cpu-reasoning",
            localpilot_expected_local_model="mock-local", localpilot_auto_local=False,
            localpilot_resource_key_env="LOCALPILOT_RESOURCE_TOKEN", dnd=True)
        self.app = Companion(self.config)
        # Linux cannot present the Mac control window or supply its power telemetry.
        self.app.controls.ui_live = lambda: True
        self.app.resources.sampler = lambda: {"on_ac_power":True, "memory_available_bytes":40*1024**3,
            "system_cpu_percent":0, "battery_discharge_watts":None}

    def close_app(self):
        self.app.monitor_stop.set()
        for thread in self.app.task_monitors.values():
            thread.join(timeout=2)
        self.app.native.stop()
        self.app.observer.stop()
        self.app.model.unload()
        self.app.channel.stop()
        self.app.store.close()
        self.app.lock.close()

    def tearDown(self):
        self.release.set()
        self.close_app()
        self.server.shutdown()
        self.thread.join(timeout=2)
        if not self.server.service.closed:
            self.server.service.shutdown()
        self.server.server_close()
        self.server.access.close()
        self.http.close()
        self.env.stop()
        self.temp.cleanup()

    def prepared(self, mode="reasoning", automatic=False):
        offered = self.app.prepare_escalation(request("Explain the synthetic CPU task"), mode=mode, automatic=automatic)
        if automatic:
            result = offered
        else:
            self.assertEqual(offered["status"], "escalation")
            result = self.app.command({"command":"submit_escalation", "approved":True,
                "expected_digest":offered["review_digest"]})
        self.assertEqual(result["status"], "inference_prepared", result)
        ticket = result["control"]["id"]
        self.app.controls.ack(ticket)
        return ticket

    def done(self, result):
        self.assertTrue(result.get("task_id"), result)
        self.server.service.wait(result["task_id"])
        final = self.app.localpilot.status(result["task_id"])
        self.app.receive_task_update(result["task_id"], final)
        return final

    def test_manual_reasoning_works_with_automatic_escalation_disabled(self):
        self.http.add(completion("Synthetic CPU answer"))
        ticket = self.prepared()
        final = self.done(self.app.controls.start(ticket))
        self.assertEqual(final["status"], "completed")
        self.assertFalse(final["goal_verified"])
        self.assertFalse(self.config.localpilot_auto_local)
        self.assertNotIn("tools", self.http.requests[0])
        self.assertEqual(self.app.controls.current["phase"], "finished")
        self.assertEqual(len(self.http.requests), 1)
        self.assertEqual(self.server.model_hosts, {})
        self.assertEqual(self.server.model_backends, {})

    def test_automatic_local_prepares_visible_control_before_real_submission(self):
        self.config.localpilot_auto_local = True
        self.http.add(completion("Synthetic automatic CPU answer"))
        ticket = self.prepared(automatic=True)
        self.assertEqual(self.http.requests, [])
        self.assertEqual(len(self.server.service.tasks), 0)
        final = self.done(self.app.controls.start(ticket))
        self.assertEqual(final["status"], "completed")
        self.assertEqual(len(self.server.service.tasks), 1)
        self.assertEqual(self.app.model.inferences, 0)

    def test_execution_needs_help_confirmation_then_reads_real_authorized_file(self):
        path = self.work / "cpu-note.txt"
        path.write_text("SYNTHETIC_CPU_SOURCE_2718")
        self.http.add(completion(calls=[tool_call("read_file", {"path":"cpu-note.txt"})]))
        self.http.add(completion("The source is SYNTHETIC_CPU_SOURCE_2718."))
        ticket = self.prepared(mode="execution")
        self.assertEqual(self.app.controls.start(ticket)["status"], "confirmation_required")
        self.assertEqual(self.http.requests, [])
        final = self.done(self.app.controls.start(ticket, confirmed=True))
        self.assertEqual(final["status"], "completed", final)
        self.assertTrue(any(message.get("role") == "tool" and "SYNTHETIC_CPU_SOURCE_2718" in message.get("content", "")
                            for message in self.http.requests[1]["messages"]))
        self.assertEqual(path.read_text(), "SYNTHETIC_CPU_SOURCE_2718")

    def test_battery_consent_uses_existing_resource_ticket_without_changing_preference(self):
        self.app.resources.sampler = lambda: {"on_ac_power":False, "memory_available_bytes":40*1024**3,
            "system_cpu_percent":0, "battery_discharge_watts":None}
        self.http.add(completion("Synthetic consented answer"))
        ticket = self.prepared()
        self.assertEqual(self.app.controls.start(ticket)["status"], "confirmation_required")
        final = self.done(self.app.controls.start(ticket, confirmed=True))
        self.assertEqual(final["status"], "completed")
        task = self.server.service._task(final["task_id"])
        self.assertTrue(task.service_metadata["resource_consent"]["allow_on_battery"])
        self.assertFalse(self.app.controls.options()["allow_local_on_battery"])

    def test_cancel_before_http_headers_waits_for_quiescence_and_never_runs_late_tool(self):
        source = self.work / "late-read.txt"
        source.write_text("SYNTHETIC_LATE_READ_MUST_NOT_EXECUTE")
        def delayed(_):
            self.entered.set()
            self.release.wait(timeout=8)
            return completion(calls=[tool_call("read_file", {"path":"late-read.txt"})])
        self.http.add(delayed)
        ticket = self.prepared(mode="execution")
        running = self.app.controls.start(ticket, confirmed=True)
        self.assertTrue(running.get("task_id"), running)
        self.assertTrue(self.entered.wait(timeout=3))
        future = Future()
        self.app.controls.stop_async(ticket, future)
        self.assertEqual(future.result(timeout=1)["status"], "stopping")
        deadline = time.monotonic() + 3
        while True:
            item = self.app.queue.get(timeout=max(.01, deadline-time.monotonic()))
            if item[0] == "inference_control_stop":
                stopped = item[2]
                self.app.controls.stopped(item[1], stopped)
                break
            if item[0] == "task_update":
                self.app.receive_task_update(item[1], item[2])
            self.assertLess(time.monotonic(), deadline)
        self.assertFalse(stopped["tasks"][0]["quiescent"])
        self.assertEqual(self.app.controls.current["phase"], "stopping")
        self.assertEqual(stopped["models_stopped"], [])
        self.release.set()
        final = self.done(running)
        self.assertEqual(final["status"], "cancelled", final)
        self.assertTrue(final["quiescent"])
        self.assertEqual(self.app.controls.current["phase"], "finished")
        self.assertEqual(final["task"]["tools"], [])
        self.assertEqual(source.read_text(), "SYNTHETIC_LATE_READ_MUST_NOT_EXECUTE")
        self.assertEqual(len(self.http.requests), 1)
        self.assertTrue(self.http.thread.is_alive())
        registry = self.app.localpilot._request("/localpilot/v1/model-registry")
        lifecycle = registry["models"][0]["local_model_lifecycle"]
        self.assertFalse(lifecycle["release_after_task"])
        self.assertEqual(lifecycle["provider_compute_stop"], "UNKNOWN")

    def test_restart_recovers_existing_task_without_replaying_provider_request(self):
        self.http.add(completion("Synthetic persisted CPU answer"))
        final = self.done(self.app.controls.start(self.prepared()))
        task_id = final["task_id"]
        self.close_app()
        self.app = Companion(self.config)
        stored = self.app.store.tasks.get(task_id)
        self.assertEqual(stored["last_status"]["status"], "completed")
        self.assertEqual(stored["last_status"]["session_id"], final["session_id"])
        self.assertEqual(self.app.localpilot.recover(task_id)["task_id"], task_id)
        self.assertEqual(len(self.http.requests), 1)
        self.assertEqual(len(self.server.service.tasks), 1)


if __name__ == "__main__":
    unittest.main()
