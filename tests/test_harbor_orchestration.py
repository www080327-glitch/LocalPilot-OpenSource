"""Product children over real HTTP and filesystem protocol fixtures, not model scores."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from scripts.harbor_budget_audit import audit_budget_log, comparison_configuration
from scripts.harbor_orchestration import arm_orchestration, orchestration_contract
from scripts.public_agent_eval import freeze, read_study
from tests import test_public_agent_eval as study_fixtures
from tests.test_local_http_backend import completion, tool_call


class OrchestrationConfigurationTests(unittest.TestCase):
    def test_default_remains_single_and_opt_in_requires_shared_local_budget(self):
        self.assertEqual(orchestration_contract({})['max_children'], 0)
        for options in ({'orchestration':'unknown'}, {'orchestration':{}}, {'max_children':2},
                        {'orchestration':'multi-agent'},
                        {'orchestration':'multi-agent','model_budget':{},'provider_kind':'remote-openai'},
                        {'orchestration':'multi-agent','model_budget':{},'max_children':True},
                        {'orchestration':'multi-agent','model_budget':{},'max_worker_steps':False},
                        {'orchestration':'multi-agent','model_budget':{},'max_output_tokens':256,'max_worker_output_tokens':512},
                        {'orchestration':'multi-agent','model_budget':{},'max_children':1,'max_running_children':2}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                orchestration_contract(options)
        contract = orchestration_contract({'orchestration':'multi-agent','model_budget':{}})
        self.assertEqual((contract['max_children'],contract['max_running_children'],contract['model_slots']), (4,2,1))
        bounded = orchestration_contract({'orchestration':'multi-agent','model_budget':{},'max_output_tokens':256})
        self.assertEqual(bounded['worker_budgets']['max_worker_output_tokens'],256)

    def test_reference_cannot_silently_ignore_candidate_worker_options(self):
        with self.assertRaises(ValueError):
            arm_orchestration({'import_path':'scripts.harbor_reference:BudgetedTerminusAgent',
                               'kwargs':{'orchestration':'multi-agent'}})

    def test_new_study_freezes_execution_contract_without_changing_old_study(self):
        fixture = study_fixtures.PublicAgentEvaluationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        original = (fixture.study_dir/'study.json').read_bytes()
        candidate = fixture.spec['arms'][0]['agent']
        candidate.pop('name')
        candidate.update(import_path='scripts.localpilot_harbor:LocalPilotHarborAgent', kwargs={
            'orchestration':'multi-agent','model_budget':{},'max_children':2,'max_running_children':2})
        fixture.spec_path.write_text(json.dumps(fixture.spec))
        directory = fixture.root/'separate-study'
        study = freeze(fixture.spec_path,fixture.repository,directory)
        self.assertEqual(study['orchestration_contracts']['localpilot']['max_children'],2)
        self.assertEqual(read_study(directory),study)
        self.assertEqual((fixture.study_dir/'study.json').read_bytes(),original)
        self.assertNotIn('orchestration_contracts',read_study(fixture.study_dir))
        job = study['jobs'][0]
        config = directory/'configs'/(job['name']+'.json')
        value = json.loads(config.read_text())
        value['agents'][0]['kwargs']['max_children'] = 3
        config.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'configuration changed'):
            read_study(directory)


@unittest.skipUnless(importlib.util.find_spec('harbor'), 'Pinned Harbor evaluation environment required')
class HarborChildContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.work = self.root/'environment-fixture'
        self.work.mkdir()
        (self.root/'tokenizer_config.json').write_text('{"fixture":true}')
        self.counter_script = self.root/'counter.py'
        self.counter_script.write_text('import json,sys\nfor line in sys.stdin:\n json.loads(line)\n print(json.dumps({"input_tokens":7}),flush=True)\n')
        self.calls, self.commands, self.backends = [], [], []
        self.wait_for_both = True
        self.no_delegation = False
        self.shell_started = 0
        self.shell_steps = 1
        self.both = asyncio.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def send_json(self, body):
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self.send_json({'data':[{'id':'fixture'}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                outer.calls.append(body)
                task = next(row['content'] for row in body['messages'] if row['role']=='user')
                results = [row for row in body['messages'] if row['role']=='tool']
                if outer.no_delegation:
                    response = completion('Direct answer; no delegation needed.')
                elif task.startswith('child-'):
                    name = task.removeprefix('child-')
                    commands = [f'printf {name} > {name}.txt',f'printf -- -step2 >> {name}.txt',f'cat {name}.txt']
                    response = completion('created '+name) if len(results) >= outer.shell_steps else completion(calls=[
                        tool_call('shell',{'command':commands[len(results)]},f'step-{name}-{len(results)+1}')])
                elif not results:
                    response = completion(calls=[tool_call('delegate',{
                        'task':'child-'+name,'backend_preference':'local','read_only':False,'mode':'async'},'child-'+name)
                        for name in ('left','right')])
                elif not any(row.get('tool_call_id')=='join' for row in results):
                    response = completion(calls=[tool_call('wait_children',{},'join')])
                else:
                    response = completion('Both worker observations collected.')
                response.update(model='fixture',usage={'prompt_tokens':7,'completion_tokens':2})
                self.send_json(response)

        self.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    async def asyncTearDown(self):
        for backend in self.backends:
            backend.close_counter()
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()
        self.thread.join(2)
        self.tmp.cleanup()

    async def exec(self, **arguments):
        from harbor.environments.base import ExecResult
        self.commands.append(arguments)
        if arguments['command']=='pwd':
            return ExecResult(return_code=0,stdout='/task\n',stderr='')
        self.assertEqual(arguments['cwd'],'/task')
        self.shell_started += 1
        if self.shell_started == 2:
            self.both.set()
        if self.wait_for_both:
            await asyncio.wait_for(self.both.wait(),5)
        process = await asyncio.create_subprocess_shell(arguments['command'],cwd=self.work,
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        stdout,stderr = await process.communicate()
        return ExecResult(return_code=process.returncode,stdout=stdout.decode(),stderr=stderr.decode())

    def agent(self, max_requests=10, *, min_available_bytes=1, trial='trial'):
        from harbor.agents.factory import AgentFactory
        from harbor.models.trial.config import AgentConfig
        from scripts.harbor_tokenizer_process import TokenizerProcess
        self.options = {'endpoint':f'http://127.0.0.1:{self.server.server_port}/v1',
            'chat_template_kwargs':{'enable_thinking':False},'orchestration':'multi-agent',
            'max_children':2,'max_running_children':2,
            'model_budget':{'tokenizer_path':str(self.root),'tokenizer_python':sys.executable,
                'max_requests':max_requests,'max_input_tokens':32768,'max_output_tokens':1024,
                'max_total_tokens':500000,'min_available_bytes':min_available_bytes}}
        self.arm = {'id':'localpilot','agent':{'import_path':'scripts.localpilot_harbor:LocalPilotHarborAgent',
                    'model_name':'fixture','kwargs':self.options}}
        config = AgentConfig.model_validate(self.arm['agent'])
        self.trial = self.root/trial
        agent = AgentFactory.create_agent_from_config(config,self.trial/'agent')
        agent.backend.capabilities = replace(agent.backend.capabilities,supports_streaming=False)
        agent.backend.counter = TokenizerProcess(sys.executable,self.root,script=self.counter_script,timeout=1)
        self.backends.append(agent.backend)
        self.identity = {'model_name':'fixture','revision':'fixture-only','quantization':'fixture-only',
                         'tokenizer_sha256':agent.backend.tokenizer_sha256}
        return agent

    def audit(self):
        return audit_budget_log(self.trial/'result.json',
            {'agent_execution':{'started_at':'fixture'}},self.arm,self.identity)

    async def test_real_product_children_share_environment_budget_and_usage(self):
        from harbor.models.agent.context import AgentContext
        agent = self.agent()
        await agent.setup(self)
        context = AgentContext()
        await agent.run('parent task',self,context)
        self.assertTrue(self.both.is_set(),'Both child shells must overlap through the owning loop')
        self.assertEqual([(self.work/(name+'.txt')).read_text() for name in ('left','right')],['left','right'])
        self.assertEqual(list((agent.logs_dir/'registry-identity').iterdir()),[])
        for request in self.calls:
            names = {tool['function']['name'] for tool in request.get('tools',[])}
            self.assertTrue(names.isdisjoint({'read_file','apply_patch','execute','move_file','http_request'}))
            if next(row['content'] for row in request['messages'] if row['role']=='user').startswith('child-'):
                self.assertLessEqual(names,{'shell'})
        report = self.audit()
        self.assertTrue(report['qualified'],report)
        self.assertEqual(report['orchestration']['children'],2)
        self.assertEqual(report['requests'],len(self.calls))
        self.assertEqual((context.n_input_tokens,context.n_output_tokens),(7*len(self.calls),2*len(self.calls)))
        self.assertEqual(agent.backend.requests,len(self.calls))
        self.assertIsNone(agent.backend.counter.process)
        evidence_path = agent.logs_dir/'localpilot-orchestration.json'
        original = evidence_path.read_bytes()
        for field, value in (('shared_backend',False), ('model_slots',2), ('input_tokens',-1),
                             ('cancellation_requested',True), ('registries',[['shell'],['shell','read_file'],['shell']])):
            with self.subTest(field=field):
                evidence = json.loads(original)
                evidence[field] = value
                evidence_path.write_text(json.dumps(evidence))
                self.assertFalse(self.audit()['qualified'])
        evidence_path.write_bytes(original)
        reference = deepcopy(self.arm)
        reference['id'] = 'reference'
        reference['agent']['import_path'] = 'scripts.harbor_reference:BudgetedTerminusAgent'
        for key in ('orchestration','max_children','max_running_children','chat_template_kwargs'):
            reference['agent']['kwargs'].pop(key)
        spec = {'purpose':'evaluation','arms':[self.arm,reference],
            'comparison':{'candidate':'localpilot','baseline':'reference'},
            'execution':{'n_concurrent_trials':1},'model_identity':self.identity}
        self.assertTrue(comparison_configuration(spec)['qualified'])
        reference['agent']['model_name'] = 'different-model'
        self.assertFalse(comparison_configuration(spec)['qualified'])

    async def test_default_worker_budgets_allow_three_real_shell_actions_before_summary(self):
        from harbor.models.agent.context import AgentContext
        self.shell_steps = 3
        agent = self.agent(max_requests=16)
        await agent.setup(self)
        context = AgentContext()
        await agent.run('parent task',self,context)
        self.assertEqual(self.shell_started,6)
        self.assertEqual([(self.work/(name+'.txt')).read_text() for name in ('left','right')],
                         ['left-step2','right-step2'])
        evidence = json.loads((agent.logs_dir/'localpilot-orchestration.json').read_text())
        self.assertEqual([child['model_calls'] for child in evidence['children']],[4,4])
        self.assertEqual([child['status'] for child in evidence['children']],['completed','completed'])
        self.assertEqual(context.metadata['runtime_status'],'completed')
        self.assertEqual(agent.budgets.max_worker_token_units,131072)
        report = self.audit()
        self.assertTrue(report['qualified'],report)
        self.assertEqual(report['requests'],11)
        self.assertEqual((context.n_input_tokens,context.n_output_tokens),(77,22))

    async def test_all_workers_exhaust_one_request_budget_without_reset_or_retry(self):
        from harbor.models.agent.context import AgentContext
        self.wait_for_both = False
        agent = self.agent(max_requests=3)
        await agent.setup(self)
        context = AgentContext()
        with self.assertRaises(RuntimeError):
            await agent.run('parent task',self,context)
        self.assertEqual(len(self.calls),3)
        rows = [json.loads(row) for row in (agent.logs_dir/'model-budget.jsonl').read_text().splitlines()]
        self.assertEqual(sum(row['status']=='budget_initialized' for row in rows),1)
        self.assertEqual(sum(row['status']=='admitted' for row in rows),3)
        self.assertTrue(any(row['status']=='denied_before_dispatch' for row in rows))
        report = self.audit()
        self.assertTrue(report['qualified'],report)
        self.assertGreater(report['denied_before_dispatch'],0)
        self.assertEqual((context.n_input_tokens,context.n_output_tokens),(21,6))
        self.assertNotEqual(context.metadata['runtime_status'],'completed')

    async def test_unavailable_tokenizer_and_memory_never_qualify_as_budget_exhaustion(self):
        from harbor.models.agent.context import AgentContext
        self.no_delegation = True
        for reason in ('tokenizer_failure','memory_headroom'):
            with self.subTest(reason=reason):
                agent = self.agent(min_available_bytes=2**62 if reason=='memory_headroom' else 1,trial=reason)
                if reason=='tokenizer_failure':
                    self.counter_script.write_text('raise RuntimeError("fixture tokenizer unavailable")\n')
                await agent.setup(self)
                with self.assertRaises(RuntimeError):
                    await agent.run('parent task',self,AgentContext())
                original = (agent.logs_dir/'model-budget.jsonl').read_bytes()
                self.assertIn(reason.encode(),original)
                report = self.audit()
                self.assertFalse(report['qualified'])
                self.assertIn(reason,report['issues'][0])
                self.assertEqual((agent.logs_dir/'model-budget.jsonl').read_bytes(),original)
                self.assertIsNone(agent.backend.counter.process)
        self.assertEqual(self.calls,[])

    async def test_evidence_write_failure_still_reaps_real_tokenizer_process(self):
        from harbor.models.agent.context import AgentContext
        self.no_delegation = True
        agent = self.agent()
        (agent.logs_dir/'localpilot-orchestration.json').mkdir()
        await agent.setup(self)
        with self.assertRaises(IsADirectoryError):
            await agent.run('parent task',self,AgentContext())
        self.assertEqual(len(self.calls),1)
        self.assertIsNone(agent.backend.counter.process)
        self.assertFalse(self.audit()['qualified'])

    async def test_opt_in_without_delegation_is_not_evidence_that_workers_ran(self):
        from harbor.models.agent.context import AgentContext
        self.no_delegation = True
        agent = self.agent()
        await agent.setup(self)
        await agent.run('parent task',self,AgentContext())
        report = self.audit()
        self.assertTrue(report['qualified'],report)
        self.assertEqual(report['orchestration']['children'],0)
        self.assertFalse(report['orchestration']['observed_delegation'])

    async def test_read_only_child_factory_blocks_shell_and_has_no_host_fallback(self):
        from agent.policy import DataPolicy
        from agent.safety import CapabilityPolicy
        from scripts.localpilot_harbor import ContainerRegistryFactory, ContainerShell
        factory = ContainerRegistryFactory(ContainerShell(self,asyncio.get_running_loop(),'/task'))
        registry = factory(self.root,permission_mode='full-permission',data_policy=DataPolicy(local_only=True),
            capabilities=CapabilityPolicy(read=True,write=False,execute=False,read_only=True))
        denied = await asyncio.to_thread(registry.call,'shell',{'command':'printf forbidden > no.txt'})
        self.assertEqual(denied['status'],'denied')
        with self.assertRaises(ValueError):
            registry.call('read_file',{'path':str(self.counter_script)})
        self.assertEqual(self.commands,[])


if __name__ == '__main__':
    unittest.main()
