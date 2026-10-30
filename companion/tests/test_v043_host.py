"""Real Host/SQLite invariants; generated local fixtures, no desktop controls."""
from concurrent.futures import Future
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from companion.config import Config
from companion.runtime.service import Companion
from companion.memory.evidence import describe


class HostProductTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.docs = self.root / "docs"
        self.docs.mkdir()
        self.app = Companion(Config(low_power_policy="off", localpilot_endpoint="", data_dir=str(self.root / "state"), watch_dirs=(str(self.docs),), backend="disabled",
            quiet_start_hour=0, quiet_end_hour=0, native_app_allowlist=("com.apple.TextEdit",)))

    def tearDown(self):
        self.app.native.stop()
        self.app.observer.stop()
        self.app.model.unload()
        self.app.channel.stop()
        self.app.store.close()
        self.app.lock.close()
        self.tmp.cleanup()

    def test_question_is_speech_with_unknown_fact_identity(self):
        self.app.ask("我的项目负责人是谁？")
        row = self.app.store.records(1, ["conversation"])[0]
        self.assertEqual(row["evidence_type"], "UNKNOWN")
        self.assertEqual(row["metadata"]["role"], "user")
        self.assertEqual(self.app.recent_memories(), [])

    def test_question_cannot_be_explicit_confirmed_fact(self):
        with self.assertRaises(ValueError):
            self.app.command({"command":"remember", "type":"user_fact", "text":"我的预算是十八万吗？"})
        self.assertEqual(self.app.store.records(10, ["user_fact"]), [])

    def test_explicit_fact_identity_survives_store_reopen(self):
        saved = self.app.command({"command":"remember", "type":"user_fact", "text":"我负责合成蓝桥项目", "fact_key":"project:owner"})
        self.assertEqual(self.app.store.records(1)[0]["evidence_type"], "USER_CONFIRMED")
        observation = self.app.observation_memory.get(saved["observation_id"])
        self.assertEqual(observation["evidence_type"], "USER_CONFIRMED")
        self.assertEqual(observation["claim"]["claim_value"], "我负责合成蓝桥项目")
        from companion.memory.store import MemoryStore
        reopened = MemoryStore(self.app.private.file("memory.sqlite3"))
        try:
            self.assertEqual(reopened.records(1, ["user_fact"])[0]["evidence_type"], "USER_CONFIRMED")
        finally:
            reopened.close()

    def test_model_inference_cannot_claim_user_confirmation(self):
        mid = self.app.store.add("summary", "用户也许负责另一个项目", "companion_model", epistemic="inferred",
                                 metadata={"evidence_type":"USER_CONFIRMED"})
        row = next(r for r in self.app.store.records() if r["id"] == mid)
        self.assertEqual(describe(row), "MODEL_INFERRED")
        self.assertEqual(row["metadata"]["evidence_type"], "MODEL_INFERRED")

    def test_sensitive_request_never_wakes_model_or_escalates(self):
        self.assertEqual(self.app.ask("请读取浏览器Cookie和密码")["status"], "denied")
        self.assertEqual(self.app.model.inferences, 0)
        self.assertIsNone(self.app.store.get("pending_escalation"))

    def test_scope_mutation_revokes_authorization_and_pending_preview(self):
        self.app.command({"command":"authorize_observation", "confirmed":True})
        old = self.app.privacy.consent_id()
        self.app.store.set("pending_escalation", {"synthetic":"old preview"})
        result = self.app.command({"command":"set_app_exclusions", "apps":["com.apple.TextEdit"]})
        self.assertEqual(result["status"], "approval_required")
        self.assertNotEqual(old, self.app.privacy.consent_id())
        self.assertIsNone(self.app.store.get("native_observation_consent"))
        self.assertIsNone(self.app.store.get("pending_escalation"))
        self.assertIn("com.apple.TextEdit", self.app.native.options["exclusions"])
        stale = self.app.command({"command":"authorize_observation", "confirmed":True, "expected_consent_id":old})
        self.assertEqual(stale["reason"], "scope_changed")

    def test_exclusions_reject_partial_invalid_update(self):
        with self.assertRaises(ValueError):
            self.app.command({"command":"set_app_exclusions", "apps":["com.apple.TextEdit", "not a bundle"]})
        self.assertEqual(self.app.config.native_app_exclusions, ())

    def test_privacy_pause_blocks_callbacks_before_queue_drain(self):
        future = Future()
        self.app.enqueue_command({"command":"pause_observation", "paused":True}, future)
        self.assertTrue(self.app.observation_pause_requested.is_set())
        self.app.enqueue_native({"synthetic":"not admitted"})
        self.assertEqual(self.app.queue.qsize(), 1)
        self.app.command({"command":"pause_observation", "paused":True})
        self.assertTrue(self.app.privacy.paused())

    def test_no_feedback_is_not_zero_usefulness(self):
        self.assertIsNone(self.app.policy.summary()["useful_rate"])
        self.assertEqual(self.app.policy.summary()["feedback_evidence"], "UNKNOWN")

    def test_silent_policy_records_no_system_notification(self):
        nid = self.app.emit_notice("repeated_error", "synthetic:repeat", "合成错误出现三次。")
        self.assertIsNotNone(nid)
        self.assertEqual(self.app.command({"command":"notices"})["notices"][0]["delivery"], "silent_evaluation")
        self.app.policy.respond(nid, "useful")
        self.assertEqual(self.app.policy.summary()["feedback"]["useful"], 1)

    def test_off_setting_blocks_explicit_reminders_without_losing_them(self):
        due = time.time()
        self.app.command({"command":"set_reminder", "text":"查看合成事项", "due_at":due, "confirmed":True})
        self.app.command({"command":"proactive_settings", "level":"off"})
        self.app.due_reminders(due+1)
        self.assertFalse(self.app.store.get("explicit_reminders")[0]["delivered"])
        self.app.command({"command":"proactive_settings", "level":"low"})
        self.app.due_reminders(due+2)
        self.assertTrue(self.app.store.get("explicit_reminders")[0]["delivered"])
        self.app.due_reminders(due+3)
        self.assertEqual(self.app.store.db.execute("SELECT count(*) FROM notices").fetchone()[0], 1)

    def test_snapshot_has_live_filtered_memory_and_permission_state(self):
        f = self.docs/"public.txt"
        f.write_text("项目：合成蓝桥\n负责人：甲\n")
        self.app.process_file(str(f), "initial")
        snapshot = self.app.command({"command":"ui_snapshot"})
        from companion import __version__
        self.assertEqual(snapshot["runtime"]["version"], "Companion "+__version__)
        self.assertTrue(snapshot["memories"])
        self.app.config.exclude_dirs = (str(self.docs),)
        self.app.scope.excludes = [self.docs]
        self.assertEqual(self.app.command({"command":"ui_snapshot"})["memories"], [])

    def test_submitted_task_does_not_emit_completed_notice(self):
        self.app.store_task_result({"status":"submitted", "task_id":"synthetic", "quiescent":False})
        self.assertEqual(self.app.store.db.execute("SELECT count(*) FROM notices").fetchone()[0], 0)

    def test_expired_fact_not_returned_in_recent_ui_memory(self):
        self.app.store.add("user_fact", "已过期合成事实", "explicit_user_statement", metadata={"expires_at":time.time()-1})
        self.assertEqual(self.app.recent_memories(), [])

    def test_local_deep_request_degrades_without_submitting(self):
        result = self.app.ask("深入分析复杂上下文")
        self.assertEqual(result["routing"]["requested_level"], 2)
        self.assertTrue(result["routing"]["degraded"])
        self.assertIsNotNone(self.app.store.get("pending_escalation"))
        self.assertEqual(result["status"], "escalation")
        self.assertEqual(self.app.model.inferences, 0)

    def test_history_followup_preserves_revocable_original_source(self):
        f = self.docs/"synthetic.txt"
        f.write_text("合成原始资料。")
        self.app.process_file(str(f), "initial")
        parent = next(r for r in self.app.store.records(20) if r["type"] == "document")
        first = self.app.store.add("conversation", "来自合成资料的先前回答", "companion_model", epistemic="inferred",
            metadata={"role":"assistant", "memory_ids":[parent["id"]], "observation_ids":[]})
        class Fake:
            def complete(self, messages, **kwargs):
                return {"status":"ok", "text":"这是先前助手说过的话，不能直接证明其内容属实。"}
            def unload(self):
                pass
        self.app.model = Fake()
        with patch.object(self.app, "retrieve", return_value=[]):
            answer = self.app.ask("你刚才说过什么？")
        self.assertEqual(answer["status"], "ok")
        child = self.app.store.records(1, ["conversation"])[0]
        self.assertIn(first, child["metadata"]["memory_ids"])
        self.assertIn(parent["id"], child["metadata"]["memory_ids"])
        self.assertTrue(self.app.conversation_accessible(child))
        self.app.command({"command":"forget", "id":parent["id"]})
        self.assertFalse(self.app.conversation_accessible(child))

    def test_pending_pause_intent_is_restored_after_restart(self):
        self.app.enqueue_command({"command":"pause_observation", "paused":True}, Future())
        self.assertTrue(self.app.private.file("observation-pause-intent.json").exists())
        c = self.app.config
        self.app.native.stop(); self.app.observer.stop(); self.app.model.unload()
        self.app.channel.stop(); self.app.store.close(); self.app.lock.close()
        self.app = Companion(c)
        self.assertTrue(self.app.privacy.paused())
        self.assertFalse(self.app.private.file("observation-pause-intent.json").exists())

    def test_expired_answer_budget_never_loads_model(self):
        self.app.model.request_deadline = time.monotonic()-1
        result = self.app.model.complete([{"role":"user", "content":"测试预算边界"}])
        self.assertEqual(result["error_stage"], "deadline")
        self.assertEqual(self.app.model.inferences, 0)
        self.assertIsNone(self.app.model.child)

    def test_window_error_title_alone_is_not_help_evidence(self):
        from companion.triggers.workflow import WorkflowSignals
        tracker=WorkflowSignals()
        for i in range(4):
            result=tracker.accept({"kind":"ax.snapshot", "timestamp":time.time()+i,
                "object":{"bundle_id":"com.google.Chrome"}, "evidence":{"window_title":"Error: demonstration", "nodes":[]}}, str(i))
            self.assertIsNone(result)

    def test_withheld_source_claim_never_reappears_as_speech(self):
        class Fake:
            def complete(self, messages, **kwargs):
                return {"status":"ok", "text":"来源：invented-phantom.txt。不存在的背景断言。"}
            def unload(self):
                pass
        self.app.model=Fake()
        result=self.app.ask("用一句话回答一般问题。")
        self.assertEqual(result["status"], "unverified")
        history=self.app.store.records(1,["conversation"])[0]
        self.assertEqual(history["summary"],result["text"])
        self.assertNotIn("不存在的背景断言",history["summary"])
        self.assertEqual(history["metadata"]["delivery"], "displayed")

    def test_repeated_static_error_carries_unknown_cause(self):
        from companion.triggers.workflow import WorkflowSignals
        tracker=WorkflowSignals()
        for i in range(3):
            result=tracker.accept({"kind":"ax.snapshot", "timestamp":time.time()+i,
                "object":{"bundle_id":"com.google.Chrome"}, "evidence":{"nodes":[{"role":"AXStaticText", "text":"Error: synthetic retry needed"}]}}, str(i))
        self.assertTrue(result["same_error"])
        self.assertIn("未知", result["reason"])


class HTTPDeadlineTests(unittest.TestCase):
    def test_trickled_loopback_response_cannot_extend_total_model_deadline(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        from companion.escalation.provider import request_chat
        class Slow(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                data = b'{"choices": [{"message":{"content":"synthetic"},"finish_reason":"stop"}]}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    for byte in data:
                        self.wfile.write(bytes([byte])); self.wfile.flush(); time.sleep(.02)
                except OSError:
                    pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
        server.daemon_threads = True
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval":.02})
        worker.start()
        start = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                request_chat("http://127.0.0.1:"+str(server.server_port), "synthetic", [{"role":"user","content":"test"}], timeout_seconds=.12)
            self.assertLess(time.monotonic()-start, .5)
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
