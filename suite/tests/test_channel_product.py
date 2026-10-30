"""Desktop controls: real private files, scripted process/platform observations."""
import hashlib
import json
import tempfile
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
from localpilot_suite import channels, channel_product as gui

class ChannelProductTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home'
        self.home.mkdir(mode=0o700)
    def call(self, action, args=None, kind='qq'):
        return gui.command(self.home, kind, action, args or {})
    def test_initial_inspection_never_installs_starts_or_creates_channel_state(self):
        with patch.object(channels, 'launch') as launch, patch.object(gui.channel_runtime, 'install') as install:
            for kind in ('qq', 'wechat'):
                result = self.call('status', kind=kind)
                self.assertEqual(result['status'], 'not_installed')
                self.assertFalse(result['connected'])
            launch.assert_not_called(); install.assert_not_called()
        self.assertFalse((self.home / 'message-platforms').exists())
    @unittest.skipUnless(sys.platform=='darwin','macOS fixed system alias')
    def test_private_channel_state_under_system_tmp_preserves_owner_only_files(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            home=Path(directory)/'product';home.mkdir(mode=0o700)
            gui.command(home,'qq','skip',{})
            state=home/'message-platforms/qq/settings.json'
            self.assertEqual(gui.private_json(state),{'skipped':True})
            self.assertEqual(state.stat().st_mode&0o777,0o600)
            self.assertEqual(state.parent.stat().st_mode&0o777,0o700)
    def test_exact_request_refuses_path_shell_url_and_implicit_confirmation(self):
        for action, args in [('install', {}), ('install', {'confirmed':False}), ('status', {'path':'/tmp'}), ('exec', {'command':'sh'}), ('login', {'confirmed':True,'url':'https://evil.test'})]:
            with self.assertRaises(ValueError): self.call(action, args)
        with self.assertRaises(ValueError): self.call('status',kind='../qq')
    def test_native_qq_secret_is_private_and_never_returned(self):
        result = self.call('qq_credentials', {'app_id':'123456','app_secret':'fixture-secret-12345','confirmed':True})
        self.assertNotIn('fixture-secret', json.dumps(result))
        path = self.home / 'message-platforms/qq/credentials.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertFalse(result['connected'])
    def test_skipping_platforms_has_separate_persistent_flags(self):
        sentinel = self.home / 'model.txt'; sentinel.write_text('keep')
        self.call('skip')
        self.assertTrue(self.call('status')['skipped'])
        self.assertNotIn('skipped',self.call('status',kind='wechat'))
        self.assertEqual(sentinel.read_text(),'keep')
    def test_qq_cannot_gain_operator_capability(self):
        with self.assertRaises(ValueError):
            self.call('operator', {'senders':[],'enabled':True,'confirmed':True})
    def test_corrupt_or_linked_state_fails_closed(self):
        hub,state = gui.roots(self.home,'qq',True)
        state.mkdir(parents=True,mode=0o700)
        (state/'state.json').symlink_to(self.home/'missing')
        with self.assertRaises(ValueError): self.call('status')
    def test_unknown_blocks_reconnect_without_mutating_state(self):
        hub,state = gui.roots(self.home,'qq',True)
        state.mkdir(parents=True,mode=0o700)
        channels.save(state/'state.json',{'messages':{'m':{'status':'unknown','delivery':'unknown'}},'blocked':{}})
        before=(state/'state.json').read_bytes()
        with patch.object(gui,'install_component',return_value=Path('/verified/node')),patch.object(channels,'launch') as launch:
            with self.assertRaisesRegex(ValueError,'UNKNOWN'):
                self.call('discover',{'confirmed':True})
            launch.assert_not_called()
        self.assertEqual(before,(state/'state.json').read_bytes())
        self.assertEqual(self.call('status')['status'],'UNKNOWN')
    def test_read_only_discovery_bridge_never_gets_core_or_operator_tokens(self):
        hub,state = gui.roots(self.home,'qq',True)
        channels.save(hub/'credentials.json', {'LP_CHANNEL_INGRESS':'x'*32,'QQ_BOT_APP_ID':'12345','QQ_BOT_APP_SECRET':'private-secret','LOCALPILOT_OPERATOR_TOKEN':'never-forward'})
        env=gui.bridge_env(hub,'qq',state)
        self.assertNotIn('LOCALPILOT_OPERATOR_TOKEN',env)
        self.assertEqual(env['LOCALPILOT_QQ_SENDERS'],'[]')
        self.assertEqual(env['LOCALPILOT_QQ_STATE_DIR'],str(state))
    def prepare_binding(self,kind='qq'):
        hub,state=gui.roots(self.home,kind,True)
        state.mkdir(parents=True,mode=0o700)
        sender=('q_' if kind=='qq' else 's_')+'a'*64
        channels.save(state/'state.json',{'peers':[sender],'messages':{},'blocked':{},'account':{'botId':'fixture-bot'}})
        channels.save(hub/'credentials.json',{'QQ_BOT_APP_ID':'12345','LP_CHANNEL_INGRESS':'x'*32})
        root=gui.runtime_root(hub,{})
        gui.private_directory(root,create=True)
        config={'routes':{'local':{'workspace':'/unused','engine':'v5','backend':{'kind':'local-openai','model':'fixture'},'plugins':{'home':'/unsafe'},'computer_use':{},'cooperation':{},'verification':{'id':'not-inherited'}}},'clients':[{'subject':'operator','operator':True,'token_env':'LOCALPILOT_OPERATOR_TOKEN','approval_for':[]}]}
        channels.save(self.home/'service.json',config)
        channels.save(self.home/'connection.json',{'url':'http://127.0.0.1:8765'})
        gui.replace_env(self.home/'clients.env','export LOCALPILOT_OPERATOR_TOKEN='+'o'*32+'\n')
        return hub,state,sender
    def test_binding_uses_exact_bridge_channel_hash_and_host_permissions(self):
        hub,state,sender=self.prepare_binding()
        configs=[]
        with patch.object(gui,'change_core',side_effect=lambda home,hub,cfg,env,**kwargs:configs.append(cfg)),patch.object(channels,'main',return_value={'status':'stopped'}):
            result=self.call('configure',{'senders':[sender],'model':'local','allow_write':False,'confirmed':True})
        self.assertFalse(result['connected'])
        cfg=configs[0]; route=next(v for k,v in cfg['routes'].items() if k.startswith('channel-'))
        self.assertEqual(route['capabilities'],{'read':True,'write':False,'execute':False})
        self.assertEqual(route['cloud_egress'],'LOCAL_ONLY')
        for key in ('plugins','computer_use','cooperation','verification'):self.assertNotIn(key,route)
        principal=cfg['clients'][-1]
        self.assertIs(principal['operator'],False);self.assertNotIn('control',principal['scopes'])
        adapter=channels.configured(gui.runtime_root(hub,gui.settings(hub)))['adapter']
        expected='qq.'+hashlib.sha256(json.dumps('12345').encode()).hexdigest()[:24]
        self.assertEqual(adapter['channels'][0]['channel'],expected)
    def test_wechat_operator_is_separate_scoped_identity(self):
        hub,state,sender=self.prepare_binding('wechat')
        self.call('operator',{'senders':[sender],'enabled':True,'confirmed':True},kind='wechat')
        configs=[]
        with patch.object(gui,'change_core',side_effect=lambda home,hub,cfg,env,**kwargs:configs.append(cfg)),patch.object(channels,'main',return_value={'status':'stopped'}):
            self.call('configure',{'senders':[sender],'model':'local','allow_write':True,'confirmed':True},kind='wechat')
        ordinary,operator=configs[0]['clients'][-2:]
        self.assertFalse(ordinary['operator']);self.assertTrue(operator['operator'])
        self.assertEqual(operator['approval_for'],[ordinary['subject']])
        self.assertEqual(operator['routes'],{})
        self.assertNotEqual(ordinary['token_env'],operator['token_env'])
    def test_exit_default_stops_only_recorded_channel_services(self):
        hub,state=gui.roots(self.home,'qq',True);gui.private_directory(gui.runtime_root(hub,{}),create=True)
        with patch.object(channels,'main',return_value={'status':'stopped'}) as main:
            self.call('exit')
            self.assertEqual([c.args[0] for c in main.call_args_list],[['stop','qq'],['stop','adapter']])
        self.call('background',{'enabled':True,'confirmed':True})
        with patch.object(channels,'main') as main:
            self.assertEqual(self.call('exit')['status'],'kept_running_by_preference');main.assert_not_called()
    def test_workspace_must_be_native_selected_outside_private_state(self):
        folder=self.home.parent/'authorized-files';folder.mkdir(mode=0o700)
        result=self.call('workspace',{'path':str(folder),'confirmed':True})
        self.assertEqual(result['label'],'authorized-files');self.assertFalse(result['active'])
        hub,_=gui.roots(self.home,'qq')
        self.assertEqual(gui.settings(hub)['workspace'],str(folder.resolve()))
        for bad in [self.home,self.home.parent]:
            with self.assertRaisesRegex(ValueError,'OVERLAPS_PRIVATE_STATE'):
                self.call('workspace',{'path':str(bad),'confirmed':True})
    def test_corrupt_generation_cannot_escape_channel_home(self):
        hub,_=gui.roots(self.home,'qq',True)
        channels.save(hub/'settings.json',{'generation':'/tmp/outside'})
        with self.assertRaisesRegex(ValueError,'GENERATION_INVALID'):self.call('status')
    def test_carry_transport_keeps_tombstones_and_unknown_without_replaying(self):
        sender='q_'+'a'*64;mid='q_m_'+'b'*64
        data={'version':1,'appId':'12345','peers':[sender],'blocked':{},'messages':{mid:{'sender':sender,'status':'unknown','delivery':'unknown'}}}
        carried=gui.carry_transport(data,'qq')
        self.assertEqual(carried['retired'],{mid:True});self.assertEqual(carried['messages'],{})
        self.assertEqual(carried['blocked'],{sender:True});self.assertEqual(data['messages'][mid]['status'],'unknown')
    def test_account_change_cannot_clear_unknown_or_replace_credentials(self):
        hub,state=gui.roots(self.home,'qq',True)
        gui.private_directory(state,create=True)
        sender='q_'+'a'*64;mid='q_m_'+'b'*64
        channels.save(state/'state.json',{'version':1,'appId':'12345','peers':[sender],'blocked':{},'messages':{mid:{'sender':sender,'status':'unknown','delivery':'unknown'}}})
        channels.save(hub/'credentials.json',{'QQ_BOT_APP_ID':'12345','QQ_BOT_APP_SECRET':'original-fixture'})
        before=(state/'state.json').read_bytes();credentials=(hub/'credentials.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'UNKNOWN'):
            self.call('qq_credentials',{'app_id':'54321','app_secret':'new-fixture-secret','confirmed':True})
        self.assertEqual((state/'state.json').read_bytes(),before)
        self.assertEqual((hub/'credentials.json').read_bytes(),credentials)
    def test_explicit_fresh_connection_keeps_original_uncertain_generation(self):
        hub,state=gui.roots(self.home,'qq',True);gui.private_directory(state,create=True)
        sender='q_'+'a'*64;mid='q_m_'+'b'*64
        channels.save(state/'state.json',{'version':1,'appId':'12345','peers':[sender],'blocked':{},'messages':{mid:{'sender':sender,'status':'unknown','delivery':'unknown'}}})
        before=(state/'state.json').read_bytes()
        with patch.object(gui,'require_quiet',return_value=[]):self.call('fresh',{'confirmed':True})
        self.assertEqual((state/'state.json').read_bytes(),before)
        _,current=gui.roots(self.home,'qq');self.assertNotEqual(state,current)
        self.assertEqual(gui.state_info(current)['retired'],{mid:True})
        self.assertEqual(gui.state_info(current)['messages'],{})
    def test_copied_process_record_cannot_signal_original_root(self):
        root=self.home/'channels';root.mkdir(mode=0o700)
        channels.save(root/'qq.process.json',{'pid':9999,'created':1.0,'executable':'/node','argv':['/node','/different/channels/runtime/share/localpilot/channels/qq-bridge/cli.mjs','run']})
        with patch('psutil.Process') as process:
            with self.assertRaisesRegex(ValueError,'NOT_OWNED'):channels.process(root,'qq')
            process.assert_not_called()
    def test_explicit_cloud_binding_keeps_task_approval_and_no_file_egress(self):
        hub,state,sender=self.prepare_binding()
        config=gui.private_json(self.home/'service.json');config['routes']['cloud']={'backend':{'kind':'deepseek-native','model':'fixture-cloud','key_file':'/not-read'},'workspace':'/unused'}
        channels.save(self.home/'service.json',config)
        args={'senders':[sender],'model':'cloud','allow_write':False,'confirmed':True}
        with patch.object(channels,'main',return_value={'status':'stopped'}),patch.object(gui,'change_core') as change:
            with self.assertRaisesRegex(ValueError,'CLOUD_REQUIRES'):self.call('configure',args)
            change.assert_not_called()
            self.call('configure',{**args,'allow_cloud':True})
            route=next(v for k,v in change.call_args.args[2]['routes'].items() if k.startswith('channel-'))
            self.assertEqual(route['cloud_egress'],'REQUIRES_APPROVAL');self.assertEqual(route['cloud_egress_paths'],[])
    def test_disconnect_rotates_to_read_only_and_keeps_host_history_scope(self):
        hub,state_dir,sender=self.prepare_binding()
        captures=[]
        def changed(home,hub,config,env,**kwargs):
            channels.save(home/'service.json',config);captures.append((config,env))
        with patch.object(gui,'change_core',side_effect=changed),patch.object(channels,'main',return_value={'status':'stopped'}):
            self.call('configure',{'senders':[sender],'model':'local','allow_write':False,'confirmed':True})
            bound=gui.settings(hub);subject=bound['subjects'][0]
            old_token=gui.credentials(hub)[next(p['token_env'] for p in captures[-1][0]['clients'] if p['subject']==subject)]
            self.call('disconnect',{'confirmed':True})
        config,environment=captures[-1]
        retired=next(p for p in config['clients'] if p['subject']==subject)
        self.assertEqual(retired['scopes'],['read']);self.assertFalse(retired['operator']);self.assertEqual(retired['routes'],{})
        op=next(p for p in config['clients'] if p['subject']=='operator');self.assertIn(subject,op['approval_for'])
        values=dict(line.removeprefix('export ').split('=',1) for line in environment.splitlines())
        self.assertNotEqual(values[retired['token_env']],old_token)
        current=gui.settings(hub);self.assertFalse(current['binding']);self.assertTrue(current['history'])
        self.assertTrue((hub/'history'/(current['history'][0]['generation']+'.json')).exists())
    def test_changed_core_since_preview_is_not_stopped_or_overwritten(self):
        hub,_,_=self.prepare_binding();before=(self.home/'service.json').read_bytes()
        with patch.object(gui,'require_quiet',return_value=[]),patch('localpilot_service.cli.stop') as stop:
            with self.assertRaisesRegex(ValueError,'CORE_CHANGED_SINCE_PREVIEW'):
                gui.change_core(self.home,hub,{},gui.read_env(self.home),expected_before={'changed':True})
            stop.assert_not_called()
        self.assertEqual((self.home/'service.json').read_bytes(),before)
    def test_partial_python_directory_is_not_an_installed_channel(self):
        root=self.home/'channels';(root/'runtime/bin').mkdir(parents=True,mode=0o700)
        (root/'runtime/bin/python').write_text('incomplete')
        self.assertFalse(channels.installed(root))
    def test_managed_channel_code_change_fails_integrity_before_start(self):
        root=self.home/'channels';(root/'runtime').mkdir(parents=True,mode=0o700)
        launcher=root/'runtime/launch.py';launcher.write_text('changed');launcher.chmod(0o600)
        channels.save(root/'installation.json',{'runtime':'suite_python_isolated_site','files':{'launch.py':'0'*64}})
        with self.assertRaisesRegex(ValueError,'INTEGRITY'):channels.installed(root)

if __name__=='__main__':unittest.main()
