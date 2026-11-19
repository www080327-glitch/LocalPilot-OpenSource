"""Fault injection for optional runtime integrity, cancellation and disk checks."""
import tempfile
import tarfile
import io
import hashlib
import json
import os
import ssl
import subprocess
import sys
import venv
from urllib.error import URLError
from pathlib import Path
import unittest
from unittest.mock import patch
from localpilot_suite import channel_runtime as runtime, channels

class ChannelRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
    def test_missing_runtime_never_falls_back_to_global_node(self):
        with patch('shutil.which',return_value='/global/node') as search:
            self.assertIsNone(runtime.installed(self.home));search.assert_not_called()
    def test_installed_binary_is_checked_before_execution(self):
        root=self.home/'channel-node';root.mkdir(mode=0o700)
        node=root/'node';node.write_bytes(b'not executable');node.chmod(0o700)
        channels.save(root/'installation.json',{'version':runtime.VERSION,'binary_sha256':'0'*64})
        with self.assertRaisesRegex(ValueError,'INTEGRITY'):runtime.installed(self.home)
    def test_low_disk_stops_before_network_or_extraction(self):
        with patch.object(runtime.platform,'system',return_value='Darwin'),patch.object(runtime.platform,'machine',return_value='arm64'),patch.object(runtime.shutil,'disk_usage',return_value=type('Disk',(),{'free':0})()),patch.object(runtime,'build_opener') as opener:
            with self.assertRaisesRegex(ValueError,'INSUFFICIENT_DISK'):runtime.install(self.home)
            opener.assert_not_called()
    def test_unsupported_architecture_is_explicit(self):
        with patch.object(runtime.platform,'system',return_value='Linux'),patch.object(runtime.platform,'machine',return_value='riscv64'):
            with self.assertRaisesRegex(ValueError,'PLATFORM_NOT_SUPPORTED'):runtime.install(self.home)
    def test_linux_archives_are_distinct_from_macos_and_unknown_hosts_reject(self):
        for architecture, name in [('x86_64', 'linux-x64'), ('aarch64', 'linux-arm64')]:
            filename, checksum = runtime.runtime_archive('Linux', architecture)
            self.assertIn(name, filename)
            self.assertEqual(len(checksum), 64)
            self.assertNotIn(checksum, {row[1] for row in runtime.ARCHIVES.values()})
        with self.assertRaisesRegex(ValueError, 'PLATFORM_NOT_SUPPORTED'):
            runtime.runtime_archive('Windows', 'AMD64')
    def test_complete_verified_download_resumes_without_network(self):
        root=self.home/'channel-node';root.mkdir(mode=0o700)
        name=runtime.ARCHIVES['arm64'][0];path=root/(name+'.part')
        with tarfile.open(path,'w:gz') as archive:
            for relative,data in [('bin/node',b'fixture binary'),('LICENSE',b'fixture license')]:
                member=tarfile.TarInfo(name.removesuffix('.tar.gz')+'/'+relative);member.size=len(data);archive.addfile(member,io.BytesIO(data))
        path.chmod(0o600);checksum=runtime.digest(path)
        with patch.object(runtime.platform,'system',return_value='Darwin'),patch.object(runtime.platform,'machine',return_value='arm64'),patch.dict(runtime.ARCHIVES,{'arm64':(name,checksum)}),patch.object(runtime,'build_opener') as opener:
            self.assertEqual(runtime.install(self.home)['status'],'installed');opener.assert_not_called()
        self.assertEqual(runtime.installed(self.home),(root/'node').resolve())
    def test_certificate_error_is_explicit_and_never_bypassed(self):
        with patch.object(runtime.platform,'system',return_value='Darwin'),patch.object(runtime.platform,'machine',return_value='arm64'),patch.object(runtime,'build_opener') as opener:
            opener.return_value.open.side_effect=URLError(ssl.SSLCertVerificationError('fixture verification error'))
            with self.assertRaisesRegex(ValueError,'TLS_VERIFICATION_FAILED'):runtime.install(self.home)
        self.assertFalse((self.home/'channel-node/node').exists())
    def test_archive_checksum_is_pinned_for_each_architecture(self):
        self.assertEqual(set(runtime.ARCHIVES),{'arm64','x86_64'})
        for name,checksum in runtime.ARCHIVES.values():
            self.assertIn(runtime.VERSION,name);self.assertEqual(len(checksum),64)

    def test_bundled_archive_uses_virtual_environment_prefix_with_symlinked_python(self):
        bundle = self.home / 'bundle with spaces'
        environment = bundle / 'runtime'
        venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
        archive_dir = bundle / 'channel-runtime'
        archive_dir.mkdir()
        name, _ = runtime.runtime_archive()
        archive_path = archive_dir / name
        with tarfile.open(archive_path, 'w:gz') as archive:
            for relative, data in [('bin/node', b'fixture binary'), ('LICENSE', b'fixture license')]:
                member = tarfile.TarInfo(name.removesuffix('.tar.gz') + '/' + relative)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        script = '''
import json, platform, sys
from pathlib import Path
from localpilot_suite import channel_runtime as runtime
archives = runtime.ARCHIVES if platform.system() == 'Darwin' else runtime.LINUX_ARCHIVES
archives[platform.machine()] = (sys.argv[2], sys.argv[3])
runtime.SOURCE = 'http://127.0.0.1:1/'
print(json.dumps(runtime.install(Path(sys.argv[1]))))
'''
        run = subprocess.run([str(environment / 'bin/python'), '-c', script,
            str(self.home / 'user-data'), name, runtime.digest(archive_path)],
            env={**os.environ, 'PYTHONPATH': str(Path(runtime.__file__).resolve().parents[1])},
            capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertTrue(result['bundled_runtime'])
        self.assertFalse(result['downloaded'])
        self.assertEqual((self.home / 'user-data/channel-node/node').read_bytes(), b'fixture binary')

if __name__=='__main__':unittest.main()
