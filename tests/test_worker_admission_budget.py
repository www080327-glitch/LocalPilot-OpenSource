"""Real AgentSession tools/SQLite; only the model replies are scripted."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent.backends import BackendResponse, Message, ModelInfo
from agent.engine_v5 import EngineV5Policy
from agent.hybrid import CloudEgressPolicy, HybridPolicy
from agent.persistence import PersistenceError, snapshot_runtime
from agent.registry import create_default_registry
from agent.session import AgentSession, SessionBudgets
from localpilot_api.service import APIError, TaskRequest, TaskService
from localpilot_service.deployment import build
from localpilot_service.desktop_sessions import apply_options
from localpilot_service.backup import copy_database
from tests.test_local_http_backend import MockServer, completion, tool_call
from tests.test_runtime_api import Backend, call


def reply(text=None, *calls):
    return BackendResponse(Message('assistant', text, list(calls)),
                           model='budget-fixture', finish_reason='tool_calls' if calls else 'stop')


class LocalBackend(Backend):
    is_local = is_loopback = True
    model_info = ModelInfo('budget-fixture', '35B', 131072)

    def health_check(self):
        return True


class WorkerAdmissionBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.work = self.root / 'workspace'
        self.work.mkdir()
        self.marker = 'observed-child-file-9417'
        (self.work / 'fact.txt').write_text(self.marker)
        self.budgets = SessionBudgets()
        self.requested = {}
        self.services = []
        self.parent = LocalBackend(*([self.parent_reply] * 6))
        self.worker = LocalBackend(*([self.worker_reply] * 6))

    def tearDown(self):
        for service in self.services:
            if not service.closed:
                service.shutdown()
        self.tmp.cleanup()

    def parent_reply(self, messages):
        if not any(m.role == 'tool' for m in messages):
            return reply(None, call('delegate', {
                'task': 'Read fact.txt and report its contents.', 'backend_preference': 'local',
                'backend_id': 'worker', 'read_only': True, **self.requested}, 'delegate-once'))
        return reply('Collected the actual child result.')

    def worker_reply(self, messages):
        results = [m for m in messages if m.role == 'tool']
        if results:
            return reply('Observed tool result: ' + results[-1].content)
        tools = self.worker.requests[-1].get('tools') or []
        if any(schema['function']['name'] == 'read_file' for schema in tools):
            return reply(None, call('read_file', {'path': 'fact.txt'}, 'child-read'))
        return reply('Cannot read the file because no tools are available.')

    def factory(self, callback):
        runtime = AgentSession(create_default_registry(self.work, tool_profile='compact'),
            local_backend=self.parent, policy='local-only', budgets=self.budgets,
            hybrid_policy=HybridPolicy(CloudEgressPolicy('LOCAL_ONLY')),
            hybrid_backends={'primary': self.parent, 'worker': self.worker}, hybrid_primary='primary',
            engine_policy=EngineV5Policy(), event_callback=callback, streaming=False)
        apply_options(runtime, {'permission_mode': 'workspace', 'agent_profile': 'standard',
                                'prompt_revision': 2, 'scope_revision': 3})
        return runtime

    def open(self):
        service = TaskService({'localpilot': self.factory}, persistence=self.root / 'runtime.sqlite3')
        self.services.append(service)
        return service

    def run_task(self):
        service = self.open()
        request = TaskRequest('Delegate one real file read.', idempotency_key='once')
        task = service.wait(service.create_task(request)['id'])
        parent = service.sessions[task['session_id']].runtime
        return service, request, task, parent, parent._children['1.1']

    def test_default_worker_reads_real_file_and_restore_does_not_replay(self):
        service, request, task, parent, child = self.run_task()
        self.assertEqual(task['status'], 'completed', task.get('error'))
        reads = [r for r in child.tool_history if r['name'] == 'read_file' and r['payload'].get('ok')]
        self.assertEqual(len(reads), 1)
        self.assertEqual(reads[0]['read_receipt']['version']['sha256'],
                         hashlib.sha256(self.marker.encode()).hexdigest())
        first_request = next(e for e in child.events.events if e.type == 'ModelRequestStarted')
        self.assertEqual(first_request.data['phase'], 'exploring')
        self.assertTrue(self.worker.requests[0]['tools'])
        self.assertGreater(child._token_units, 0)
        self.assertLessEqual(child._token_units, child.budgets.max_token_units)
        self.assertLessEqual(parent._token_units, parent.budgets.max_token_units)
        self.assertGreaterEqual(parent._token_units, child._token_units)
        self.assertTrue(all(u.input_tokens is None and u.output_tokens is None for u in parent._usage))
        before = snapshot_runtime(parent)
        calls = (len(self.parent.requests), len(self.worker.requests))
        service.suspend()
        reopened = self.open()
        restored = reopened.sessions[task['session_id']].runtime
        self.assertEqual(restored.tool_history, before['history'])
        self.assertEqual(restored._children['1.1'].budgets, child.budgets)
        self.assertEqual(restored._token_units, parent._token_units)
        self.assertEqual(reopened.create_task(request)['id'], task['id'])
        self.assertEqual((len(self.parent.requests), len(self.worker.requests)), calls)

    def test_explicit_host_ceiling_preserves_first_request_reserve(self):
        self.budgets = replace(self.budgets, max_worker_token_units=32768)
        self.assert_bounded_without_tools()

    def test_explicit_delegate_budget_cannot_be_silently_increased(self):
        self.requested = {'budget': {'tokens': 32768}}
        self.assert_bounded_without_tools()

    def assert_bounded_without_tools(self):
        _, _, _, parent, child = self.run_task()
        self.assertEqual(child.budgets.max_token_units, 32768)
        self.assertEqual(child.tool_history, [])
        first = next(e for e in child.events.events if e.type == 'FinalizingStarted')
        self.assertEqual(first.data['reason'], 'token_reserve')
        self.assertEqual(first.data['attempts'], 0)
        self.assertIsNone(self.worker.requests[0]['tools'])
        self.assertLessEqual(parent._token_units, parent.budgets.max_token_units)

    def test_parent_remaining_budget_still_caps_new_default(self):
        self.budgets = replace(self.budgets, max_token_units=100000, max_output_tokens=512, max_steps=6)
        _, _, _, parent, child = self.run_task()
        self.assertLess(child.budgets.max_token_units, self.budgets.max_worker_token_units)
        self.assertLessEqual(child._token_units, child.budgets.max_token_units)
        self.assertLessEqual(parent._token_units, parent.budgets.max_token_units)


def create_legacy_checkpoint(config_path):
    """Run under the actual old checkout, using its normal build and SQLite store."""
    server = build(config_path)
    try:
        sid = server.service.create_session(desktop_options={
            'permission_mode': 'full', 'agent_profile': 'standard',
            'prompt_revision': 2, 'scope_revision': 3})['id']
        runtime = server.service.sessions[sid].runtime
        original = runtime.registry._tools['apply_patch']

        def interrupted(**kwargs):
            original(**kwargs)
            raise OSError('Controlled receipt loss after real file write')

        runtime.registry._tools['apply_patch'] = interrupted
        request = TaskRequest('Write exactly one marker.', session_id=sid, idempotency_key='legacy-unknown')
        task = server.service.wait(server.service.create_task(request)['id'])
        payload = next(p for p in server.service.store.load() if p['session']['id'] == sid)
        switched = server.service.create_session(owner_subject='test', desktop_options={
            'permission_mode': 'full', 'agent_profile': 'standard',
            'prompt_revision': 2, 'scope_revision': 3})['id']
        child_task = server.service.wait(server.service.create_task(TaskRequest(
            'Delegate one bounded observation.', session_id=switched))['id'])
        if child_task['status'] != 'completed':
            raise AssertionError(child_task)
        from localpilot_service.session_migration import switch_model
        switch_model(server, server.access.principals['operator'], switched, {
            'client_subject': 'test', 'model': 'alternate', 'expected_model': 'localpilot',
            'source': 'local_only'})
        switched_payload = next(p for p in server.service.store.load() if p['session']['id'] == switched)
        Path(config_path).with_name('legacy.json').write_text(json.dumps({
            'task': task, 'payload': payload, 'source': str(Path(__file__).resolve()),
            'budget': runtime.budgets.max_worker_token_units, 'switched_payload': switched_payload}))
        server.service.suspend()
    finally:
        if not server.service.closed:
            server.service.shutdown()
        server.server_close()
        server.access.close()


@unittest.skipUnless(os.environ.get('LOCALPILOT_WORKER_BUDGET_LEGACY_SOURCE'),
                     'needs the actual pinned checkout with the old worker default')
class WorkerBudgetUpgradeTests(unittest.TestCase):
    def test_old_build_unknown_restore_new_default_and_strict_host_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            work = root / 'workspace'
            work.mkdir()
            model = MockServer()
            model.add(completion(calls=[tool_call('apply_patch', {
                'changes': [{'path': 'effect.txt', 'operation': 'create', 'content': 'one effect'}]}, 'effect-once')]))
            model.add(completion('The effect is UNKNOWN; no replay.'))
            model.add(completion(calls=[tool_call('delegate', {
                'task': 'Return a bounded observation.', 'backend_preference': 'local',
                'read_only': True}, 'legacy-child')]))
            model.add(completion('No tools executed.'))
            model.add(completion('Collected the bounded child result.'))
            config = {'schema_version': 1, 'port': 0, 'data_dir': str(root / 'data'),
                'clients': [{'subject': 'test', 'token_env': 'LP_WORKER_UPGRADE_FIXTURE',
                             'routes': {'localpilot': 'localpilot', 'alternate': 'alternate'}},
                            {'subject': 'operator', 'token_env': 'LP_WORKER_UPGRADE_OPERATOR',
                             'operator': True, 'approval_for': ['test'], 'scopes': ['read', 'control']}],
                'routes': {'localpilot': {'workspace': str(work), 'tool_profile': 'compact',
                    'backend': {'kind': 'local-openai', 'base_url': model.base_url, 'model': 'mock-local',
                                'capabilities': {'tool_calling': True, 'streaming': False}}}}}
            config['routes']['alternate'] = json.loads(json.dumps(config['routes']['localpilot']))
            path = root / 'service.json'
            path.write_text(json.dumps(config))
            path.chmod(0o600)
            servers = []
            try:
                source = Path(os.environ['LOCALPILOT_WORKER_BUDGET_LEGACY_SOURCE']).resolve()
                entry = ("import runpy,sys;sys.path.insert(0,sys.argv[1]);"
                         "runpy.run_path(sys.argv[2],run_name='legacy_fixture')"
                         "['create_legacy_checkpoint'](sys.argv[3])")
                with patch.dict(os.environ, {'LP_WORKER_UPGRADE_FIXTURE': 'b' * 32,
                                            'LP_WORKER_UPGRADE_OPERATOR': 'o' * 32}):
                    command = [sys.executable, '-c', entry, str(source), str(Path(__file__).resolve()), str(path)]
                    subprocess.run(command, cwd=source, check=True, timeout=30)
                    before = json.loads(path.with_name('legacy.json').read_text())
                    if os.environ.get('LOCALPILOT_WORKER_BUDGET_EVIDENCE'):
                        evidence = Path(os.environ['LOCALPILOT_WORKER_BUDGET_EVIDENCE'])
                        evidence.mkdir(parents=True, exist_ok=False)
                        copy_database(root / 'data/runtime.sqlite3', evidence / 'legacy.sqlite3')
                        (evidence / 'legacy-fixture.json').write_text(json.dumps(before, indent=2))
                        (evidence / 'legacy-command.json').write_text(json.dumps({'argv': command,
                            'cwd': str(source), 'source_budget_sha256': hashlib.sha256(
                                (source / 'agent/session_types.py').read_bytes()).hexdigest()}, indent=2))
                    self.assertEqual(before['budget'], 32768)
                    sid, tid = before['task']['session_id'], before['task']['id']
                    self.assertTrue(any(r['side_effect_status'] == 'unknown'
                                        for r in before['payload']['runtime']['history']))
                    switched_sid = before['switched_payload']['session']['id']
                    request_count = len(model.requests)
                    for _ in range(2):
                        server = build(path)
                        servers.append(server)
                        runtime = server.service.sessions[sid].runtime
                        self.assertEqual(runtime.budgets.max_worker_token_units, 32768)
                        self.assertEqual(runtime.tool_history, before['payload']['runtime']['history'])
                        self.assertEqual(server.service.create_task(TaskRequest('Write exactly one marker.',
                            session_id=sid, idempotency_key='legacy-unknown'))['id'], tid)
                        self.assertEqual(server.service.task_snapshot(tid)['recovery']['class'], 'UNKNOWN_BLOCKED')
                        self.assertEqual((work / 'effect.txt').read_text(), 'one effect')
                        self.assertEqual(len(model.requests), request_count)
                        switched = before['switched_payload']
                        old_route = server.service.sessions[switched['session']['id']]
                        self.assertEqual(old_route.model, 'alternate')
                        self.assertEqual(old_route.child_route_contexts, switched['session']['child_route_contexts'])
                        self.assertEqual(old_route.runtime._children['1.1'].budgets.max_token_units, 32768)
                        self.assertEqual(snapshot_runtime(old_route.runtime)['children'], switched['runtime']['children'])
                        server.service.suspend()
                        server.server_close()
                        server.access.close()
                    moved = root / 'moved'
                    (moved / 'data').mkdir(parents=True, mode=0o700)
                    moved.chmod(0o700)
                    copy_database(root / 'data/runtime.sqlite3', moved / 'data/runtime.sqlite3')
                    moved_config = json.loads(json.dumps(config))
                    moved_config['data_dir'] = str(moved / 'data')
                    moved_config['restore_path_migration'] = {'version': 1, 'private_roots': [
                        {'source': str(root / suffix), 'destination': str(moved / suffix)}
                        for suffix in ('data', 'data/logs', '')]}
                    moved_path = moved / 'service.json'
                    moved_path.write_text(json.dumps(moved_config))
                    moved_path.chmod(0o600)
                    rebased = build(moved_path)
                    servers.append(rebased)
                    self.assertEqual(rebased.service.sessions[sid].runtime.budgets.max_worker_token_units, 32768)
                    self.assertEqual(rebased.service.sessions[sid].runtime.tool_history,
                                     before['payload']['runtime']['history'])
                    self.assertEqual(rebased.service.sessions[switched_sid].runtime._children['1.1'].budgets.max_token_units, 32768)
                    self.assertEqual(rebased.service.task_snapshot(tid)['recovery']['class'], 'UNKNOWN_BLOCKED')
                    self.assertEqual(len(model.requests), request_count)
                    rebased.service.suspend()
                    rebased.server_close()
                    rebased.access.close()
                    server = build(path)
                    servers.append(server)
                    from localpilot_service.session_migration import switch_model
                    switch_model(server, server.access.principals['operator'], switched_sid, {
                        'client_subject': 'test', 'model': 'localpilot', 'expected_model': 'alternate',
                        'source': 'local_only'})
                    self.assertEqual(server.service.sessions[switched_sid].runtime.budgets.max_worker_token_units, 32768)
                    self.assertEqual(len(model.requests), request_count)
                    server.service.suspend()
                    server.server_close()
                    server.access.close()
                    config['routes']['localpilot']['budgets'] = {'max_worker_token_units': 131072}
                    path.write_text(json.dumps(config))
                    with self.assertRaises(PersistenceError):
                        build(path)
                    config['routes']['localpilot']['budgets'] = {'max_worker_steps': 4}
                    path.write_text(json.dumps(config))
                    with self.assertRaises(PersistenceError):
                        build(path)
                    config['routes']['localpilot']['budgets'] = {'max_worker_token_units': 32768}
                    path.write_text(json.dumps(config))
                    pinned = build(path)
                    servers.append(pinned)
                    self.assertEqual(pinned.service.sessions[sid].runtime.budgets.max_worker_token_units, 32768)
                    pinned.service.suspend()
                    pinned.server_close()
                    pinned.access.close()
                    config['routes']['localpilot'].pop('budgets')
                    config['routes']['localpilot']['backend']['model'] = 'different-model'
                    path.write_text(json.dumps(config))
                    with self.assertRaises(PersistenceError):
                        build(path)
                    config['routes']['localpilot']['backend']['model'] = 'mock-local'
                    config['routes']['alternate']['budgets'] = {'max_worker_token_units': 131072}
                    path.write_text(json.dumps(config))
                    server = build(path)
                    servers.append(server)
                    with self.assertRaisesRegex(APIError, 'budgets'):
                        switch_model(server, server.access.principals['operator'], switched_sid, {
                            'client_subject': 'test', 'model': 'alternate', 'expected_model': 'localpilot',
                            'source': 'local_only'})
                    new_sid = server.service.create_session()['id']
                    self.assertEqual(server.service.sessions[new_sid].runtime.budgets.max_worker_token_units, 131072)
                    self.assertEqual(server.service.sessions[sid].runtime.budgets.max_worker_token_units, 32768)
            finally:
                for server in servers:
                    if not server.service.closed:
                        server.service.shutdown()
                        server.server_close()
                        server.access.close()
                model.close()


if __name__ == '__main__':
    unittest.main()
