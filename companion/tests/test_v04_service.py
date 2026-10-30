from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from companion.config import Config
from companion.observers.events import ObservationEvent, redact_text, sanitize
from companion.runtime.service import Companion
from companion.triggers.workflow import WorkflowSignals
from companion.model import ModelManager
from companion.observers.documents import extract


class ShortReply:
    def __init__(self, text):
        self.text = text
        self.messages = None

    def complete(self, messages, max_tokens):
        self.messages = messages
        return {"status":"ok", "text":self.text}

    def unload(self):
        pass


class ServiceV04Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.docs = Path(self.tmp.name).resolve()/"docs"
        self.docs.mkdir()
        self.config = Config(low_power_policy="off", localpilot_endpoint="", data_dir=str(Path(self.tmp.name).resolve()/"state"), watch_dirs=(str(self.docs),), backend="disabled",
                             quiet_start_hour=0, quiet_end_hour=0, dnd=True)
        self.app = Companion(self.config)
        self.config.localpilot_auto_local=False
        self.app.controls._test_bypass=True

    def tearDown(self):
        self.app.native.stop()
        self.app.observer.stop()
        self.app.model.unload()
        self.app.channel.stop()
        self.app.store.close()
        self.app.lock.close()
        self.tmp.cleanup()

    def native(self, evidence=None, kind="app.activated", timestamp=None):
        return {"source":"nsworkspace", "kind":kind, "timestamp":time.time() if timestamp is None else timestamp,
                "object":{"bundle_id":"com.example.fixture", "pid":123, "title":"private page"},
                "evidence":evidence or {"notification":"activated", "window_title":"private"}, "confidence":1}

    def consent(self, content=False):
        self.config.native_observation_enabled = True
        self.config.native_app_allowlist = ("com.example.fixture",)
        self.config.native_content_app_allowlist = ("com.example.fixture",) if content else ()
        self.app.privacy.authorize(True)

    def test_default_no_native_capture(self):
        self.app.process_native(self.native())
        self.assertEqual(self.app.observation_memory.status()["records"], 0)

    def test_consent_exact_scope_and_metadata(self):
        self.consent()
        self.app.process_native(self.native())
        rows = self.app.observation_memory.records()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("private", json.dumps(rows[0]["evidence"]))
        self.assertNotIn("title", rows[0]["object"])
        self.config.native_app_allowlist += ("com.example.new",)
        self.assertFalse(self.app.privacy.native_allowed())

    def test_excluded_app_never_persisted(self):
        self.consent()
        self.config.native_app_exclusions = ("com.example.fixture",)
        self.app.privacy.authorize(True)
        self.app.process_native(self.native())
        self.assertEqual(self.app.observation_memory.status()["records"], 0)

    def test_pause_files_and_native_across_restart_state(self):
        self.consent()
        self.app.command({"command":"pause_observation", "paused":True})
        file = self.docs/"work.txt"
        file.write_text("普通资料")
        self.app.process_file(str(file), "modified")
        self.app.process_native(self.native())
        self.assertTrue(self.app.privacy.paused())
        self.assertEqual(self.app.store.records(), [])
        self.assertTrue(self.app.store.get("observation_paused"))

    def test_sensitive_document_not_indexed_and_existing_purged(self):
        file = self.docs/"work.txt"
        file.write_text("项目：正常\n预算：17万")
        self.app.process_file(str(file), "initial")
        self.assertTrue(self.app.store.fingerprint(str(file)))
        file.write_text("密码：never-store-this\napi_key=never-store-this")
        self.app.process_file(str(file), "modified")
        self.assertFalse(self.app.store.fingerprint(str(file)))
        self.assertFalse(self.app.observation_memory.records())
        self.assertNotIn("never-store-this", json.dumps(self.app.store.records()))
        self.assertFalse(any(e.get("path") == str(file) for e in self.app.events))
        self.assertFalse(self.app.store.db.execute("SELECT 1 FROM memories WHERE source_reference=?", (str(file),)).fetchone())

    def test_secret_named_document_not_read(self):
        file = self.docs/"credentials.txt"
        file.write_text("secret")
        self.assertFalse(self.app.scope.allowed(file))
        self.app.process_file(str(file), "initial")
        self.assertFalse(self.app.store.records())

    def test_explicit_api_key_and_chinese_secret_file_names_not_read(self):
        for name in ("api_key.txt", "密钥.md", "个人密码.txt"):
            file = self.docs/name
            file.write_text("opaque-fixture-value")
            self.assertFalse(self.app.scope.allowed(file))
            self.app.process_file(str(file), "initial")
        self.assertFalse(self.app.store.records())

    def test_legacy_same_hash_secret_is_not_reused_and_all_events_purged(self):
        file = self.docs/"legacy.txt"
        file.write_text("password=synthetic-legacy-secret\n项目：旧数据", encoding="utf-8")
        raw = file.read_bytes()
        self.app.store.replace_document(str(file), hashlib.sha256(raw).hexdigest(), file.stat().st_mtime_ns,
                                        extract(raw, ".txt"), "项目：旧数据")
        self.app.store.add("computer_event", "modified legacy.txt", "file_observer", str(file),
                           metadata={"error_signature":"password=synthetic-legacy-secret"})
        self.assertFalse(self.app.retrieve("旧数据"))
        self.app.process_file(str(file), "initial")
        self.assertFalse(self.app.store.db.execute("SELECT 1 FROM memories WHERE source_reference=?", (str(file),)).fetchone())
        self.assertFalse(self.app.store.fingerprint(str(file)))

    def test_source_version_and_stale_context(self):
        file = self.docs/"work.txt"
        file.write_text("项目：测试\n预算：17万")
        self.app.process_file(str(file), "initial")
        first = self.app.observation_memory.records()[0]
        file.write_text("项目：测试\n预算：18万")
        self.app.process_file(str(file), "modified")
        self.assertFalse(self.app.observation_memory.is_current(first))
        self.assertEqual(len(self.app.observation_memory.records(current_only=True)), 1)

    def test_file_bytes_unchanged(self):
        file = self.docs/"work.txt"
        file.write_text("项目：测试\n预算：17万")
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        self.app.process_file(str(file), "initial")
        self.app.retention()
        self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(), digest)

    def test_clear_removes_new_memory_and_pauses(self):
        self.consent()
        self.app.process_native(self.native())
        self.app.command({"command":"clear", "confirmation":"DELETE_COMPANION_MEMORY"})
        self.assertEqual(self.app.observation_memory.status()["records"], 0)
        self.assertTrue(self.app.privacy.paused())

    def test_scope_exclusion_hides_old_observations(self):
        self.consent()
        self.app.process_native(self.native())
        self.config.native_app_exclusions = ("com.example.fixture",)
        self.assertEqual(self.app.command({"command":"observations"})["observations"], [])

    def test_unknown_task_id_denied(self):
        with self.assertRaises(ValueError):
            self.app.command({"command":"task_status", "task_id":"task_unknown"})

    def test_model_cannot_inject_observation_command(self):
        with self.assertRaises(ValueError):
            self.app.command({"command":"record_observation", "event":self.native()})

    def test_foreign_file_command_denied(self):
        with self.assertRaises(ValueError):
            self.app.command({"command":"write_file", "path":str(self.docs/"work.txt")})

    def test_native_metadata_schema_bound(self):
        self.consent()
        raw = self.native({"nodes":[{"id":n, "role":"AXGroup", "text":"unapproved"} for n in range(80)]}, kind="ax.snapshot")
        raw["source"] = "accessibility"
        self.config.native_ax_enabled = True
        self.app.privacy.authorize(True)
        result = self.app.privacy.filter_native(raw)
        self.assertLessEqual(len(result["evidence"]["nodes"]), 64)
        self.assertNotIn("unapproved", json.dumps(result))

    def test_secure_subtree_rejected_again_at_service_boundary(self):
        self.consent(content=True)
        self.config.native_ax_enabled = True
        self.app.privacy.authorize(True)
        raw = self.native({"nodes":[{"id":0, "role":"AXTextField", "subrole":"AXSecureTextField", "text":"must-never-store"},
                                     {"id":1, "parent":0, "role":"AXStaticText", "text":"also-private"},
                                     {"id":2, "role":"AXStaticText", "text":"ordinary fixture"}]}, kind="ax.snapshot")
        raw["source"] = "accessibility"
        event = self.app.privacy.filter_native(raw)
        self.assertNotIn("must-never-store", json.dumps(event))
        self.assertNotIn("also-private", json.dumps(event))
        self.assertIn("ordinary fixture", json.dumps(event))

    def test_old_ax_structure_unavailable_when_ax_disabled(self):
        self.consent()
        self.config.native_ax_enabled = True
        self.app.privacy.authorize(True)
        raw = self.native({"node_count":1, "coverage":"PARTIAL"}, kind="ax.snapshot")
        raw["source"] = "accessibility"
        self.app.process_native(raw)
        self.config.native_ax_enabled = False
        self.app.privacy.authorize(True)
        self.assertFalse(self.app.command({"command":"observations"})["observations"])

    def test_explicit_fact_conflict_and_expiry(self):
        first = self.app.command({"command":"remember", "type":"user_fact", "text":"小明", "fact_key":"测试项目.负责人", "expires_days":1})
        second = self.app.command({"command":"remember", "type":"user_fact", "text":"小红", "fact_key":"测试项目.负责人"})
        self.assertTrue(self.app.observation_memory.conflicts(second["observation_id"]))
        self.assertFalse(self.app.observation_memory.is_current(first["observation_id"], now=time.time()+86401))
        with self.app.store.db:
            self.app.store.db.execute("UPDATE memories SET metadata=? WHERE id=?", (json.dumps({"expires_at":1}),first["id"]))
        self.assertFalse(any(r["id"] == first["id"] for r in self.app.retrieve("小明")))
        self.app.command({"command":"forget", "id":second["id"]})
        self.assertIsNone(self.app.observation_memory.get(second["observation_id"]))

    def test_model_invented_local_source_is_not_displayed(self):
        self.app.model = ModelManager(self.config, self.app.store, adapter=ShortReply("来源：README.md，第1行。只读权限允许查看。"))
        result = self.app.ask("请简单解释权限")
        self.assertEqual(result["status"], "unverified")
        self.assertNotIn("第1行", result["text"])
        self.assertEqual(result["source_verification"][-1]["reason"], "source_not_provided_in_context")

    def test_genuine_simple_reply_does_not_require_local_file_source(self):
        self.app.model = ModelManager(self.config, self.app.store, adapter=ShortReply("可以，今天也希望你顺利。"))
        result = self.app.ask("请说一句鼓励的话")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["text"], "可以，今天也希望你顺利。")

    def test_queue_truncation_remains_visible(self):
        raw = self.native({"nodes":[{"id":n, "role":"AXGroup"} for n in range(70)], "truncated":False})
        self.app.enqueue_native(raw)
        event = self.app.queue.get_nowait()[1]
        self.assertTrue(event["evidence"]["truncated"])
        self.assertEqual(len(event["evidence"]["nodes"]), 64)

    def test_model_invented_chinese_filename_is_not_displayed(self):
        self.app.model = ModelManager(self.config, self.app.store, adapter=ShortReply("来源：《项目汇报.pptx》第1页。"))
        result = self.app.ask("请简单解释资料")
        self.assertEqual(result["status"], "unverified")
        self.assertNotIn("第1页", result["text"])

    def test_explicit_missing_quoted_chinese_document_not_summarized(self):
        result = self.app.ask("请概括《项目汇报.pptx》")
        self.assertEqual(result["model"]["status"], "not_called")
        self.assertIn("找不到", result["text"])


class EventV04Tests(unittest.TestCase):
    def test_sensitive_filter_and_epistemic_boundary(self):
        event = ObservationEvent.create("file_observer", "updated", {"path":"/allowed/file.txt"},
                                       {"password":"omit", "summary":"密码：secret-value", "ordinary":"safe"})
        self.assertNotIn("secret-value", json.dumps(event.to_dict()))
        self.assertNotIn("password", event.evidence)
        self.assertEqual(event.epistemic, "observed")

    def test_event_identity_tracks_version_and_evidence(self):
        args = ("file_observer", "updated", {}, {"summary":"test"})
        a, b = ObservationEvent.create(*args, timestamp=1), ObservationEvent.create(*args, timestamp=2)
        self.assertEqual(a.dedupe_key, b.dedupe_key)
        self.assertNotEqual(a.dedupe_key, ObservationEvent.create(*args, version_id="v2").dedupe_key)

    def test_invalid_event_rejected(self):
        for value in (float("nan"), -1, True):
            with self.assertRaises(ValueError):
                ObservationEvent.create("source", "kind", {}, {}, timestamp=value)

    def test_workflow_no_focus_inference_and_wake_resets(self):
        tracker = WorkflowSignals()
        for n in range(10):
            self.assertIsNone(tracker.accept({"kind":"app.activated", "object":{"bundle_id":"com.example.app"},
                                             "evidence":{}, "timestamp":n}, str(n)))
        tracker.accept({"kind":"system.did_wake", "object":{}, "evidence":{}, "timestamp":10}, "wake")
        self.assertEqual(len(tracker.events), 0)

    def test_error_evidence_distinct_not_replays(self):
        tracker = WorkflowSignals()
        for n in range(3):
            result = tracker.accept({"kind":"ax.snapshot", "object":{"bundle_id":"com.example.app"},
                                     "evidence":{"text":"Error: compile blocked"}, "timestamp":n}, "same")
        self.assertIsNone(result)
        for n in range(3):
            result = tracker.accept({"kind":"ax.snapshot", "object":{"bundle_id":"com.example.app"},
                                     "evidence":{"text":"Error: compile blocked"}, "timestamp":n+3}, str(n))
        self.assertTrue(result["same_error"])

    def test_configuration_defaults_local_and_disabled(self):
        with tempfile.TemporaryDirectory() as base:
            file = Path(base)/"config.json"
            file.write_text(json.dumps({"data_dir":base+"/state", "backend":"disabled"}))
            config = Config.load(file)
            self.assertFalse(config.native_observation_enabled)
            self.assertFalse(config.localpilot_allow_remote)
            self.assertEqual(config.watch_dirs, ())
