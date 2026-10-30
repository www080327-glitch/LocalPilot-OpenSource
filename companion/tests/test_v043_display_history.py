"""Displayed speaker history, with fake generation and real Host/SQLite controls."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from companion.config import Config
from companion.runtime.service import Companion


class DisplayedHistoryTests(unittest.TestCase):
    def test_withheld_source_claim_cannot_reappear_as_delivered_speech(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            documents = root / "documents"
            documents.mkdir()
            app = Companion(Config(low_power_policy="off", localpilot_endpoint="", data_dir=str(root / "state"), watch_dirs=(str(documents),),
                                   backend="disabled", dnd=True, notifications=False))
            app.model.complete = Mock(side_effect=[
                {"status": "ok", "text": "根据来源 phantom.txt 的 line 1，SQLite 的用途是受控值。"},
                {"status": "ok", "text": "受控回忆回复。"}])
            try:
                response = app.ask("SQLite 有什么用途？")
                self.assertEqual(response["status"], "unverified")
                self.assertNotIn("phantom.txt", response["text"])
                assistant = [row for row in app.store.records(10, ["conversation"])
                             if row["source"] == "companion_model"]
                self.assertEqual(len(assistant), 1)
                self.assertEqual(assistant[0]["summary"], response["text"],
                                 "Only the text actually delivered may enter speaker history")
                app.ask("你刚才说了什么？")
                import json
                recalled_prompt = json.dumps(app.store.get("pending_escalation"), ensure_ascii=False)
                self.assertIn(response["text"], recalled_prompt)
                self.assertNotIn("phantom.txt", recalled_prompt,
                                 "A held raw citation claim must not reappear as past speech")
            finally:
                app.native.stop()
                app.observer.stop()
                app.model.unload()
                if app.secondary_model:
                    app.secondary_model.unload()
                app.channel.stop()
                app.store.close()
                app.lock.close()


if __name__ == "__main__":
    unittest.main()
