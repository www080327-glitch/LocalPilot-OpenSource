"""Real local wheel lock generation; native Mach-O/APP execution is a separate gate."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from macos_artifacts import architecture, runtime_lock, wheel_supports

spec = importlib.util.spec_from_file_location('lock_runtime_dependencies', SCRIPTS / 'lock-runtime-dependencies.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class MacArtifactTests(unittest.TestCase):
    def test_platform_tags_do_not_treat_arm64_or_linux_as_intel_mac(self):
        self.assertEqual(architecture('amd64'), 'x86_64')
        self.assertEqual(architecture('aarch64'), 'arm64')
        for tag in ('macosx_10_13_x86_64', 'macosx_11_0_universal2', 'any'):
            self.assertTrue(wheel_supports('sample-1.0-py3-none-' + tag + '.whl', 'x86_64'))
        for tag in ('macosx_11_0_arm64', 'manylinux_2_17_x86_64', 'win_amd64'):
            self.assertFalse(wheel_supports('sample-1.0-py3-none-' + tag + '.whl', 'x86_64'))

    def test_exact_local_artifacts_produce_a_new_lock_without_changing_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = root / 'fixture-1.0-cp314-cp314-macosx_10_15_x86_64.whl'
            with zipfile.ZipFile(wheel, 'w') as archive:
                archive.writestr('fixture-1.0.dist-info/METADATA', 'Metadata-Version: 2.1\nName: fixture\nVersion: 1.0\n')
            base = {'packages': {'fixture': {'version': '1.0', 'license': 'MIT'}}}
            lock = generator.create_lock(root, base, 'x86_64')
            self.assertEqual(lock['packages']['fixture']['sha256'], hashlib.sha256(wheel.read_bytes()).hexdigest())
            self.assertEqual(lock['architecture'], 'x86_64')
            self.assertEqual(base['packages']['fixture'], {'version': '1.0', 'license': 'MIT'})
            path = root / 'intel-lock.json'
            path.write_text(json.dumps(lock))
            self.assertEqual(runtime_lock(path, 'x86_64'), lock)
            with self.assertRaisesRegex(ValueError, 'different architecture'):
                runtime_lock(path, 'arm64')
            with self.assertRaisesRegex(ValueError, 'does not support'):
                generator.create_lock(root, base, 'arm64')
            base['packages']['fixture']['version'] = '2.0'
            with self.assertRaisesRegex(ValueError, 'version differs'):
                generator.create_lock(root, base, 'x86_64')

    def test_current_arm_lock_requires_distinct_reviewed_intel_wheels(self):
        baseline = SCRIPTS.parent / 'runtime-dependencies.json'
        runtime_lock(baseline, 'arm64')
        with self.assertRaisesRegex(ValueError, 'no x86_64 wheel'):
            runtime_lock(baseline, 'x86_64')


if __name__ == '__main__':
    unittest.main()
