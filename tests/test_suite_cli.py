"""Public protocol and CLI safety over real HTTP/SQLite; scripted model only."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from localpilot_service import cli
from localpilot_service.protocol import check, manifest
import tests.test_agent_service as fixture


class SuiteCLITests(unittest.TestCase):
    setUp=fixture.AgentServiceTests.setUp
    tearDown=fixture.AgentServiceTests.tearDown
    start=fixture.AgentServiceTests.start
    stop=fixture.AgentServiceTests.stop
    factory=fixture.AgentServiceTests.factory
    done=fixture.AgentServiceTests.done
    denied=fixture.AgentServiceTests.denied

    def home(self):
        home=cli.private_dir(self.root/'cli')
        cli.save(home/'connection.json', {'url':self.url,'token_env':'TEST_CLI_TOKEN'})
        return home

    def test_cold_start_waits_beyond_thirty_seconds_without_a_second_process(self):
        from unittest.mock import Mock
        from urllib.error import URLError
        home=cli.private_dir(self.root/'cold-start')
        cli.save(home/'service.json',{'host':'127.0.0.1','port':0})
        cli.save(home/'connection.json',{'url':self.url,'token_env':'TEST_CLI_TOKEN'})
        clock=[0.0];process=Mock(pid=123);process.poll.return_value=None
        client=Mock()
        def health(_):
            if clock[0]<45:raise URLError('warming')
            return {'version':'fixture'}
        with patch.object(cli,'owned',return_value=None),patch.object(cli.subprocess,'Popen',return_value=process) as launch,patch.object(cli,'environment',return_value={}),patch.object(cli,'connection',return_value=client),patch.object(cli,'compatible',side_effect=health),patch.object(cli.time,'monotonic',side_effect=lambda:clock[0]),patch.object(cli.time,'sleep',side_effect=lambda n:clock.__setitem__(0,clock[0]+n)):
                result=cli.start(home,manager='detached')
        self.assertEqual(result['status'],'running');self.assertGreaterEqual(clock[0],45)
        self.assertEqual(launch.call_count,1);self.assertEqual(client.timeout,1)

    def test_every_openapi_operation_uses_a_declared_authentication_scheme(self):
        spec=json.loads((Path(cli.__file__).parent/'openapi.json').read_text())
        declared=set(spec['components']['securitySchemes'])
        for path,operations in spec['paths'].items():
            for operation in operations.values():
                if isinstance(operation,dict):
                    for requirement in operation.get('security',[]):self.assertLessEqual(set(requirement),declared,path)

    def test_contract_is_additive_and_rejects_missing_or_new_major(self):
        self.assertEqual(check(self.codex.request('/healthz')), 'compatible')
        self.assertEqual(check({'version':'4.9.1rc2'}), 'legacy_audited_4.9.1')
        for health in [{'version':'unknown'},{'compatibility':{**manifest(),'agent_service_api':'2.0'}},
                       {'compatibility':{**manifest(),'capabilities':[]}}]:
            with self.assertRaises(ValueError):check(health)
        self.assertEqual(self.backend.requests, [])

    def test_task_list_cannot_expose_another_subject(self):
        a=self.done(self.codex.submit('mine',idempotency_key='one'))
        b=self.dsh.submit('other',idempotency_key='two');self.service.wait(b['id'])
        self.assertEqual([t['id'] for t in self.codex.request('/localpilot/v1/tasks')['tasks']],[a['id']])
        self.assertEqual([t['id'] for t in self.operator.request('/localpilot/v1/tasks')['tasks']],[a['id']])

    def test_cli_json_show_and_reconnect_do_not_replay_submission(self):
        home=self.home();a=self.done(self.codex.submit('hello',idempotency_key='once'))
        with patch.dict(os.environ,TEST_CLI_TOKEN='c'*32):
            out=io.StringIO()
            with contextlib.redirect_stdout(out):
                rc=cli.main(['--home',str(home),'--json','task','show',a['id']])
            self.assertEqual(rc,0);self.assertEqual(json.loads(out.getvalue())['id'],a['id'])
            with contextlib.redirect_stdout(io.StringIO()) as first:
                cli.follow(self.codex,a['id'],home,json_output=True)
            with contextlib.redirect_stdout(io.StringIO()) as second:
                cli.follow(self.codex,a['id'],home,json_output=True)
            self.assertTrue(first.getvalue());self.assertEqual(second.getvalue(),'')
        self.assertEqual(len(self.backend.requests),1)

    def test_cli_ordinary_token_does_not_auto_approve(self):
        home=self.home()
        from tests.test_runtime_api import Backend,answer,call
        self.backend=Backend(answer(None,call('apply_patch',{'changes':[{'path':'never.txt','operation':'create','content':'x'}]},'w')))
        a=self.done(self.codex.submit('write',idempotency_key='approval'))
        with patch.dict(os.environ,TEST_CLI_TOKEN='c'*32), contextlib.redirect_stdout(io.StringIO()):
            rc=cli.main(['--home',str(home),'--json','task','approve',a['id'],'--action-id',a['required_action']['id'],'--operator-token-env','TEST_CLI_TOKEN'])
        self.assertEqual(rc,3);self.assertFalse((self.workspace/'never.txt').exists())

    def test_credentials_are_parsed_never_executed_and_not_printed(self):
        home=self.home();path=home/'clients.env'
        path.write_text('export TEST_CLI_TOKEN=$(touch unsafe)\n');path.chmod(0o600)
        with self.assertRaises(ValueError):cli.environment(home)
        self.assertFalse((home/'unsafe').exists())
        path.write_text('export TEST_CLI_TOKEN=secret_value\n')
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(['--home',str(home),'--json','config']),0)
        self.assertNotIn('secret_value',out.getvalue())

    def test_concurrent_lifecycle_lock_and_pid_identity_fail_closed(self):
        home=self.home()
        with cli.lock(home):
            with self.assertRaises(ValueError):
                with cli.lock(home):pass
        cli.save(home/'process.json',{'pid':os.getpid(),'created':0})
        with self.assertRaises(ValueError):cli.owned(home)

    def test_incompatible_service_rejects_before_context_submission(self):
        from localpilot_service import protocol
        home=self.home();args=cli.parser().parse_args(['agent','private question'])
        with patch.object(protocol,'manifest',return_value={**manifest(),'agent_service_api':'2.0'}):
            with self.assertRaises(ValueError):cli.submit(args,home,self.codex,args.text)
        self.assertEqual(self.backend.requests,[])

    def test_oversized_new_task_is_rejected_before_runtime_and_preserves_prior_receipts(self):
        first=self.done(self.codex.submit('first',idempotency_key='size-prior'))
        self.denied(413,lambda:self.codex.submit('验'*1500,idempotency_key='oversized'))
        self.assertEqual(len(self.service.tasks),1)
        self.assertEqual(len(self.backend.requests),1)
        self.assertEqual(self.codex.status(first['id'])['result'],first['result'])

    def test_managed_task_controller_survives_cli_return_and_retry_does_not_duplicate(self):
        import threading,time,psutil
        from contextlib import contextmanager
        from tests.test_runtime_api import StreamBackend
        class Manager:
            def __init__(self):self.seen=threading.Event();self.active=False
            @contextmanager
            def lease(self,*args,**kwargs):
                self.active=True
                try:yield
                finally:self.active=False
            def status(self):return {'status':'ready' if self.active else 'unloaded','model_process_alive':self.active,'active_leases':int(self.active),'release_after_task':True,'control_surface_required':True}
            def heartbeat(self,task,ticket):self.seen.set()
        home=self.home();manager=Manager();backend=StreamBackend();backend.manager=manager;self.backend=backend
        self.server.catalog['localpilot']={'adapter':'deepseek','deployment_status':'ready','prompt_profile':'standard','reasoning_only':False,'local_model_lifecycle':{'control_surface_required':True}}
        try:
            with patch.dict(os.environ,TEST_CLI_TOKEN='c'*32,DEEPSEEK_API_KEY='fake-provider-secret'),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['--home',str(home),'--json','agent','fixture','--key','controller','--detach']),0)
                self.assertTrue(manager.seen.wait(5),'detached CLI did not keep its public heartbeat alive')
                control=next(home.glob('control-*.json'));first=json.loads(control.read_text())
                self.assertNotIn('token',control.read_text().lower())
                self.assertEqual(cli.main(['--home',str(home),'--json','agent','fixture','--key','controller','--detach']),0)
                self.assertEqual(json.loads(control.read_text())['pid'],first['pid'])
                self.assertEqual(len(backend.requests),1)
                child=psutil.Process(first['pid']);self.assertNotIn('DEEPSEEK_API_KEY',child.environ())
                backend.release.set();self.service.wait(first['task_id'])
                child.wait(timeout=21)
                self.assertEqual(json.loads(control.read_text())['state'],'finished')
        finally:backend.release.set()

    def test_managed_init_generates_one_pool_shared_user_and_reference_only_credentials(self):
        from localpilot_service.configure import main as configure
        from localpilot_service import cached_omlx
        home=cli.private_dir(self.root/'managed-init');snapshot=self.root/'cached';snapshot.mkdir();(snapshot/'config.json').write_text('{}')
        with patch.object(cached_omlx,'SNAPSHOT',snapshot),contextlib.redirect_stdout(io.StringIO()):
            configure(['--workspace',str(self.workspace),'--directory',str(home),'--model',cached_omlx.MODEL,'--managed-qwen35','--cloud-key-file',str(self.root/'existing-provider.key')])
        config=json.loads((home/'service.json').read_text());clients={c['subject']:c for c in config['clients']}
        self.assertEqual(clients['local']['routes']['localpilot'],'companion-execution')
        managed_routes={'companion-execution','companion-reasoning'}
        self.assertEqual({c['subject'] for c in config['clients'] if not c.get('operator') and managed_routes.intersection(c['routes'].values())},{'local'})
        self.assertEqual(clients['resource']['scopes'],['read','resource_control'])
        self.assertEqual(config['routes']['default']['deployment_status'],'not_deployed')
        self.assertEqual(config['routes']['companion-execution']['managed_local_model'],config['routes']['companion-reasoning']['managed_local_model'])
        self.assertNotIn('api_key_env',config['routes']['companion-execution']['backend'])
        self.assertEqual(config['routes']['companion-cloud-reasoning']['cloud_egress'],'REQUIRES_APPROVAL')
        self.assertNotIn('sk-',(home/'clients.env').read_text())

    def test_doctor_checks_missing_model_and_credential_references_without_inference(self):
        from localpilot_service import cached_omlx
        home=self.home();cli.save(home/'service.json',{'routes':{'local':{'backend':{'key_file':str(self.root/'absent.key')},'managed_local_model':{'snapshot':str(self.root/'absent-model')}}}})
        with patch.dict(os.environ,TEST_CLI_TOKEN='c'*32),patch.object(cached_omlx,'BINARY',str(self.root/'absent-launcher')),contextlib.redirect_stdout(io.StringIO()) as out:
            code=cli.main(['--home',str(home),'--json','doctor'])
        self.assertEqual(code,2);result=json.loads(out.getvalue())
        self.assertEqual({x['code'] for x in result['configuration']['issues']},{'cached_model_files_missing','managed_model_launcher_missing','provider_key_reference_unreadable'})
        self.assertEqual(result['model_health'],'NOT_PROBED');self.assertEqual(self.backend.requests,[])
