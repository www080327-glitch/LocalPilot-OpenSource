from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from companion.config import Config
from companion.observers.source_formats import parse_source
from companion.runtime.service import Companion


class SourceImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.config = Config(data_dir=str(self.root / "state"), backend="disabled", localpilot_endpoint="",
                             low_power_policy="off", quiet_start_hour=0, quiet_end_hour=0)
        self.app = Companion(self.config)

    def close_app(self):
        self.app.native.stop()
        self.app.observer.stop()
        self.app.model.unload()
        self.app.channel.stop()
        self.app.store.close()
        self.app.lock.close()

    def tearDown(self):
        self.close_app()
        self.temp.cleanup()

    def codex(self, path=None, messages=None):
        path = path or self.root / "rollout.jsonl"
        messages = messages or [("user_message", "检查 parser 的错误处理"), ("agent_message", "我已拟定修复方案，尚未运行测试。")]
        path.write_text("\n".join(json.dumps({"timestamp":datetime.now().astimezone().isoformat(),
            "type":"event_msg", "payload":{"type":role, "message":text}}, ensure_ascii=False) for role, text in messages))
        return path

    def connect(self, path, kind="codex", **options):
        return self.app.command({"command":"source_connect", "kind":kind, "path":str(path), **options})

    def test_nothing_is_discovered_without_explicit_selection(self):
        self.codex()
        self.assertEqual(self.app.sources.poll(), [])
        self.assertEqual(self.app.command({"command":"source_list"})["sources"], [])
        self.assertEqual(self.app.observation_memory.records(), [])
        self.assertEqual(self.app.model.inferences, 0)

    def test_import_answer_keeps_provenance_and_never_promotes_assistant_completion(self):
        path = self.codex()
        original = path.read_bytes()
        result = self.connect(path, label="测试对话")
        self.assertEqual(result["sync"]["status"], "ok")
        self.assertEqual(result["sync"]["records"], 2)
        answer = self.app.ask("我今天在 Codex 做了什么？")
        self.assertEqual(len(answer["items"]), 2)
        self.assertIn("尚未运行测试", answer["text"])
        self.assertIn("不独立证明", answer["coverage"])
        self.assertTrue(all(row["source_path"] == str(path) and row["locator"].startswith("record ") for row in answer["items"]))
        assistant = next(row for row in self.app.observation_memory.records() if row["object"]["role"] == "assistant")
        self.assertEqual(assistant["evidence_epistemic"], "reported_unverified_text")
        self.assertFalse(assistant["evidence"]["completion_verified"])
        self.assertEqual(answer["model"]["status"], "not_called")
        self.assertEqual(self.app.localpilot.network_calls, 0)
        self.assertEqual(self.app.model.inferences, 0)
        self.assertEqual(self.app.store.records(10, ["user_fact"]), [])
        self.assertEqual(path.read_bytes(), original)

    def test_codex_excludes_reasoning_tools_environment_and_protocol_duplicates(self):
        path = self.codex(messages=[("user_message", "请检查 parser"), ("agent_message", "公开回复"),
                                   ("agent_reasoning", "PRIVATE_REASONING"), ("user_message", "<environment_context>PRIVATE_ENV</environment_context>")])
        with path.open("a") as stream:
            for row in (
                {"type":"response_item", "payload":{"type":"function_call", "arguments":"PRIVATE_TOOL"}},
                {"type":"response_item", "payload":{"role":"assistant", "content":[{"type":"output_text", "text":"公开回复"}]}},
                {"type":"event_msg", "channel":"analysis", "payload":{"type":"agent_message", "message":"PRIVATE_ANALYSIS"}},
            ):
                stream.write("\n" + json.dumps(row))
        result = self.connect(path)
        self.assertEqual(result["sync"]["records"], 2)
        self.assertEqual(result["sync"]["skipped_records"], 5)
        stored = "\n".join(self.app.store.db.iterdump())
        for value in ("PRIVATE_REASONING", "PRIVATE_TOOL", "PRIVATE_ENV", "PRIVATE_ANALYSIS"):
            self.assertNotIn(value, stored)

    def test_plain_json_visible_export_and_secret_redaction(self):
        path = self.root / "messages.json"
        path.write_text(json.dumps({"messages":[{"role":"user", "content":"token = sk-" + "a"*32},
            {"role":"assistant", "channel":"analysis", "content":"hidden reasoning"},
            {"type":"reasoning", "role":"assistant", "content":"HIDDEN_REASONING_RECORD"},
            {"role":"assistant", "content":[{"type":"output_text", "text":"visible"}, {"type":"reasoning", "text":"PRIVATE_PART"}]}]}))
        self.assertEqual(self.connect(path)["sync"]["records"], 2)
        text = json.dumps(self.app.observation_memory.records())
        self.assertNotIn("sk-" + "a"*32, text)
        self.assertNotIn("hidden reasoning", text)
        self.assertNotIn("HIDDEN_REASONING_RECORD", text)
        self.assertNotIn('PRIVATE_PART', text)

    def test_same_import_is_idempotent_and_revision_switches_current_snapshot(self):
        path = self.codex()
        source_id = self.connect(path)["source"]["id"]
        before = [row["id"] for row in self.app.observation_memory.records()]
        result = self.app.sources.sync(source_id)
        self.assertEqual((result["records"], result["cached_files"]), (2, 1))
        self.assertEqual([row["id"] for row in self.app.observation_memory.records()], before)
        self.codex(path, [("user_message", "全新记录，只在新版中保留")])
        self.assertEqual(self.app.observation_memory.records(), [])
        self.app.sources.sync(source_id)
        current = self.app.observation_memory.records()
        self.assertEqual(len(current), 1)
        self.assertIn("全新记录", current[0]["summary"])
        self.assertFalse(any(self.app.observation_memory.is_current(mid) for mid in before))

    def test_revised_historical_messages_are_current_by_import_version(self):
        path = self.root / "history.json"
        for year in (2025, 2024):
            path.write_text(json.dumps([{"role":"user", "content":f"Historical {year}", "timestamp":f"{year}-01-01T10:00:00+00:00"}]))
            result = self.connect(path)
            self.assertEqual(result["sync"]["status"], "ok")
        rows = self.app.observation_memory.records()
        self.assertEqual(len(rows), 1)
        self.assertIn("Historical 2024", rows[0]["summary"])
        self.assertGreater(rows[0]["expires_at"], time.time())

    def test_disabled_revoked_and_deleted_sources_are_not_used_by_answers_or_history(self):
        path = self.codex()
        source_id = self.connect(path)["source"]["id"]
        answer = self.app.ask("最近 Codex 有什么记录？")
        stored_answer = next(row for row in self.app.store.records(10, ["conversation"]) if row["metadata"].get("role") == "assistant")
        self.assertTrue(answer["items"])
        self.assertTrue(self.app.conversation_accessible(stored_answer))
        self.app.sources.set_enabled(source_id, False)
        self.assertFalse(self.app.conversation_accessible(stored_answer))
        self.assertEqual(self.app.ask("Codex 对话记录")["items"], [])
        self.app.sources.set_enabled(source_id, True)
        self.assertTrue(self.app.observation_memory.records())
        path.unlink()
        self.assertEqual(self.app.observation_memory.records(), [])
        revoked = self.app.sources.revoke(source_id)
        self.assertEqual(revoked["removed_records"], 2)
        self.assertEqual(self.app.observation_memory.status()["records"], 0)
        self.assertEqual(self.app.sources.list()["sources"], [])

    def test_invalid_changed_export_reports_unavailable_without_stale_context(self):
        path = self.codex()
        source_id = self.connect(path)["source"]["id"]
        path.write_text('{"broken"')
        result = self.app.sources.sync(source_id)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["errors"], [{"file":path.name, "reason":"JSONDecodeError"}])
        self.assertEqual(self.app.observation_memory.records(), [])

    def test_pause_prevents_reads_and_retrieval_and_resume_needs_no_new_grant(self):
        path = self.codex()
        source_id = self.connect(path)["source"]["id"]
        self.app.command({"command":"pause_observation", "paused":True})
        self.assertEqual(self.app.sources.sync(source_id)["status"], "paused")
        self.assertEqual(self.app.observation_memory.records(), [])
        self.app.command({"command":"pause_observation", "paused":False})
        self.assertEqual(self.app.sources.sync(source_id)["status"], "ok")
        self.assertEqual(len(self.app.observation_memory.records()), 2)

    def test_registration_and_memory_survive_restart_and_disabled_stays_disabled(self):
        path = self.codex()
        source_id = self.connect(path, follow=False)["source"]["id"]
        self.close_app()
        self.app = Companion(self.config)
        source = self.app.sources.get(source_id)
        self.assertFalse(source["follow"])
        self.assertEqual(len(self.app.ask("Codex 对话记录")["items"]), 2)
        self.app.sources.set_enabled(source_id, False)
        self.close_app()
        self.app = Companion(self.config)
        self.assertFalse(self.app.sources.get(source_id)["enabled"])
        self.assertEqual(self.app.observation_memory.records(), [])

    def test_directory_follow_is_bounded_and_does_not_read_sibling_or_symlink(self):
        directory = self.root / "selected"
        directory.mkdir()
        self.codex(directory / "one.jsonl")
        secret = self.codex(self.root / "outside.jsonl", [("user_message", "OUTSIDE_MARKER")])
        (directory / "link.jsonl").symlink_to(secret)
        result = self.connect(directory)
        self.assertEqual((result["sync"]["files"], result["sync"]["records"]), (1, 2))
        self.assertNotIn("OUTSIDE_MARKER", json.dumps(self.app.observation_memory.records()))
        self.codex(directory / "two.jsonl")
        self.assertEqual(self.app.sources.poll(now=100)[0]["files"], 2)
        self.assertEqual(self.app.sources.poll(now=110), [])
        self.config.max_scan_files = 1
        self.assertTrue(self.app.sources.sync(result["source"]["id"])["truncated"])
        with self.assertRaises(ValueError):
            self.connect(directory / "link.jsonl")

    def test_private_file_and_invalid_grants_are_rejected_at_connection(self):
        path = self.codex(self.root / "credentials.jsonl")
        with self.assertRaises(ValueError):
            self.connect(path)
        with self.assertRaises(ValueError):
            self.connect(self.root / "missing.jsonl")
        with self.assertRaises(ValueError):
            self.connect(self.codex(), follow="true")

    def test_meeting_subtitle_has_precise_cue_locator_and_no_inferred_meeting_date(self):
        path = self.root / "meeting.vtt"
        path.write_bytes(b"WEBVTT\r\n\r\n\r\n00:00.000 --> 00:02.000\r\nAlice: Review parser.\r\n\r\n\r\n00:02.000 --> 00:04.000\r\nBob: Not deployed yet.\r\n")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        result = self.connect(path, "meeting", label="显式字幕")
        self.assertEqual(result["sync"]["records"], 2)
        rows = self.app.observation_memory.records()
        self.assertEqual({row["evidence"]["locator"] for row in rows}, {"lines 5-5", "lines 9-9"})
        self.assertEqual({row["evidence"]["cue_start"] for row in rows}, {"00:00.000", "00:02.000"})
        answer = self.app.ask("今天会议讨论了什么？")
        self.assertIn("Not deployed yet", answer["text"])
        self.assertTrue(all(item["timestamp_basis"] == "file_modified_time_not_meeting_time" for item in answer["items"]))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_meeting_text_srt_and_invalid_json_use_real_parser(self):
        srt, _ = parse_source("meeting", b"1\n00:00:01,000 --> 00:00:03,000\nPublic transcript\n", ".srt", 100)
        text, _ = parse_source("meeting", "讨论接口变更。\n没有录音。".encode(), ".md", 100)
        self.assertEqual(srt[0]["locator"], "lines 3-3")
        self.assertEqual(text[0]["locator"], "lines 1-2")
        with self.assertRaises(ValueError):
            parse_source("codex", b'{"messages":"not-an-array"}', ".json", 100)

    def test_clear_memory_removes_grants_and_does_not_modify_sources(self):
        path = self.codex()
        original = path.read_bytes()
        self.connect(path)
        self.app.command({"command":"clear", "confirmation":"DELETE_COMPANION_MEMORY"})
        self.assertEqual(self.app.sources.list()["sources"], [])
        self.assertEqual(self.app.observation_memory.status()["records"], 0)
        self.assertEqual(path.read_bytes(), original)

    def test_retention_does_not_reimport_expired_content_from_unchanged_files(self):
        path = self.codex()
        source_id = self.connect(path)["source"]["id"]
        self.app.observation_memory.retain(now=time.time()+31*86400)
        result = self.app.sources.sync(source_id)
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["records"], 0)
        self.assertEqual(self.app.observation_memory.records(), [])

    def test_historical_import_keeps_raw_storage_window_and_reported_epistemic_after_compression(self):
        path = self.root / "historical.json"
        path.write_text(json.dumps([{"role":"assistant", "content":"Unverified historical assistant statement",
                                    "timestamp":"2024-01-01T00:00:00+00:00"}]))
        self.connect(path)
        self.app.observation_memory.retain(now=time.time()+86400)
        row = self.app.observation_memory.records()[0]
        self.assertEqual(row["raw_state"], "raw")
        self.app.observation_memory.retain(now=time.time()+8*86400)
        row = self.app.observation_memory.records()[0]
        self.assertEqual(row["raw_state"], "compressed")
        self.assertEqual(row["evidence_type"], "MODEL_INFERRED")
        self.assertEqual(row["evidence_epistemic"], "reported_unverified_text")
        self.assertEqual(row["evidence"]["locator"], "record 1")
        self.assertNotIn("text", row["evidence"])


class SourceCLIIntegrationTests(unittest.TestCase):
    def test_real_process_source_cli_and_evidence_question(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config = root / "config.json"
            config.write_text(json.dumps({"data_dir":str(root / "state"), "backend":"disabled", "localpilot_endpoint":"",
                "low_power_policy":"off", "dnd":True, "notifications":False}))
            transcript = root / "meeting.txt"
            transcript.write_text("Synthetic meeting: review the source importer tomorrow.")
            log = root / "process.log"
            with log.open("w") as output:
                process = subprocess.Popen([sys.executable, "-m", "companion", "--config", str(config), "run"], stdout=output, stderr=output)
            try:
                from companion.cli import client
                runtime_config = Config.load(config)
                deadline = time.monotonic()+10
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail(log.read_text())
                    try:
                        if client(runtime_config, {"command":"status"}, timeout=1)["status"] == "running":
                            break
                    except (OSError, ValueError, RuntimeError):
                        pass
                    time.sleep(.05)
                else:
                    self.fail("Companion process did not become ready: " + log.read_text())
                base = [sys.executable, "-m", "companion", "--config", str(config), "--json"]
                connected = subprocess.run(base + ["source-connect", "meeting", str(transcript), "--once"], capture_output=True, text=True, timeout=10)
                self.assertEqual(connected.returncode, 0, connected.stderr)
                source_id = json.loads(connected.stdout)["source"]["id"]
                answer = subprocess.run(base + ["ask", "今天会议说了什么？"], capture_output=True, text=True, timeout=10)
                self.assertEqual(answer.returncode, 0, answer.stderr)
                self.assertIn("review the source importer tomorrow", json.loads(answer.stdout)["text"])
                disabled = subprocess.run(base + ["source-enable", source_id, "off"], capture_output=True, text=True, timeout=10)
                self.assertEqual(disabled.returncode, 0, disabled.stderr)
                self.assertEqual(client(runtime_config, {"command":"ask", "text":"今天会议说了什么？"})["items"], [])
                self.assertEqual(client(runtime_config, {"command":"source_coverage"})["audio_capture"], "EXPLICIT_ON_DEVICE_ONLY")
                client(runtime_config, {"command":"shutdown"})
                self.assertEqual(process.wait(timeout=10), 0, log.read_text())
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
