"""Host controls: real effects and loopback transport, scripted model only."""
from pathlib import Path
import hashlib
import json
import tempfile
import threading
import unittest
from agent.engine_v5 import EngineV5Policy
from agent.permissions import ToolRiskMetadata
from agent.persistence import snapshot_runtime, restore_runtime, recovery_class, PersistenceError
from agent.registry import create_default_registry
from agent.session import AgentSession, SessionBudgets
from agent.stabilization import HostVerification
from localpilot_api.service import TaskService, TaskRequest
from localpilot_api.server import APIServer
from localpilot_api.client import Client
from tests.test_runtime_api import Backend, answer, call


class SDKAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def session(self, steps, *, uncertain=True, engine=False, **opts):
        registry = create_default_registry(self.root, permission_mode='full-permission')
        def effect(workspace_root):
            p = Path(workspace_root) / 'effect.txt'
            p.write_text((p.read_text() if p.exists() else '') + 'EFFECT\n')
            if uncertain:
                raise OSError('after actual mutation')
            return {'status': 'ok'}
        registry.register('effect', effect, ToolRiskMetadata(mutating=True), schema={
            'type': 'function', 'function': {'name': 'effect', 'parameters': {'type': 'object', 'properties': {}}}})
        return AgentSession(registry, backend=Backend(*steps), policy='cloud-only', streaming=False,
            budgets=SessionBudgets(max_steps=10, max_token_units=1000000),
            engine_policy=EngineV5Policy() if engine else None, **opts)

    def test_unknown_new_id_turn_and_snapshot_preserve_one_effect(self):
        for engine in (False, True):
            with self.subTest(engine=engine):
                path = self.root / 'effect.txt'
                if path.exists(): path.unlink()
                s = self.session([answer(None, call('effect', {}, 'first')),
                    answer(None, call('effect', {}, 'second')), answer('done')], engine=engine)
                self.addCleanup(s.close)
                r = s.run_turn('effect once')
                self.assertEqual(path.read_text().splitlines(), ['EFFECT'])
                self.assertEqual(r.task_outcome, 'unknown')
                self.assertFalse(r.task_succeeded)
                self.assertEqual(recovery_class(s), 'UNKNOWN_BLOCKED')
                restored = self.session([answer(None, call('effect', {}, 'third')), answer('done')], engine=engine)
                self.addCleanup(restored.close)
                restore_runtime(restored, snapshot_runtime(s))
                restored.run_turn('new turn cannot discard old uncertainty')
                self.assertEqual(path.read_text().splitlines(), ['EFFECT'])
                self.assertEqual(recovery_class(restored), 'UNKNOWN_BLOCKED')

    def test_identical_settled_business_operations_are_not_permanently_deduplicated(self):
        s = self.session([answer(None, call('effect', {}, 'one')), answer(None, call('effect', {}, 'two')), answer('done')], uncertain=False)
        self.addCleanup(s.close)
        s.run_turn('two authorized business operations')
        self.assertEqual(len((self.root / 'effect.txt').read_text().splitlines()), 2)

    def test_predispatch_validation_can_be_corrected_without_unknown(self):
        s = self.session([answer(None, call('effect', {'extra': 1}, 'bad')), answer(None, call('effect', {}, 'good')), answer('done')], uncertain=False)
        self.addCleanup(s.close)
        s.run_turn('correct argument')
        self.assertEqual((self.root / 'effect.txt').read_text().splitlines(), ['EFFECT'])
        self.assertNotEqual(recovery_class(s), 'UNKNOWN_BLOCKED')

    def test_authorization_guard_failure_is_proven_not_dispatched(self):
        s = self.session([answer(None, call('effect', {}, 'one')), answer('done')])
        self.addCleanup(s.close)
        def denied(*args): raise PermissionError('revoked before invocation')
        s.registry.authorization_guard = denied
        s.run_turn('denied')
        self.assertFalse((self.root / 'effect.txt').exists())
        self.assertNotEqual(recovery_class(s), 'UNKNOWN_BLOCKED')

    def test_verifier_only_has_authoritative_outcome_while_turn_is_compatible(self):
        for status in ('failed', 'unknown', 'blocked', 'not_run', 'passed'):
            with self.subTest(status=status):
                check = lambda root, r: HostVerification(status, 'host assertion', {}, True, True, True)
                s = self.session([answer('DELIVERED')], verification_callback=check)
                self.addCleanup(s.close)
                r = s.run_turn('verify')
                self.assertEqual(r.status, 'completed')
                self.assertEqual(r.task_outcome, 'unverified' if status == 'not_run' else status)
                self.assertEqual(r.task_succeeded, status == 'passed')

    def test_strict_without_verifier_and_exception_never_pass(self):
        def unavailable(*args): raise TimeoutError('host verifier deadline')
        for opts in ({'strict_task': True}, {'verification_required': True, 'verification_callback': unavailable}):
            s = self.session([answer('PASS')], **opts)
            self.addCleanup(s.close)
            r = s.run_turn('strict')
            self.assertEqual(r.status, 'incomplete')
            self.assertFalse(r.task_succeeded)
        ordinary = self.session([answer('hello')])
        self.addCleanup(ordinary.close)
        self.assertEqual(ordinary.run_turn('chat').status, 'completed')

    def test_resource_changes_and_contract_change_cannot_preserve_acceptance(self):
        p = self.root / 'result.txt'; p.write_text('old')
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        def stale(*args):
            p.write_text('new')
            return HostVerification('passed', 'bound old version', {'result.txt': digest}, True, True, True)
        s = self.session([answer('done')], verification_callback=stale)
        self.addCleanup(s.close)
        self.assertEqual(s.run_turn('verify').task_outcome, 'unknown')
        strict = self.session([], strict_task=True)
        self.addCleanup(strict.close)
        with self.assertRaises(PersistenceError): restore_runtime(strict, snapshot_runtime(s))

    def test_taskservice_http_preserves_failure_even_without_service_metadata(self):
        def factory(cb):
            return self.session([answer('PASS')], event_callback=cb,
                verification_callback=lambda *a: HostVerification('failed', 'independent', {}, False, True, True))
        service = TaskService({'localpilot': factory})
        self.addCleanup(service.shutdown)
        server = APIServer(('127.0.0.1', 0), service, api_key='fixture')
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True); thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(2)))
        client = Client(f'http://127.0.0.1:{server.server_port}', api_key='fixture')
        value = client.request('/v1/responses', {'input': 'verify'})
        task = service.wait(value['id'])
        self.assertEqual(task['status'], 'incomplete')
        self.assertEqual(task['result']['task_outcome'], 'failed')
        public = client.request('/v1/responses/' + value['id'])
        self.assertEqual(public['localpilot']['task_outcome'], 'failed')
        self.assertFalse(public['localpilot']['task_succeeded'])

    def test_bounded_output_does_not_erase_effect_safety(self):
        s = self.session([])
        self.addCleanup(s.close)
        value = s.registry._bound_result({'status': 'error', 'body': 'x' * 200000,
            'action_may_have_applied': True, 'replay_allowed': False})
        self.assertTrue(value['action_may_have_applied'])
        self.assertFalse(value['replay_allowed'])

    def test_json_exception_after_mutation_is_not_a_repairable_argument_error(self):
        s=self.session([answer(None,call('effect',{},'first')),
            answer(None,call('effect',{},'new-id')),answer('done')])
        self.addCleanup(s.close)
        def effect(workspace_root):
            p=Path(workspace_root)/'effect.txt'
            p.write_text((p.read_text() if p.exists() else '')+'EFFECT\n')
            raise json.JSONDecodeError('after dispatch','invalid',0)
        s.registry._tools['effect']=effect
        result=s.run_turn('Only one effect')
        self.assertEqual((self.root/'effect.txt').read_text().splitlines(),['EFFECT'])
        self.assertEqual(result.task_outcome,'unknown')
        self.assertEqual(s.tool_history[0]['side_effect_status'],'unknown')
        self.assertFalse(s.tool_history[0]['payload']['result']['replay_allowed'])
