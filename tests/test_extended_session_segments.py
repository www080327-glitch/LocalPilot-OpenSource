"""Completed Computer/Adaptive turns archive through the normal service transaction."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from agent.adaptive import AdaptivePolicy, TaskTraits
from agent.engine_v5 import EngineV5Policy
from agent.hybrid import CloudEgressPolicy, HybridPolicy
from agent.persistence import PersistenceError, backend_identity, snapshot_runtime
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets
from computer.native_macos import ComputerScope, NativeComputerRuntime, NativeMacOSBackend
from localpilot_api.service import TaskRequest, TaskService
from tests.test_native_computer_use import NativeTransport
from tests.test_computer_runtime import APP, condition
from tests.test_runtime_api import Backend, answer, call


class ExtendedSessionSegmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.backend = Backend(*(answer('completed') for _ in range(40)))
        self.mode = 'adaptive'
        self.services = []
        self.addCleanup(self.close_services)

    def close_services(self):
        for service in reversed(self.services):
            if service.store.failed:
                service.store.close()
            elif not service.closed:
                service.shutdown()

    def factory(self, callback):
        options = {}
        if self.mode == 'adaptive':
            options = {'hybrid_policy': HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED')),
                'hybrid_backends': {'cloud': self.backend}, 'hybrid_primary': 'cloud',
                'adaptive_policy': AdaptivePolicy(mode='automatic', allowed_categories=('file',), model_lock='cloud'),
                'task_traits': TaskTraits(),
                'capability_profiles': {'version': 1, 'models': {'cloud': {
                    'identity': backend_identity(self.backend), 'available': True,
                    'categories': {'file': {'samples': 2, 'successes': 2, 'median_cloud_cost_usd': .001}}}}}}
        else:
            directory = self.root / 'computer'
            directory.mkdir(mode=0o700, exist_ok=True)
            native = NativeComputerRuntime(NativeMacOSBackend([APP], directory / 'control', transport=NativeTransport()),
                scopes=[ComputerScope(APP, ('Test',), background=True)],
                evidence_directory=directory, verification_timeout=0)
            native.cloud_egress = CloudEgressPolicy('CLOUD_ALLOWED')
            options['computer_runtime'] = native
        return AgentSession(create_default_registry(self.workspace, permission_mode='full-permission'),
            backend=self.backend, policy='cloud-only', streaming=False, event_callback=callback,
            engine_policy=EngineV5Policy(max_completion_repairs=0), retry_policy=RetryPolicy(max_attempts=1),
            budgets=SessionBudgets(max_steps=12, max_tool_calls=20, max_token_units=1000000, max_output_tokens=512),
            **options)

    def service(self):
        service = TaskService({'localpilot': self.factory}, persistence=self.root / 'runtime.sqlite3',
                              history_rotation_bytes=1)
        self.services.append(service)
        return service

    def task(self, service, text, sid=None):
        task = service.wait(service.create_task(TaskRequest(text, session_id=sid))['id'])
        self.assertEqual(task['status'], 'completed', task.get('error') or task['result'])
        return task

    def test_adaptive_decisions_cost_reservations_and_lock_survive_rotation_and_restart(self):
        service = self.service()
        first = self.task(service, 'first')
        sid = first['session_id']
        self.task(service, 'second', sid)
        before = snapshot_runtime(service.sessions[sid].runtime)
        self.task(service, 'third', sid)
        runtime = service.sessions[sid].runtime
        self.assertEqual(service.store.runtime_segment(sid, 0)['runtime'], before)
        self.assertEqual([d['key']['turn'] for d in runtime.adaptive.state['decisions']], [2, 3])
        self.assertEqual({r['turn'] for r in runtime.adaptive.state['cloud_reservations']}, {2, 3})
        self.assertGreater(runtime.adaptive.spent(), 0)
        self.assertTrue(all(d['selected'] == 'cloud' for d in runtime.adaptive.state['decisions']))
        state, spent = deepcopy(runtime.adaptive.state), runtime.adaptive.spent()
        service.suspend()
        service = self.service()
        runtime = service.sessions[sid].runtime
        self.assertEqual(runtime.adaptive.state, state)
        self.assertEqual(runtime.adaptive.spent(), spent)
        self.assertEqual(service.task_snapshot(first['id']), first)
        self.task(service, 'fourth', sid)
        self.assertEqual([d['key']['turn'] for d in runtime.adaptive.state['decisions']], [3, 4])

    def test_adaptive_rotation_failure_restores_live_state_and_durable_latest_turn(self):
        service = self.service()
        sid = self.task(service, 'first')['session_id']
        self.task(service, 'second', sid)
        runtime = service.sessions[sid].runtime
        before = snapshot_runtime(runtime)

        def fail(stage, point):
            if stage == 'before_commit' and point == 'history_rotated':
                raise OSError('injected transaction failure')

        service.store.fault_hook = fail
        with self.assertRaises(PersistenceError):
            service.create_task(TaskRequest('third', session_id=sid))
        self.assertEqual(snapshot_runtime(runtime), before)
        service.store.close()
        restored = self.service()
        self.assertEqual(restored.sessions[sid].runtime.adaptive.state, runtime.adaptive.state)
        self.assertEqual(restored.store.runtime_segments(sid), [])

    def test_computer_rotation_preserves_live_observation_and_restart_requires_reobservation(self):
        self.mode = 'computer'
        self.backend.steps = [answer(None, call('inspect_tree', {'app': APP}, 'first-read')), answer('first'),
                              answer(None, call('inspect_tree', {'app': APP}, 'second-read')), answer('second'), answer('third')]
        service = self.service()
        first = self.task(service, 'first')
        sid = first['session_id']
        self.task(service, 'second', sid)
        runtime = service.sessions[sid].runtime
        before = snapshot_runtime(runtime)
        observations, revision = deepcopy(runtime.computer.observations), runtime.computer.revision
        self.task(service, 'third', sid)
        self.assertEqual(service.store.runtime_segment(sid, 0)['runtime'], before)
        self.assertEqual(runtime.computer.observations, observations)
        self.assertEqual(runtime.computer.revision, revision)
        self.assertEqual({r['turn_id'] for r in runtime.tool_history}, {2})
        service.suspend()
        restored = self.service()
        runtime = restored.sessions[sid].runtime
        self.assertTrue(runtime.computer.paused)
        self.assertFalse(runtime.computer.observations)
        self.assertEqual(runtime.computer.revision, revision + 1)
        self.assertEqual(restored.task_snapshot(first['id']), first)
        result = runtime.registry.call('set_value', {'app': APP, 'element': 'input',
            'observation': observations[APP]['token'], 'value': 'new', 'postcondition': condition()})
        self.assertFalse(result.get('action_sent', False))
        self.assertEqual(runtime.computer.backend.transport.sent, 0)

    def test_computer_paused_or_unknown_journal_prevents_rotation(self):
        self.mode = 'computer'
        service = self.service()
        sid = self.task(service, 'first')['session_id']
        self.task(service, 'second', sid)
        session = service.sessions[sid]
        self.assertIsNotNone(service._history_rotation(session))
        session.runtime.take_over_computer()
        self.assertIsNone(service._history_rotation(session))
        session.runtime.computer.resume()
        session.runtime.computer.journal.begin(APP, {'action': 'pending native operation'})
        self.assertIsNone(service._history_rotation(session))
        self.assertEqual(service.store.runtime_segments(sid), [])
