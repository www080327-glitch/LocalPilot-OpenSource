"""Durable request retries use real SQLite/HTTP; models remain scripted."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import unittest

from agent.registry import create_default_registry
from agent.finalization import FinalizationPolicy
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets
from agent.stabilization import HostVerification
from localpilot_api.service import APIError, TaskRequest, TaskService
from localpilot_api.server import APIServer
from localpilot_api.client import Client
from tests.test_runtime_api import Backend, answer, call


class DurableRequestRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root/'workspace'
        self.workspace.mkdir()
        self.backend = Backend(answer('delivered'), answer('duplicate request executed'))
        self.services = []

    def tearDown(self):
        for service in self.services:
            if service.store and service.store.connection:
                service.suspend()
        self.temp.cleanup()

    def factory(self, cb):
        return AgentSession(create_default_registry(self.workspace, permission_mode='approve-mutations'),
            backend=self.backend, policy='cloud-only', streaming=False, event_callback=cb,
            retry_policy=RetryPolicy(max_attempts=1))

    def service(self, **kwargs):
        service = TaskService({'localpilot':self.factory}, persistence=self.root/'runtime.db', **kwargs)
        self.services.append(service)
        return service

    def request(self, **kwargs):
        return TaskRequest('deliver this controlled task', idempotency_key='disconnect-retry-42', **kwargs)

    def test_same_request_after_completion_and_restart_keeps_task_and_model_count(self):
        service = self.service()
        request = self.request()
        first = service.wait(service.create_task(request)['id'])
        self.assertEqual(service.create_task(request), first)
        service.suspend()
        restored = self.service()
        recovered = restored.task_snapshot(first['id'])
        self.assertEqual(restored.create_task(request), recovered)
        self.assertEqual(len(self.backend.requests), 1)
        self.assertEqual(len(restored.tasks), 1)
        self.assertEqual(len(restored.sessions), 1)

    def test_key_conflict_refuses_changed_input_route_deadline_and_output_budget(self):
        service = self.service()
        request = self.request()
        service.wait(service.create_task(request)['id'])
        for conflict in (replace(request,input='different task'), replace(request,model='different'),
                         replace(request,timeout_seconds=121), replace(request,max_output_tokens=32)):
            with self.assertRaises(APIError) as error:
                service.create_task(conflict)
            self.assertEqual(error.exception.code,'idempotency_conflict')
        self.assertEqual(len(self.backend.requests), 1)

    def test_replay_lookup_precedes_capacity_and_busy_approval_check(self):
        self.backend = Backend(answer(None,call('apply_patch',{'changes':[
            {'operation':'create','path':'one.txt','content':'proof'}]},'write')),answer('delivered'))
        service = self.service(max_tasks=1,max_sessions=1)
        request = self.request()
        pending = service.wait(service.create_task(request)['id'])
        self.assertEqual(pending['status'],'requires_approval')
        self.assertEqual(service.create_task(request), pending)
        self.assertFalse((self.workspace/'one.txt').exists())
        service.act(pending['id'],'approve',pending['required_action']['id'])
        final = service.wait(pending['id'])
        self.assertEqual(service.create_task(request),final)
        self.assertEqual(len(final['tools']),1)

    def test_concurrent_duplicate_requests_admit_one_task(self):
        service=self.service()
        gate=threading.Barrier(6)
        ids=[]
        def submit():
            gate.wait()
            ids.append(service.create_task(self.request())['id'])
        threads=[threading.Thread(target=submit) for _ in range(6)]
        for t in threads:t.start()
        for t in threads:t.join(3)
        self.assertEqual(len(ids),6)
        self.assertEqual(len(set(ids)),1)
        service.wait(ids[0])
        self.assertEqual(len(self.backend.requests),1)

    def test_invalid_keys_and_unkeyed_requests_keep_existing_behavior(self):
        service=self.service()
        for key in ('','a'*129,42,'line\nbreak',True):
            with self.assertRaises(APIError):
                service.create_task(replace(self.request(),idempotency_key=key))
        for _ in range(2):service.wait(service.create_task(TaskRequest('unkeyed'))['id'])
        self.assertEqual(len(service.tasks),2)

    def test_native_http_accepts_key_and_standard_openai_subset_stays_strict(self):
        service=self.service()
        server=APIServer(('127.0.0.1',0),service,api_key='fixture-api',control_token='fixture-host')
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':0.02},daemon=True)
        thread.start()
        client=Client(f'http://127.0.0.1:{server.server_port}',api_key='fixture-api')
        try:
            body={'input':'controlled task','idempotency_key':'native-retry'}
            first=client.request('/localpilot/v1/tasks',body)
            service.wait(first['id'])
            duplicate=client.request('/localpilot/v1/tasks',body)
            self.assertEqual(duplicate['id'],first['id'])
            from urllib.error import HTTPError
            with self.assertRaises(HTTPError) as error:
                client.request('/v1/responses',{'model':'localpilot',**body})
            self.assertEqual(error.exception.code,400)
        finally:
            server.shutdown();server.server_close();thread.join(3)

    def test_key_plaintext_is_not_stored_in_checkpoint_or_snapshot(self):
        service=self.service()
        request=self.request()
        final=service.wait(service.create_task(request)['id'])
        raw=service.store.connection.execute('SELECT payload FROM checkpoints').fetchone()[0]
        self.assertNotIn(request.idempotency_key,raw)
        self.assertNotIn(request.idempotency_key,json.dumps(final))

    def test_final_only_incomplete_http_body_recovers_without_replaying_write(self):
        from http.client import IncompleteRead
        backend=Backend(answer(None,call('apply_patch',{'changes':[
            {'operation':'create','path':'one.txt','content':'proof'}]},'write')),
            IncompleteRead(b'partial JSON',100),answer('one.txt delivered'))
        def check(root,evidence):
            import hashlib
            ok=(root/'one.txt').read_text()=='proof'
            return HostVerification('passed' if ok else 'failed','exact one.txt',
                {'one.txt':hashlib.sha256((root/'one.txt').read_bytes()).hexdigest()},ok,ok,ok)
        runtime=AgentSession(create_default_registry(self.workspace,permission_mode='full-permission'),
            backend=backend,policy='cloud-only',streaming=False,retry_policy=RetryPolicy(max_attempts=1),
            budgets=SessionBudgets(max_steps=3,max_token_units=1048576),
            finalization_policy=FinalizationPolicy(),completion_check=check,
            verification_callback=lambda root,result:check(root,result))
        result=runtime.run_turn('create one.txt then deliver')
        self.assertEqual(result.status,'completed')
        self.assertEqual(result.completion['attempts'],2)
        self.assertEqual([h['kind'] for h in result.completion['history']],['IncompleteRead','delivered'])
        self.assertEqual(len(runtime.tool_history),1)
        self.assertEqual(len(backend.requests),3)
        self.assertIsNone(backend.requests[-1]['tools'])

    def test_stream_length_with_tool_fragments_cannot_become_final_only_success(self):
        import io
        import hashlib
        from agent.deepseek import DeepSeekBackend
        (self.workspace/'one.txt').write_text('proof')
        mutation=call('apply_patch',{'changes':[{'operation':'create','path':'never.txt','content':'never'}]},'partial-write')
        chunks=[{'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'id':mutation.id,'function':{'name':mutation.name,'arguments':mutation.arguments}}]}}]},
                {'choices':[{'index':0,'delta':{},'finish_reason':'length'}],'usage':{'prompt_tokens':7,'completion_tokens':16}}]
        raw=(''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n').encode()
        stop=b'data: {"choices":[{"index":0,"delta":{"content":"claimed final"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        model=DeepSeekBackend(api_key='fixture-only-no-network')
        requests=[]
        def fixture_open(payload):
            requests.append(payload)
            return io.BytesIO(raw if len(requests)==1 else stop)
        model._open=fixture_open
        def check(root,evidence):
            return HostVerification('passed','exact existing fixture one.txt',
                {'one.txt':hashlib.sha256((root/'one.txt').read_bytes()).hexdigest()},True,True,True)
        runtime=AgentSession(create_default_registry(self.workspace,permission_mode='full-permission'),backend=model,
            policy='cloud-only',streaming=True,retry_policy=RetryPolicy(max_attempts=1),
            budgets=SessionBudgets(max_steps=6,max_token_units=1048576),finalization_policy=FinalizationPolicy(),completion_check=check)
        result=runtime.run_turn('controlled incomplete tool response')
        self.assertEqual(result.status,'error')
        self.assertEqual(len(requests),1)
        self.assertFalse((self.workspace/'never.txt').exists())
        self.assertEqual(result.model_calls[0].finish_reason,'length')


if __name__=='__main__':unittest.main()
