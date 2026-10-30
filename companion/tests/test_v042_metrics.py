"""Queue failures remain visible without writing SQLite from AX callbacks."""
from pathlib import Path
from queue import Queue
import tempfile
import threading
import unittest

from companion.config import Config
from companion.runtime.service import Companion


class ObserverMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Companion(Config(low_power_policy="off", localpilot_endpoint="", data_dir=str(Path(self.tmp.name).resolve()/"state"),
                                    backend="disabled", dnd=True))
        self.addCleanup(self.tmp.cleanup)
        for action in (self.app.lock.close, self.app.store.close,
                       self.app.channel.stop, self.app.model.unload,
                       self.app.observer.stop, self.app.native.stop):
            self.addCleanup(action)

    @staticmethod
    def event():
        return {"source":"accessibility", "kind":"ax.snapshot",
                "object":{"bundle_id":"org.localpilot.test"},
                "evidence":{"read_status":"READ_FAILED", "complete":False},
                "confidence":1}

    def test_callback_thread_reports_invalid_and_full_queue_without_sqlite(self):
        self.app.queue = Queue(maxsize=1)
        errors = []
        def reader():
            try:
                self.app.enqueue_native({})
                self.app.enqueue_native(self.event())
                self.app.enqueue_native(self.event())
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=reader)
        thread.start(); thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        metrics = self.app.status()["native_metrics"]
        self.assertEqual((metrics["rejected"], metrics["enqueued"], metrics["queue_full"]), (1,1,1))
        self.assertEqual(metrics["queue_high_water"], 1)
        self.assertEqual(self.app.observation_memory.status()["records"], 0)

    def test_privacy_filter_and_failed_read_have_separate_counts(self):
        self.app.process_native(self.event())
        self.app.config.native_observation_enabled = True
        self.app.config.native_ax_enabled = True
        self.app.config.native_app_allowlist = ("org.localpilot.test",)
        self.app.privacy.authorize(True)
        self.app.process_native(self.event())
        metrics = self.app.status()["native_metrics"]
        self.assertEqual(metrics["privacy_filtered"], 1)
        self.assertEqual(metrics["processed"], 1)
        self.assertGreaterEqual(metrics["processing_ms_total"], metrics["processing_ms_max"])
        row = self.app.observation_memory.records()[0]
        self.assertEqual(row["evidence"]["read_status"], "READ_FAILED")
        self.assertFalse(row["evidence"]["complete"])

    def test_pause_does_not_spawn_retries_when_queue_is_full(self):
        self.app.queue = Queue(maxsize=1)
        self.app.queue.put_nowait(("native", {}, None))
        self.app.enqueue_native(self.event())
        self.assertFalse(self.app.rescan_required)
        self.assertIsNone(self.app.native_retry_at)
        self.app.stopping = True
        self.app.enqueue_native(self.event())
        self.assertEqual(self.app.status()["native_metrics"]["queue_full"], 1)


if __name__ == "__main__":
    unittest.main()
