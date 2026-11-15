"""Installed Suite/component lifecycle against real Core; no platform accounts."""
import http.client
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from tests.channel_fixtures import ENV, QA, QQ, RealOfficial, configuration


@unittest.skipUnless(os.name == 'posix' and os.environ.get('LP_TEST_CHANNEL_WHEEL'),
                     'Requires installed Suite and explicit built optional wheel; POSIX lifecycle')
class InstalledSuiteChannelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='Suite渠道 验收 ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.host = RealOfficial(self.root)
        self.addCleanup(self.host.close)
        self.home = self.root/'suite-home'
        self.env = {k:os.environ[k] for k in ('PATH','HOME','TMPDIR','TMP','TEMP','LANG','SystemRoot') if k in os.environ}
        self.env.update(ENV)
        self.channel = configuration(self.host.url)
        self.config = self.root/'channels.json'
        self.config.write_text(json.dumps(self.channel))
        self.config.chmod(0o600)
        clients = [{'subject':name.lower(),'token_env':name,'scopes':['read','submit']}
                   for name in ('QA','QB','WA','WB')]
        clients += [{'subject':'op','token_env':'OP','scopes':['read','control'],'operator':True,'approval_for':['wa']}]
        self.core = self.root/'core.json'
        self.core.write_text(json.dumps({'clients':clients,'routes':{'localpilot':{'workspace':str(self.host.workspace)}}}))
        self.core.chmod(0o600)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0))
            self.port = listener.getsockname()[1]
        self.cli('install', '--wheel', os.environ['LP_TEST_CHANNEL_WHEEL'])
        self.cli('configure', '--config', str(self.config), '--core-config', str(self.core),
                 '--state-dir', str(self.root/'fresh-state'), '--port', str(self.port))
        self.addCleanup(lambda: self.cli('stop', 'adapter'))

    def cli(self, *args):
        result = subprocess.run([sys.executable,'-m','localpilot_suite.cli','--home',str(self.home),
                                 '--json','channels',*args], env=self.env, capture_output=True,
                                text=True, timeout=150)
        diagnostic = ''
        if result.returncode:
            try:
                lines = (self.home/'channels/adapter.error.log').read_text(encoding='utf-8', errors='replace').splitlines()
            except OSError:
                lines = []
            diagnostic = '\n'.join(line for line in lines if re.fullmatch(
                r'CHANNEL_PROCESS_RECORD_FAILED stage=identity_record exception=[A-Za-z_][A-Za-z0-9_]* errno=(?:none|-?[0-9]+)', line))
        self.assertEqual(result.returncode,0,result.stdout+result.stderr+'\n'+diagnostic)
        for secret in ENV.values():
            self.assertNotIn(secret,result.stdout+result.stderr)
        data = json.loads(result.stdout)
        if args[:1] == ('start',) and data.get('pid'):
            import psutil
            child = psutil.Process(data['pid'])
            created = child.create_time()
            def cleanup_child():
                try:
                    current = psutil.Process(child.pid)
                    command = current.cmdline()
                    if (abs(current.create_time()-created)<.02 and 'localpilot_channels' in command
                            and str((self.home/'channels/adapter.json').resolve()) in command):
                        current.terminate()
                        current.wait(timeout=20)
                except psutil.NoSuchProcess:
                    pass
            self.addCleanup(cleanup_child)
        return data

    def post(self, route, body):
        conn = http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
        try:
            conn.request('POST',route,json.dumps(body),{'Authorization':'Bearer '+ENV['QIN'],'Content-Type':'application/json'})
            response = conn.getresponse()
            data = json.loads(response.read())
            self.assertIn(response.status,(200,409))
            return data
        finally:
            conn.close()

    def start_with_identity_observation(self, mode):
        script = '''import errno,json,sys,psutil
from localpilot_suite import channels
from localpilot_suite.cli import main
mode=sys.argv.pop(1)
real_cmdline,real_save=psutil.Process.cmdline,channels.save
observed={'calls':0,'saves':0,'pid':None}
def cmdline(process):
    observed['calls']+=1;observed['pid']=process.pid
    if observed['calls']==1:
        return ['synthetic','--changed'] if mode=='changed_initial' else []
    if mode=='changed_final':return ['synthetic','--changed']
    if mode=='empty_final':return []
    return real_cmdline(process)
def save(path,value):
    observed['saves']+=1
    if mode=='save_failure':raise OSError(errno.ENOSPC,'SYNTHETIC_SAVE_FAILURE')
    return real_save(path,value)
psutil.Process.cmdline,channels.save=cmdline,save
try:
    code=main()
finally:
    observed['alive']=observed['pid'] is not None and psutil.pid_exists(observed['pid'])
    print('STARTUP_TEST '+json.dumps(observed),file=sys.stderr)
raise SystemExit(code)
'''
        result = subprocess.run([sys.executable,'-c',script,mode,'--home',str(self.home),
                                 '--json','channels','start','adapter'],env=self.env,
                                capture_output=True,text=True,timeout=150)
        for secret in ENV.values():
            self.assertNotIn(secret,result.stdout+result.stderr)
        observed = json.loads(next(line.removeprefix('STARTUP_TEST ') for line in result.stderr.splitlines()
                                   if line.startswith('STARTUP_TEST ')))
        return result.returncode, json.loads(result.stdout), observed

    def test_empty_initial_identity_is_confirmed_after_real_http_readiness(self):
        code, result, observed = self.start_with_identity_observation('empty_initial')
        self.assertEqual(code,0,result)
        self.assertEqual(result['status'],'running')
        self.assertEqual(observed['calls'],2)
        self.assertEqual(observed['saves'],1)
        self.assertTrue(observed['alive'])
        self.assertEqual(self.cli('status')['processes']['adapter'],'running')
        self.assertEqual(self.cli('stop','adapter')['status'],'stopped')

    def test_changed_or_still_empty_identity_is_rejected_without_startup_retry(self):
        for mode, calls in [('changed_initial',1),('changed_final',2),('empty_final',2)]:
            with self.subTest(mode=mode):
                code, result, observed = self.start_with_identity_observation(mode)
                self.assertEqual(code,2)
                self.assertEqual(result,{'error':'CHANNEL_PROCESS_RECORD_FAILED'})
                self.assertEqual(observed['calls'],calls)
                self.assertEqual(observed['saves'],0)
                self.assertFalse(observed['alive'])
                self.assertEqual(self.cli('status')['processes']['adapter'],'stopped')

    def test_final_record_save_failure_reaps_child_after_real_http_readiness(self):
        code, result, observed = self.start_with_identity_observation('save_failure')
        self.assertEqual(code,2)
        self.assertEqual(result,{'error':'CHANNEL_PROCESS_RECORD_FAILED'})
        self.assertEqual(observed['calls'],2)
        self.assertEqual(observed['saves'],1)
        self.assertFalse(observed['alive'])
        self.assertIn('exception=OSError errno=28',(self.home/'channels/adapter.error.log').read_text())
        self.assertEqual(self.cli('status')['processes']['adapter'],'stopped')

    def test_installed_adapter_start_query_sigterm_restart_and_safe_uninstall(self):
        self.assertEqual(self.cli('start','adapter')['status'],'running')
        first = self.post('/messages',{'channel':QQ,'sender_id':QA,'message_id':'suite-one','text':'list'})
        for _ in range(100):
            final = self.post('/tasks/query',{'channel':QQ,'sender_id':QA,'task_id':'suite-one'})
            if final['status'] != 'processing':
                break
            time.sleep(.02)
        self.assertEqual(final['status'],'completed')
        self.assertEqual(final['audit']['successful_non_reused_receipts'],1)
        self.assertEqual(final['evidence']['independent_verification'],'NOT_RUN')
        self.assertEqual(self.cli('task','--channel',QQ,'--sender-id',QA,'--task-id','suite-one')['official_task_id'],first['official_task_id'])
        self.assertIsNone(self.cli('pending','--channel',QQ,'--sender-id',QA)['active_task'])
        doctor = self.cli('doctor')
        self.assertEqual(doctor['core_identities'],'ready')
        self.assertEqual(self.cli('stop','adapter')['status'],'stopped')
        self.assertEqual(self.cli('start','adapter')['status'],'running')
        same = self.post('/messages',{'channel':QQ,'sender_id':QA,'message_id':'suite-one','text':'list'})
        self.assertEqual(same['official_task_id'],first['official_task_id'])
        self.assertEqual(self.host.executions,['list_directory'])
        self.cli('stop','adapter')
        self.assertEqual(self.cli('uninstall','--execute')['status'],'uninstalled')
        self.assertTrue((self.root/'fresh-state/adapter/channels.sqlite3').exists())
        self.assertFalse((self.home/'channels/runtime').exists())


    def test_sigint_releases_adapter_sqlite_and_allows_explicit_restart(self):
        import signal
        from localpilot_suite.channels import process
        self.cli('start','adapter')
        owned = process(self.home/'channels','adapter')
        self.assertIsNotNone(owned)
        owned.send_signal(signal.SIGINT)
        owned.wait(timeout=20)
        self.assertEqual(self.cli('status')['processes']['adapter'],'stopped')
        self.assertEqual(self.cli('start','adapter')['status'],'running')
        self.cli('stop','adapter')
