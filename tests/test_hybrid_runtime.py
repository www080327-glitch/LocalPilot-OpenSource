"""Scripted model controls; real Gateway/files/SQLite/threads, never Hybrid E2E."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from agent.async_runtime import AsyncPolicy
from agent.backends import BackendChunk, BackendCapabilities, ModelInfo, Message
from agent.deepseek import DeepSeekAPIError
from agent.hybrid import CloudEgressPolicy, HybridPolicy, CloudEgressDenied, sha
from agent.local_http import LocalBackendError, LocalResourceExhausted, LocalHTTPBackend
from agent.persistence import PersistenceError, restore_runtime, snapshot_runtime
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.safety import CapabilityPolicy
from agent.session import AgentSession, SessionBudgets
from agent.stabilization import StabilizationControls
from localpilot_api.service import APIError, TaskService, TaskRequest
from tests.test_runtime_api import Backend, answer, call


class Local(Backend):
    is_local = True
    is_loopback = True
    model_info = ModelInfo('scripted-local-Q', '35B', 65536)
    def health_check(self):
        return True


def patch(path, id='write', content='proof'):
    return answer(None, call('apply_patch', {'changes': [{'path': path, 'operation': 'create', 'content': content}]}, id))


def spawn(target, task='work', id='spawn', read_only=False, async_=False, alias=None):
    args = {'task': task, 'backend_preference': target, 'read_only': read_only,
            'backend_id': alias or target}
    if async_:
        args['mode'] = 'async'
    return call('delegate', args, id)


class HybridRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workspace = self.root/'workspace'
        self.workspace.mkdir()
        self.cloud = Backend(answer('cloud final'))
        self.local = Local(answer('local final'))
        self.policy = HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED'))
        self.primary = 'local'
        self.mode = 'full-permission'
        self.async_policy = None
        self.services, self.runtimes = [], []
        self.catalog_extra = {}
        self.budgets = SessionBudgets(max_steps=64, max_tool_calls=64, max_token_units=8000000,
            max_worker_steps=8, max_worker_tool_calls=8, max_worker_token_units=600000,
            max_subagents_per_turn=4)
    def tearDown(self):
        for s in self.services:
            if s.store and s.store.failed:
                s.store.close()
            elif not s.closed:
                s.shutdown(timeout=10)
        for r in self.runtimes:
            if r._persistence_hook:
                continue  # suspended service owns its surviving tree
            if not r._drive_lock.locked() and r.state.value != 'session_finished':
                r.close()
        self.tmp.cleanup()
    def factory(self, cb=None):
        r = AgentSession(create_default_registry(self.workspace, permission_mode=self.mode),
            local_backend=self.local, cloud_backend=self.cloud, policy='balanced', streaming=False,
            hybrid_policy=self.policy, hybrid_primary=self.primary,
            hybrid_backends={'local': self.local, 'cloud': self.cloud, **self.catalog_extra},
            budgets=self.budgets, event_callback=cb, retry_policy=RetryPolicy(max_attempts=1),
            stabilization=StabilizationControls(False, True, 'off', 0), async_policy=self.async_policy)
        self.runtimes.append(r)
        return r
    def service(self):
        s = TaskService({'localpilot': self.factory}, persistence=self.root/'runtime.db', async_policy=self.async_policy)
        self.services.append(s)
        return s
    def act(self, s, t, action='approve'):
        s.act(t['id'], action, t['required_action']['id'])
        return s.wait(t['id'])
    def run_task(self, s):
        return s.wait(s.create_task(TaskRequest('controlled work'))['id'])
    def test_default_disabled_catalog_and_schema(self):
        r = AgentSession(create_default_registry(self.workspace), backend=self.cloud)
        self.assertNotIn('backend_id', r._schemas()[len(r.registry.schemas())]['function']['parameters']['properties'])
        self.assertNotIn('hybrid', snapshot_runtime(r))
        r.close()

    def test_single_eligible_provider_does_not_advertise_an_impossible_switch(self):
        for policy,primary in [('local-only','local'),('cloud-only','cloud'),('balanced','local')]:
            r=AgentSession(create_default_registry(self.workspace),local_backend=self.local,cloud_backend=self.cloud,
                policy=policy,streaming=False,runtime_tools=False,hybrid_policy=self.policy,
                hybrid_backends={'local':self.local,'cloud':self.cloud},hybrid_primary=primary)
            self.runtimes.append(r)
            names={s['function']['name'] for s in r._schemas()}
            self.assertEqual('request_model_switch' in names,policy=='balanced')
            if policy=='local-only':
                with self.assertRaises(CloudEgressDenied):r.hybrid.check_target('cloud')
            if policy=='cloud-only':
                with self.assertRaises(CloudEgressDenied):r.hybrid.check_target('local')

    def test_multiple_allowed_cloud_routes_keep_model_switch_available(self):
        r=AgentSession(create_default_registry(self.workspace),local_backend=self.local,cloud_backend=self.cloud,
            policy='cloud-only',streaming=False,runtime_tools=False,hybrid_policy=self.policy,
            hybrid_backends={'local':self.local,'cloud':self.cloud,'cloud2':Backend(answer('second'))},hybrid_primary='cloud')
        self.runtimes.append(r)
        self.assertIn('request_model_switch',{s['function']['name'] for s in r._schemas()})
        with self.assertRaises(ValueError):
            AgentSession(create_default_registry(self.workspace), hybrid_primary='local')
    def test_cloud_parent_local_child_fixed_route(self):
        self.primary = 'cloud'
        self.cloud = Backend(answer(None, spawn('local')), answer('aggregated'))
        self.local = Local(patch('local.txt'), answer('local verified'))
        r = self.factory(); result = r.run_turn('controlled work')
        self.assertEqual(result.status, 'completed')
        self.assertEqual(r.subagents[0]['backend_id'], 'local')
        self.assertEqual((self.workspace/'local.txt').read_text(), 'proof')
        self.assertEqual(result.runtime_metrics['hybrid']['calls'], 4)
        self.assertEqual({a['configured_model'] for a in r._children['1.1'].hybrid.state['attempts']}, {'scripted-local-Q'})
    def test_local_parent_cloud_child_needs_host_not_model_approval(self):
        self.local = Local(answer(None, spawn('cloud')), answer('aggregated'))
        self.cloud = Backend(patch('cloud.txt'), answer('cloud verified'))
        s = self.service(); t = self.run_task(s)
        self.assertEqual(t['status'], 'requires_approval')
        self.assertFalse(self.cloud.requests)
        t = self.act(s, t)
        self.assertEqual(t['status'], 'completed', t.get('error'))
        self.assertEqual(t['subagents'][0]['backend_id'], 'cloud')
        self.assertEqual(t['result']['runtime_metrics']['hybrid']['calls'], 4)
    def test_registered_models_can_differ_within_same_backend_kind(self):
        other = Local(patch('other.txt'), answer('done'))
        other.model_info = ModelInfo('other-local-model', '35B', 65536)
        self.catalog_extra = {'other': other}
        self.local = Local(answer(None, spawn('local', alias='other')), answer('done'))
        r = self.factory(); self.assertEqual(r.run_turn('work').status, 'completed')
        self.assertEqual(r.subagents[0]['configured_model'], 'other-local-model')
    def test_model_mismatch_unknown_alias_and_boundary_rejected(self):
        r = self.factory()
        for args in ({'backend_id': 'missing'}, {'backend_id': 'local', 'model': 'made-up'}, {'backend_id': 'cloud'}):
            with self.subTest(args=args), self.assertRaises((ValueError, CloudEgressDenied)):
                r.hybrid.resolve('local', **{'alias': args['backend_id'], 'model': args.get('model')})
        self.assertFalse(r._children)
    def test_mixed_children_really_overlap_after_cloud_approval(self):
        self.async_policy = AsyncPolicy(max_model_requests=2)
        barrier = threading.Barrier(2)
        intervals = []
        lock = threading.Lock()
        def work(messages):
            started = time.monotonic(); barrier.wait(timeout=3); time.sleep(.06)
            with lock:
                intervals.append((started, time.monotonic()))
            return answer('read only work complete')
        self.local = Local(answer(None, spawn('cloud', id='c', read_only=True, async_=True),
                                  spawn('local', id='l', read_only=True, async_=True)), work, answer('parent done'))
        self.cloud = Backend(work)
        r = self.factory(); first = r.run_turn('work')
        self.assertEqual(first.status, 'approval_required')
        final = r.approve()
        self.assertEqual(final.status, 'completed', final.text)
        self.assertEqual(len(intervals), 2)
        self.assertLess(max(x[0] for x in intervals), min(x[1] for x in intervals))
        self.assertEqual({c['backend_id'] for c in r.subagents}, {'cloud', 'local'})
    def test_exact_cloud_egress_approval_and_restart_epoch(self):
        self.primary = 'cloud'; self.policy = HybridPolicy()
        s = self.service(); t = self.run_task(s)
        self.assertEqual(t['required_action']['requests'][0]['kind'], 'cloud_egress')
        self.assertFalse(self.cloud.requests)
        old = t['required_action']['id']; s.suspend(); s = self.service()
        t = s.task_snapshot(t['id'])
        with self.assertRaises(APIError):
            s.act(t['id'], 'approve', old)
        t = self.act(s, t)
        self.assertEqual(t['status'], 'completed', t.get('error'))
        self.assertEqual(len(self.cloud.requests), 1)
    def test_egress_approval_is_not_blanket_authorization_for_next_request(self):
        self.primary = 'cloud'; self.policy = HybridPolicy()
        self.cloud = Backend(answer(None, call('file_info', {'path': 'a.txt'})), answer('done'))
        r = self.factory(); self.assertEqual(r.run_turn('work').status, 'approval_required')
        self.assertEqual(r.approve().status, 'approval_required')
        self.assertEqual(len(self.cloud.requests), 1)
        self.assertEqual(r.approve().status, 'completed')
    def test_rejected_egress_keeps_local_backend_available(self):
        self.primary = 'cloud'; self.policy = HybridPolicy()
        r = self.factory(); r.run_turn('work'); self.assertEqual(r.reject().status, 'incomplete')
        self.assertFalse(self.cloud.requests)
        self.assertIs(r.local_backend, self.local)
    def test_local_only_policy_cannot_be_relaxed_by_catalog(self):
        self.policy = HybridPolicy(CloudEgressPolicy('LOCAL_ONLY'))
        r = self.factory()
        with self.assertRaises(CloudEgressDenied):
            r.hybrid.resolve('cloud')
        r.hybrid.state['backend_id'] = 'cloud'
        with self.assertRaises(CloudEgressDenied):
            r.hybrid.authorize([Message('user', 'work')], [])
        self.assertFalse(self.cloud.requests)
    def test_default_egress_withholds_file_stdout_private_reasoning_and_arguments(self):
        self.primary = 'cloud'
        r = self.factory()
        messages = [Message('assistant', 'untrusted secret narrative', [call('read_file', {'path': 'private.txt'}, 'r')], reasoning_content='PRIVATE_REASONING'),
                    Message('tool', json.dumps({'ok': True, 'result': 'FULL_FILE_SECRET'}), tool_call_id='r'),
                    Message('assistant', None, [call('execute', {'argv': ['env']}, 'e')]),
                    Message('tool', json.dumps({'ok': True, 'result': {'stdout': 'FULL_ENV_SECRET'}}), tool_call_id='e'),
                    patch('private.txt', content='LOCAL_FILE_BODY').message]
        projected = r.hybrid.project_messages(messages)
        raw = json.dumps([m.to_dict(include_reasoning=True) for m in projected])
        for secret in ('PRIVATE_REASONING', 'FULL_FILE_SECRET', 'FULL_ENV_SECRET', 'LOCAL_FILE_BODY', 'untrusted secret narrative'):
            self.assertNotIn(secret, raw)
        self.assertIn('LOCAL_BODY_WITHHELD', raw)
        self.assertEqual(messages[0].reasoning_content, 'PRIVATE_REASONING')
        self.assertEqual(projected[1].tool_call_id, 'r')
    def test_allowlisted_file_body_still_cannot_contain_known_credentials(self):
        self.primary = 'cloud'; self.cloud.api_key = 'SENTINEL_NEVER_SEND_CREDENTIAL_123'
        self.policy = HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED', ('review.py',)))
        r = self.factory()
        messages = [Message('assistant', None, [call('read_file', {'path': 'review.py'}, 'r')]),
                    Message('tool', json.dumps({'ok': True, 'result': self.cloud.api_key}), tool_call_id='r')]
        projected = r.hybrid.project_messages(messages)
        with self.assertRaises(CloudEgressDenied):
            r.hybrid.authorize(projected, [])
        self.assertNotIn(self.cloud.api_key, json.dumps(r.hybrid.state['egress']))
        self.assertFalse(self.cloud.requests)
    def test_explicit_review_path_retains_read_body(self):
        self.primary = 'cloud'; self.policy = HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED', ('review.py',)))
        r = self.factory()
        messages = [Message('assistant', None, [call('read_file', {'path': 'review.py'}, 'r')]), Message('tool', 'CODE_FOR_REVIEW', tool_call_id='r')]
        self.assertIn('CODE_FOR_REVIEW', json.dumps([m.to_dict() for m in r.hybrid.project_messages(messages)]))
    def test_switch_preserves_receipt_call_ids_and_recomputes_target_context(self):
        self.local = Local(patch('once.txt'), answer(None, call('request_model_switch',
            {'target': 'cloud', 'backend_id': 'cloud', 'reason': 'review', 'task_complexity': 'complex', 'scope': 'session'}, 'switch')))
        self.cloud.model_info = replace(self.cloud.model_info, effective_context=50000)
        r = self.factory(); first = r.run_turn('write once then review')
        self.assertEqual(first.status, 'approval_required')
        before = deepcopy(r.tool_history)
        self.assertEqual(r.approve().status, 'completed')
        self.assertEqual(r.tool_history[0], before[0])
        self.assertEqual(r.hybrid.state['generation'], 1)
        self.assertEqual(r.hybrid.state['handoffs'][0]['contract']['context_budget']['capacity_units'], 50000)
        self.assertIn('write', [m.tool_call_id for m in self.cloud.requests[0]['messages'] if m.role == 'tool'])
        self.assertEqual(len([x for x in r.tool_history if x['name'] == 'apply_patch']), 1)
    def test_turn_scoped_switch_restores_registered_model(self):
        self.local = Local(answer(None, call('request_model_switch', {'target': 'cloud', 'reason': 'review', 'task_complexity': 'complex'}, 's')), answer('local next'))
        r = self.factory(); r.run_turn('work'); r.approve()
        self.assertEqual(r.primary, 'cloud')
        self.assertEqual(r.run_turn('next').status, 'completed')
        self.assertEqual(r.hybrid.state['backend_id'], 'local')
    def test_transient_local_failure_escalates_same_task_without_replaying_mutation(self):
        self.policy = replace(self.policy, automatic_failover=True)
        self.local = Local(patch('once.txt'), TimeoutError('local timeout'))
        r = self.factory(); self.assertEqual(r.run_turn('work').status, 'completed')
        self.assertEqual(r.hybrid.state['backend_id'], 'cloud')
        self.assertEqual(len(r.tool_history), 1)
        self.assertEqual(r.hybrid.summary()['by_backend']['local']['unknown_usage_calls'], 1)
        self.assertIn('once.txt', json.dumps([m.to_dict() for m in self.cloud.requests[0]['messages']]))
    def test_cloud_429_and_5xx_fallback_to_local(self):
        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status):
                self.primary = 'cloud'; self.policy = replace(self.policy, automatic_failover=True)
                self.cloud = Backend(DeepSeekAPIError('controlled', status_code=status)); self.local = Local(answer('local recovery'))
                r = self.factory(); self.assertEqual(r.run_turn('work').status, 'completed')
                self.assertEqual(r.hybrid.state['backend_id'], 'local')
    def test_authentication_failure_does_not_auto_switch(self):
        self.primary = 'cloud'; self.policy = replace(self.policy, automatic_failover=True)
        self.cloud = Backend(DeepSeekAPIError('controlled', status_code=401))
        r = self.factory(); self.assertEqual(r.run_turn('work').status, 'error')
        self.assertFalse(self.local.requests)
    def test_unknown_mutation_is_quarantined_and_cannot_failover(self):
        self.policy = replace(self.policy, automatic_failover=True)
        self.local = Local(patch('unknown.txt'), TimeoutError('cannot replay unknown'))
        s = self.service(); sid = s.create_session()['id']; r = s.sessions[sid].runtime
        fn = r.registry._tools['apply_patch']
        def unknown(**args):
            fn(**args); return {'status': 'unknown'}
        r.registry._tools['apply_patch'] = unknown
        t = s.wait(s.create_task(TaskRequest('work', session_id=sid))['id'])
        self.assertEqual(t['status'], 'requires_human')
        self.assertEqual(t['recovery']['class'], 'UNKNOWN_BLOCKED')
        self.assertFalse(self.cloud.requests)
        s.suspend(); s = self.service(); t = s.task_snapshot(t['id'])
        with self.assertRaises(APIError):
            s.act(t['id'], 'continue', t['required_action']['id'])
        self.assertEqual(len(list(self.workspace.glob('unknown*'))), 1)
    def test_switch_does_not_approve_tools_or_bypass_read_only_child(self):
        self.local = Local(answer(None, spawn('cloud', read_only=True)), answer('parent'))
        self.cloud = Backend(patch('forbidden.txt'), answer('claimed complete'))
        s = self.service(); t = self.run_task(s); t = self.act(s, t)
        self.assertNotEqual(t['status'], 'completed')
        self.assertFalse((self.workspace/'forbidden.txt').exists())
        self.assertEqual(t['subagents'][0]['obligation_status'], 'unresolved')
    def test_model_usage_cost_and_parent_aggregation_do_not_duplicate(self):
        self.policy = replace(self.policy, rates=(('cloud', 1.0, 2.0),))
        self.local = Local(answer(None, spawn('cloud', read_only=True)), answer('parent'))
        s = self.service(); t = self.act(s, self.run_task(s)); r = s.sessions[t['session_id']].runtime
        metrics = r.hybrid.summary(); r._sync_children(); r._sync_children()
        self.assertEqual(r.hybrid.summary(), metrics)
        self.assertEqual(metrics['calls'], 3)
        self.assertAlmostEqual(metrics['by_backend']['cloud']['estimated_api_cost_usd'], .000013)
        self.assertEqual(metrics['actual_api_cost'], 'UNKNOWN')
    def test_cloud_quota_shared_by_children(self):
        self.policy = replace(self.policy, max_cloud_requests_per_turn=1)
        self.local = Local(answer(None, spawn('cloud')), answer('parent'))
        self.cloud = Backend(answer(None, call('file_info', {'path': 'absent'})), answer('second blocked'))
        s = self.service(); t = self.act(s, self.run_task(s))
        self.assertNotEqual(t['status'], 'completed')
        self.assertEqual(len(self.cloud.requests), 1)
    def test_checkpoint_identity_policy_drift_and_missing_section_refused(self):
        s = self.service(); self.run_task(s); s.suspend()
        self.policy = replace(self.policy, max_cloud_requests_per_turn=33)
        with self.assertRaises(PersistenceError):
            self.service()
        r = self.factory(); data = snapshot_runtime(r); data.pop('hybrid')
        with self.assertRaises(PersistenceError):
            restore_runtime(r, data)
    def test_inflight_usage_is_unknown_after_restore(self):
        r = self.factory(); r.hybrid.begin_attempt(10, None)
        data = snapshot_runtime(r); restored = self.factory(); restore_runtime(restored, json.loads(json.dumps(data)))
        self.assertEqual(restored.hybrid.state['attempts'][0]['status'], 'process_interrupted')
        self.assertIsNone(restored.hybrid.state['attempts'][0]['input_tokens'])
    def test_context_and_secret_denial_do_not_send_requests(self):
        self.primary = 'cloud'; self.policy = HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED', max_request_bytes=128))
        r = self.factory(); self.assertEqual(r.run_turn('work').status, 'error')
        self.assertFalse(self.cloud.requests)
    def test_stage_handoff_approval_survives_sqlite_restart(self):
        self.local = Local(patch('once.txt'), answer(None, call('request_model_switch',
            {'target': 'cloud', 'reason': 'stage two', 'task_complexity': 'complex', 'scope': 'session'}, 'switch')))
        s = self.service(); t = self.run_task(s); s.suspend(); s = self.service()
        t = self.act(s, s.task_snapshot(t['id']))
        self.assertEqual(t['status'], 'completed', t.get('error'))
        self.assertEqual(len([x for x in t['tools'] if x['name'] == 'apply_patch']), 1)
        r = s.sessions[t['session_id']].runtime
        self.assertEqual(r.hybrid.state['task']['task_id'], t['id'])
        self.assertEqual(r.hybrid.state['task']['generation'], 1)

    def test_host_cloud_delegate_approval_does_not_redrive_live_local_child(self):
        self.async_policy = AsyncPolicy(max_model_requests=2)
        active = threading.Event(); release = threading.Event()
        def delayed(messages):
            active.set(); release.wait(3)
            return patch('local.txt')
        self.primary = 'cloud'
        self.cloud = Backend(answer(None, spawn('local', async_=True, id='l'),
            spawn('cloud', async_=True, id='c')), answer('cloud child'), answer('parent'))
        self.local = Local(delayed, answer('local child'))
        s = self.service(); t = self.run_task(s)
        self.assertEqual(t['status'], 'requires_approval'); self.assertTrue(active.wait(2))
        s.act(t['id'], 'approve', t['required_action']['id']); release.set(); t = s.wait(t['id'])
        self.assertEqual(t['status'], 'completed', t.get('error'))
        self.assertTrue((self.workspace/'local.txt').exists())
        self.assertEqual(t['subagents'][0]['status'], 'completed')
        self.assertEqual([e['event'] for e in t['subagents'][0]['timeline']], ['start', 'completed'])

    def test_switch_keeps_fresh_mutation_approval_separate(self):
        self.mode = 'approve-mutations'
        self.local = Local(answer(None, call('request_model_switch',
            {'target': 'cloud', 'reason': 'escalation', 'task_complexity': 'complex'}, 's')))
        self.cloud = Backend(patch('approved.txt'), answer('done'))
        r = self.factory(); self.assertEqual(r.run_turn('work').status, 'approval_required')
        self.assertEqual(r.approve().status, 'approval_required')
        self.assertFalse((self.workspace/'approved.txt').exists())
        self.assertEqual(r.pending_approval['kind'], 'tool')
        self.assertEqual(r.approve().status, 'completed')

    def test_host_policy_change_clears_old_turn_hybrid_restore(self):
        self.local = Local(answer(None, call('request_model_switch', {'target': 'cloud', 'reason': 'review', 'task_complexity': 'complex'}, 's')))
        self.cloud = Backend(answer('cloud first'), answer('cloud next'))
        r = self.factory(); r.run_turn('work'); r.approve(); r.set_policy('cloud-only')
        self.assertEqual(r.run_turn('next').status, 'completed')
        self.assertEqual(r.hybrid.state['backend_id'], 'cloud')

    def test_cloud_review_local_repair_keeps_canonical_feedback_and_versions(self):
        self.policy = HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED', ('review.py',)))
        self.budgets = replace(self.budgets, max_primary_switches_per_turn=2)
        self.mode = 'approve-mutations'
        self.local = Local(patch('review.py', content='return 1'),
            answer(None, call('read_file', {'path': 'review.py'}, 'r1')),
            answer(None, call('request_model_switch', {'target': 'cloud', 'reason': 'code review', 'task_complexity': 'complex', 'scope': 'session'}, 'sc')),
            answer(None, call('apply_patch', {'changes': [{'path': 'review.py', 'operation': 'update', 'old_text': 'return 1', 'new_text': 'return 2'}]}, 'repair')),
            answer(None, call('read_file', {'path': 'review.py'}, 'r2')), answer('fixed'))
        self.cloud = Backend(answer(None, call('read_file', {'path': 'review.py'}, 'review')),
            answer(None, call('request_model_switch', {'target': 'local', 'reason': 'review feedback: replace return 1 with return 2', 'task_complexity': 'simple', 'scope': 'session'}, 'sl')))
        r = self.factory(); result = r.run_turn('Controlled review then repair')
        for _ in range(4):
            self.assertEqual(result.status, 'approval_required', result.text)
            result = r.approve()
        self.assertEqual(result.status, 'completed', result.text)
        self.assertEqual((self.workspace/'review.py').read_text(), 'return 2')
        self.assertEqual(len(r.hybrid.state['handoffs']), 2)
        self.assertIn('return 1', json.dumps([m.to_dict() for m in self.cloud.requests[1]['messages']]))
        self.assertIn('review feedback', json.dumps([m.to_dict() for m in self.local.requests[-1]['messages']]))
        self.assertEqual(len([x for x in r.tool_history if x['name'] == 'apply_patch']), 2)

    def test_partial_cloud_stream_never_auto_switches_or_executes_proposal(self):
        class Interrupted(Backend):
            capabilities = BackendCapabilities(supports_tool_calling=True, supports_streaming=True)
            def stream(self, messages, **kwargs):
                yield BackendChunk('text', 'partial output')
                raise ConnectionError('Controlled SSE interruption')
        self.primary = 'cloud'; self.cloud = Interrupted()
        self.policy = replace(self.policy, automatic_failover=True)
        r = self.factory(); r.streaming = True
        self.assertEqual(r.run_turn('work').status, 'error')
        self.assertFalse(self.local.requests)
        self.assertFalse(r.tool_history)
        self.assertEqual(r.hybrid.summary()['by_backend']['cloud']['unknown_usage_calls'], 1)

    def test_approval_yields_only_after_live_mutation_intent_settles(self):
        self.async_policy = AsyncPolicy(max_model_requests=2); self.primary = 'cloud'
        entered = threading.Event(); release = threading.Event()
        self.cloud = Backend(answer(None, spawn('local', async_=True, id='l'), spawn('cloud', async_=True, id='c')),
                             answer('cloud child'), answer('parent'))
        self.local = Local(patch('safe.txt'), answer('local child'))
        s = self.service(); sid = s.create_session()['id']; r = s.sessions[sid].runtime
        original = r._delegate
        def delegate(c, args, approved=False):
            payload = original(c, args, approved)
            if args['backend_preference'] == 'local' and r._children:
                child = r._children['1.1']; fn = child.registry._tools['apply_patch']
                def slow(**kw):
                    entered.set(); release.wait(3); return fn(**kw)
                child.registry._tools['apply_patch'] = slow
            return payload
        r._delegate = delegate
        task = s.create_task(TaskRequest('work', session_id=sid)); self.assertTrue(entered.wait(2))
        time.sleep(.08)
        self.assertEqual(s.task_snapshot(task['id'])['status'], 'running')
        release.set(); task = s.wait(task['id'])
        self.assertEqual(task['status'], 'requires_approval')
        self.assertNotEqual(task.get('recovery', {}).get('class'), 'UNKNOWN_BLOCKED')
        self.assertEqual(self.act(s, task)['status'], 'completed')

    def test_json_credential_pattern_is_denied_without_a_backend_key_match(self):
        self.primary = 'cloud'; r = self.factory()
        for content in ('{"password":"SENTINEL_CREDENTIAL_987"}', 'access_token=TOKEN_SENTINEL_12345', '-----BEGIN PRIVATE KEY-----'):
            with self.subTest(content=content), self.assertRaises(CloudEgressDenied):
                r.hybrid.authorize([Message('user', content)], [])

    def test_initial_fixed_route_drift_is_part_of_checkpoint_fence(self):
        s = self.service(); self.run_task(s); s.suspend(); self.primary = 'cloud'
        with self.assertRaises(PersistenceError):
            self.service()

    def test_child_patch_cannot_be_replayed_by_parent_with_new_id_or_json_order(self):
        self.primary = 'cloud'
        self.cloud = Backend(answer(None, spawn('local')),
            answer(None, call('apply_patch', {'changes': [{'content': 'proof', 'operation': 'create', 'path': 'once.txt'}]}, 'new-parent-id')),
            answer(None, call('read_file', {'path': 'once.txt'}, 'fresh')), answer('verified'))
        self.local = Local(patch('once.txt'), answer('child'))
        r = self.factory(); count = []; original = r.registry._tools['apply_patch']
        def forbidden(**args):
            count.append(args); return original(**args)
        r.registry._tools['apply_patch'] = forbidden
        self.assertEqual(r.run_turn('work').status, 'completed')
        self.assertFalse(count)
        reused = [x for x in r.tool_history if x['id'] == 'new-parent-id'][0]
        self.assertTrue(reused['receipt_reused'])
        self.assertFalse(reused['payload']['result']['action_sent'])
        self.assertEqual((self.workspace/'once.txt').read_text(), 'proof')

    def test_semantic_dedup_does_not_cross_tasks_or_allow_changed_mutation(self):
        self.local = Local(patch('once.txt'), answer('first'), patch('other.txt'), answer('second'))
        r = self.factory(); r.run_turn('first')
        self.assertIsNone(r.hybrid.completed_patch({'changes': [{'operation': 'create', 'path': 'once.txt', 'content': 'different'}]}))
        r.run_turn('second')
        self.assertIsNone(r.hybrid.completed_patch({'changes': [{'operation': 'create', 'path': 'once.txt', 'content': 'proof'}]}))

    def test_failed_small_context_switch_is_denied_without_closing_local_session(self):
        self.cloud.model_info = replace(self.cloud.model_info, effective_context=12000)
        self.local = Local(answer(None, call('request_model_switch', {'target': 'cloud', 'reason': 'review', 'task_complexity': 'complex'}, 's')), answer('continue local safely'))
        r = self.factory(); r.run_turn('work'); result = r.approve()
        self.assertEqual(result.status, 'completed')
        self.assertEqual(r.hybrid.state['backend_id'], 'local')
        self.assertFalse(self.cloud.requests)

    def test_provider_resource_abort_is_typed_and_has_no_executable_response(self):
        from tests.test_local_http_backend import MockServer
        server = MockServer()
        try:
            server.add({'error': {'code': 'prefill_memory_aborted', 'message': 'Provider body must not be echoed'}})
            backend = LocalHTTPBackend(base_url=server.base_url, model='mock-local', size_class='35B', effective_context=65536)
            with self.assertRaises(LocalResourceExhausted) as caught:
                backend.request([Message('user', 'work')])
            self.assertTrue(caught.exception.retryable)
            self.assertIsNone(caught.exception.response)
            self.assertNotIn('Provider body', str(caught.exception))
        finally:
            server.close()

    def test_resource_abort_can_escalate_without_mutation_replay(self):
        self.policy = replace(self.policy, automatic_failover=True)
        self.local = Local(patch('once.txt'), LocalResourceExhausted('Controlled local resource admission', retryable=True))
        r = self.factory(); self.assertEqual(r.run_turn('work').status, 'completed')
        self.assertEqual(r.hybrid.state['backend_id'], 'cloud')
        self.assertEqual(len(r.tool_history), 1)
        self.assertEqual(r.hybrid.summary()['by_backend']['local']['unknown_usage_calls'], 1)

    def test_backend_admission_serializes_local_and_keeps_cloud_parallel(self):
        self.async_policy = AsyncPolicy(max_model_requests=2, max_local_model_requests=1, max_cloud_model_requests=1)
        intervals = []
        lock = threading.Lock()
        active = {'local': 0, 'cloud': 0}; peak = {'local': 0, 'cloud': 0, 'all': 0}
        def work(kind):
            start = time.monotonic()
            with lock:
                active[kind] += 1; peak[kind] = max(peak[kind], active[kind]); peak['all'] = max(peak['all'], sum(active.values()))
            time.sleep(.12)
            with lock:
                active[kind] -= 1; intervals.append((kind, start, time.monotonic()))
            return answer('child complete')
        class RoutedLocal(Local):
            def request(this, messages, **kwargs):
                from benchmarks.hybrid_runtime import handoff
                goal = handoff(messages)['current_goal']
                if goal == 'controlled work':
                    if not any(c.name == 'delegate' for m in messages for c in m.tool_calls):
                        return answer(None, spawn('cloud', task='C', id='c', read_only=True, async_=True),
                            spawn('local', task='L1', id='l1', read_only=True, async_=True),
                            spawn('local', task='L2', id='l2', read_only=True, async_=True))
                    return answer('parent complete')
                return work('local')
        self.local = RoutedLocal(); self.cloud = Backend(lambda m: work('cloud'))
        r = self.factory(); self.assertEqual(r.run_turn('controlled work').status, 'approval_required')
        self.assertEqual(r.approve().status, 'completed')
        self.assertEqual(peak, {'local': 1, 'cloud': 1, 'all': 2})
        local_intervals = sorted((s, e) for k, s, e in intervals if k == 'local')
        self.assertGreaterEqual(local_intervals[1][0], local_intervals[0][1])

    def test_optional_backend_limits_preserve_old_policy_fingerprint(self):
        from agent.async_runtime import policy_snapshot
        original = policy_snapshot(AsyncPolicy())
        self.assertNotIn('max_local_model_requests', original)
        self.assertNotIn('max_cloud_model_requests', original)
        limited = policy_snapshot(AsyncPolicy(max_local_model_requests=1))
        self.assertEqual(limited['max_local_model_requests'], 1)

    def test_local_adapter_bearer_credential_cannot_leave_in_cloud_context(self):
        self.primary = 'cloud'; self.local._api_key = 'SENTINEL_LOCAL_AUTH_VALUE_654321'
        r = self.factory()
        with self.assertRaises(CloudEgressDenied):
            r.hybrid.authorize([Message('user', self.local._api_key)], [])
        self.assertNotIn(self.local._api_key, json.dumps(r.hybrid.state['egress']))

    def test_unqualified_external_mutation_cannot_dispatch_or_claim_completed(self):
        self.local = Local(answer(None, call('execute', {'argv': ['true']}, 'external')), answer('claimed complete'))
        r = self.factory(); r.registry.gateway.capabilities = CapabilityPolicy(execute=True)
        sent = []
        r.registry._tools['execute'] = lambda **kw: sent.append(kw) or {'status': 'ok'}
        result = r.run_turn('run the external command')
        self.assertEqual(result.status, 'incomplete')
        self.assertFalse(sent)
        self.assertFalse(r.tool_history[0]['payload']['result']['action_sent'])
        self.assertEqual(r.tool_history[0]['side_effect_status'], 'not_completed')
