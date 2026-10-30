"""Missing user-work evidence cannot be replaced by an invented model fact."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from companion.config import Config
from companion.runtime.routing import work_fact_requires_source
from companion.runtime.service import Companion


class WorkSourceGuardTests(unittest.TestCase):
    def test_gate_is_limited_to_direct_work_fact_questions(self):
        for question in ("我的项目代号是什么？", "我的项目预算是多少？", "我的项目负责人是谁？",
                         "What is my project name?"):
            self.assertTrue(work_fact_requires_source(question),question)
        for question in ("SQLite 是什么？", "我的项目代号是紫杉，请记住。", "项目预算通常如何计算？",
                         "我遇到连接失败，下一步怎么检查？"):
            self.assertFalse(work_fact_requires_source(question),question)

    def test_missing_source_blocks_model_without_claiming_model_improvement(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Companion(Config(low_power_policy="off", localpilot_endpoint="", data_dir=str(Path(temporary).resolve()/"state"),backend="disabled",dnd=True))
            try:
                app.model.complete = Mock(return_value={"status":"ok","text":"Project Alpha"})
                result = app.ask("我的项目代号是什么？")
                self.assertEqual(result["model"]["reason"],"work_source_guard")
                self.assertEqual(result["status"],"unavailable")
                app.model.complete.assert_not_called()
                self.assertNotIn("Project Alpha",result["text"])
                again = app.ask("我的项目代号是什么？")
                self.assertEqual(again["model"]["reason"],"work_source_guard")
                app.model.complete.assert_not_called()
                result = app.ask("SQLite 是什么？")
                app.model.complete.assert_called_once()
            finally:
                app.native.stop(); app.observer.stop(); app.model.unload()
                app.channel.stop(); app.store.close(); app.lock.close()


if __name__ == "__main__":
    unittest.main()
