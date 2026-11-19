"""Saved chat pagination through the actual Companion command dispatcher."""
from pathlib import Path
import tempfile
import unittest

from companion.config import Config
from companion.runtime.service import Companion


class PetHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name).resolve()
        self.documents = root / "documents"
        self.documents.mkdir()
        self.config = Config(data_dir=str(root / "data"), backend="disabled", localpilot_endpoint="",
                             low_power_policy="off", notifications=False, dnd=True, watch_dirs=(str(self.documents),))
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
        self.temporary.cleanup()

    def history(self, **options):
        return self.app.command({"command":"pet_history", **options})

    def test_saved_speakers_and_stable_ids_restore_after_restart(self):
        reply = self.app.command({"command":"pet_ask", "text":"你好"})
        self.close_app()
        self.app = Companion(self.config)
        page = self.history()
        self.assertEqual([row["role"] for row in page["messages"]], ["user", "assistant"])
        self.assertEqual([row["id"] for row in page["messages"]], [reply["question_id"], reply["answer_id"]])
        self.assertEqual(page["messages"][0]["text"], "你好")
        self.assertEqual(page["messages"][1]["text"], reply["text"])
        self.assertEqual(page["messages"][1]["answer_id"], reply["answer_id"])
        self.assertIsNone(page["next_before"])
        self.assertEqual(self.app.model.inferences, 0)
        self.assertEqual(self.app.localpilot.network_calls, 0)

    def test_pages_use_stable_cursor_even_when_timestamps_tie(self):
        ids = [self.app.store.add("conversation", f"历史消息 {i}", "user_chat", timestamp=100,
                                 metadata={"role":"user"}) for i in range(11)]
        seen, before = [], None
        while True:
            page = self.history(limit=3, before=before)
            self.assertLessEqual(len(page["messages"]), 3)
            seen.extend(row["id"] for row in reversed(page["messages"]))
            before = page["next_before"]
            if before is None:
                break
        self.assertEqual(seen, sorted(ids, reverse=True))
        self.assertEqual(len(seen), len(set(seen)))

    def test_skipped_rows_advance_the_cursor_without_exposing_revoked_content(self):
        oldest = self.app.store.add("conversation", "允许展示的原话。", "user_chat", timestamp=1,
                                    metadata={"role":"user"})
        for i in range(4):
            self.app.store.add("conversation", "不再允许展示的私密内容。", "companion_model", timestamp=10+i,
                epistemic="inferred", metadata={"role":"assistant", "delivery":"displayed",
                                                "memory_ids":["deleted-parent"], "observation_ids":[]})
        first = self.history(limit=2)
        self.assertEqual(first["messages"], [])
        second = self.history(limit=2, before=first["next_before"])
        self.assertEqual(second["messages"], [])
        self.assertNotEqual(first["next_before"], second["next_before"])
        last = self.history(limit=2, before=second["next_before"])
        self.assertEqual([row["id"] for row in last["messages"]], [oldest])
        self.assertIsNone(last["next_before"])

    def test_memory_off_does_not_read_saved_conversations(self):
        self.app.command({"command":"pet_ask", "text":"你好"})
        self.app.command({"command":"pet_memory", "enabled":False})
        statements = []
        self.app.store.db.set_trace_callback(statements.append)
        self.assertEqual(self.history(), {"status":"ok", "messages":[], "next_before":None})
        self.assertFalse(any("FROM memories" in sql for sql in statements))

    def test_history_limits_and_cursor_are_validated_at_command_entry(self):
        for limit in (0, 51, True, "30"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.history(limit=limit)
        for before in ({}, {"timestamp":float("nan"), "id":"a"*32},
                       {"timestamp":1, "id":"invalid"}, {"timestamp":True, "id":"a"*32}, []):
            with self.subTest(before=before), self.assertRaises(ValueError):
                self.history(before=before)

    def test_clear_leaves_no_saved_timeline(self):
        self.app.command({"command":"pet_ask", "text":"你好"})
        self.app.command({"command":"clear", "confirmation":"DELETE_COMPANION_MEMORY"})
        self.assertEqual(self.history()["messages"], [])
        self.assertIsNone(self.history()["next_before"])

    def test_verified_fact_reply_restores_only_while_its_source_is_current(self):
        path = self.documents / "budget.txt"
        path.write_text("项目：天河\n预算：100000元\n")
        self.app.process_file(str(path), "created")
        reply = self.app.command({"command":"pet_ask", "text":"天河预算是多少？"})
        answer = self.app.store.record(reply["answer_id"])
        self.assertEqual(answer["source"], "companion_fact_guard")
        self.assertEqual(answer["metadata"]["question_id"], reply["question_id"])
        self.assertIn(reply["answer_id"], [row["id"] for row in self.history()["messages"]])
        self.app.store.invalidate_source(str(path))
        self.assertNotIn(reply["answer_id"], [row["id"] for row in self.history()["messages"]])


if __name__ == "__main__":
    unittest.main()
