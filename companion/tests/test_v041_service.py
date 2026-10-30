"""Reader recovery and historical window privacy; no desktop access."""
from pathlib import Path
from io import BytesIO
import json
import tempfile
import unittest
from unittest.mock import Mock

from companion.config import Config
from companion.runtime.service import Companion


class ReaderServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Companion(Config(low_power_policy="off", localpilot_endpoint="", data_dir=str(Path(self.tmp.name).resolve()/"state"), backend="disabled", dnd=True))
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.app.lock.close)
        self.addCleanup(self.app.store.close)
        self.addCleanup(self.app.channel.stop)
        self.addCleanup(self.app.model.unload)
        self.addCleanup(self.app.observer.stop)
        self.addCleanup(self.app.native.stop)

    def crash(self):
        self.app.config.native_observation_enabled = True
        self.app.privacy.authorize(True)
        self.app.native = Mock()
        self.app.native.status.return_value = {"state":"stopped", "reason":"native helper exited"}
        self.app.native.process.poll.return_value = -9

    def test_crash_restarts_only_after_backoff_and_reaps_owned_helper(self):
        self.crash()
        self.app.maintain_native(100)
        self.app.maintain_native(109)
        self.app.native.start.assert_not_called()
        self.app.maintain_native(110)
        self.app.native.stop.assert_called_once()
        self.app.native.start.assert_called_once()
        self.assertEqual(self.app.native_restart_attempts, 1)

    def test_protocol_failure_is_not_retried(self):
        self.crash()
        self.app.native.status.return_value = {"state":"error", "reason":"native protocol line exceeded budget"}
        self.app.maintain_native(100)
        self.app.maintain_native(200)
        self.app.native.start.assert_not_called()

    def test_manual_rebuild_and_deliberate_stop_are_not_retried(self):
        self.crash()
        for state, reason in (("MANUAL_REQUIRED", "build helper"), ("stopped", "native helper stopped"), ("paused", "observation paused"), ("error", "helper untrusted")):
            self.app.native.status.return_value = {"state":state,"reason":reason}
            self.app.maintain_native(100)
            self.app.maintain_native(200)
        self.app.native.start.assert_not_called()

    def test_pause_cancels_scheduled_retry(self):
        self.crash()
        self.app.maintain_native(100)
        self.app.store.set("observation_paused", True)
        self.app.maintain_native(200)
        self.assertIsNone(self.app.native_retry_at)
        self.app.native.start.assert_not_called()

    def test_retry_cap_prevents_crash_loop(self):
        self.crash()
        for now in (100,110,120,150,160,250,260,400):
            self.app.maintain_native(now)
        self.assertEqual(self.app.native.start.call_count, 3)

    def test_window_exclusion_rejects_legacy_capture_after_reauthorization(self):
        c=self.app.config
        c.native_observation_enabled=True; c.native_ax_enabled=True
        c.native_app_allowlist=("com.example.synthetic",)
        c.native_window_exclusions=("Synthetic excluded",)
        self.app.privacy.authorize(True)
        row={"source":"accessibility", "object":{"bundle_id":"com.example.synthetic"}}
        self.assertFalse(self.app.observation_accessible(row))
        row["object"]["acquisition_scope"]=self.app.privacy.consent_id()
        self.assertTrue(self.app.observation_accessible(row))
        c.native_window_exclusions+=("Another excluded",)
        self.app.privacy.authorize(True)
        self.assertFalse(self.app.observation_accessible(row))

    def test_standalone_service_keeps_memory_chat_dnd_without_localpilot(self):
        self.assertEqual(self.app.status()["localpilot"], "LOCALPILOT_UNAVAILABLE")
        self.assertTrue(self.app.status()["dnd"])
        self.app.command({"command":"remember","type":"user_fact","text":"Synthetic budget 17"})
        self.assertGreater(self.app.store.db.execute("SELECT count(*) FROM memories").fetchone()[0],0)
        self.assertIn("你好",self.app.command({"command":"ask","text":"你好"})["text"])

    def test_absent_helper_is_explicit_and_does_not_disable_memory(self):
        self.app.config.native_observation_enabled=True
        self.app.privacy.authorize(True)
        result=self.app.native.start()
        self.assertIn(result["state"], {"MANUAL_REQUIRED","unavailable"})
        self.assertEqual(self.app.status()["localpilot"], "LOCALPILOT_UNAVAILABLE")
        self.assertEqual(self.app.command({"command":"ask","text":"你好"})["status"], "ok")

    def test_failed_subtree_path_survives_callback_queue_and_sqlite(self):
        c=self.app.config
        c.native_observation_enabled=True; c.native_ax_enabled=True
        c.native_app_allowlist=("com.example.synthetic",)
        self.app.privacy.authorize(True)
        raw={"source":"macos.ax","kind":"ax.snapshot","timestamp":"2026-10-11T00:00:00Z", "object":{"bundle_id":"com.example.synthetic"},
            "evidence":{"read_status":"READ_FAILED","complete":False,"read_errors":[{
                "attribute":"AXChildren","path":[0,1,2],"scope":"AXWindows","structural":True,
                "status":"READ_FAILED","error":-25204,"reason":"AX_attribute_read_failed",
                "retry_allowed":True,"retry_class":"fresh_read_allowed_no_action_replay"}]}}
        from companion.observers.native import NativeObserver
        reader=NativeObserver(c,self.app.enqueue_native)
        process=Mock(stdout=BytesIO((json.dumps(raw)+"\n").encode()))
        process.poll.return_value=0
        reader._read(process)
        kind,event,_=self.app.queue.get_nowait()
        self.assertEqual(kind,"native")
        self.app.process_native(event)
        stored=self.app.observation_memory.records()[0]
        self.assertEqual(stored["evidence"]["read_errors"][0]["path"],[0,1,2])
        self.assertEqual(stored["evidence"]["read_status"],"READ_FAILED")
        self.assertFalse(stored["evidence"]["complete"])

    def test_queue_container_clipping_cannot_retain_success_complete(self):
        raw={"source":"accessibility","kind":"ax.snapshot","object":{},"evidence":{
            "nodes":[{"id":i,"role":"AXStaticText"} for i in range(80)],
            "read_status":"READ_SUCCESS_NONEMPTY","complete":True,"structural_complete":True}}
        self.app.enqueue_native(raw)
        _,event,_=self.app.queue.get_nowait()
        self.assertEqual(len(event["evidence"]["nodes"]),64)
        self.assertTrue(event["evidence"]["truncated"])
        self.assertFalse(event["evidence"]["complete"])
        self.assertEqual(event["evidence"]["read_status"],"READ_PARTIAL")

    def test_dense_valid_callback_is_trimmed_and_saved_with_partial_status(self):
        from companion.observers.native import NativeObserver
        c=self.app.config
        c.native_observation_enabled=True; c.native_ax_enabled=True
        c.native_app_allowlist=("com.example.synthetic",); c.native_content_app_allowlist=c.native_app_allowlist
        self.app.privacy.authorize(True)
        nodes=[{"id":0,"role":"AXWindow","children_read_status":"READ_SUCCESS_NONEMPTY"}]
        for i in range(1,64):
            row={"id":i,"parent":0,"role":"AXStaticText","children_read_status":"READ_SUCCESS_EMPTY"}
            if i<=8: row["text"]="合成文本"*125
            nodes.append(row)
        raw={"source":"macos.ax","kind":"ax.snapshot","timestamp":"2026-10-11T00:00:00Z",
            "object":{"bundle_id":"com.example.synthetic"},"evidence":{"nodes":nodes,
            "read_status":"READ_SUCCESS_NONEMPTY","complete":True,"structural_complete":True}}
        reader=NativeObserver(c,self.app.enqueue_native)
        process=Mock(stdout=BytesIO((json.dumps(raw,ensure_ascii=False)+"\n").encode()))
        process.poll.return_value=0; reader._read(process)
        _,event,_=self.app.queue.get_nowait()
        self.app.process_native(event)
        stored=self.app.observation_memory.records()[0]
        self.assertGreater(len(stored["evidence"]["nodes"]),0)
        self.assertLess(len(stored["evidence"]["nodes"]),64)
        self.assertEqual(stored["evidence"]["read_status"],"READ_PARTIAL")
        self.assertFalse(stored["evidence"]["complete"])


if __name__ == "__main__":
    unittest.main()
