"""Real SQLite/FTS and request construction; generation is a recorded fixture."""
import json
from pathlib import Path
import tempfile
import unittest

from companion.config import Config
from companion.runtime.service import Companion


class ChatHistoryArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name).resolve()
        self.config = Config(data_dir=str(root / "state"), backend="disabled", localpilot_endpoint="",
                             low_power_policy="off", dnd=True, notifications=False, history_record_limit=20000)
        self.requests = []
        self.open_app()

    def open_app(self):
        self.app = Companion(self.config)
        self.app.model.complete = self.reply

    def reply(self, messages, **kwargs):
        self.requests.append(messages)
        return {"status":"ok", "text":"受控回忆回答。"}

    def close_app(self):
        self.app.native.stop()
        self.app.observer.stop()
        self.app.model.unload()
        self.app.channel.stop()
        self.app.store.close()
        self.app.lock.close()

    def tearDown(self):
        self.close_app()
        self.temporary.cleanup()

    def noise(self, count):
        with self.app.store.db:
            self.app.store.db.executemany("INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?)", [
                (f"unrelated-{i}", "conversation", 100 + i, "user_chat", "", f"Unrelated weather {i}",
                 1.0, "factual", json.dumps({"role":"user"})) for i in range(count)])

    def test_archive_match_survives_reopen_and_recent_history(self):
        text = "蓝杉交接编号为 ARCHIVE752。尚未完成：修复解析器空行、核对两条金额、补齐回滚记录。"
        mid = self.app.store.add("conversation", text, "user_chat", timestamp=1, metadata={"role":"user"})
        self.noise(250)
        self.close_app()
        self.open_app()
        queries = []
        self.app.store.db.set_trace_callback(queries.append)
        result = self.app.ask("之前我说过的蓝杉交接编号是什么？")
        prompt = self.requests[-1][-1]["content"]
        self.assertIn(text, prompt)
        self.assertIn(mid, prompt)
        self.assertIn("不证明工作事实", prompt)
        self.assertFalse(any(row["type"] == "conversation" for row in result["memories"]))
        stored = self.app.store.db.execute("SELECT summary FROM memories WHERE id=?", (mid,)).fetchone()[0]
        self.assertEqual(stored, text)
        self.assertEqual(self.app.store.db.execute("SELECT count(*) FROM memory_fts WHERE id=?", (mid,)).fetchone()[0], 1)
        recent_queries = [sql for sql in queries if "SELECT * FROM memories WHERE type IN" in sql]
        self.assertEqual(len(recent_queries), 1, "Recall must not reload 100 rows once per candidate")

    def test_old_assistant_speech_is_found_without_becoming_fact_authority(self):
        question_id = self.app.store.add("conversation", "请记录这轮受控对话。", "user_chat",
                                         timestamp=1, metadata={"role":"user"})
        text = "青禾回滚仍缺原始日志，我只做完了准备，没有完成验证。"
        mid = self.app.store.add("conversation", text, "companion_model", timestamp=2, epistemic="inferred",
            metadata={"role":"assistant", "question_id":question_id, "delivery":"displayed",
                      "memory_ids":[], "observation_ids":[]})
        self.noise(250)
        self.close_app()
        self.open_app()
        self.app.ask("你之前说过的青禾回滚是什么情况？")
        request = self.app.store.get("pending_escalation")
        self.assertIsNotNone(request, "Mixed speakers use the existing role-sensitive reasoning route")
        recalled = next(row for row in request["relevant_memories"] if row["id"] == mid)
        self.assertEqual(recalled["summary"], text)
        self.assertEqual(recalled["metadata"]["role"], "assistant")
        self.assertEqual(recalled["epistemic"], "inferred")
        self.assertEqual(self.app.store.records(10, ["user_fact"]), [])

    def test_archive_excerpt_contains_the_match_after_the_first_500_characters(self):
        detail = "珊瑚事项：仍需核对金额与回滚日志。"
        original = "仅供背景参考。" * 140 + detail
        mid = self.app.store.add("conversation", original, "user_chat", timestamp=1, metadata={"role":"user"})
        self.noise(150)
        self.app.ask("之前我说过的珊瑚事项是什么？")
        prompt = self.requests[-1][-1]["content"]
        self.assertIn(detail, prompt)
        entries, _ = json.JSONDecoder().raw_decode(prompt[prompt.index("["):])
        excerpt = next(row for row in entries if row["id"] == mid)
        self.assertEqual(excerpt["text"], original[excerpt["excerpt_start"]:excerpt["excerpt_end"]])
        self.assertEqual(excerpt["original_chars"], len(original))
        self.assertLessEqual(len(excerpt["text"]), 500)
        self.assertEqual(self.app.store.record(mid)["summary"], original)

    def test_valid_old_dependency_is_looked_up_by_identity_after_reopen(self):
        parent = self.app.store.add("user_fact", "受控交接代号是榆木。", "explicit_user_statement", timestamp=1)
        answer = self.app.store.add("conversation", "受控回答使用了榆木代号。", "companion_model", timestamp=2,
            epistemic="inferred", metadata={"role":"assistant", "delivery":"displayed",
                                            "memory_ids":[parent], "observation_ids":[]})
        self.noise(10005)
        self.close_app()
        self.open_app()
        row = next(r for r in self.app.store.records(20000, ["conversation"]) if r["id"] == answer)
        queries = []
        self.app.store.db.set_trace_callback(queries.append)
        self.assertTrue(self.app.conversation_accessible(row))
        self.assertFalse(any("ORDER BY timestamp" in sql for sql in queries),
                         "Checking one dependency must not scan an age-limited archive")
        with self.app.store.db:
            self.app.store.db.execute("DELETE FROM memories WHERE id=?", (parent,))
        self.assertFalse(self.app.conversation_accessible(row))

    def test_old_recalled_answer_with_forgotten_dependency_stays_excluded(self):
        self.app.store.add("conversation", "玄鹤项目有一个不应再被展示的旧回答。", "companion_model", timestamp=1,
            epistemic="inferred", metadata={"role":"assistant", "delivery":"displayed",
                                            "memory_ids":["forgotten-source"], "observation_ids":[]})
        self.noise(150)
        self.app.ask("你之前说过的玄鹤项目是什么？")
        self.assertNotIn("不应再被展示", self.requests[-1][-1]["content"])
        self.assertIsNone(self.app.store.get("pending_escalation"))

    def test_full_text_matches_do_not_override_stored_speaker_identity(self):
        self.app.store.add("conversation", "紫竹误标内容不能作为用户原话。", "user_chat", timestamp=1,
                           metadata={"role":"assistant"})
        self.noise(150)
        self.app.ask("之前我说过的紫竹内容是什么？")
        self.assertNotIn("误标内容", self.requests[-1][-1]["content"])

    def test_terse_continuation_forwards_only_the_last_linked_pair(self):
        self.app.store.add("conversation", "不相关的旧项目叫浮云。", "user_chat", timestamp=1,
                           metadata={"role":"user"})
        question = "请用一句话解释 SQLite。"
        self.app.ask(question)
        result = self.app.ask("继续")
        pending = self.app.store.get("pending_escalation")
        self.assertIsNotNone(pending)
        self.assertEqual(pending["user_request"], "继续")
        self.assertEqual([row["summary"] for row in pending["relevant_memories"]],
                         [question, "受控回忆回答。"])
        self.assertFalse(any(row["type"] != "conversation" for row in pending["relevant_memories"]))
        self.assertEqual(result["delegation_mode"], "reasoning")

    def test_force_help_receives_the_same_linked_continuation(self):
        question = "请用一句话解释 SQLite。"
        self.app.ask(question)
        self.app.ask("继续", force_help=True)
        pending = self.app.store.get("pending_escalation")
        self.assertEqual([row["summary"] for row in pending["relevant_memories"]],
                         [question, "受控回忆回答。"])
        self.assertEqual(self.app.store.get("pending_escalation_mode"), "execution")

    def test_terse_continuation_does_not_guess_without_a_linked_pair(self):
        self.app.store.add("conversation", "以前讨论过一个旧项目。", "user_chat", timestamp=1,
                           metadata={"role":"user"})
        self.app.ask("继续")
        prompt = self.requests[-1][-1]["content"]
        self.assertNotIn("旧项目", prompt)
        self.assertNotIn("相关对话记录", prompt)

    def test_terse_continuation_does_not_revive_forgotten_source_content(self):
        question_id = self.app.store.add("conversation", "请解释这份获准文件。", "user_chat", timestamp=1,
                                         metadata={"role":"user"})
        self.app.store.add("conversation", "过期私密内容。", "companion_model", timestamp=2,
            epistemic="inferred", metadata={"role":"assistant", "question_id":question_id, "delivery":"displayed",
                                            "memory_ids":["forgotten-source"], "observation_ids":[]})
        self.app.ask("继续", force_help=True)
        pending = self.app.store.get("pending_escalation")
        self.assertEqual(pending["relevant_memories"], [])
        self.assertNotIn("过期私密内容", json.dumps(pending, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
