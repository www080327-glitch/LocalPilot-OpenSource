import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/pet-control.py"
spec = importlib.util.spec_from_file_location("pet_control", SCRIPT)
pet_control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pet_control)


class TestAppPetControl(unittest.TestCase):
    def test_resolves_the_client_directory_used_by_the_test_app(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            marker = root / "test-owner.json"
            marker.write_text(json.dumps({"purpose": "LocalPilot installation E2E"}))
            marker.chmod(0o600)
            self.assertEqual(pet_control.test_client(root), root.resolve() / "client")
            marker.write_text(json.dumps({"purpose": "different application"}))
            with self.assertRaisesRegex(ValueError, "installation test root"):
                pet_control.test_client(root)

    def test_existing_sample_is_ignored_until_native_writer_replaces_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pet-animation-probe.json"
            path.write_text('{"segments": []}')
            before = pet_control.report_stamp(path)
            with self.assertRaises(TimeoutError):
                pet_control.fresh_report(path, before, 0.05)
            replacement = path.with_suffix(".tmp")
            sample = {"segments": [{"mode": "PEEKING", "observed_fps": 0}]}
            replacement.write_text(json.dumps(sample))
            replacement.replace(path)
            self.assertEqual(pet_control.fresh_report(path, before, 1), sample)
