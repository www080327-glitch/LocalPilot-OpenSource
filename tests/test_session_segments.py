"""Completed-turn rotation over real AgentSession, tools and SQLite transactions."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.backends import ModelInfo
from agent.engine_v5 import EngineV5Policy
from agent.hybrid import CloudEgressPolicy, HybridPolicy
from agent.persistence import PersistenceError, SQLiteRuntimeStore, digest, dumps, snapshot_runtime
from agent.registry import ToolRegistry, create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets
from agent.session_types import SessionState
from localpilot_api.service import APIError, TaskRequest, TaskService
from localpilot_service.deployment import build
from tests.test_local_http_backend import MockServer, completion
from tests.test_runtime_api import Backend, answer, call


class SessionSegmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        (self.workspace / 'fact.txt').write_text('EXACT-RETAINED-FACT')
        self.path = self.root / 'runtime.sqlite3'
        self.backend = Backend(*(answer(str(i)) for i in range(100)))
        self.services = []
        self.permission = 'full-permission'
        self.engine = True
        self.egress = None
        self.worker = None
        self.tools = True
        self.runtime_events = 2000

    def tearDown(self):
        for service in self.services:
            if service.store and service.store.failed:
                service.store.close()
            elif not service.closed:
                service.shutdown()
        self.temp.cleanup()

    def factory(self, callback):
        registry = (create_default_registry if self.tools else ToolRegistry)(
            self.workspace, permission_mode=self.permission)
        hybrid = {}
        if self.egress:
            self.backend.service_cache_stable_prefix = True
            hybrid = {'hybrid_policy': HybridPolicy(CloudEgressPolicy(self.egress, ('fact.txt',))),
                      'hybrid_backends': {'cloud': self.backend}, 'hybrid_primary': 'cloud'}
        runtime = AgentSession(registry, backend=self.backend, policy='cloud-only', streaming=False,
            event_callback=callback, retry_policy=RetryPolicy(max_attempts=1),
            engine_policy=EngineV5Policy(max_completion_repairs=0) if self.engine else None,
            budgets=SessionBudgets(max_steps=12, max_tool_calls=20, max_token_units=1000000,
                                  max_output_tokens=512),
            cloud_worker_backends={'LIGHT': self.worker} if self.worker else None, **hybrid)
        runtime.events.max_events = self.runtime_events
        return runtime

    def service(self, **options):
        service = TaskService({'localpilot': self.factory}, persistence=self.path,
                             history_rotation_bytes=options.pop('history_rotation_bytes', 1), **options)
        self.services.append(service)
        return service

    def run_task(self, service, request):
        return service.wait(service.create_task(request)['id'])

    def test_rotation_preserves_exact_prefix_receipts_guidance_and_frozen_tasks_after_restart(self):
        self.backend = Backend(answer(None, call('read_file', {'path': 'fact.txt'}, 'read')),
            answer('first fact'), answer(None, call('read_file', {'path': 'fact.txt'}, 'read')),
            answer('second fact'), answer('third'), answer('fourth'))
        service = self.service()
        original = TaskRequest('first question', idempotency_key='first')
        first = self.run_task(service, original)
        sid = first['session_id']
        first_events = service.events(first['id'], wait_seconds=0)[0]
        first_payload = service._task_payload(service._task(first['id']))
        second = self.run_task(service, TaskRequest('second question', session_id=sid,
                               instructions='Keep this exact current-turn guidance.', idempotency_key='second'))
        second_payload = service._task_payload(service._task(second['id']))
        before = snapshot_runtime(service.sessions[sid].runtime)
        prefix = deepcopy(self.backend.requests[-1]['messages'])
        third = self.run_task(service, TaskRequest('third question', session_id=sid))
        self.assertEqual(third['status'], 'completed')
        segment = service.store.runtime_segment(sid, 0)
        self.assertEqual(segment['runtime'], before)
        self.assertEqual(segment['last_turn'], 2)
        runtime = service.sessions[sid].runtime
        self.assertNotIn('first question', [message.content for message in runtime.messages])
        self.assertTrue(any('exact current-turn guidance' in (message.content or '') for message in runtime.messages))
        self.assertEqual(prefix, self.backend.requests[-1]['messages'][:len(prefix)])
        self.assertEqual(service.task_snapshot(first['id']), first)
        self.assertEqual(service.events(first['id'], wait_seconds=0)[0], first_events)
        self.assertEqual(service._task_payload(service._task(first['id'])), first_payload)
        self.assertEqual(service._task_payload(service._task(second['id'])), second_payload)
        self.assertNotIn(first['id'], service.tasks)
        self.assertEqual(service.sessions[sid].history_generation, 1)
        latest_snapshot = snapshot_runtime(runtime)
        latest_prefix = deepcopy(self.backend.requests[-1]['messages'])
        service.suspend()
        service = self.service()
        restored = snapshot_runtime(service.sessions[sid].runtime)
        self.assertEqual(restored['delivery'], latest_snapshot['delivery'])
        self.assertEqual(restored['request_history'], latest_snapshot['request_history'])
        calls = len(self.backend.requests)
        self.assertEqual(service.create_task(original), first)
        self.assertEqual(len(self.backend.requests), calls)
        fourth = self.run_task(service, TaskRequest('fourth question', session_id=sid))
        self.assertEqual(fourth['status'], 'completed')
        self.assertEqual(latest_prefix, self.backend.requests[-1]['messages'][:len(latest_prefix)])
        self.assertEqual(service.sessions[sid].runtime.turn_id, 4)
        self.assertEqual(service.task_snapshot(first['id']), first)
        self.assertEqual(service.task_snapshot(third['id']), third)

    def test_cloud_hybrid_rotation_keeps_current_budget_and_admitted_window(self):
        self.egress = 'CLOUD_ALLOWED'
        service = self.service()
        first = self.run_task(service, TaskRequest('first'))
        sid = first['session_id']
        self.run_task(service, TaskRequest('second', session_id=sid))
        before = snapshot_runtime(service.sessions[sid].runtime)
        prefix = deepcopy(self.backend.requests[-1]['messages'])
        third = self.run_task(service, TaskRequest('third', session_id=sid))
        runtime = service.sessions[sid].runtime
        self.assertEqual(third['status'], 'completed')
        self.assertEqual(service.store.runtime_segment(sid, 0)['runtime'], before)
        self.assertEqual([attempt['turn_id'] for attempt in runtime.hybrid.state['attempts']], [2, 3])
        self.assertEqual([attempt['id'] for attempt in runtime.hybrid.state['attempts']], [1, 2])
        self.assertEqual([entry['turn_id'] for entry in runtime.hybrid.state['egress']], [2, 3])
        self.assertEqual(runtime.hybrid.summary()['calls'], 1)
        self.assertEqual(prefix, self.backend.requests[-1]['messages'][:len(prefix)])
        state = deepcopy(runtime.hybrid.state)
        service.suspend()
        service = self.service()
        self.assertEqual(service.sessions[sid].runtime.hybrid.state, state)
        self.run_task(service, TaskRequest('fourth', session_id=sid))
        self.assertEqual([attempt['id'] for attempt in service.sessions[sid].runtime.hybrid.state['attempts']], [2, 3])

    def test_small_context_rotations_bound_active_history_and_checkpoint(self):
        self.tools = False
        self.runtime_events = 30
        self.backend = Backend(*(answer('old observation ' * 90) for _ in range(40)))
        self.backend.model_info = ModelInfo('small-scripted', 'scripted', 5500)
        service = self.service(max_events=30, history_rotation_bytes=12000)
        sid = service.create_session()['id']
        runtime = service.sessions[sid].runtime
        for detail in ('unfinished exact cancellation receipt', 'unfinished exact Intel check',
                       'unfinished exact child outcome', 'unfinished exact focus restoration'):
            runtime.goals.create(detail, status='blocked')
        goals = deepcopy(runtime._goal_records())
        for index in range(40):
            task = self.run_task(service, TaskRequest(f'{index}: ' + 'specific original requirement ' * 60,
                                                     session_id=sid, idempotency_key=str(index)))
            self.assertEqual(task['status'], 'incomplete')
            self.assertEqual(runtime._goal_records(), goals)
            self.assertLessEqual(len(runtime.messages), 7)
            self.assertLessEqual(len(service.tasks), 3)
        self.assertGreater(service.sessions[sid].history_generation, 30)
        self.assertTrue(any(event.type == 'ContextCompacted' for event in runtime.events.events))
        raw = service.store.connection.execute('SELECT payload FROM checkpoints WHERE session_id=?', (sid,)).fetchone()[0]
        self.assertLess(len(raw.encode()), 100000)
        self.assertEqual(service.task_snapshot(service.task_for_key(digest('0')).id)['user_input'],
                         '0: ' + 'specific original requirement ' * 60)
        segment_count = service.store.connection.execute('SELECT count(*) FROM runtime_segments').fetchone()[0]
        self.assertEqual(segment_count, service.sessions[sid].history_generation)

    def test_threshold_counts_utf8_bytes_and_does_not_rotate_below_limit(self):
        service = self.service(history_rotation_bytes=10**9)
        first = self.run_task(service, TaskRequest('旧内容' * 300))
        sid = first['session_id']
        self.run_task(service, TaskRequest('最新问题', session_id=sid))
        self.assertEqual(service.store.runtime_segments(sid), [])
        raw = dumps(snapshot_runtime(service.sessions[sid].runtime))
        service.history_rotation_bytes = len(raw) + 1
        self.assertGreater(len(raw.encode()), service.history_rotation_bytes)
        self.run_task(service, TaskRequest('下一轮', session_id=sid))
        self.assertEqual(service.sessions[sid].history_generation, 1)

    def test_latest_completed_child_and_its_finalization_survive_rotation(self):
        delegate = lambda identity: answer(None, call('delegate', {'task': 'Read fact.txt',
            'backend_preference': 'cloud', 'tier': 'LIGHT', 'read_only': True}, identity))
        self.backend = Backend(delegate('child-one'), answer('first collected'),
                               delegate('child-two'), answer('second collected'), answer('third'))
        self.worker = Backend(answer(None, call('read_file', {'path': 'fact.txt'}, 'read')),
                              answer('first child fact'), answer(None, call('read_file', {'path': 'fact.txt'}, 'read')),
                              answer('second child fact'))
        service = self.service()
        first = self.run_task(service, TaskRequest('first child task'))
        sid = first['session_id']
        second = self.run_task(service, TaskRequest('second child task', session_id=sid))
        runtime = service.sessions[sid].runtime
        child_ids = list(runtime._children)
        self.assertEqual(len(child_ids), 2)
        self.assertEqual(first['status'], 'completed')
        self.assertEqual(second['status'], 'completed')
        self.run_task(service, TaskRequest('third task', session_id=sid))
        self.assertEqual(list(runtime._children), child_ids[-1:])
        self.assertEqual(runtime._children[child_ids[-1]].state, SessionState.SESSION_FINISHED)
        self.assertEqual(set(service.store.runtime_segment(sid, 0)['runtime']['children']), set(child_ids))
        self.assertEqual(service.children(first['id']), first['subagents'])
        self.assertEqual(service.children(second['id']), second['subagents'])
        service.suspend()
        service = self.service()
        self.assertEqual(list(service.sessions[sid].runtime._children), child_ids[-1:])
        self.assertEqual(service.task_snapshot(first['id']), first)

    def test_pending_approval_does_not_rotate_or_archive_active_work(self):
        self.permission = 'approve-mutations'
        self.backend = Backend(answer('one'), answer('two'), answer(None, call('apply_patch', {'changes': [
            {'path': 'pending.txt', 'operation': 'create', 'content': 'pending'}]}, 'pending')))
        service = self.service(history_rotation_bytes=10**9)
        first = self.run_task(service, TaskRequest('first'))
        sid = first['session_id']
        self.run_task(service, TaskRequest('second', session_id=sid))
        pending = self.run_task(service, TaskRequest('needs approval', session_id=sid))
        self.assertEqual(pending['status'], 'requires_approval')
        service.history_rotation_bytes = 1
        before = snapshot_runtime(service.sessions[sid].runtime)
        with self.assertRaises(APIError) as blocked:
            service.create_task(TaskRequest('new', session_id=sid))
        self.assertEqual(blocked.exception.code, 'session_busy')
        self.assertEqual(snapshot_runtime(service.sessions[sid].runtime), before)
        self.assertEqual(service.store.runtime_segments(sid), [])
        self.assertFalse((self.workspace / 'pending.txt').exists())

    def test_unknown_real_mutation_remains_blocked_without_rotation(self):
        self.backend = Backend(answer('one'), answer('two'), answer(None, call('apply_patch', {'changes': [
            {'path': 'uncertain.txt', 'operation': 'create', 'content': 'written once'}]}, 'uncertain')))
        service = self.service(history_rotation_bytes=10**9)
        first = self.run_task(service, TaskRequest('first'))
        sid = first['session_id']
        self.run_task(service, TaskRequest('second', session_id=sid))
        registry = service.sessions[sid].runtime.registry
        apply_patch = registry._tools['apply_patch']
        def lose_receipt(**kwargs):
            apply_patch(**kwargs)
            raise TimeoutError('receipt unavailable after the real write')
        registry._tools['apply_patch'] = lose_receipt
        pending = self.run_task(service, TaskRequest('uncertain write', session_id=sid))
        self.assertEqual(pending['status'], 'requires_human')
        service.history_rotation_bytes = 1
        before = snapshot_runtime(service.sessions[sid].runtime)
        with self.assertRaises(APIError):
            service.create_task(TaskRequest('new', session_id=sid))
        self.assertEqual(snapshot_runtime(service.sessions[sid].runtime), before)
        self.assertEqual(service.store.runtime_segments(sid), [])
        self.assertEqual((self.workspace / 'uncertain.txt').read_text(), 'written once')

    def test_exact_egress_grants_remain_unmodified_during_rotation_and_restart(self):
        self.egress = 'REQUIRES_APPROVAL'
        service = self.service()
        sid = service.create_session()['id']
        for index in range(3):
            pending = self.run_task(service, TaskRequest(str(index), session_id=sid))
            self.assertEqual(pending['status'], 'requires_approval')
            service.act(pending['id'], 'approve', pending['required_action']['id'])
            self.assertEqual(service.wait(pending['id'])['status'], 'completed')
        self.assertEqual(len(service.sessions[sid].runtime.hybrid.state['grants']), 3)
        self.assertEqual(len(service.store.runtime_segments(sid)), 1)
        archived = service.store.runtime_segment(sid, 0)['runtime']['hybrid']['state']['grants']
        self.assertEqual(archived, service.sessions[sid].runtime.hybrid.state['grants'][:2])
        grants = deepcopy(service.sessions[sid].runtime.hybrid.state['grants'])
        service.suspend()
        service = self.service()
        self.assertEqual(service.sessions[sid].runtime.hybrid.state['grants'], grants)

    def test_fault_before_and_after_commit_preserves_history_and_never_replays(self):
        for stage in ('before_commit', 'after_commit'):
            with self.subTest(stage=stage):
                self.path = self.root / (stage + '.sqlite3')
                filename = stage + '.txt'
                self.backend = Backend(answer(None, call('apply_patch', {'changes': [
                    {'path': filename, 'operation': 'create', 'content': 'once'}]}, 'write')),
                    answer('first'), answer('second'), answer('third'))
                self.egress = 'CLOUD_ALLOWED'
                service = self.service()
                original = TaskRequest('first', idempotency_key=stage)
                first = self.run_task(service, original)
                sid = first['session_id']
                self.run_task(service, TaskRequest('second', session_id=sid))
                before = snapshot_runtime(service.sessions[sid].runtime)
                prefix = deepcopy(self.backend.requests[-1]['messages'])
                calls = len(self.backend.requests)
                def fail(current, point):
                    if current == stage and point == 'history_rotated':
                        raise OSError('injected rotation storage failure')
                service.store.fault_hook = fail
                with self.assertRaises(PersistenceError):
                    service.create_task(TaskRequest('third', session_id=sid))
                self.assertTrue(service.store.failed)
                self.assertEqual(snapshot_runtime(service.sessions[sid].runtime), before)
                self.assertEqual(len(self.backend.requests), calls)
                service.store.close()
                service = self.service()
                self.assertEqual(service.sessions[sid].history_generation, int(stage == 'after_commit'))
                self.assertEqual(service.create_task(original), first)
                self.assertEqual(len(self.backend.requests), calls)
                third = self.run_task(service, TaskRequest('third', session_id=sid))
                self.assertEqual(third['status'], 'completed')
                self.assertEqual(service.sessions[sid].history_generation, 1)
                self.assertEqual(service.store.runtime_segment(sid, 0)['runtime'], before)
                self.assertEqual(prefix, self.backend.requests[-1]['messages'][:len(prefix)])
                self.assertEqual((self.workspace / filename).read_text(), 'once')
                self.assertEqual(service.task_snapshot(first['id']), first)

    def test_older_session_without_start_metadata_retains_last_whole_turn(self):
        service = self.service(history_rotation_bytes=10**9)
        first = self.run_task(service, TaskRequest('first'))
        sid = first['session_id']
        self.run_task(service, TaskRequest('second', session_id=sid))
        payload = service.store.load()[0]
        payload['session'].pop('history_generation')
        payload['session'].pop('context_start')
        service.suspend()
        legacy_store = SQLiteRuntimeStore(self.path)
        try:
            legacy_store.save(sid, payload, 'older_session_fixture')
        finally:
            legacy_store.close()
        service = self.service()
        self.run_task(service, TaskRequest('third', session_id=sid))
        self.assertEqual(service.sessions[sid].history_generation, 1)
        self.assertIn('second', [message.content for message in service.sessions[sid].runtime.messages])

    def test_deployment_factory_default_hybrid_rotates_and_restores_over_http_backend(self):
        model = MockServer()
        self.addCleanup(model.close)
        for number in range(4):
            model.add(completion('reply ' + str(number)))
        config = {'schema_version': 1, 'port': 0, 'data_dir': str(self.root / 'deployed'),
            'clients': [{'subject': 'fixture', 'token_env': 'LP_SEGMENT_FIXTURE'}],
            'routes': {'localpilot': {'workspace': str(self.workspace), 'engine': 'v5',
                'permissions': 'approve-mutations', 'cache_stable_prefix': True,
                'backend': {'kind': 'local-openai', 'base_url': model.base_url, 'model': 'mock-local',
                            'capabilities': {'streaming': False, 'tool_calling': True}},
                'budgets': {'max_output_tokens': 512}}}}
        path = self.root / 'service.json'
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        with patch.dict(os.environ, LP_SEGMENT_FIXTURE='s' * 32):
            server = build(path)
            try:
                service = server.service
                self.services.append(service)
                service.history_rotation_bytes = 1
                first = self.run_task(service, TaskRequest('first deployed'))
                sid = first['session_id']
                self.assertIsNotNone(service.sessions[sid].runtime.hybrid)
                self.assertEqual(service.sessions[sid].runtime.hybrid.policy.egress.mode, 'LOCAL_ONLY')
                self.run_task(service, TaskRequest('second deployed', session_id=sid))
                prefix = deepcopy(model.requests[-1]['messages'])
                third = self.run_task(service, TaskRequest('third deployed', session_id=sid))
                self.assertEqual(third['status'], 'completed', third.get('error'))
                self.assertEqual(service.sessions[sid].history_generation, 1)
                self.assertEqual(prefix, model.requests[-1]['messages'][:len(prefix)])
                service.suspend()
            finally:
                server.server_close()
                server.access.close()
            server = build(path)
            try:
                service = server.service
                self.services.append(service)
                service.history_rotation_bytes = 1
                self.assertEqual(service.sessions[sid].history_generation, 1)
                self.assertEqual(service.task_snapshot(first['id']), first)
                fourth = self.run_task(service, TaskRequest('fourth deployed', session_id=sid))
                self.assertEqual(fourth['status'], 'completed', fourth.get('error'))
                self.assertEqual(service.sessions[sid].history_generation, 2)
                self.assertEqual(len(model.requests), 4)
            finally:
                server.server_close()
                server.access.close()


if __name__ == '__main__':
    unittest.main()
