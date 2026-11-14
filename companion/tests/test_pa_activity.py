from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import time
import unittest

from companion.config import Config
from companion.memory.activity import activity_digest
from companion.observers.events import ObservationEvent
from companion.runtime.service import Companion


class PersonalActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Companion(Config(data_dir=str(Path(self.temp.name).resolve()/"state"), backend="disabled",
            localpilot_endpoint="", low_power_policy="off", quiet_start_hour=0, quiet_end_hour=0,
            native_observation_enabled=True, native_ax_enabled=True, native_all_apps_enabled=True,
            native_all_apps_content_enabled=True, proactive_level="low"))
        self.app.privacy.authorize(confirmed=True)
        self.noon = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)

    def tearDown(self):
        self.app.native.stop(); self.app.observer.stop(); self.app.model.unload(); self.app.channel.stop()
        self.app.store.close(); self.app.lock.close(); self.temp.cleanup()

    def observe(self, text="Synthetic source: discussed parser changes.", at=None, read_status="READ_SUCCESS_NONEMPTY"):
        raw = {"source":"accessibility", "kind":"ax.snapshot", "timestamp":time.time() if at is None else at,
               "object":{"bundle_id":"com.openai.codex"},
               "evidence":{"window_title":"Synthetic project", "read_status":read_status,
                           "nodes":[{"id":0, "role":"AXStaticText", "text":text}]}}
        return self.app.observation_memory.add(self.app.privacy.filter_native(raw))

    def attach_task(self, task_id="fixture_task"):
        self.app.store.set("localpilot_tasks", {task_id:{"endpoint":self.app.config.localpilot_endpoint}})
        return task_id

    def test_low_frequency_morning_and_evening_greetings_are_persistent_and_model_free(self):
        morning = self.noon.replace(hour=9).timestamp()
        self.assertIsNotNone(self.app.scheduled_greeting(morning))
        self.assertIsNone(self.app.scheduled_greeting(morning + 60))
        self.assertIsNotNone(self.app.scheduled_greeting(self.noon.replace(hour=19).timestamp()))
        rows = list(self.app.store.db.execute("SELECT message FROM notices ORDER BY timestamp"))
        self.assertEqual(len(rows), 2)
        self.assertIn("早上好", rows[0][0]); self.assertIn("晚上好", rows[1][0])
        self.assertEqual(self.app.model.inferences, 0)
        self.assertEqual(self.app.localpilot.network_calls, 0)

    def test_native_wake_uses_existing_permission_and_daily_deduplication(self):
        at = self.noon.replace(hour=10).timestamp()
        for kind in ("system.did_wake", "session.became_active", "system.screens_wake"):
            self.app.process_native(ObservationEvent.create("session", kind, {"type":"system"},
                {"notification":kind, "coverage":"PARTIAL", "lock_state":"UNKNOWN"}, timestamp=at).to_dict())
        self.assertEqual(self.app.store.db.execute("SELECT count(*) FROM notices").fetchone()[0], 1)
        self.assertEqual(self.app.model.inferences, 0)

    def test_quiet_hours_and_disabled_proactivity_still_apply(self):
        self.app.store.set("dnd", True)
        self.assertIsNone(self.app.scheduled_greeting(self.noon.replace(hour=9).timestamp()))
        self.app.store.set("dnd", False)
        self.app.store.set("proactive_level", "off")
        self.assertIsNone(self.app.scheduled_greeting(self.noon.replace(hour=19).timestamp()))

    def test_day_digest_uses_occurrences_when_same_window_is_seen_on_two_days(self):
        yesterday = (self.noon - timedelta(days=1)).replace(hour=10).timestamp()
        today = self.noon.replace(hour=9).timestamp()
        old = self.observe(at=yesterday)
        merged = self.observe(at=today)
        self.assertEqual(old["id"], merged["id"])
        self.observe("Only present today.", at=today + 60)
        before = activity_digest(self.app.observation_memory, "yesterday", now=self.noon.timestamp())
        after = activity_digest(self.app.observation_memory, "today", now=self.noon.timestamp())
        self.assertEqual([item["timestamp"] for item in before["items"]], [yesterday])
        self.assertEqual(len(after["items"]), 2)
        self.assertNotIn("Only present today", before["text"])
        self.assertEqual(before["items"][0]["retained_occurrences"], 1)
        self.assertEqual(before["items"][0]["id"], old["id"])

    def test_digest_rechecks_revoked_observation_and_keeps_incomplete_read_status(self):
        self.observe(at=self.noon.replace(hour=9).timestamp(), read_status="READ_PARTIAL")
        result = activity_digest(self.app.observation_memory, now=self.noon.timestamp())
        self.assertEqual(result["items"][0]["read_status"], "READ_PARTIAL")
        self.assertIn("未读取的会议声音", result["coverage"])
        self.app.store.set("native_observation_consent", "revoked")
        self.assertEqual(activity_digest(self.app.observation_memory, now=self.noon.timestamp())["items"], [])

    def test_natural_day_question_and_command_use_saved_sources_without_model(self):
        source = self.observe()
        answer = self.app.ask("我今天做了什么？")
        direct = self.app.command({"command":"activity_digest"})
        self.assertEqual(answer["items"][0]["id"], source["id"])
        self.assertEqual(answer["items"], direct["items"])
        self.assertEqual(answer["model"]["status"], "not_called")
        self.assertEqual(self.app.model.inferences, 0)
        self.assertEqual(self.app.localpilot.network_calls, 0)
        self.assertEqual(self.app.store.records(10, ["user_fact"]), [])

    def test_pet_memory_off_does_not_expose_activity(self):
        self.observe()
        self.app.command({"command":"pet_memory", "enabled":False})
        answer = self.app.command({"command":"pet_ask", "text":"我今天做了什么？"})
        self.assertEqual(answer["status"], "unavailable")
        self.assertNotIn("Synthetic", json.dumps(answer))

    def test_digest_limits_and_empty_records_are_explicit(self):
        self.assertIn("不能据此判断你没有工作", self.app.command({"command":"activity_digest"})["text"])
        for n in range(3):
            self.observe(f"Synthetic source {n}")
        result = self.app.command({"command":"activity_digest", "limit":2})
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["items"]), 2)
        with self.assertRaises(ValueError):
            self.app.command({"command":"activity_digest", "day":"last year"})

    def test_task_completion_feedback_does_not_require_verified_goal_or_repeat(self):
        task_id = self.attach_task()
        result = {"task_id":task_id, "status":"completed", "quiescent":True, "agent_response":"Synthetic answer", "goal_verified":False}
        self.app.receive_task_update(task_id, result)
        self.app.receive_task_update(task_id, result)
        saved = self.app.store.get("localpilot_tasks")[task_id]
        self.assertIn("尚未经独立验收", saved["feedback"]["text"])
        self.assertFalse(saved["feedback"]["goal_verified"])
        self.assertIn("notice_id", saved["feedback"])
        self.assertEqual(self.app.store.db.execute("SELECT count(*) FROM notices").fetchone()[0], 1)
        self.assertEqual(self.app.observation_memory.status()["records"], 1)

    def test_failure_and_human_wait_feedback_are_saved_even_when_notifications_are_muted(self):
        task_id = self.attach_task()
        self.app.store.set("proactive_level", "off")
        for status, quiet, expected in (("requires_human", False, "需要你接手"), ("requires_approval", False, "等待"), ("failed", True, "失败")):
            self.app.receive_task_update(task_id, {"task_id":task_id, "status":status, "quiescent":quiet})
            saved = self.app.store.get("localpilot_tasks")[task_id]
            self.assertIn(expected, saved["feedback"]["text"])
        self.assertEqual(self.app.store.db.execute("SELECT count(*) FROM notices").fetchone()[0], 0)

    def test_unknown_receipt_never_becomes_success_feedback(self):
        task_id = self.attach_task()
        self.app.receive_task_update(task_id, {"task_id":task_id, "status":"completed", "quiescent":True,
                                             "unknown_mutation":True, "goal_verified":False})
        feedback = self.app.store.get("localpilot_tasks")[task_id]["feedback"]
        self.assertIn("尚不确定", feedback["text"])
        self.assertIn("不会自动重做", feedback["text"])

    def test_missing_battery_sensor_keeps_resource_sample_with_unknown_power(self):
        from unittest.mock import patch
        from companion.runtime.system_resources import snapshot
        with patch("psutil.sensors_battery", side_effect=FileNotFoundError("missing power_supply")):
            result = snapshot()
        self.assertIsNone(result["on_ac_power"])
        self.assertIsNone(result["battery_percent"])
        self.assertIsNone(result["battery_discharge_watts"])
        self.assertGreater(result["memory_total_bytes"], 0)


class ImmediateFeedbackTransportTests(unittest.TestCase):
    def test_ack_arrives_before_pending_answer_and_final_preserves_result(self):
        from companion.channels.server import LocalChannel
        from urllib.request import Request, urlopen
        pending = []
        channel = LocalChannel(0, "test-only", lambda command, future: pending.append(future))
        channel.start()
        try:
            request = Request(f"http://127.0.0.1:{channel.port}/pet-stream", data=json.dumps({"command":"pet_ask", "text":"你好"}).encode(),
                              headers={"Authorization":"Bearer test-only", "Content-Type":"application/json"})
            with urlopen(request, timeout=3) as response:
                first = json.loads(response.readline().decode()[6:])
                self.assertEqual(first["event"], "accepted")
                self.assertEqual(first["task_execution"], "not_started")
                self.assertFalse(pending[0].done())
                pending[0].set_result({"status":"ok", "text":"Ready"})
                tail = response.read().decode()
                self.assertIn('"event": "final"', tail)
                self.assertIn("Ready", tail)
        finally:
            channel.stop()

    def test_stream_failure_is_final_sse_frame_without_second_http_response(self):
        from companion.channels.server import LocalChannel
        from urllib.request import Request, urlopen
        def enqueue(command, future):
            future.set_exception(RuntimeError("Synthetic failure"))
        channel = LocalChannel(0, "test-only", enqueue)
        channel.start()
        try:
            request = Request(f"http://127.0.0.1:{channel.port}/pet-stream", data=json.dumps({"command":"pet_ask", "text":"你好"}).encode(),
                              headers={"Authorization":"Bearer test-only", "Content-Type":"application/json"})
            with urlopen(request, timeout=3) as response:
                data = response.read().decode()
            events = [json.loads(line[6:]) for line in data.splitlines() if line.startswith("data: ")]
            self.assertEqual([event["event"] for event in events], ["accepted", "final"])
            self.assertEqual(events[-1]["result"]["status"], "error")
            self.assertNotIn("HTTP/", data)
        finally:
            channel.stop()


if __name__ == "__main__":
    unittest.main()
