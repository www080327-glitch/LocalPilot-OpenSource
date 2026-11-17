"""V5 model windows over real sessions, tools and SQLite; scripted model output."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from agent.backends import ModelInfo
from agent.context_budget import request_budget
from agent.engine_v5 import EngineV5Policy
from agent.hybrid import CloudEgressPolicy, HybridPolicy
from agent.persistence import PersistenceError, restore_runtime, snapshot_runtime
from agent.registry import ToolRegistry, create_default_registry
from agent.session import AgentSession, SessionBudgets
from localpilot_api.service import TaskRequest, TaskService
from localpilot_service.desktop_sessions import apply_options
from tests.test_runtime_api import Backend, answer, call


class RequestHistoryTests(unittest.TestCase):
    def runtime(self, root, backend, *, egress=None, tools=True, policy=None):
        registry = create_default_registry(root) if tools else ToolRegistry(root)
        options = {}
        if egress:
            backend.service_cache_stable_prefix = True
            options = {'hybrid_policy': HybridPolicy(egress),
                       'hybrid_backends': {'cloud': backend}, 'hybrid_primary': 'cloud'}
        session = AgentSession(registry, backend=backend, policy='cloud-only', streaming=False,
            engine_policy=policy or EngineV5Policy(), runtime_tools=tools,
            budgets=SessionBudgets(max_steps=12, max_token_units=1000000, max_output_tokens=512),
            **options)
        self.addCleanup(session.close)
        return session

    def test_real_tool_turn_extends_exact_request_without_polluting_canonical_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'note.txt').write_text('EXACT-OBSERVED-FACT')
            backend = Backend(answer(None, call('read_file', {'path': 'note.txt'}, 'read')),
                              answer(None, call('list_directory', {'path': '.'}, 'list')),
                              answer('done'))
            runtime = self.runtime(root, backend, egress=CloudEgressPolicy('CLOUD_ALLOWED', ('note.txt',)))
            result = runtime.run_turn('Read the note and inspect its directory.')
            self.assertEqual(result.status, 'completed')
            self.assertEqual(len(backend.requests), 3)
            for first, second in zip(backend.requests, backend.requests[1:]):
                self.assertEqual(first['messages'], second['messages'][:len(first['messages'])])
            self.assertTrue(any(m.role == 'tool' and 'EXACT-OBSERVED-FACT' in m.content
                                for m in backend.requests[1]['messages']))
            self.assertEqual([m.content for m in runtime.messages if m.role == 'user'],
                             ['Read the note and inspect its directory.'])
            self.assertEqual(len(runtime.tool_history), 2)
            self.assertEqual(runtime._request_history.messages, backend.requests[-1]['messages'])

    def test_sqlite_restart_keeps_dispatched_window_and_appends_new_turn(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace = root / 'workspace'
            workspace.mkdir()
            backend = Backend(answer('first reply'), answer('second reply'))
            factory = lambda callback: self.runtime(workspace, backend,
                egress=CloudEgressPolicy('CLOUD_ALLOWED'))
            service = TaskService({'localpilot': factory}, persistence=root / 'runtime.sqlite3')
            first = service.create_task(TaskRequest('first question', idempotency_key='one'))
            service.wait(first['id'])
            first_view = deepcopy(backend.requests[0]['messages'])
            service.suspend()
            service = TaskService({'localpilot': factory}, persistence=root / 'runtime.sqlite3')
            try:
                second = service.create_task(TaskRequest('second question', session_id=first['session_id'],
                                                        idempotency_key='two'))
                service.wait(second['id'])
                self.assertEqual(first_view, backend.requests[1]['messages'][:len(first_view)])
                self.assertTrue(any(m.role == 'assistant' and m.content == 'first reply'
                                    for m in backend.requests[1]['messages']))
            finally:
                service.shutdown()

    def test_repeated_compaction_keeps_full_pending_goals_and_bounds_only_model_window(self):
        with tempfile.TemporaryDirectory() as folder:
            backend = Backend(*(answer('observation-' + str(i) + ': ' + 'evidence ' * 110)
                                for i in range(40)))
            backend.model_info = ModelInfo('bounded-fixture', 'scripted', 5500)
            runtime = self.runtime(Path(folder), backend, tools=False,
                                   policy=EngineV5Policy(max_completion_repairs=0))
            for index, detail in enumerate(('missing cancellation receipt', 'unverified file hash',
                                           'Intel native interaction', 'Companion focus restoration')):
                runtime.goals.create(f'Problem {index}: {detail}; exact next action is retained.', status='blocked')
            goals = deepcopy(runtime._goal_records())
            task = 'Continue all four unresolved checks with these exact details: ' + 'specific input ' * 85
            for _ in range(40):
                self.assertEqual(runtime.run_turn(task).status, 'incomplete')
            compacted = [event for event in runtime.events.events if event.type == 'ContextCompacted']
            self.assertGreaterEqual(len(compacted), 3)
            for request in backend.requests:
                state = json.loads(request['messages'][-1].content.split('\n', 1)[1])
                self.assertEqual(state['original_task'], task)
                self.assertEqual(state['goals'], goals)
                self.assertLessEqual(request_budget(request['messages'], request['tools'],
                                                    request['max_tokens'])['total_tokens'], 5500)
            self.assertEqual(len(runtime.messages), 81)
            self.assertLess(len(runtime._request_history.messages), 20)
            self.assertTrue(any(m.content and 'observation-0:' in m.content for m in runtime.messages))
            self.assertFalse(any(m.content and 'observation-0:' in m.content
                                 for m in runtime._request_history.messages))

    def test_rejected_egress_does_not_advance_dispatched_context(self):
        with tempfile.TemporaryDirectory() as folder:
            backend = Backend(answer('first reply'))
            runtime = self.runtime(Path(folder), backend, egress=CloudEgressPolicy('CLOUD_ALLOWED'))
            self.assertEqual(runtime.run_turn('public first').status, 'completed')
            before = runtime._request_history.snapshot()
            runtime.hybrid.policy = replace(runtime.hybrid.policy, egress=CloudEgressPolicy('REQUIRES_APPROVAL'))
            self.assertEqual(runtime.run_turn('public second').status, 'approval_required')
            self.assertEqual(runtime._request_history.snapshot(), before)
            self.assertEqual(len(backend.requests), 1)

    def test_egress_scope_change_reprojects_history_without_old_body(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'note.txt').write_text('PATH-SCOPED-BODY-CANARY')
            backend = Backend(answer(None, call('read_file', {'path': 'note.txt'}, 'read')),
                              answer('read complete'), answer('continued'))
            runtime = self.runtime(root, backend, egress=CloudEgressPolicy('CLOUD_ALLOWED', ('note.txt',)))
            self.assertEqual(runtime.run_turn('Read note.txt').status, 'completed')
            previous_scope = runtime._request_history.scope
            self.assertIn('PATH-SCOPED-BODY-CANARY', json.dumps(runtime._request_history.snapshot()))
            runtime.hybrid.policy = replace(runtime.hybrid.policy, egress=CloudEgressPolicy('CLOUD_ALLOWED'))
            self.assertEqual(runtime.run_turn('Continue without that file body.').status, 'completed')
            self.assertNotEqual(previous_scope, runtime._request_history.scope)
            self.assertNotIn('PATH-SCOPED-BODY-CANARY', json.dumps(runtime._request_history.snapshot()))
            states = [m for m in backend.requests[-1]['messages'] if m.content and
                      m.content.startswith('Current Host state')]
            self.assertEqual(len(states), 1)

    def test_model_change_starts_a_fresh_request_series(self):
        with tempfile.TemporaryDirectory() as folder:
            backend = Backend(answer('one'), answer('two'))
            runtime = self.runtime(Path(folder), backend)
            runtime.run_turn('first')
            old_scope = runtime._request_history.scope
            backend.model_info = replace(backend.model_info, name='another-model')
            runtime.run_turn('second')
            self.assertNotEqual(old_scope, runtime._request_history.scope)
            states = [m for m in backend.requests[-1]['messages'] if m.content and
                      m.content.startswith('Current Host state')]
            self.assertEqual(len(states), 1)

    def test_desktop_profile_and_permission_changes_use_current_prompt_and_tools(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            backend = Backend(answer('standard'), answer('minimal'), answer('isolated'))
            runtime = self.runtime(root, backend)
            options = {'permission_mode': 'full', 'agent_profile': 'standard',
                       'prompt_revision': 2, 'scope_revision': 3}
            apply_options(runtime, options)
            self.assertEqual(runtime.run_turn('first').status, 'completed')
            previous_scope = runtime._request_history.scope
            canonical_count = len(runtime.messages)
            apply_options(runtime, {**options, 'agent_profile': 'minimal'})
            self.assertEqual(len(runtime.messages), canonical_count)
            self.assertEqual(runtime.run_turn('second').status, 'completed')
            self.assertNotEqual(previous_scope, runtime._request_history.scope)
            self.assertEqual(backend.requests[-1]['messages'][0], runtime.messages[0])
            self.assertNotEqual(backend.requests[0]['messages'][0], backend.requests[1]['messages'][0])
            self.assertEqual(sum(m.content and m.content.startswith('Current Host state')
                                 for m in backend.requests[-1]['messages']), 1)
            apply_options(runtime, {**options, 'permission_mode': 'isolated'})
            self.assertEqual(runtime.run_turn('third').status, 'completed')
            self.assertEqual(backend.requests[-1]['messages'][0], runtime.messages[0])
            state = json.loads(backend.requests[-1]['messages'][-1].content.split('\n', 1)[1])
            self.assertEqual(state['permission_mode'], 'approve-mutations')
            self.assertNotIn('apply_patch', [tool['function']['name'] for tool in backend.requests[-1]['tools']])
            with self.assertRaises(PermissionError):
                runtime.registry.call('apply_patch', {'changes': [
                    {'path': 'denied.txt', 'operation': 'create', 'content': 'blocked'}]})
            self.assertFalse((root / 'denied.txt').exists())

    def test_legacy_snapshot_restores_without_a_model_window(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime = self.runtime(root, Backend(answer('before')))
            runtime.run_turn('first')
            snapshot = snapshot_runtime(runtime)
            snapshot.pop('request_history')
            restored = self.runtime(root, Backend(answer('after')))
            restore_runtime(restored, snapshot)
            self.assertEqual(restored._request_history.messages, [])
            self.assertEqual(restored.run_turn('second').status, 'completed')

    def test_restore_validates_canonical_cursor_once(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = self.runtime(Path(folder), Backend(answer()))
            runtime.run_turn('first')
            snapshot = snapshot_runtime(runtime)
            snapshot['request_history']['source_count'] = len(runtime.messages) + 1
            with self.assertRaisesRegex(PersistenceError, 'request history'):
                restore_runtime(runtime, snapshot)


if __name__ == '__main__':
    unittest.main()
