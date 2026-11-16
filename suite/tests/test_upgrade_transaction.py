"""Real isolated venv/pip imports, local wheels and preserved user files."""
import json
from pathlib import Path
import shutil
import sys
import os
import plistlib
from unittest.mock import patch
import subprocess
import tempfile
import unittest
import venv
import zipfile

from localpilot_suite import upgrades
from localpilot_suite.channels import save


def wheel(directory, module, version, *, requires=(), broken=False, incomplete_channel=False, legacy_channels=False):
    name = upgrades.NAMES[module].replace('-', '_')
    path = directory / f'{name}-{version}-py3-none-any.whl'
    package = upgrades.IMPORTS[module]
    metadata = f'Metadata-Version: 2.1\nName: {upgrades.NAMES[module]}\nVersion: {version}\nRequires-Python: >=3.11\n'
    metadata += ''.join('Requires-Dist: '+value+'\n' for value in requires)
    files = {package+'/__init__.py':"raise RuntimeError('broken candidate import')\n" if broken else
             ('__version__' if module=='companion' else 'VERSION')+' = '+repr(version)+'\n',
             name+'-'+version+'.dist-info/METADATA':metadata,
             name+'-'+version+'.dist-info/WHEEL':'Wheel-Version: 1.0\nGenerator: local-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n'}
    if module=='core':files[package+'/protocol.py']="API_VERSION = '1.0'\n"
    if module=='core' and legacy_channels:
        files['localpilot_channels/__init__.py']='VERSION = '+repr('embedded-in-core-'+version)+'\n'
    if module=='channels':
        files[package+'/__main__.py']='import localpilot_channels\n'
        prefix=name+'-'+version+'.data/data/share/localpilot/channels/'
        for relative in ['qq-bridge/cli.mjs','qq-bridge/bridge.mjs','qq-bridge/gateway.mjs',
                         'wechat-ilink-bridge/cli.mjs','wechat-ilink-bridge/bridge.mjs',
                         'channel-common/security.mjs','channel-common/evidence.mjs']:
            if incomplete_channel and relative=='channel-common/security.mjs':continue
            files[prefix+relative]='// synthetic channel code '+version+'\n'
    record=name+'-'+version+'.dist-info/RECORD'
    files[record]=''.join(f'{name},,\n' for name in [*files,record])
    with zipfile.ZipFile(path,'w') as archive:
        for name,text in files.items():archive.writestr(name,text)
    return path


class UpgradeTransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=tempfile.TemporaryDirectory()
        cls.root=Path(cls.fixture.name)
        cls.artifacts=cls.root/'wheels';cls.artifacts.mkdir()
        cls.old=[wheel(cls.artifacts,'core','5.0.0b1'), wheel(cls.artifacts,'companion','0.5.6'),
                 wheel(cls.artifacts,'suite','0.2.0',requires=('localpilot-agent-service>=5.0.0b1,<6','localpilot-companion>=0.5.6,<0.6')), wheel(cls.artifacts,'channels','0.1.0a3')]
        cls.new=[wheel(cls.artifacts,'core','5.0.0b2'), wheel(cls.artifacts,'companion','0.5.7'),
                 wheel(cls.artifacts,'suite','0.2.1',requires=('localpilot-agent-service>=5.0.0b1,<6','localpilot-companion>=0.5.7,<0.6')), wheel(cls.artifacts,'channels','0.1.0a4')]
        cls.base=cls.root/'base'
        venv.EnvBuilder(with_pip=True).create(cls.base)
        subprocess.run([str(cls.base/'bin/python'),'-I','-m','pip','install','--no-index','--no-deps',*map(str,cls.old)],
                       check=True,capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.home=self.folder/'home';self.home.mkdir(mode=0o700)
        self.runtime=self.folder/'runtime';shutil.copytree(self.base,self.runtime,symlinks=True)
        self.python=str(self.runtime/'bin/python')
        self.data=self.home/'history.sqlite3';self.data.write_bytes(b'preserved history and UNKNOWN receipts')
        self.credentials=self.home/'clients.env';self.credentials.write_text('synthetic test token');self.credentials.chmod(0o600)

    def plan(self, targets=None):
        return upgrades.plan(self.home,targets or self.new,self.old,python=self.python)

    def assert_preserved(self):
        self.assertEqual(self.data.read_bytes(),b'preserved history and UNKNOWN receipts')
        self.assertEqual(self.credentials.read_text(),'synthetic test token')

    def test_combined_plan_install_and_explicit_reverse_rollback(self):
        plan=self.plan()
        self.assertEqual([row['module'] for row in plan['components']],['core','companion','suite','channels'])
        self.assertEqual(plan['status'],'plan_only')
        result=upgrades.execute(self.home,plan['id'],fingerprint=plan['fingerprint'])
        self.assertEqual(result['status'],'completed')
        self.assertEqual(upgrades.execute(self.home,plan['id']),result)
        observed=upgrades._runtime(self.python,self.home)
        self.assertEqual(observed['versions']['localpilot-suite'],'0.2.1')
        restored=upgrades.execute(self.home,plan['id'],rollback=True)
        self.assertEqual(restored['status'],'rolled_back')
        self.assertEqual([row['module'] for row in restored['rollback_steps']],['suite','companion','core','channels'])
        self.assertEqual(upgrades._runtime(self.python,self.home)['versions']['localpilot-suite'],'0.2.0')
        self.assertEqual(upgrades.history(self.home)['upgrades'][0]['receipt'],restored)
        self.assert_preserved()

    def test_successful_pip_but_failed_import_rolls_back_all_changed_components(self):
        folder=self.folder/'broken';folder.mkdir()
        broken=wheel(folder,'core','5.0.0b3',broken=True)
        plan=self.plan([broken,*self.new[1:]])
        result=upgrades.execute(self.home,plan['id'])
        self.assertEqual(result['status'],'failed_rolled_back')
        self.assertTrue(all(row['exit']==0 for row in result['steps']))
        self.assertIn('verification failed',result['failure'])
        observed=upgrades._runtime(self.python,self.home)
        self.assertEqual(observed['versions']['localpilot-agent-service'],'5.0.0b1')
        self.assertEqual(observed['versions']['localpilot-companion'],'0.5.6')
        self.assertEqual(observed['versions']['localpilot-suite'],'0.2.0')
        self.assert_preserved()

    def test_incompatible_combination_and_wrong_rollback_are_rejected_before_install(self):
        folder=self.folder/'incompatible';folder.mkdir()
        invalid=wheel(folder,'suite','0.2.2',requires=('localpilot-agent-service>=6',))
        with self.assertRaisesRegex(ValueError,'Incompatible component set'):
            self.plan([*self.new[:2],invalid,self.new[3]])
        with self.assertRaisesRegex(ValueError,'installed version'):
            upgrades.plan(self.home,self.new,self.new,python=self.python)
        self.assertFalse((self.home/'upgrades').exists())
        self.assert_preserved()

    def test_reviewed_copies_are_independent_and_detect_tampering(self):
        plan=self.plan()
        artifact=Path(plan['components'][0]['target']['path'])
        self.assertNotEqual(str(artifact),str(self.new[0]))
        artifact.write_bytes(artifact.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'changed after review'):
            upgrades.execute(self.home,plan['id'])
        self.assertFalse((self.home/'upgrades'/plan['id']/'receipt.json').exists())
        self.assert_preserved()

    def test_changed_installed_version_invalidates_old_plan(self):
        plan=self.plan()
        subprocess.run([self.python,'-I','-m','pip','install','--no-index','--no-deps','--force-reinstall',str(self.new[0])],
                       check=True,capture_output=True)
        with self.assertRaisesRegex(ValueError,'changed after review'):
            upgrades.execute(self.home,plan['id'])
        self.assert_preserved()

    def test_old_upgrade_receipt_cannot_overwrite_a_later_component_version(self):
        plan=self.plan()
        self.assertEqual(upgrades.execute(self.home,plan['id'])['status'],'completed')
        folder=self.folder/'later';folder.mkdir()
        later=wheel(folder,'core','5.0.0b9')
        subprocess.run([self.python,'-I','-m','pip','install','--no-index','--no-deps','--force-reinstall',str(later)],check=True,capture_output=True)
        with self.assertRaisesRegex(ValueError,'changed since this upgrade'):
            upgrades.execute(self.home,plan['id'],rollback=True)
        self.assertEqual(upgrades._runtime(self.python,self.home)['versions']['localpilot-agent-service'],'5.0.0b9')
        self.assert_preserved()

    def test_departed_gui_with_changed_installation_leaves_a_handoff_failure_receipt(self):
        import psutil
        plan=self.plan()
        source=self.folder/'candidate/LocalPilot Test.app'
        (source/'Contents').mkdir(parents=True)
        (source/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'io.localpilot.desktop.test','CFBundleShortVersionString':'fixture'}))
        with patch.object(upgrades.app_install.subprocess,'run',return_value=subprocess.CompletedProcess([],0)):
            plan['desktop']=upgrades.app_install.make_plan(source,test_app=True,home=self.folder/'app-home')
        plan['fingerprint']=upgrades._fingerprint(plan)
        save(self.home/'upgrades'/plan['id']/'plan.json',plan)
        subprocess.run([self.python,'-I','-m','pip','install','--no-index','--no-deps','--force-reinstall',str(self.new[0])],check=True,capture_output=True)
        departed=subprocess.Popen([self.python,'-c','pass'])
        created=psutil.Process(departed.pid).create_time()
        departed.wait()
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        result=subprocess.run([sys.executable,'-m','localpilot_suite.upgrades','--home',str(self.home),
            '--plan',plan['id'],'--fingerprint',plan['fingerprint'],'--wait-pid',str(departed.pid),
            '--wait-created',str(created)],env=env,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        failure=json.loads((self.home/'upgrades'/plan['id']/'handoff-error.json').read_text())
        self.assertEqual(failure['status'],'handoff_failed')
        self.assertIn('changed after review',failure['error'])
        self.assertEqual(upgrades.history(self.home)['upgrades'][0]['handoff_error'],failure)
        self.assert_preserved()

    def test_legacy_core_requires_channels_artifacts_and_restores_them_after_core(self):
        folder=self.folder/'legacy';folder.mkdir()
        legacy=wheel(folder,'core','5.0.0b1',legacy_channels=True)
        for artifact in (legacy,self.old[3]):
            subprocess.run([self.python,'-I','-m','pip','install','--no-index','--no-deps','--force-reinstall',str(artifact)],check=True,capture_output=True)
        with self.assertRaisesRegex(ValueError,'Legacy Core wheel also owns Channels'):
            upgrades.plan(self.home,[self.new[0]],[legacy],python=self.python)
        plan=upgrades.plan(self.home,self.new,[legacy,*self.old[1:]],python=self.python)
        self.assertTrue(plan['legacy_core_channel_overlap'])
        self.assertEqual(upgrades.execute(self.home,plan['id'])['status'],'completed')
        restored=upgrades.execute(self.home,plan['id'],rollback=True)
        self.assertEqual(restored['status'],'rolled_back')
        self.assertEqual(restored['rollback_steps'][-1]['module'],'channels')
        result=subprocess.run([self.python,'-c','import localpilot_channels;print(localpilot_channels.VERSION)'],capture_output=True,text=True,check=True,cwd=self.home)
        self.assertEqual(result.stdout.strip(),'0.1.0a3')
        self.assert_preserved()

    def test_failed_legacy_core_step_restores_channels_even_before_channels_install_is_attempted(self):
        folder=self.folder/'legacy-early';folder.mkdir()
        legacy=wheel(folder,'core','5.0.0b1',legacy_channels=True)
        for artifact in (legacy,self.old[3]):
            subprocess.run([self.python,'-I','-m','pip','install','--no-index','--no-deps','--force-reinstall',str(artifact)],check=True,capture_output=True)
        invalid=wheel(folder,'core','5.0.0b8')
        with zipfile.ZipFile(invalid,'a') as archive:
            archive.writestr('localpilot_agent_service-5.0.0b8.data/unsupported-scheme/file.txt','forces a real pip install rejection')
        plan=upgrades.plan(self.home,[invalid,*self.new[1:]],[legacy,*self.old[1:]],python=self.python)
        result=upgrades.execute(self.home,plan['id'])
        self.assertEqual(result['status'],'failed_rolled_back')
        self.assertEqual(result['attempted'],['core'])
        self.assertEqual([row['module'] for row in result['rollback_steps']],['core','channels'])
        observed=subprocess.run([self.python,'-c','import localpilot_channels;print(localpilot_channels.VERSION)'],capture_output=True,text=True,check=True,cwd=self.home)
        self.assertEqual(observed.stdout.strip(),'0.1.0a3')
        self.assert_preserved()

    def installed_channel(self):
        from localpilot_suite import channels,channel_product
        hub,state=channel_product.roots(self.home,'qq',create=True)
        root=channel_product.runtime_root(hub,{})
        channels.private_directory(root.parent,create=True)
        channels.main(['install','--wheel',str(self.old[3])],root.parent)
        channels.private_directory(state,create=True)
        channels.save(state/'state.json',{'messages':{'observed':{'status':'unknown','delivery':'unknown'}},'blocked':{'observed':True}})
        return root,state

    def test_channels_runtime_participates_in_combined_upgrade_and_rollback(self):
        from localpilot_suite import channels,channel_product
        root,state=self.installed_channel()
        prior=(root/'installation.json').read_bytes()
        messages=(state/'state.json').read_bytes()
        plan=self.plan()
        self.assertEqual(plan['channels']['runtimes'][0]['version'],'0.1.0a3')
        result=upgrades.execute(self.home,plan['id'])
        self.assertEqual(result['status'],'completed')
        self.assertTrue(channel_product.component_compatible(root,self.home))
        self.assertEqual(channels.private_json(root/'installation.json')['version'],'0.1.0a4')
        restored=upgrades.execute(self.home,plan['id'],rollback=True)
        self.assertEqual(restored['status'],'rolled_back')
        self.assertEqual((root/'installation.json').read_bytes(),prior)
        self.assertEqual((state/'state.json').read_bytes(),messages)
        self.assertTrue(channels.installed(root))
        self.assertFalse((self.home/'channels-wheel.json').exists())
        self.assert_preserved()

    def test_incomplete_channel_assets_restore_previous_runtime_and_all_component_wheels(self):
        from localpilot_suite import channels
        root,state=self.installed_channel()
        prior=(root/'installation.json').read_bytes()
        messages=(state/'state.json').read_bytes()
        folder=self.folder/'incomplete-channel';folder.mkdir()
        incomplete=wheel(folder,'channels','0.1.0a5',incomplete_channel=True)
        plan=self.plan([*self.new[:3],incomplete])
        result=upgrades.execute(self.home,plan['id'])
        self.assertEqual(result['status'],'failed_rolled_back')
        self.assertIn('CHANNEL_BRIDGE_MODULE_MISSING',result['failure'])
        self.assertEqual((root/'installation.json').read_bytes(),prior)
        self.assertEqual((state/'state.json').read_bytes(),messages)
        self.assertTrue(channels.installed(root))
        self.assertEqual(upgrades._runtime(self.python,self.home)['versions']['localpilot-channels'],'0.1.0a3')
        self.assert_preserved()

    def test_running_owned_process_blocks_without_terminating_it(self):
        import psutil
        process=subprocess.Popen([self.python,'-c','import time;time.sleep(30)'])
        self.addCleanup(lambda:process.wait() if process.poll() is not None else (process.terminate(),process.wait()))
        save(self.home/'process.json',{'pid':process.pid,'created':psutil.Process(process.pid).create_time()})
        plan=self.plan()
        self.assertEqual(plan['blocking_services'],['Core'])
        with self.assertRaisesRegex(ValueError,'Stop these services'):
            upgrades.execute(self.home,plan['id'])
        self.assertIsNone(process.poll())
        self.assert_preserved()


if __name__=='__main__':unittest.main()
