"""V0.3 regression cases; process controls are not physical sleep or human trials."""
from concurrent.futures import Future
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from companion.cli import client, start, stop
from companion.config import Config, PrivateData
from companion.memory import MemoryStore
from companion.memory.retention import retain
from companion.model.backend import ModelManager
from companion.observers.documents import extract, extractive_summary
from companion.runtime.process import service_record
from companion.runtime.service import Companion


class StabilityTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1]/".data"
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name).resolve()
        self.docs = self.root/"documents"
        self.docs.mkdir()
        self.config = Config(low_power_policy="off", localpilot_endpoint="", data_dir=str(self.root/"state"), watch_dirs=(str(self.docs),), backend="disabled", dnd=True, quiet_start_hour=0, quiet_end_hour=0)
        self.obj = Companion(self.config)

    def tearDown(self):
        self.obj.model.unload()
        try:
            self.obj.store.close()
        except Exception:
            pass  # Some tests exercise full run cleanup.
        self.obj.channel.stop()
        self.obj.lock.close()
        self.temp.cleanup()

    def index(self, name="budget.txt", text="项目：测试\n预算：17万\n"):
        file = self.docs/name
        file.write_text(text)
        self.obj.process_file(str(file), "initial")
        return file

    def claim(self, file, location, value, field="budget"):
        row = next(r for r in self.obj.store.records(kinds=["document"]) if r["source_reference"] == str(file) and self.obj.store.is_current(r))
        meta = row["metadata"]
        return {"memory_id":row["id"], "version_id":meta["version_id"], "file_hash":meta["sha256"], "source_file":str(file), "location":location, "value":value, "field":field}

    def test_atomic_runtime_failed_publication_preserves_previous(self):
        private = self.obj.private
        private.write("runtime.json", '{"old":true}')
        with patch("companion.config.os.replace", side_effect=OSError("injected publication failure")):
            with self.assertRaises(OSError):
                private.write("runtime.json", '{"new":true}')
        self.assertEqual(json.loads(private.file("runtime.json").read_text()), {"old":True})
        self.assertEqual(list(private.root.glob(".write-*")), [])

    def test_atomic_runtime_success_permissions(self):
        file = self.obj.private.write("runtime.json", '{"new":true}')
        self.assertEqual(json.loads(file.read_text()), {"new":True})
        self.assertEqual(file.stat().st_mode & 0o777, 0o600)

    def test_constructor_failure_releases_lock(self):
        self.obj.lock.close()
        with patch("companion.runtime.service.LocalChannel", side_effect=OSError("port occupied")):
            with self.assertRaises(OSError):
                Companion(self.config)
        other = Companion(self.config)
        other.channel.stop(); other.store.close(); other.lock.close()

    def test_runtime_publication_failure_cleans_all_resources(self):
        with patch("companion.runtime.service.signal.signal"), patch.object(self.obj.private, "write", side_effect=OSError("publish failed")):
            with self.assertRaises(OSError):
                self.obj.run()
        self.assertFalse(self.obj.channel.thread.is_alive())
        self.assertTrue(self.obj.lock.closed)
        self.assertFalse(self.obj.private.file("runtime.json").exists())

    def test_observer_start_failure_cleans_runtime_and_lock(self):
        with patch("companion.runtime.service.signal.signal"), patch.object(self.obj.observer, "start", side_effect=OSError("observer failed")):
            with self.assertRaises(OSError):
                self.obj.run()
        self.assertFalse(self.obj.channel.thread.is_alive())
        self.assertTrue(self.obj.lock.closed)
        self.assertFalse(self.obj.private.file("runtime.json").exists())

    def test_signal_handler_does_not_write_database(self):
        with patch.object(self.obj.store, "set", side_effect=AssertionError("signal entered DB")), patch.object(self.obj.model, "unload", side_effect=AssertionError("blocking unload")):
            self.obj.stop_signal()
        self.assertTrue(self.obj.stopping)
        self.assertTrue(self.obj.model.stopping)

    def test_stopping_rejects_new_commands_and_events(self):
        self.obj.stopping = True
        future = Future()
        self.obj.enqueue_command({"command":"remember"}, future)
        self.obj.enqueue_event("budget.txt", "modified")
        self.assertEqual(future.result()["status"], "stopping")
        self.assertEqual(self.obj.queue.qsize(), 0)

    def test_stopping_model_does_not_reload_or_count(self):
        manager = ModelManager(self.config, self.obj.store)
        manager.request_stop()
        self.assertEqual(manager.complete([])["status"], "unavailable")
        self.assertEqual(manager.inferences, 0)

    def test_cancelled_queued_command_never_mutates(self):
        cancelled = Future(); cancelled.cancel()
        done = Future()
        self.obj.enqueue_command({"command":"remember", "type":"preference", "text":"must not save"}, cancelled)
        self.obj.enqueue_command({"command":"shutdown"}, done)
        with patch("companion.runtime.service.signal.signal"):
            self.obj.run()
        reopened = MemoryStore(self.obj.private.file("memory.sqlite3"))
        try:
            self.assertFalse(reopened.records(kinds=["preference"]))
        finally:
            reopened.close()
        self.assertEqual(done.result()["status"], "stopping")

    def test_scheduling_gap_resets_activity_and_syncs_missed_files(self):
        old = self.index()
        self.obj.events.append({"kind":"modified", "project":"p", "timestamp":time.time()})
        self.obj.store.set("project_activity", {"p":{"since":1,"last":2}})
        old.write_text("项目：测试\n预算：18万\n")
        new = self.docs/"missed.txt"; new.write_text("missed unique fact")
        self.obj.pending[str(old)] = (time.monotonic(), "modified")
        self.assertTrue(self.obj.recover_gap(self.obj.last_loop_wall+200, self.obj.last_loop_mono+1))
        self.assertFalse(self.obj.pending); self.assertFalse(self.obj.events)
        self.assertEqual(self.obj.store.get("project_activity"), {})
        self.obj.model = Mock()
        self.obj.scan()
        self.assertTrue(any(r["source_reference"] == str(new) for r in self.obj.store.records(kinds=["document"])))
        self.assertIn("18万", self.obj.ask("测试预算")["text"])
        self.obj.model.complete.assert_not_called()

    def test_normal_loop_does_not_rescan(self):
        self.assertFalse(self.obj.recover_gap(self.obj.last_loop_wall+30, self.obj.last_loop_mono+30))
        self.assertFalse(self.obj.rescan_required)

    def test_first_command_after_gap_sees_missed_new_source(self):
        answer, done = Future(), Future()
        self.obj.enqueue_command({"command":"retrieve", "text":"newunique"}, answer)
        self.obj.enqueue_command({"command":"shutdown"}, done)
        recover = self.obj.recover_gap
        fired = False
        def after_startup():
            nonlocal fired
            if fired:
                return False
            fired = True
            (self.docs/"missed.txt").write_text("newunique source")
            return recover(self.obj.last_loop_wall+200, self.obj.last_loop_mono+1)
        with patch("companion.runtime.service.signal.signal"), patch.object(self.obj, "recover_gap", side_effect=after_startup):
            self.obj.run()
        self.assertTrue(any(Path(r["source_reference"]).name == "missed.txt" for r in answer.result()["memories"]))

    def test_clock_rollback_recovers_without_duplicate_notice(self):
        self.obj.policy.record("greeting", "existing", "hi")
        self.assertTrue(self.obj.recover_gap(self.obj.last_loop_wall-300, self.obj.last_loop_mono+1))
        self.obj.scan()
        self.assertEqual(self.obj.store.db.execute("SELECT count(*) FROM notices").fetchone()[0], 1)

    def test_recovery_respects_clear_index_pause(self):
        self.index()
        self.obj.command({"command":"clear", "confirmation":"DELETE_COMPANION_MEMORY"})
        self.obj.recover_gap(self.obj.last_loop_wall+300, self.obj.last_loop_mono+300)
        self.obj.scan()
        self.assertFalse(self.obj.store.records())

    def test_compacted_fts_stays_compacted_after_multiple_reopens(self):
        for i in range(9):
            self.index(text="项目：测试\n预算："+str(i+30)+"万\n")
        retain(self.obj.store, recent=1, metadata_limit=4)
        compact = [r["id"] for r in self.obj.store.records(kinds=["document"]) if r["metadata"].get("retained")]
        for _ in range(3):
            reopened = MemoryStore(self.obj.private.file("memory.sqlite3"))
            try:
                self.assertTrue(compact)
                self.assertFalse(any(reopened.db.execute("SELECT 1 FROM memory_fts WHERE id=?", (mid,)).fetchone() for mid in compact))
            finally:
                reopened.close()

    def test_restart_repairs_v02_compacted_fts(self):
        for i in range(5):
            self.index(text="预算："+str(i)+"万\n")
        retain(self.obj.store, recent=1, metadata_limit=4)
        mid = next(r["id"] for r in self.obj.store.records(kinds=["document"]) if r["metadata"].get("retained"))
        self.obj.store.db.execute("INSERT INTO memory_fts VALUES(?,?)", (mid,"stale archive")); self.obj.store.db.commit()
        reopened = MemoryStore(self.obj.private.file("memory.sqlite3"))
        try:
            self.assertFalse(reopened.db.execute("SELECT 1 FROM memory_fts WHERE id=?", (mid,)).fetchone())
        finally:
            reopened.close()

    def test_conflict_revision_growth_is_linear(self):
        for i in range(40):
            self.index(text="项目：测试\n预算："+str(i)+"万\n")
        self.assertEqual(self.obj.store.db.execute("SELECT count(*) FROM conflicts").fetchone()[0], 39)
        self.index("other.txt", "项目：测试\n预算：999万\n")
        docs = self.obj.retrieve("测试预算")
        self.assertTrue(all(r["conflicts"] for r in docs if r["type"] == "document"))

    def test_retention_ages_pending_under_dnd_and_counts_once(self):
        now = time.time()
        for i in range(9):
            self.obj.policy.record("deadline", str(i), "hello", delivery="displayed_native_banner", now=now-7200-i)
        retain(self.obj.store, record_limit=3, now=now)
        self.assertEqual(self.obj.store.get("runtime_totals")["ignored"], 9)
        self.assertEqual(self.obj.store.db.execute("SELECT count(*) FROM notices").fetchone()[0], 3)
        retain(self.obj.store, record_limit=3, now=now)
        self.assertEqual(self.obj.store.get("runtime_totals")["ignored"], 9)

    def test_errors_are_bounded_persistent_and_keep_stages(self):
        for i in range(25):
            self.obj.record_error("scan", "injected "+str(i))
        reopened = MemoryStore(self.obj.private.file("memory.sqlite3"))
        try:
            self.assertEqual(len(reopened.get("recent_errors")), 20)
            self.assertEqual(reopened.get("runtime_totals")["errors"], 25)
            self.assertEqual(reopened.get("recent_errors")[-1]["stage"], "scan")
        finally:
            reopened.close()

    def test_truncated_number_and_quote_are_never_supported(self):
        self.config.max_document_chars = 5
        file = self.index(text="预算：170000元\n")
        self.assertFalse(self.obj.store.db.execute("SELECT 1 FROM claims").fetchone())
        for field, value in (("budget","17"), ("quote","预算：17")):
            result = self.obj.verifier.verify(self.claim(file,"line 1",value,field))
            self.assertEqual(result["status"], "UNVERIFIED")
            self.assertEqual(result["reason"], "incomplete_extracted_location")

    def test_complete_line_before_cut_still_verifies(self):
        self.config.max_document_chars = 8
        file = self.index(text="预算：17万\n后面被截断\n")
        self.assertEqual(self.obj.verifier.verify(self.claim(file,"line 1","17万"))["status"], "SUPPORTED")

    def test_missing_location_in_one_source_cannot_silently_pass(self):
        file = self.index()
        source = {"memory_id":self.claim(file,"line 2","17万")["memory_id"], "source_location":[]}
        self.assertEqual(self.obj.verifier.verify_sources([source])[0]["status"], "UNVERIFIED")

    def test_chinese_exact_line_correct_and_wrong(self):
        self.index()
        memories = self.obj.retrieve("测试预算")
        correct = self.obj.verifier.answer("预算为17万，来自budget.txt第2行。", memories)
        self.assertEqual(correct[0]["status"], "SUPPORTED")
        self.assertEqual(correct[-1]["status"], "UNVERIFIED")
        self.assertEqual(self.obj.verifier.answer("预算为17万，来自budget.txt第1行。", memories)[0]["status"], "CONTRADICTED")

    def test_markdown_line_is_exact_and_no_section_is_guessed(self):
        self.index("budget.md", "# 测试\n预算：17万\n")
        memories = self.obj.retrieve("测试预算")
        self.assertEqual(self.obj.verifier.answer("预算为17万，来自budget.md第2行。", memories)[0]["status"], "SUPPORTED")

    def test_chinese_range_approximation_and_multiple_locations_unverified(self):
        self.index()
        for loc in ("第1-2行", "第2行附近", "第1行和第2行"):
            self.assertEqual(self.obj.verifier.answer("预算为17万，来自budget.txt"+loc+"。", self.obj.retrieve("预算"))[0]["status"], "UNVERIFIED")

    def test_multiple_scalar_assertions_do_not_ignore_wrong_second_value(self):
        self.index()
        results = self.obj.verifier.answer("budget.txt第2行预算17万，预算18万。", self.obj.retrieve("预算"))
        self.assertEqual(results[0]["status"], "SUPPORTED")
        self.assertEqual(results[1]["status"], "CONTRADICTED")

    def test_owner_deadline_supported_without_promoting_whole_sentence(self):
        self.index("owner.txt", "负责人：小陶\n截止日期：11月16日\n")
        for text in ("负责人是小陶，来自owner.txt第1行。", "截止日期是11月16日，来自owner.txt第2行。"):
            results = self.obj.verifier.answer(text, self.obj.retrieve("负责人截止日期"))
            self.assertEqual(results[0]["status"], "SUPPORTED")
            self.assertEqual(results[-1]["status"], "UNVERIFIED")

    def test_duplicate_filename_remains_unverified(self):
        self.index()
        memories = self.obj.retrieve("预算")
        other = dict(memories[0], id="other", source_reference="/other/budget.txt")
        self.assertEqual(self.obj.verifier.answer("budget.txt第2行预算17万。", memories+[other])[0]["status"], "UNVERIFIED")

    def test_fabricated_filename_with_real_name_suffix_is_unverified(self):
        self.index()
        self.assertEqual(self.obj.verifier.answer("fake-budget.txt第2行预算17万。", self.obj.retrieve("预算"))[0]["status"], "UNVERIFIED")


class ProcessTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1]/".data"; base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name).resolve()
        self.filename = self.root/"config.json"
        self.filename.write_text(json.dumps({"data_dir":str(self.root/"state"), "backend":"disabled", "dnd":True}))
        self.config = Config.load(self.filename)

    def tearDown(self):
        stop(self.config)
        self.temp.cleanup()

    def test_real_sigkill_stale_status_stop_restart_and_singleton(self):
        import psutil
        start(self.config,self.filename)
        private = PrivateData(self.config.data_dir)
        runtime, process = service_record(private)
        second = subprocess.run([sys.executable,"-m","companion","--config",str(self.filename),"run"], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(second.returncode,0)
        self.assertIn("already running",second.stderr)
        os.kill(process.pid,signal.SIGKILL)
        process.wait(timeout=10)
        with self.assertRaises(FileNotFoundError):
            client(self.config,{"command":"status"})
        self.assertEqual(stop(self.config)["status"], "stopped")
        self.assertFalse(private.file("runtime.json").exists())
        self.assertEqual(start(self.config,self.filename)["status"], "running")

    def test_live_identity_mismatch_is_preserved(self):
        import psutil
        private = PrivateData(self.config.data_dir)
        private.write("runtime.json", json.dumps({"pid":os.getpid(), "created":psutil.Process().create_time()}))
        try:
            with self.assertRaises(RuntimeError):
                stop(self.config)
            self.assertTrue(private.file("runtime.json").exists())
        finally:
            private.file("runtime.json").unlink()

    def test_corrupt_dead_runtime_recoverable_without_signalling(self):
        private = PrivateData(self.config.data_dir)
        private.write("runtime.json", "{")
        self.assertEqual(stop(self.config)["status"], "stopped")
        self.assertEqual(start(self.config,self.filename)["status"], "running")

    def test_parent_monitor_exits_when_real_parent_is_killed(self):
        import psutil
        script = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','from companion.model.worker import watch_parent; import os,time; watch_parent(os.getppid(),.05); time.sleep(60)']); print(p.pid,flush=True); time.sleep(60)"
        parent = subprocess.Popen([sys.executable,"-c",script], stdout=subprocess.PIPE, text=True)
        child = None
        try:
            child = psutil.Process(int(parent.stdout.readline()))
            # Let the child start its monitor before killing the parent.
            time.sleep(.3)
            parent.kill(); parent.wait(timeout=5)
            child.wait(timeout=5)
        finally:
            if parent.poll() is None:
                parent.kill(); parent.wait(timeout=5)
            parent.stdout.close()
            if child and child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                child.kill(); child.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
