"""Compare actual old/new host factories; never replace a persisted fingerprint."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


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


class PR9CompatibilityTests(unittest.TestCase):
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
