"""Prompt/source controls with fake replies; no claim of real model quality."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from companion.config import Config
from companion.runtime.service import Companion


class ChatContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name).resolve()
        self.documents = root / "documents"
        self.documents.mkdir()
        self.app = Companion(Config(low_power_policy="off", localpilot_endpoint="", data_dir=str(root / "state"), watch_dirs=(str(self.documents),),
                                    backend="disabled", dnd=True, notifications=False))
        self.app.model.complete = Mock(side_effect=lambda *args, **kwargs: {"status": "ok", "text": "受控测试回答。"})

    def tearDown(self):
        self.app.native.stop(); self.app.observer.stop(); self.app.model.unload()
        self.app.channel.stop(); self.app.store.close(); self.app.lock.close()
        self.temporary.cleanup()

    def last_prompt(self):
        return self.app.model.complete.call_args.args[0][-1]["content"]

    def test_repeated_definition_does_not_promote_old_questions_to_sources(self):
        self.app.ask("请用一句话说明 SQLite 的用途。")
        question = "用一句话说明只读权限是什么。"
        self.assertTrue(any(r["type"] == "conversation" for r in self.app.retrieve(question)))
        for _ in range(5):
            result = self.app.ask(question)
            self.assertEqual(result["memories"], [])
            self.assertNotIn("SQLite", self.last_prompt())
            self.assertNotIn("相关对话记录", self.last_prompt())
            self.assertNotIn("相关持久记忆", self.last_prompt())
            self.assertIn(question, self.last_prompt())
        count = self.app.store.db.execute("SELECT count(*) FROM memories WHERE source='user_chat'").fetchone()[0]
        self.assertEqual(count, 6, "Separation must not erase dialogue history")

    def test_explicit_history_is_speech_context_not_observed_work_fact(self):
        self.app.store.add("conversation", "这轮受控对话的项目代号是紫杉。", "user_chat", metadata={"role": "user"})
        result = self.app.ask("刚才告诉你的项目代号是什么？")
        prompt = self.last_prompt()
        self.assertIn("相关对话记录", prompt)
        self.assertIn("不证明工作事实", prompt)
        self.assertIn("紫杉", prompt)
        self.assertIn('"role": "user"', prompt)
        self.assertNotIn('"role": "unknown"', prompt)
        self.assertNotIn('"evidence_class": "OBSERVED"', prompt)
        self.assertFalse(any(r["type"] == "conversation" for r in result["memories"]))

    def test_old_unknown_question_cannot_unlock_work_source_guard(self):
        self.app.store.add("conversation", "我的项目代号是什么？", "user_chat", metadata={"role": "user"})
        result = self.app.ask("我的项目代号是什么？")
        self.assertEqual(result["model"]["reason"], "work_source_guard")
        self.app.model.complete.assert_not_called()

    def test_history_recall_keeps_declaration_when_latest_turn_is_question(self):
        self.app.store.add("conversation", "这轮受控对话里的项目代号是紫杉，请简短回复收到。",
                           "user_chat", metadata={"role": "user"}, timestamp=1)
        self.app.store.add("conversation", "刚才告诉你的项目代号是什么？",
                           "user_chat", metadata={"role": "user"}, timestamp=2)
        self.app.ask("我刚才告诉你的资料是什么？")
        self.assertIn("紫杉", self.last_prompt(), "Retrieving only the last question loses the actual user declaration")
        self.assertIn("不证明工作事实", self.last_prompt())
        self.assertNotIn('"evidence_class": "OBSERVED"', self.last_prompt())

    def test_role_mismatch_is_not_admitted_as_user_speech(self):
        self.app.store.add("conversation", "刚才说过的代号是隐藏模型内容。", "user_chat", metadata={"role": "assistant"})
        self.app.ask("刚才说过的代号是什么？")
        self.assertNotIn("隐藏模型内容", self.last_prompt())
        self.assertNotIn("相关对话记录", self.last_prompt())

    def test_explicit_saved_fact_remains_retrievable_evidence(self):
        self.app.command({"command": "remember", "type": "user_fact", "text": "我的项目代号是紫杉。"})
        result = self.app.ask("我的项目代号是什么？")
        self.app.model.complete.assert_called_once()
        self.assertTrue(any(r["type"] == "user_fact" for r in result["memories"]))
        self.assertIn("紫杉", self.last_prompt())
        self.assertIn('"evidence_class": "OBSERVED"', self.last_prompt())

    def test_model_and_reflection_cannot_become_work_fact_authority(self):
        self.app.store.add("conversation", "我的项目代号是幻影。", "companion_model", epistemic="inferred", metadata={"role": "assistant"})
        self.app.store.add("reflection", "我的项目代号可能是幻影。", "companion_reflection", epistemic="reflection")
        result = self.app.ask("我的项目代号是什么？")
        self.assertEqual(result["model"]["reason"], "work_source_guard")
        self.app.model.complete.assert_not_called()

    def test_inline_current_context_stays_current_and_excludes_old_questions(self):
        self.app.store.add("conversation", "我的项目代号是什么？", "user_chat", metadata={"role": "user"})
        question = "测试资料：受控项目代号为白榆。请只根据这段资料回答：项目代号是什么？"
        self.app.ask(question)
        self.assertIn(question, self.last_prompt())
        self.assertNotIn("相关持久记忆", self.last_prompt())
        self.assertNotIn("相关对话记录", self.last_prompt())

    def test_document_source_is_retained_after_dialogue_separation(self):
        path = self.documents / "context.txt"
        path.write_text("项目：受控测试\n项目代号：青禾\n")
        self.app.process_file(str(path), "created")
        result = self.app.ask("context.txt 中项目代号是什么？")
        self.assertTrue(any(r["type"] == "document" for r in result["memories"]))
        self.assertIn("青禾", self.last_prompt())
        self.assertIn("context.txt", self.last_prompt())


if __name__ == "__main__":
    unittest.main()
