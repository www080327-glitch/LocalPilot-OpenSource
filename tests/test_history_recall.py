"""Canonical recall through ordinary model dispatch and real SQLite archives."""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

from agent.engine_v5 import EngineV5Policy
from agent.hybrid import CloudEgressPolicy, HybridPolicy
from agent.persistence import PersistenceError
from agent.registry import create_default_registry
from agent.session import AgentSession, SessionBudgets
from localpilot_api.service import TaskRequest, TaskService
from localpilot_service.workspaces import WorkspaceGrants
from localpilot_service.security import AccessPolicy, Principal
from localpilot_service.desktop_sessions import switch_profile
from tests.test_runtime_api import Backend, answer, call


class HistoryRecallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'work'
        self.workspace.mkdir()
        self.path = self.root / 'runtime.sqlite3'
        self.grants = WorkspaceGrants(self.root / 'workspace-grants.json')
        self.hybrid = False
        self.output_tokens = 512
        self.backend = Backend(*(answer('completed') for _ in range(20)))
        self.services = []
        self.addCleanup(self.close_services)

    def close_services(self):
        for service in reversed(self.services):
            if service.store.failed:
                service.store.close()
            elif not service.closed:
                service.shutdown()

    def service(self):
        def factory(callback):
            options = ({'hybrid_policy': HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED')),
                        'hybrid_backends': {'cloud': self.backend}, 'hybrid_primary': 'cloud'}
                       if self.hybrid else {})
            runtime = AgentSession(create_default_registry(self.workspace, permission_mode='full-permission'),
                backend=self.backend, policy='cloud-only', event_callback=callback, streaming=False,
                engine_policy=EngineV5Policy(), budgets=SessionBudgets(max_steps=12, max_tool_calls=20,
                    max_token_units=1000000, max_output_tokens=self.output_tokens), **options)
            runtime._workspace_grants = self.grants
            return runtime
        service = TaskService({'localpilot': factory}, persistence=self.path, history_rotation_bytes=1)
        self.services.append(service)
        return service

    @staticmethod
    def task(service, text, session=None):
        return service.wait(service.create_task(TaskRequest(text, session_id=session))['id'])

    def archived(self, text='原始约定 NEEDLE ' + 'z' * 4020):
        service = self.service()
        sid = self.task(service, text)['session_id']
        self.task(service, 'second', sid)
        self.task(service, 'third', sid)
        self.assertNotIn(text, [m.content for m in service.sessions[sid].runtime.messages])
        return service, sid, text

    def test_model_recalls_original_text_in_chunks_after_rotation_and_restart(self):
        service, sid, original = self.archived()
        self.backend.steps = [answer(None, call('recall_history', {'query': 'NEEDLE'}, 'recall')),
                                  answer('consulted history')]
        task = self.task(service, 'Use the earlier agreement', sid)
        self.assertEqual(task['status'], 'completed', task.get('error'))
        runtime = service.sessions[sid].runtime
        receipt = next(r for r in runtime.tool_history if r['id'] == 'recall')
        match = receipt['payload']['result']['matches'][0]
        registry = runtime.registry
        first = registry.call('recall_history', {'reference': match['reference']})
        second = registry.call('recall_history', {'reference': match['reference'],
                                                'offset': first['next_offset']})
        self.assertEqual(first['text'] + second['text'], original)
        self.assertIsNone(second['next_offset'])
        service.suspend()
        restored = self.service()
        again = restored.sessions[sid].runtime.registry.call('recall_history',
            {'reference': match['reference']})
        self.assertEqual(first, again)

    def test_same_session_permissions_and_visible_text_only(self):
        first = answer('PUBLIC ANSWER')
        first.message.reasoning_content = 'PRIVATE-REASONING'
        first.message.native_replay = {'kind': 'provider-private', 'value': 'PRIVATE-REPLAY'}
        (self.workspace / 'private.txt').write_text('TOOL-ONLY-ORIGINAL')
        self.backend.steps = [answer(None, call('read_file', {'path': 'private.txt'})),
                              first, answer('second'), answer('third'), answer('other')]
        service, sid, _ = self.archived('FIRST-OWNER-QUESTION')
        other = self.task(service, 'SECOND-OWNER-QUESTION')['session_id']
        runtime = service.sessions[sid].runtime
        for query in ('PRIVATE-REASONING', 'PRIVATE-REPLAY', 'TOOL-ONLY-ORIGINAL', 'SECOND-OWNER-QUESTION'):
            result = runtime.registry.call('recall_history', {'query': query})
            self.assertEqual(result['matches'], [])
        entry = runtime.registry.call('recall_history', {'query': 'FIRST-OWNER-QUESTION'})['matches'][0]
        not_found = service.sessions[other].runtime.registry.call('recall_history',
            {'reference': entry['reference']})
        self.assertEqual(not_found['status'], 'not_found')
        runtime.registry.gateway.capabilities = replace(runtime.registry.gateway.capabilities, read=False)
        denied = runtime.registry.call('recall_history', {'query': 'FIRST-OWNER-QUESTION'})
        self.assertEqual(denied['status'], 'denied')
        projected = runtime.registry.canonical_history_reader.project_cloud_result(runtime._payload(denied))
        self.assertEqual(projected['result']['status'], 'denied')
        self.assertNotIn('recall_history', [s['function']['name'] for s in runtime._schemas()])
        runtime.registry.gateway.capabilities = replace(runtime.registry.gateway.capabilities, read=True)

        grants = WorkspaceGrants(self.root / 'grants.json')
        grant = grants.create('owner', str(self.workspace), 'read', [])
        runtime.registry.authorization_guard = lambda name, arguments: grants.guard(grant['id'], name, arguments)
        self.assertEqual(runtime.registry.call('recall_history', {'reference': entry['reference']})['status'], 'ok')
        grants.revoke(grant['id'], 'owner')
        with self.assertRaises(PermissionError):
            runtime.registry.call('recall_history', {'reference': entry['reference']})

    def test_schema3_additive_backfill_preserves_version_and_checkpoint_bytes(self):
        service, sid, _ = self.archived()
        service.suspend()
        with sqlite3.connect(self.path) as db:
            db.execute('DROP TABLE runtime_history_text')
            db.execute('DROP TABLE runtime_history_sources')
            db.execute('PRAGMA user_version=3')
            original = db.execute('SELECT * FROM runtime_segments').fetchall()
        service = self.service()
        self.assertIsNone(service.store.migration_backup)
        self.assertEqual(service.store.connection.execute('PRAGMA user_version').fetchone()[0], 3)
        registry = service.sessions[sid].runtime.registry
        first = registry.call('recall_history', {'query': 'NEEDLE'})
        self.assertTrue(first['matches'])
        self.assertEqual(service.store.connection.execute('SELECT * FROM runtime_segments').fetchall(), original)
        changes = service.store.connection.total_changes
        self.assertEqual(registry.call('recall_history', {'query': 'NEEDLE'}), first)
        self.assertEqual(service.store.connection.total_changes, changes)

    def test_folder_bound_desktop_profile_change_keeps_recall_available(self):
        service = self.service()
        grant = self.grants.create('owner', str(self.workspace), 'read', [])
        options = {'permission_mode': 'request', 'agent_profile': 'standard',
                   'workspace_grant': grant['id'], 'scope_revision': 3, 'prompt_revision': 2}
        sid = service.create_session(owner_subject='owner', desktop_options=options)['id']
        self.task(service, 'Keep PROFILE-MARKER', sid)
        runtime = service.sessions[sid].runtime
        original = runtime.registry
        operator = Principal('operator', 'o' * 32, scopes=frozenset({'read', 'control'}),
                             operator=True, approval_for=('owner',))
        access = AccessPolicy([operator, Principal('owner', 'w' * 32)], audit_path=self.root / 'access.jsonl')
        self.addCleanup(access.close)
        server = SimpleNamespace(service=service, catalog={}, access=access)
        switch_profile(server, operator, sid, {'client_subject': 'owner',
            'agent_profile': 'minimal', 'expected_profile': 'standard'})
        self.assertIsNot(runtime.registry, original)
        self.assertTrue(runtime.registry.call('recall_history', {'query': 'PROFILE-MARKER'})['matches'])
        service.suspend()
        restored = self.service().sessions[sid].runtime
        self.assertTrue(restored.registry.call('recall_history', {'query': 'PROFILE-MARKER'})['matches'])

    def test_cloud_hybrid_can_read_original_user_text_without_disclosing_assistant_history(self):
        self.hybrid = True
        self.backend.steps = [answer('PRIVATE-ASSISTANT shared-token'), answer('second'), answer('third')]
        service, sid, original = self.archived('ORIGINAL-USER shared-token')
        self.backend.steps = [answer(None, call('recall_history', {'query': 'shared-token'}, 'recall')),
                              answer('consulted original user text')]
        self.task(service, 'Recall our prior messages', sid)
        runtime = service.sessions[sid].runtime
        receipt = next(r for r in runtime.tool_history if r['id'] == 'recall')
        self.assertEqual({item['role'] for item in receipt['payload']['result']['matches']}, {'user'})
        sent = next(m for m in self.backend.requests[-1]['messages'] if m.role == 'tool' and m.tool_call_id == 'recall')
        projected = json.loads(sent.content)['result']
        self.assertEqual([item['text'] for item in projected['matches']], [original])
        self.assertNotIn('PRIVATE-ASSISTANT', sent.content)
        generation, position, checksum = service.store.connection.execute(
            "SELECT generation,position,sha256 FROM runtime_history_text WHERE session_id=? AND body=? LIMIT 1",
            (sid, 'PRIVATE-ASSISTANT shared-token')).fetchone()
        reference = f'history:{generation}:{position}:{checksum}'
        self.backend.steps = [answer(None, call('recall_history', {'reference': reference}, 'private-read')), answer('withheld')]
        self.task(service, 'Read the assistant reference', sid)
        sent = next(m for m in self.backend.requests[-1]['messages'] if m.role == 'tool' and m.tool_call_id == 'private-read')
        self.assertEqual(json.loads(sent.content)['result']['status'], 'withheld')
        self.assertNotIn('PRIVATE-ASSISTANT', sent.content)

    def test_cloud_search_filters_ineligible_assistant_echoes_before_result_limit(self):
        self.hybrid = True
        self.backend.steps = [answer(f'Assistant NEEDLE {index}') for index in range(14)]
        service = self.service()
        sid = self.task(service, 'Original USER NEEDLE')['session_id']
        for index in range(13):
            self.task(service, f'Followup {index}', sid)
        result = service.sessions[sid].runtime.registry.call('recall_history', {'query': 'NEEDLE'})
        self.assertEqual([item['text'] for item in result['matches']], ['Original USER NEEDLE'])

    def test_unicode_search_and_exact_chunks_preserve_references_within_gateway_byte_budget(self):
        self.output_tokens = 8192
        original = '🦊' * 5000
        self.backend.steps[0] = answer(original)
        service = self.service()
        sid = None
        for index in range(10):
            sid = self.task(service, str(index) + '😀' * 1000, sid)['session_id']
        registry = service.sessions[sid].runtime.registry
        matches = registry.call('recall_history', {'query': '😀'})
        self.assertNotIn('truncated', matches)
        self.assertLessEqual(len(json.dumps(matches, ensure_ascii=False).encode()), registry.gateway.max_output_bytes)
        self.assertEqual(len(matches['matches']), 10)
        reference = registry.call('recall_history', {'query': '🦊'})['matches'][0]['reference']
        fragments, offset = [], 0
        while offset is not None:
            result = registry.call('recall_history', {'reference': reference, 'offset': offset})
            self.assertNotIn('truncated', result)
            self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode()), registry.gateway.max_output_bytes)
            self.assertEqual(result['offset'], sum(map(len, fragments)))
            fragments.append(result['text'])
            offset = result['next_offset']
            if offset is not None:
                self.assertEqual(offset, sum(map(len, fragments)))
        self.assertGreater(len(fragments), 1)
        self.assertEqual(''.join(fragments), original)

    def test_invalid_requests_and_corrupt_index_never_return_text(self):
        service, sid, _ = self.archived()
        registry = service.sessions[sid].runtime.registry
        for arguments in ({}, {'query': ''}, {'query': 'a', 'reference': 'bad'},
                          {'reference': 'history:0:1:bad'}, {'query': 'a', 'offset': 2}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                registry.call('recall_history', arguments)
        service.store.connection.execute("UPDATE runtime_history_text SET body='FORGED NEEDLE'")
        with self.assertRaises(PersistenceError):
            registry.call('recall_history', {'query': 'NEEDLE'})
        self.assertTrue(service.store.failed)
