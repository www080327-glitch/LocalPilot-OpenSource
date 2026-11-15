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
crypto_spec = importlib.util.spec_from_file_location('cryptography_builder', SCRIPTS / 'build-cryptography-wheel.py')
crypto_builder = importlib.util.module_from_spec(crypto_spec)
crypto_spec.loader.exec_module(crypto_builder)


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

    def test_intel_wheel_requires_cpython_314_abi_and_supported_macos(self):
        for tag in ['cp313-cp313-macosx_10_13_x86_64',
                    'cp314-cp314t-macosx_10_13_x86_64',
                    'pp310-pypy310_pp73-macosx_10_15_x86_64',
                    'cp314-cp314-macosx_16_0_x86_64',
                    'py2-none-any']:
            with self.subTest(tag=tag):
                self.assertFalse(wheel_supports('fixture-1.0-' + tag + '.whl', 'x86_64'))
        for tag in ['cp36-abi3-macosx_10_9_x86_64',
                    'cp314-cp314-macosx_10_15_universal2',
                    'py2.py3-none-any']:
            with self.subTest(tag=tag):
                self.assertTrue(wheel_supports('fixture-1.0-' + tag + '.whl', 'x86_64'))

    def test_pypi_selection_uses_compatible_abi_and_skips_yanked_files(self):
        def row(tag, **kwargs):
            return dict(filename='fixture-1.0-' + tag + '.whl',packagetype='bdist_wheel',**kwargs)
        selected = row('cp36-abi3-macosx_10_9_x86_64')
        files = [row('cp314-cp314t-macosx_10_13_x86_64'),
                 row('cp314-cp314-macosx_10_13_x86_64', yanked=True),
                 row('cp314-cp314-macosx_15_0_x86_64', requires_python='>=3.15'),
                 selected, row('cp314-cp314-macosx_11_0_arm64')]
        self.assertEqual(generator.select_wheel(files, 'x86_64'), selected)
        self.assertIsNone(generator.select_wheel(files[:3], 'x86_64'))

    def test_existing_download_is_hash_verified_without_network_or_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=root/'fixture-1.0-py3-none-any.whl'
            path.write_bytes(b'actual-fixture-content')
            row={'filename':path.name,'url':'https://files.pythonhosted.org/fixture.whl',
                 'digests':{'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}}
            observed=generator.fetch_artifact(row,root)
            self.assertEqual(observed['bytes'],len(path.read_bytes()))
            row['digests']['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'hash mismatch'):
                generator.fetch_artifact(row,root)
            self.assertEqual(path.read_bytes(),b'actual-fixture-content')

    def test_lock_checks_distribution_python_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            wheel=root/'fixture-1.0-py3-none-any.whl'
            with zipfile.ZipFile(wheel,'w') as archive:
                archive.writestr('fixture-1.0.dist-info/METADATA',
                    'Metadata-Version: 2.1\nName: fixture\nVersion: 1.0\nRequires-Python: >=3.15\n')
            with self.assertRaisesRegex(ValueError,'Python 3.14.6'):
                generator.create_lock(root,{'packages':{'fixture':{'version':'1.0'}}},'x86_64')

    def test_native_record_requires_matching_source_target_and_real_artifact_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            wheel=root/'cryptography-50.0.2-cp311-abi3-macosx_15_0_x86_64.whl'
            wheel.write_bytes(b'local native artifact fixture')
            record={'kind':'CONTROLLED_NATIVE_SOURCE_BUILD','architecture':'x86_64',
                    'source_sha256':crypto_builder.SOURCE_SHA256,'wheel':wheel.name,
                    'sha256':hashlib.sha256(wheel.read_bytes()).hexdigest()}
            path=root/'cryptography-build.json'
            path.write_text(json.dumps(record))
            self.assertEqual(generator.read_build_record(root,'cryptography','x86_64'),record)
            with self.assertRaisesRegex(ValueError,'does not match'):
                generator.read_build_record(root,'cryptography','arm64')
            wheel.write_bytes(b'changed artifact')
            with self.assertRaisesRegex(ValueError,'does not match'):
                generator.read_build_record(root,'cryptography','x86_64')

    def test_static_openssl_license_is_bundled_and_wheel_record_is_regenerated(self):
        from wheel.wheelfile import WheelFile
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'cryptography-50.0.2-cp311-abi3-macosx_15_0_x86_64.whl'
            dist='cryptography-50.0.2.dist-info'
            with zipfile.ZipFile(source,'w') as archive:
                archive.writestr(dist+'/METADATA','Metadata-Version: 2.4\nName: cryptography\nVersion: 50.0.2\n')
                archive.writestr(dist+'/WHEEL','Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: false\nTag: cp311-abi3-macosx_15_0_x86_64\n')
                archive.writestr('cryptography/binding.so',b'fixture binary')
                archive.writestr(dist+'/RECORD','old invalid record')
            target=root/'final'/source.name
            crypto_builder.bundle_openssl_license(source,target,b'OpenSSL license fixture\n')
            with WheelFile(target) as wheel:
                self.assertEqual(wheel.read(dist+'/licenses/OPENSSL.txt'),b'OpenSSL license fixture\n')
                self.assertEqual(wheel.read('cryptography/binding.so'),b'fixture binary')
                self.assertIn(b'License-File: OPENSSL.txt',wheel.read(dist+'/METADATA'))
                self.assertNotIn(b'old invalid record',wheel.read(dist+'/RECORD'))


if __name__ == '__main__':
    unittest.main()
