import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

from localpilot_suite.installer_download import fetch
from localpilot_suite.product_backup import backup, restore
from localpilot_suite.installation import service
from localpilot_service.cli import save


class Response(io.BytesIO):
    def __init__(self, value, status=200, headers=None):
        super().__init__(value); self.status=status; self.headers=headers or {}


class InstallerDownloadTests(unittest.TestCase):
    def test_interrupted_download_resumes_at_exact_range_and_verifies(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'installer.dmg';payload=b'complete verified installer'
            target.with_name(target.name+'.partial').write_bytes(payload[:8])
            def server(request,timeout):
                self.assertEqual(request.get_header('Range'),'bytes=8-')
                return Response(payload[8:],206,{'Content-Range':f'bytes 8-{len(payload)-1}/{len(payload)}'})
            result=fetch('https://example.test/pinned',target,len(payload),hashlib.sha256(payload).hexdigest(),server)
            self.assertEqual(result['resumed_bytes'],8);self.assertEqual(target.read_bytes(),payload)

    def test_server_ignoring_range_restarts_without_appending(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'installer';target.with_name('installer.partial').write_bytes(b'pa')
            fetch('https://example.test',target,4,hashlib.sha256(b'full').hexdigest(),lambda *a,**k:Response(b'full'))
            self.assertEqual(target.read_bytes(),b'full')

    def test_wrong_range_and_hash_never_promote_an_installer(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'installer';partial=target.with_name('installer.partial');partial.write_bytes(b'x')
            with self.assertRaises(ValueError):fetch('https://example.test',target,4,'0'*64,lambda *a,**k:Response(b'bad',206,{'Content-Range':'bytes 0-2/4'}))
            self.assertEqual(partial.read_bytes(),b'x');self.assertFalse(target.exists())
            with self.assertRaises(ValueError):fetch('https://example.test',target,4,'0'*64,lambda *a,**k:Response(b'evil'))
            self.assertFalse(target.exists())

    def test_network_failure_preserves_partial_and_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'installer';partial=target.with_name('installer.partial');partial.write_bytes(b'old')
            with self.assertRaisesRegex(ValueError,'下载中断'):fetch('https://example.test',target,9,'0'*64,lambda *a,**k:(_ for _ in ()).throw(TimeoutError()))
            self.assertEqual(partial.read_bytes(),b'old')
            other=Path(folder)/'other';other.write_bytes(b'protected');partial.unlink();partial.symlink_to(other)
            with self.assertRaises(ValueError):fetch('https://example.test',target,9,'0'*64)
            self.assertEqual(other.read_bytes(),b'protected')


class RecoveryTests(unittest.TestCase):
    def fixture(self,root):
        home=root/'home';home.mkdir(mode=0o700)
        for name in ('data','companion-data'):(home/name).mkdir(mode=0o700)
        key=root/'provider.key';key.write_text('synthetic-credential-not-real');key.chmod(0o600)
        save(home/'service.json',{'data_dir':str(home/'data'),'routes':{'default':{'workspace':str(root/'workspace'),'backend':{'kind':'deepseek-native','key_file':str(key)}}},'port':8765})
        save(home/'connection.json',{'url':'http://127.0.0.1:8765','token_env':'LOCALPILOT_HTTP_TOKEN'})
        save(home/'companion.json',{'data_dir':str(home/'companion-data'),'localpilot_endpoint':'http://127.0.0.1:8765'})
        save(home/'model-preferences.json',{'preserved':True})
        (home/'clients.env').write_text('export LOCALPILOT_HTTP_TOKEN=synthetic-token-123456\n');(home/'clients.env').chmod(0o600)
        for path in [home/'data/runtime.sqlite3',home/'companion-data/memory.sqlite3']:
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE history(text)');db.execute("INSERT INTO history VALUES('before upgrade')");db.commit()
            path.chmod(0o600)
        return home

    def test_upgrade_backup_and_recovery_preserve_history_keys_and_original(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);home=self.fixture(root);source=root/'backup';backup(home,source)
            old=(home/'service.json').read_bytes();destination=root/'restored';result=restore(source,destination)
            self.assertFalse(result['original_data_overwritten']);self.assertFalse(result['service_started'])
            from companion.config import PrivateData
            self.assertEqual(PrivateData((destination/'companion-data').resolve()).file('.companion-data-owner').read_text(),'localpilot-companion-v0\n')
            self.assertEqual((home/'service.json').read_bytes(),old)
            config=json.loads((destination/'service.json').read_text());conn=json.loads((destination/'connection.json').read_text())
            self.assertNotEqual(conn['url'],'http://127.0.0.1:8765')
            key=Path(config['routes']['default']['backend']['key_file'])
            self.assertTrue(key.is_relative_to(destination.resolve()));self.assertEqual(key.read_text(),'synthetic-credential-not-real')
            for name in ('core-data/runtime.sqlite3','companion-data/memory.sqlite3'):
                with closing(sqlite3.connect(destination/name)) as db:self.assertEqual(db.execute('SELECT text FROM history').fetchone()[0],'before upgrade')
            self.assertEqual(json.loads((destination/'model-preferences.json').read_text()),{'preserved':True})
            with self.assertRaises(ValueError):restore(source,home)

    def test_corrupt_backup_and_low_disk_fail_before_creating_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);home=self.fixture(root);source=root/'backup';backup(home,source);destination=root/'restored'
            with patch('shutil.disk_usage',return_value=shutil._ntuple_diskusage(10,10,0)):
                with self.assertRaisesRegex(ValueError,'空间不足'):restore(source,destination)
            self.assertFalse(destination.exists())
            (source/'clients.env').write_text('tampered')
            with self.assertRaisesRegex(ValueError,'校验失败'):restore(source,destination)
            self.assertFalse(destination.exists())

    def test_missing_backend_initializes_no_model_or_cloud_request(self):
        # A malformed old install must be preserved; never patch its JSON heuristically.
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder)/'partial';home.mkdir(mode=0o700);save(home/'connection.json',{'url':'http://127.0.0.1:1'})
            before=(home/'connection.json').read_bytes()
            from localpilot_suite.desktop_setup import prepare
            with self.assertRaisesRegex(ValueError,'配置不完整'):prepare(home,Path(folder)/'workspace')
            self.assertEqual((home/'connection.json').read_bytes(),before)

    def test_start_failure_is_reported_and_never_replayed(self):
        with tempfile.TemporaryDirectory() as folder:
            home=self.fixture(Path(folder))
            with patch('localpilot_service.cli.connection',side_effect=ConnectionError()),patch('localpilot_service.cli.start',side_effect=ValueError('occupied port')) as start:
                with self.assertRaisesRegex(ValueError,'occupied port'):service(home,'core','recover')
                self.assertEqual(start.call_count,1)
            with self.assertRaises(ValueError):service(home,'core','arbitrary-command')

    def test_cold_start_is_observed_without_launching_twice(self):
        from localpilot_suite.installation import start_core
        with patch('localpilot_service.cli.start',side_effect=ValueError('Service is still starting after 30 seconds')) as start, \
             patch('localpilot_service.cli.connection'), \
             patch('localpilot_service.cli.compatible',side_effect=[OSError('not ready'),{'status':'ready'}]), \
             patch('localpilot_suite.installation.time.sleep'):
            self.assertEqual(start_core(Path('/synthetic/home'))['status'],'ready')
            self.assertEqual(start.call_count,1)

    def test_backup_refuses_insufficient_destination_space(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);home=self.fixture(root);destination=root/'backup'
            with patch('shutil.disk_usage',return_value=shutil._ntuple_diskusage(10,10,0)):
                with self.assertRaisesRegex(ValueError,'空间不足'):backup(home,destination)
            self.assertFalse(destination.exists());self.assertTrue((home/'clients.env').exists())

    def test_unready_owned_home_process_is_not_started_twice(self):
        from localpilot_suite.installation import start_core
        from types import SimpleNamespace
        process=SimpleNamespace(info={'uids':SimpleNamespace(real=os.getuid()),'cmdline':['/python','-m','localpilot_service.cli','--home','/synthetic/home','_serve']})
        with patch('psutil.process_iter',return_value=[process]),patch('localpilot_service.cli.start') as start, \
             patch('localpilot_service.cli.connection'),patch('localpilot_service.cli.compatible',return_value={'status':'ready'}):
            self.assertEqual(start_core(Path('/synthetic/home'))['status'],'ready');start.assert_not_called()

    def test_companion_starting_is_observed_before_claiming_ready(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            home=self.fixture(Path(folder))
            responses=[SimpleNamespace(returncode=0,stdout='{"status":"starting"}'),SimpleNamespace(returncode=0,stdout='{"status":"running"}')]
            with patch('localpilot_service.cli.environment',return_value={}),patch('subprocess.run',side_effect=responses) as run,patch('localpilot_suite.installation.time.sleep'):
                self.assertEqual(service(home,'companion','recover')['status'],'running')
                self.assertEqual([call.args[0][-1] for call in run.call_args_list],['start','status'])

    def test_omlx_renamed_argv_keeps_identity_but_reused_pid_and_foreign_executable_do_not(self):
        from localpilot_suite.product_installer import owned_process_matches
        from types import SimpleNamespace
        process=SimpleNamespace(uids=lambda:SimpleNamespace(real=os.getuid()),create_time=lambda:100.0,
            exe=lambda:'/Applications/oMLX.app/Contents/Resources/Python/bin/python',cmdline=lambda:['omlx-server','',''])
        self.assertTrue(owned_process_matches(process,{'created':100.0},Path('/Applications/oMLX.app')))
        self.assertFalse(owned_process_matches(process,{'created':99.0},Path('/Applications/oMLX.app')))
        process.exe=lambda:'/usr/bin/python3'
        self.assertFalse(owned_process_matches(process,{'created':100.0},Path('/Applications/oMLX.app')))

    def test_backend_status_uses_private_bearer_and_never_follows_redirects(self):
        from http.server import BaseHTTPRequestHandler,HTTPServer
        import threading
        from urllib.request import build_opener,ProxyHandler
        from localpilot_suite.product_control import OmlxAdmin,NoBackendRedirects
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                seen.append(self.path)
                if self.path=='/redirect':
                    self.send_response(302);self.send_header('Location','/leak');self.end_headers();return
                if self.headers.get('Authorization')!='Bearer synthetic-local-test-key':
                    self.send_response(401);self.end_headers();return
                self.send_response(200);self.end_headers();self.wfile.write(b'{"active_requests":0}')
        server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=lambda:server.serve_forever(poll_interval=.05));thread.start()
        try:
            admin=OmlxAdmin.__new__(OmlxAdmin);admin.base=f'http://127.0.0.1:{server.server_port}';admin.settings={'auth':{'api_key':'synthetic-local-test-key'}};admin.opener=build_opener(ProxyHandler({}),NoBackendRedirects())
            self.assertEqual(admin.request('/api/status')['active_requests'],0)
            with self.assertRaises(ValueError):admin.request('/redirect')
            self.assertEqual(seen,['/api/status','/redirect'])
        finally:server.shutdown();thread.join();server.server_close()


if __name__=='__main__':unittest.main()
