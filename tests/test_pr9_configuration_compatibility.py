"""Compare actual old/new host factories; never replace a persisted fingerprint."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


BASELINE = '0a7fdff36f45a471130293b508b5d008f40cecf9'
PROBE = '''
import json, sys
from agent.persistence import configuration
from localpilot_service.deployment import build
from localpilot_service.desktop_sessions import apply_options
server = build(sys.argv[1])
try:
    result = {}
    for name, factory in server.service.routes.items():
        runtime = factory(None)
        try:
            if sys.argv[2] == 'desktop':
                apply_options(runtime, {'permission_mode':'full','agent_profile':'standard',
                                        'scope_revision':3,'prompt_revision':2})
            result[name] = configuration(runtime)
        finally:
            runtime.close()
    print(json.dumps(result, sort_keys=True))
finally:
    server.service.suspend()
    server.server_close()
    server.access.close()
'''

CHECKPOINT = '''
import json, sys
from agent.backends import BackendResponse, Message
from localpilot_api.service import TaskRequest
from localpilot_service.deployment import build
server = build(sys.argv[1])
try:
    saved = server.service.create_session(sys.argv[2], owner_subject='test',
        desktop_options={'permission_mode':'full','agent_profile':'standard',
                         'scope_revision':3,'prompt_revision':2})
    runtime = server.service.sessions[saved['id']].runtime
    runtime._request_once = lambda *args: BackendResponse(Message('assistant', 'PR9 fixture reply'),
        {'prompt_tokens':10,'completion_tokens':4}, 'transport-fixture', 'stop')
    task = server.service.create_task(TaskRequest('Retain this PR9 conversation', model=sys.argv[2], session_id=saved['id']),
                                      owner_subject='test')
    task = server.service.wait(task['id'])
    assert task['status'] == 'completed', task
    print(json.dumps({'session_id':saved['id'], 'task_id':task['id'],
                      'payload':server.service.store.load()[0]}))
finally:
    server.service.suspend()
    server.server_close()
    server.access.close()
'''


class PR9CompatibilityTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('LOCALPILOT_PR9_SOURCE'), 'NOT_RUN: requires pinned public PR9 source')
    def test_actual_desktop_checkpoint_restores_frozen_prompt_and_current_host_view(self):
        from agent.backends import BackendResponse, Message
        from agent.persistence import PersistenceError
        from localpilot_api.service import TaskRequest
        from localpilot_service.deployment import build
        from tests.test_local_http_backend import MockServer

        baseline = Path(os.environ['LOCALPILOT_PR9_SOURCE']).resolve()
        revision = subprocess.check_output(['git','rev-parse','HEAD'], cwd=baseline, text=True).strip()
        self.assertEqual(revision, BASELINE)
        provider = MockServer()
        self.addCleanup(provider.close)
        provider.models = ['local-fixture']
        environment = {'LP_COMPAT_TOKEN':'t'*32, 'LP_COMPAT_CLOUD':'fixture-only'}
        for mode in ('local-only','local-first','balanced','cloud-first','cloud-only'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, environment):
                root = Path(temporary).resolve()
                work = root/'work'
                work.mkdir()
                primary = 'local' if mode in {'local-only','local-first','balanced'} else 'cloud'
                partner = 'cloud' if primary == 'local' else 'local'
                config = {'schema_version':1, 'port':0, 'data_dir':str(root/'data'),
                    'clients':[{'subject':'test','token_env':'LP_COMPAT_TOKEN',
                                'routes':{'local':'local','cloud':'cloud'}}],
                    'routes':{
                        'local':{'workspace':str(work),'engine':'v5','cache_stable_prefix':True,
                            'backend':{'kind':'local-openai','model':'local-fixture',
                                       'base_url':provider.base_url,'context_budget':32768}},
                        'cloud':{'workspace':str(work),'engine':'v5','cache_stable_prefix':True,
                            'backend':{'kind':'deepseek','model':'cloud-fixture',
                                       'api_key_env':'LP_COMPAT_CLOUD','agent_engine':'deepseek_optimized'}}}}
                config['routes'][primary].update(cloud_egress='CLOUD_ALLOWED', cooperation={
                    partner+'_route':partner, 'optimizer':{'mode':mode}})
                path = root/'service.json'
                path.write_text(json.dumps(config))
                path.chmod(0o600)
                process = subprocess.run([sys.executable,'-c',CHECKPOINT,str(path),primary],
                    cwd=baseline, env={**os.environ,'PYTHONPATH':str(baseline)},
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(process.returncode, 0, process.stderr)
                before = json.loads(process.stdout)
                server = build(path)
                try:
                    runtime = server.service.sessions[before['session_id']].runtime
                    self.assertEqual(runtime._persistence_config, before['payload']['configuration'])
                    self.assertEqual([m.to_dict(include_reasoning=True) for m in runtime.messages],
                                     before['payload']['runtime']['messages'])
                    system = next(m.content for m in runtime.messages if m.role == 'system')
                    runtime._refresh_prompt()
                    self.assertEqual(next(m.content for m in runtime.messages if m.role == 'system'), system)
                    requests = []
                    def transport(backend, messages, schemas, effort):
                        requests.append((messages, schemas))
                        return BackendResponse(Message('assistant','Restored fixture reply'),
                            {'prompt_tokens':10,'completion_tokens':4},'transport-fixture','stop')
                    runtime._request_once = transport
                    task = server.service.create_task(TaskRequest('Continue the restored conversation',
                        model=primary, session_id=before['session_id']), owner_subject='test')
                    result = server.service.wait(task['id'])
                    self.assertEqual(result['status'], 'completed', result)
                    messages, schemas = requests[0]
                    self.assertTrue(any(s['function']['name'] == 'shell' for s in schemas))
                    state = json.loads(messages[-1].content.split('\n',1)[1])
                    if sys.platform == 'linux':
                        self.assertEqual(state['host_shell']['platform'], 'linux')
                        self.assertEqual(state['host_shell']['scoped_backend'], 'bubblewrap')
                        self.assertEqual(state['host_shell']['permission_mode'], 'full-permission')
                        self.assertIn('Persisted macOS labels are historical', state['host_shell']['contract'])
                    else:
                        self.assertNotIn('host_shell', state)
                    self.assertFalse(any('"host_shell"' in (m.content or '') for m in runtime.messages))
                    self.assertEqual(next(m.content for m in runtime.messages if m.role == 'system'), system)
                    self.assertEqual(server.service.task_snapshot(before['task_id'])['status'], 'completed')
                finally:
                    server.service.suspend()
                    server.server_close()
                    server.access.close()
                config['routes'][primary]['capabilities'] = {'read':False}
                path.write_text(json.dumps(config))
                with self.assertRaisesRegex(PersistenceError, 'Persistent service restore refused') as refused:
                    build(path)
                self.assertIn('Host configuration changed', str(refused.exception.__cause__))

    @unittest.skipUnless(os.environ.get('LOCALPILOT_PR9_SOURCE'), 'NOT_RUN: requires pinned public PR9 source')
    def test_legacy_routes_and_desktop_contracts_keep_exact_configuration(self):
        baseline = Path(os.environ['LOCALPILOT_PR9_SOURCE']).resolve()
        revision = subprocess.check_output(['git','rev-parse','HEAD'], cwd=baseline, text=True).strip()
        self.assertEqual(revision, BASELINE)
        current = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            work = root/'work'
            work.mkdir()
            local = {'workspace':str(work), 'engine':'v5', 'cache_stable_prefix':True,
                     'backend':{'kind':'local-openai','model':'local-fixture',
                                'base_url':'http://127.0.0.1:9/v1','context_budget':32768}}
            cloud = {'workspace':str(work), 'engine':'v5', 'cache_stable_prefix':True,
                     'backend':{'kind':'deepseek','model':'cloud-fixture','api_key_env':'LP_COMPAT_CLOUD',
                                'agent_engine':'deepseek_optimized'}}
            environment = {**os.environ, 'LP_COMPAT_TOKEN':'t'*32, 'LP_COMPAT_CLOUD':'fixture-only'}
            for mode in ('local-only','local-first','balanced','cloud-first','cloud-only'):
                for desktop in (False, True):
                    with self.subTest(mode=mode, desktop=desktop):
                        config = {'schema_version':1,'port':0,'data_dir':str(root/'data'),
                                  'clients':[{'subject':'test','token_env':'LP_COMPAT_TOKEN',
                                              'routes':{'local':'local','cloud':'cloud'}}],
                                  'routes':{'local':json.loads(json.dumps(local)), 'cloud':json.loads(json.dumps(cloud))}}
                        primary = 'local' if mode in {'local-only','local-first','balanced'} else 'cloud'
                        partner = 'cloud' if primary == 'local' else 'local'
                        config['routes'][primary]['cooperation'] = {
                            partner+'_route':partner, 'optimizer':{'mode':mode}}
                        config['routes'][primary]['cloud_egress'] = 'CLOUD_ALLOWED'
                        path = root/'service.json'
                        path.write_text(json.dumps(config))
                        path.chmod(0o600)
                        def probe(source):
                            process = subprocess.run([sys.executable,'-c',PROBE,str(path),'desktop' if desktop else 'service'],
                                cwd=source, env={**environment, 'PYTHONPATH':str(source)},
                                capture_output=True, text=True, timeout=30)
                            self.assertEqual(process.returncode, 0, process.stderr)
                            return json.loads(process.stdout)
                        self.assertEqual(probe(current), probe(baseline))


if __name__ == '__main__':
    unittest.main()
