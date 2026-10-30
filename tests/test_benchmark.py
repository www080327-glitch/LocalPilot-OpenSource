import tempfile
import unittest
from pathlib import Path

from benchmarks.run import FIXTURES, check_answer, create_fixture_workspace
from benchmarks.tasks import PROMPT_VERSION, TASKS


class BenchmarkTests(unittest.TestCase):
    def test_corpus_has_unique_ids_and_covers_requested_groups(self):
        ids = [task["id"] for task in TASKS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(TASKS), 20)
        self.assertEqual(PROMPT_VERSION, "v1")
        self.assertIn("smoke_missing_file", ids)
        self.assertIn("no_guess_unknown", ids)

    def test_fixture_files_are_written_and_deterministic_checks_use_expected_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            create_fixture_workspace(directory)
            for relative_path, expected in FIXTURES.items():
                self.assertEqual(Path(directory, relative_path).read_text(encoding="utf-8"), expected)
        task = {"expected_facts": ["Kestrel", "4"]}
        self.assertEqual(check_answer(task, "The codename is Kestrel and worker limit is 4.", 2), (True, [], None))
        self.assertFalse(check_answer(task, "The codename is unknown.", 2)[0])


if __name__ == "__main__":
    unittest.main()
