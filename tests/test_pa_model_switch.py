"""Real loopback HTTP, canonical Runtime checkpoints and SQLite; scripted models."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError

from agent.async_runtime import AsyncPolicy
from agent.backends import BackendCapabilities, ModelInfo
from agent.engine_v5 import EngineV5Policy
from agent.hybrid import CloudEgressPolicy, HybridPolicy
from agent.persistence import snapshot_runtime
from agent.policy import DataPolicy
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession
from localpilot_api.service import TaskService
from localpilot_service.security import AccessPolicy, Principal
from localpilot_service.server import ServiceServer
from localpilot_service.sdk import Client
from tests.test_runtime_api import Backend, answer, call


class ScriptedBackend(Backend):
    def health_check(self):
        return True


class ModelSwitchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'work'
        self.workspace.mkdir()
        self.backends = {'internal-a':ScriptedBackend(answer('first')), 'internal-b':ScriptedBackend(answer('second'))}
        for name, backend in self.backends.items():
            backend.model_info = ModelInfo(name, '35B', 131072)
            backend.capabilities = BackendCapabilities(supports_tool_calling=True,
                supported_thinking_efforts=('none', 'high'), default_thinking_effort='none')
        self.backends['internal-a'].is_local = True
        self.target_workspace = self.workspace
        self.async_policy = AsyncPolicy()
        self.use_v5 = False
        self.services = []
        self.start()

    def factory(self, name, callback):
        backend = self.backends[name]
        local = backend.is_local
        workspace = self.workspace if name == 'internal-a' else self.target_workspace
        policy = DataPolicy(local_only=local)
        return AgentSession(create_default_registry(workspace, data_policy=policy),
            backend=backend, policy='local-only' if local else 'cloud-only',
            data_policy=policy, hybrid_policy=HybridPolicy(CloudEgressPolicy('LOCAL_ONLY' if local else 'CLOUD_ALLOWED')),
            hybrid_backends={'selected':backend}, hybrid_primary='selected',
            async_policy=self.async_policy, engine_policy=EngineV5Policy() if self.use_v5 else None,
            event_callback=callback, retry_policy=RetryPolicy(max_attempts=1))

    def start(self):
        routes = {name:lambda cb, n=name:self.factory(n, cb) for name in self.backends}
        self.service = TaskService(routes, persistence=self.root / 'runtime.db', async_policy=self.async_policy)
        self.services.append(self.service)
        aliases = {'a':'internal-a', 'b':'internal-b'}
        self.access = AccessPolicy([
            Principal('desktop', 'd'*32, routes=aliases),
            Principal('other', 'x'*32, routes=aliases),
            Principal('operator', 'o'*32, routes=aliases, operator=True, approval_for=('desktop',), scopes=frozenset({'read','control'})),
        ], audit_path=self.root / 'audit.jsonl')
        self.server = ServiceServer(('127.0.0.1', 0), self.service, access=self.access)
        self.server.catalog = {name:{'deployment_status':'ready', 'capabilities':['tool_calling'],
            'model':name, 'adapter':'local-openai' if b.is_local else 'remote-openai',
            'cloud_egress':'LOCAL_ONLY' if b.is_local else 'CLOUD_ALLOWED'} for name,b in self.backends.items()}
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval':.01}, daemon=True)
        self.thread.start()
        self.client = Client('http://127.0.0.1:'+str(self.server.server_port), token='d'*32)
        self.operator = Client(self.client.base_url, token='o'*32)

    def stop(self):
        self.server.shutdown()
        self.thread.join(2)
        self.server.server_close()
        self.access.close()

    def restart(self):
        self.stop()
        self.service.suspend()
        self.start()

    def tearDown(self):
        self.stop()
        for service in self.services:
            if service.store.connection:
                if service.store.failed:
                    service.store.close()
                    service.scheduler.close()
                else:
                    service.shutdown()
        self.temp.cleanup()

    def session(self, mode='full', profile='standard'):
        return self.operator.request('/localpilot/v1/desktop-sessions', {
            'client_subject':'desktop', 'model':'a', 'source':'balanced',
            'options':{'permission_mode':mode, 'agent_profile':profile}}, key='session-'+mode+'-'+profile)

    def switch(self, sid, model='b', expected='a', source='balanced', client=None, **extra):
        return (client or self.operator).request('/localpilot/v1/desktop-sessions/'+sid+'/model', {
            'client_subject':'desktop', 'model':model, 'expected_model':expected, 'source':source, **extra})

    def submit(self, sid, text, key):
        task = self.client.submit(text, session_id=sid, idempotency_key=key)
        self.service.wait(task['id'])
        return self.client.status(task['id'])

    def denied(self, code, fn, error_code=None):
        with self.assertRaises(HTTPError) as raised:
            fn()
        with raised.exception as error:
            self.assertEqual(error.code, code)
            if error_code:
                self.assertEqual(json.loads(error.read())['error']['code'], error_code)

    def test_canonical_history_receipts_tasks_and_idempotency_survive_switch_and_restart(self):
        self.backends['internal-a'].steps = [answer(None, call('apply_patch', {
            'changes':[{'path':'marker.txt','operation':'create','content':'ORBIT'}]}, 'write-once')), answer('Saved ORBIT')]
        session = self.session(profile='minimal')
        sid = session['id']
        first = self.submit(sid, 'Remember ORBIT and save it.', 'first')
        self.assertEqual(first['status'], 'completed')
        runtime = self.service.sessions[sid].runtime
        before = snapshot_runtime(runtime)
        result = self.switch(sid, reasoning_effort='high')
        current = self.service.sessions[sid].runtime
        self.assertEqual(result['id'], sid)
        self.assertEqual(result['model'], 'b')
        self.assertEqual(result['thinking']['effective'], 'high')
        self.assertEqual(result['desktop_options'], session['desktop_options'])
        after = snapshot_runtime(current)
        for key in ('history','completed','goals','subagents','working','budgets','gateway_audit'):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual([m for m in after['messages'] if m['role'] != 'system'],
                         [m for m in before['messages'] if m['role'] != 'system'])
        self.assertEqual(current.hybrid.state['attempts'], runtime.hybrid.state['attempts'])
        self.assertEqual(len(self.backends['internal-b'].requests), 0)
        self.assertEqual(self.client.status(first['id'])['model'], 'a')
        self.assertEqual(self.client.status(first['id'])['session_model'], 'b')
        self.assertEqual(self.switch(sid)['id'], sid)
        self.denied(409, lambda:self.switch(sid, 'a', 'a'), 'model_conflict')
        self.restart()
        restored = self.service.sessions[sid]
        self.assertEqual(restored.model, 'internal-b')
        self.assertEqual(restored.runtime.thinking_mode, 'high')
        self.assertEqual(restored.runtime.tool_history, before['history'])
        self.assertEqual(self.client.submit('Remember ORBIT and save it.', model='a', session_id=sid, idempotency_key='first')['id'], first['id'])
        second = self.submit(sid, 'Recall the marker.', 'second')
        self.assertEqual(second['status'], 'completed')
        self.assertEqual(second['session_id'], sid)
        self.assertEqual(second['model'], 'b')
        self.assertIn('Remember ORBIT and save it.', [m.content for m in self.backends['internal-b'].requests[-1]['messages']])
        self.assertEqual((self.workspace / 'marker.txt').read_text(), 'ORBIT')
        self.assertEqual(len(self.service.sessions), 1)
        self.assertEqual(len(restored.runtime.tool_history), 1)

    def test_v5_stable_prompt_and_async_policy_continue_on_target(self):
        self.stop()
        self.service.suspend()
        self.use_v5 = True
        self.start()
        sid = self.session()['id']
        self.submit(sid, 'hello', 'v5-one')
        self.switch(sid)
        self.restart()
        task = self.submit(sid, 'again', 'v5-two')
        self.assertEqual(task['status'], 'completed')
        self.assertEqual(len(self.backends['internal-b'].requests), 1)
        self.assertIs(self.service.sessions[sid].runtime._scheduler, self.service.scheduler)

    def test_incompatible_workspace_keeps_original_session(self):
        sid = self.session()['id']
        first = self.submit(sid, 'keep history', 'workspace')
        old = self.service.sessions[sid].runtime
        before = snapshot_runtime(old)
        self.target_workspace = self.root / 'different'
        self.target_workspace.mkdir()
        self.denied(409, lambda:self.switch(sid), 'model_switch_contract_incompatible')
        self.assertIs(self.service.sessions[sid].runtime, old)
        self.assertEqual(snapshot_runtime(old), before)
        self.assertEqual(self.client.status(first['id'])['session_model'], 'a')
        self.assertEqual(len(self.backends['internal-b'].requests), 0)

    def test_unsupported_thinking_source_readiness_or_owner_does_not_mutate(self):
        sid = self.session()['id']
        old = self.service.sessions[sid].runtime
        self.denied(403, lambda:self.switch(sid, client=self.client), 'control_required')
        self.denied(409, lambda:self.switch(sid, source='local_only'), 'model_source_forbidden')
        self.denied(409, lambda:self.switch(sid, reasoning_effort='extreme'), 'thinking_not_supported')
        self.server.catalog['internal-b']['deployment_status'] = 'not_deployed'
        self.denied(409, lambda:self.switch(sid), 'model_not_deployed')
        self.server.catalog['internal-b']['deployment_status'] = 'ready'
        other = self.service.create_session('internal-a', owner_subject='other', desktop_options={
            'permission_mode':'full','agent_profile':'standard','prompt_revision':2,'scope_revision':3})
        self.denied(403, lambda:self.switch(other['id']), 'scope_forbidden')
        self.assertIs(self.service.sessions[sid].runtime, old)
        self.assertEqual(self.service.sessions[sid].model, 'internal-a')

    def test_pending_approval_and_unknown_receipts_cannot_be_bypassed(self):
        self.backends['internal-a'].steps = [answer(None, call('apply_patch', {
            'changes':[{'path':'unknown.txt','operation':'create','content':'written once'}]}, 'uncertain')), answer('done')]
        sid = self.session('request')['id']
        registry = self.service.sessions[sid].runtime.registry
        original = registry._tools['apply_patch']
        def lost_receipt(**args):
            result = original(**args)
            if (self.workspace / 'unknown.txt').exists():
                raise TimeoutError('receipt unavailable')
            return result
        registry._tools['apply_patch'] = lost_receipt
        first = self.submit(sid, 'save marker', 'unknown')
        self.assertEqual(first['status'], 'requires_approval')
        self.denied(409, lambda:self.switch(sid), 'session_busy')
        self.operator.continue_task(first['id'], first['required_action']['id'], action='approve')
        self.service.wait(first['id'])
        unknown = self.client.status(first['id'])
        self.assertEqual(unknown['receipt_summary']['unknown_effects'], 1)
        self.denied(409, lambda:self.switch(sid), 'session_busy')
        self.client.cancel(first['id'])
        self.service.wait(first['id'])
        self.denied(409, lambda:self.switch(sid), 'model_switch_unavailable')
        self.assertEqual(self.client.status(first['id'])['receipt_summary']['unknown_effects'], 1)
        self.assertEqual((self.workspace / 'unknown.txt').read_text(), 'written once')
        self.assertEqual(len(self.backends['internal-b'].requests), 0)

    def test_failed_checkpoint_restores_old_runtime_and_restart_uses_old_route(self):
        sid = self.session()['id']
        self.submit(sid, 'retain persisted history', 'before-fault')
        old = self.service.sessions[sid].runtime
        def fail(stage, point):
            if stage == 'before_commit' and point == 'desktop_model_changed':
                raise OSError('simulated storage failure')
        self.service.store.fault_hook = fail
        self.denied(503, lambda:self.switch(sid), 'model_switch_storage_unavailable')
        self.assertIs(self.service.sessions[sid].runtime, old)
        self.assertEqual(self.service.sessions[sid].model, 'internal-a')
        self.stop()
        self.service.store.close()
        self.service.scheduler.close()
        self.start()
        self.assertEqual(self.service.sessions[sid].model, 'internal-a')
        self.assertIn('retain persisted history', [m.content for m in self.service.sessions[sid].runtime.messages])

    def test_completed_child_backend_cannot_be_silently_rebound(self):
        self.backends['internal-a'].steps = [answer(None, call('delegate', {
            'task':'bounded review', 'backend_preference':'local', 'backend_id':'selected',
            'read_only':True, 'mode':'sync'}, 'child-once')), answer('Child complete'), answer('Parent complete')]
        sid = self.session()['id']
        first = self.submit(sid, 'review with one child', 'child')
        self.assertEqual(first['status'], 'completed')
        old = self.service.sessions[sid].runtime
        self.assertEqual(len(old._children), 1)
        before = snapshot_runtime(old)
        self.denied(409, lambda:self.switch(sid), 'model_switch_children_incompatible')
        self.assertEqual(snapshot_runtime(old), before)
        self.assertEqual(len(self.backends['internal-b'].requests), 0)

    def test_native_reasoning_remains_canonical_but_is_not_replayed_to_another_provider(self):
        response = answer('Visible answer')
        response.message.reasoning_content = 'private provider reasoning'
        response.message.native_replay = {'provider':'scripted', 'signature':'fixture-signature'}
        self.backends['internal-a'].steps = [response]
        sid = self.session()['id']
        self.submit(sid, 'remember', 'reasoning-one')
        self.switch(sid)
        self.restart()
        runtime = self.service.sessions[sid].runtime
        canonical = next(m for m in runtime.messages if m.content == 'Visible answer')
        self.assertEqual(canonical.reasoning_content, 'private provider reasoning')
        self.assertEqual(canonical.native_replay, response.message.native_replay)
        self.submit(sid, 'continue', 'reasoning-two')
        projected = next(m for m in self.backends['internal-b'].requests[-1]['messages'] if m.content == 'Visible answer')
        self.assertIsNone(projected.reasoning_content)
        self.assertIsNone(projected.native_replay)


if __name__ == '__main__':
    unittest.main()
