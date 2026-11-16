import json
from pathlib import Path
import tempfile
import unittest

from companion.config import Config, MAX_AGENT_TASK_TIMEOUT_SECONDS
from companion.escalation.localpilot import LocalPilotProvider


class LongTaskLimitsTests(unittest.TestCase):
    def test_two_hour_and_day_long_tasks_survive_config_and_transport_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'companion.json'
            for seconds in (7200, MAX_AGENT_TASK_TIMEOUT_SECONDS):
                with self.subTest(seconds=seconds):
                    path.write_text(json.dumps({'localpilot_task_timeout_seconds': seconds}))
                    provider = LocalPilotProvider(Config.load(path))
                    self.assertEqual(provider.task_timeout, seconds)
                    self.assertEqual(provider.timeout, 15)

    def test_invalid_task_deadlines_are_still_rejected(self):
        for value in (0, True, float('nan'), 86401):
            with self.subTest(value=value), self.assertRaises(ValueError):
                LocalPilotProvider(Config(localpilot_task_timeout_seconds=value))

    def test_long_task_does_not_expand_the_transport_connection_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'companion.json'
            path.write_text(json.dumps({'localpilot_task_timeout_seconds': 7200,
                                       'localpilot_timeout_seconds': 121}))
            with self.assertRaisesRegex(ValueError, 'timeout exceeds'):
                Config.load(path)


if __name__ == '__main__':
    unittest.main()
