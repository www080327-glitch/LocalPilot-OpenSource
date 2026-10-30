"""Scripted integration/fault tests. Never evidence of real keyboard/IME compatibility."""
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from agent.registry import create_default_registry
from agent.session import AgentSession
from computer.backend import AXBackend, ComputerBackend
from computer.local_native import LocalNativeBackend, KINDS
from computer.runtime import ComputerRuntime, ControlState
from tests.test_computer_runtime import MemoryAX, ScriptBackend, response, APP, condition


class NativeTransport(MemoryAX):
    def __init__(self):
        super().__init__()
        self.nodes[0]['role'] = 'AXTextArea'
        self.epoch = 0
        self.birth = '1.2'
        self.pid = 1234567
        self.window_id = 42
        self.control_generation = 1
        self.responder_window_verified = True
        self.trace = []
        self.context_error = False
        self.read_error = False
        self.noop = False
        self.cleanup_unknown = False
        self.requests = []
        self.controller = {'instance': 'scripted-controller', 'pid': 9876543, 'process_birth': '9.8'}
        self.stop_seen = threading.Event()
        self.env.update(focused_element={'role': 'AXTextArea'}, input_idle_seconds=0)

    def inspect_tree(self, app, **bounds):
        self.trace.append('observe')
        self.epoch += 1
        if self.read_error and self.sent:
            raise RuntimeError('scripted readback failed after side effect')
        return {**super().inspect_tree(app, **bounds), 'pid': self.pid, 'epoch': self.epoch}

    def identity(self):
        return {'app': APP, 'pid': self.pid, 'process_birth': self.birth, 'epoch': self.epoch, 'controller': self.controller,
                'window_id': self.window_id, 'geometry': [1, 2, 300, 400],
                'control_generation': self.control_generation,
                'responder_proof': {'focused_window_matches': self.responder_window_verified}}

    def request(self, **r):
        self.requests.append(r)
        if r['op'] == 'native_context':
            if self.context_error:
                return {'status': 'error', 'error': 'capability_rejected'}
            return {'status': 'ok', 'target': self.identity()}
        assert r['op'] == 'native_text'
        self.trace.append('native_enter')
        self.entered.set()
        if self.fault == 'timeout':
            raise TimeoutError('scripted native timeout')
        if self.identity() != r['target'] or Path(r['stop_path']).exists():
            return {'status': 'error', 'error': 'capability_rejected', 'action_sent': False,
                    'input_cleanup': {'status': 'ok', 'cleanup': 'no_owned_inputs'}}
        self.sent += 1
        before = self.environment()
        if self.block:
            # The scripted transport models a pending down/up pair, observing stop independently.
            self.release.wait(3)
            if Path(r['stop_path']).exists():
                self.stop_seen.set()
        if not self.noop:
            self.nodes[0]['value'] += r['text']
        if self.fault == 'mouse':
            self.env['mouse'] = [200, 300]
        if self.fault == 'front':
            self.env.update(frontmost_app=APP, frontmost_pid=self.pid)
        self.trace.append('cleanup')
        result = {'status': 'error' if self.stop_seen.is_set() else 'ok',
                'error': 'native_dispatch_interrupted' if self.stop_seen.is_set() else None,
                'action_sent': True, 'before': before, 'after': self.environment(),
                'dispatch_stage': 'POSTED', 'posted_events': 2, 'target_tap': 'NOT_RUN',
                'request_id': r['request_id'],
                'input_cleanup': {'status': 'error' if self.cleanup_unknown else 'ok',
                                  'cleanup': 'UNKNOWN' if self.cleanup_unknown else 'owned_key_up_POSTED'}}
        if self.fault == 'wrong_id':
            result['request_id'] = 'stale-request'
        if self.fault == 'missing_cleanup':
            result.pop('input_cleanup')
        return result


def target(kind='NSTextView'):
    return {'app': APP, 'kind': kind, 'window_title': 'qualified test window',
            'identifier': 'input', 'bundle_path': '/owned/fixture.app',
            'executable_sha256': 'a' * 64, 'evidence': 'scripted-test-only-not-native-evidence'}


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Keep advisory lease files isolated from actual product instances.
        p = patch('computer.local_native.BUILD', Path(self.tmp.name) / 'build')
        p.start(); self.addCleanup(p.stop)
        self.transport = NativeTransport()
        self.backend = LocalNativeBackend([APP], enabled=True, targets=[target()], transport=self.transport)
        self.addCleanup(self.backend.close)
        self.runtime = ComputerRuntime(self.backend, allowed_apps=[APP], verification_timeout=0)
        self.registry = create_default_registry(self.tmp.name, permission_mode='full-permission')
        self.runtime.register_tools(self.registry)

    def proposal(self, text='new'):
        tree = self.runtime.inspect_tree(APP)
        return {'app': APP, 'element': 'input', 'observation': tree['observation'], 'text': text,
                'postcondition': condition(value='old' + text)}

    def test_legacy_contract_and_native_schema_visibility(self):
        old = AXBackend(MemoryAX())
        self.assertIsInstance(old, ComputerBackend)
        self.assertIsInstance(self.backend, ComputerBackend)
        registry = create_default_registry(self.tmp.name)
        ComputerRuntime(old, allowed_apps=[APP]).register_tools(registry)
        with self.assertRaises(ValueError):
            registry.metadata('type_text')
        self.assertTrue(self.registry.metadata('type_text').mutating)

    def test_default_off_and_empty_qualification(self):
        with self.assertRaises(ValueError):
            LocalNativeBackend([APP], targets=[target()], transport=self.transport)
        with self.assertRaises(ValueError):
            LocalNativeBackend([APP], enabled=True, transport=self.transport)

    def test_unverified_families_and_bad_qualifications_rejected(self):
        for kind in ['ViewBridge', 'Electron', 'menu', 'background_mouse', 'UNKNOWN']:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                LocalNativeBackend([APP], enabled=True, targets=[target(kind)], transport=self.transport)
        for changes in [{'bundle_path': 'relative'}, {'executable_sha256': 'bad'}, {'evidence': ''},
                        {'app': 'outside.scope'}, {'concurrent_input': True}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                LocalNativeBackend([APP], enabled=True, targets=[{**target(), **changes}], transport=self.transport)

    def test_all_three_accepted_families_require_explicit_host_qualification(self):
        for kind in KINDS:
            self.assertEqual(LocalNativeBackend._validate_target(target(kind), [APP])['kind'], kind)
        self.assertIn('E2E_NOT_RUN', self.backend.capabilities['ime_isolation'])
        self.assertIn('rejected', self.backend.capabilities['background_mouse'])

    def test_permission_approval_sends_nothing_until_approved(self):
        registry = create_default_registry(self.tmp.name, permission_mode='approve-mutations')
        self.runtime.register_tools(registry)
        args = self.proposal()
        self.assertEqual(registry.call('type_text', args)['status'], 'approval_required')
        self.assertEqual(self.transport.sent, 0)
        self.assertTrue(registry.call('type_text', args, approved=True)['verified'])
        self.assertEqual(self.transport.sent, 1)

    def test_read_only_worker_cannot_send_native_keyboard(self):
        from agent.safety import CapabilityPolicy
        registry = create_default_registry(self.tmp.name, permission_mode='full-permission',
                                           capabilities=CapabilityPolicy(read_only=True))
        self.runtime.register_tools(registry)
        result = registry.call('type_text', self.proposal(), approved=True)
        self.assertNotEqual(result.get('status'), 'ok')
        self.assertEqual(self.transport.sent, 0)

    def test_scoped_concurrent_input_verifies_and_retains_receipt(self):
        result = self.registry.call('type_text', self.proposal())
        self.assertTrue(result['verified'])
        self.assertEqual(result['dispatch_stage'], 'POSTED')
        self.assertEqual(result['target_tap'], 'NOT_RUN')
        self.assertEqual(result['input_cleanup']['cleanup'], 'owned_key_up_POSTED')
        self.assertFalse(result['replay_allowed'])
        self.assertEqual(result['target_identity']['process_birth'], '1.2')
        self.assertEqual(result['owner'], self.backend.owner)
        self.assertIsNone(self.backend._states[(APP, 'input')]['software_cursor']['position'])

    def test_legacy_ax_protection_remains_with_native_backend(self):
        args = self.proposal()
        args.pop('text'); args['value'] = 'new'; args['postcondition'] = condition()
        result = self.registry.call('set_value', args)
        self.assertEqual(result['error'], 'user_text_input_active')
        self.assertEqual(self.transport.sent, 0)

    def test_unverified_control_and_context_failure_reject_before_send(self):
        self.transport.context_error = True
        result = self.registry.call('type_text', self.proposal())
        self.assertEqual(result['error'], 'capability_rejected')
        self.assertFalse(result['action_sent'])
        self.assertEqual(self.transport.sent, 0)

    def test_qualification_failure_reason_survives_until_receipt_and_refresh(self):
        original = self.transport.request
        self.transport.request = lambda **r: ({'status': 'error', 'error': 'capability_rejected',
            'reason': 'native_responder_unverified', 'action_sent': False} if r['op'] == 'native_context' else original(**r))
        result = self.registry.call('type_text', self.proposal())
        self.assertEqual(result['reason'], 'native_responder_unverified')
        self.assertEqual(result['qualification']['reason'], 'native_responder_unverified')
        self.assertFalse(result['action_sent'])
        self.assertTrue(self.runtime.paused)
        self.transport.request = original
        self.assertEqual(self.runtime.resume()['status'], 'ok')
        self.assertFalse(self.backend._qualification_failures)
        self.assertEqual(self.transport.sent, 0)  # Resume observes; never replays.

    def test_ambiguous_qualification_rejects(self):
        self.backend.targets.append(target('WKWebView'))
        self.assertEqual(self.registry.call('type_text', self.proposal())['error'], 'capability_rejected')
        self.assertEqual(self.transport.sent, 0)

    def test_dom_qualification_is_explicit_and_only_wk_textarea(self):
        policy = target('WKWebView')
        policy['dom_identifier'] = policy.pop('identifier')
        for bad in [{**policy, 'kind': 'NSTextView'}, {**policy, 'identifier': 'input'}]:
            with self.assertRaises(ValueError):
                LocalNativeBackend._validate_target(bad, [APP])
        self.backend.targets = [LocalNativeBackend._validate_target(policy, [APP])]
        self.transport.nodes[0]['identifier'] = None
        self.transport.nodes[0]['dom_identifier'] = 'input'
        tree = self.backend.inspect_tree(APP)
        self.assertIn((APP, 'input'), self.backend._states)
        self.transport.nodes[0]['role'] = 'AXTextField'
        self.backend.inspect_tree(APP)
        self.assertFalse(self.backend._states)

    def test_dom_qualification_rejects_duplicate_or_incomplete_observation(self):
        policy = target('WKWebView')
        policy['dom_identifier'] = policy.pop('identifier')
        self.backend.targets = [policy]
        self.transport.nodes[0]['dom_identifier'] = 'input'
        self.transport.nodes.append({**self.transport.nodes[0], 'handle': 'duplicate'})
        self.backend.inspect_tree(APP)
        self.assertFalse(self.backend._states)
        self.transport.nodes.pop()
        original = self.transport.inspect_tree
        self.transport.inspect_tree = lambda app, **bounds: {**original(app, **bounds), 'truncated': True}
        self.backend.inspect_tree(APP)
        self.assertFalse(self.backend._states)

    def test_same_pid_second_owner_lease_conflict(self):
        self.proposal()
        second = LocalNativeBackend([APP], enabled=True, targets=[target()], transport=NativeTransport())
        self.addCleanup(second.close)
        second.inspect_tree(APP)
        self.assertEqual(second.qualify_action('type_text', APP, {'handle': 'input'})['error'], 'capability_rejected')
        self.backend.quiesce()
        second.inspect_tree(APP)
        self.assertEqual(second.qualify_action('type_text', APP, {'handle': 'input'})['status'], 'ok')

    def test_lease_expiry_and_observation_expiry(self):
        args = self.proposal()
        self.backend.clock = lambda: 10**12
        self.assertEqual(self.registry.call('type_text', args)['reason'], 'lease_expired')
        self.assertEqual(self.transport.sent, 0)

    def test_stale_observation_and_reused_pid_reject(self):
        args = self.proposal()
        self.transport.birth = 'new-process'
        self.assertEqual(self.registry.call('type_text', args)['error'], 'capability_rejected')
        self.assertEqual(self.transport.sent, 0)
        self.runtime.observe(APP)
        self.assertEqual(self.registry.call('type_text', args)['error'], 'computer_paused')
        self.assertEqual(self.transport.sent, 0)

    def test_window_rebuild_requires_new_identity_and_new_proposal(self):
        args = self.proposal()
        old = deepcopy(self.backend._states[(APP, 'input')]['identity'])
        self.transport.window_id += 1  # Same title, geometry, PID and text.
        denied = self.registry.call('type_text', args)
        self.assertFalse(denied['action_sent'])
        self.assertEqual(self.transport.sent, 0)
        self.assertEqual(self.runtime.resume()['status'], 'ok')
        self.assertEqual(self.registry.call('type_text', args)['error'], 'stale_observation')
        self.assertEqual(self.runtime.resume()['status'], 'ok')
        fresh = self.proposal()
        identity = self.backend._states[(APP, 'input')]['identity']
        self.assertNotEqual(old['window_id'], identity['window_id'])
        self.assertNotEqual(old['epoch'], identity['epoch'])
        self.assertTrue(self.registry.call('type_text', fresh)['verified'])
        self.assertEqual(self.transport.sent, 1)

    def test_control_replacement_cannot_reuse_same_identifier_qualification(self):
        args = self.proposal()
        self.transport.control_generation += 1
        self.assertFalse(self.registry.call('type_text', args)['action_sent'])
        self.assertEqual(self.transport.sent, 0)
        self.assertEqual(self.runtime.resume()['status'], 'ok')
        self.assertTrue(self.registry.call('type_text', self.proposal())['verified'])

    def test_responder_window_binding_changes_reject_existing_lease(self):
        args = self.proposal()
        self.transport.responder_window_verified = False
        self.assertFalse(self.registry.call('type_text', args)['action_sent'])
        self.assertEqual(self.transport.sent, 0)
        # A new read without qualified responder evidence must stay rejected.
        self.transport.context_error = True
        self.assertEqual(self.runtime.resume()['status'], 'ok')
        self.assertEqual(self.registry.call('type_text', self.proposal())['error'], 'capability_rejected')
        self.assertEqual(self.transport.sent, 0)

    def test_repeated_observation_never_preserves_old_approval_binding(self):
        args = self.proposal()
        previous = deepcopy(self.backend._states[(APP, 'input')])
        for _ in range(10):
            self.runtime.observe(APP)
            current = self.backend._states[(APP, 'input')]
            self.assertNotEqual(previous['lease'], current['lease'])
            self.assertNotEqual(previous['identity']['epoch'], current['identity']['epoch'])
            previous = deepcopy(current)
        self.assertEqual(self.registry.call('type_text', args)['error'], 'stale_observation')
        self.assertEqual(self.transport.sent, 0)

    def test_native_requires_exact_target_text_postcondition(self):
        for post in [condition('result', 'new'), {'selector': {'identifier': 'input'}, 'exists': True},
                     {'selector': {'identifier': 'input'}, 'attribute': 'value', 'not_equals': 'old'},
                     condition(value=None)]:
            with self.subTest(post=post), self.assertRaises(ValueError):
                self.runtime.act('type_text', **{**self.proposal(), 'postcondition': post})
        self.assertEqual(self.transport.sent, 0)

    def test_bounded_utf16_and_host_policy_injection(self):
        with self.assertRaises(ValueError):
            self.runtime.act('type_text', **self.proposal('😀' * 33))
        with self.assertRaises(ValueError):
            self.runtime.act('type_text', **{**self.proposal(), 'enabled': True})
        with self.assertRaises(TypeError):
            self.registry.call('type_text', {**self.proposal(), 'allow_frontmost': True})
        self.assertEqual(self.transport.sent, 0)

    def test_noop_posted_is_not_success(self):
        self.transport.noop = True
        result = self.registry.call('type_text', self.proposal())
        self.assertTrue(result['action_sent'])
        self.assertFalse(result['verified'])
        self.assertEqual(result['error'], 'postcondition_failed')
        self.assertTrue(self.runtime.paused)

    def test_clipped_native_readback_is_unknown(self):
        original = self.transport.inspect_tree
        def clipped(app, **bounds):
            result = original(app, **bounds)
            if self.transport.sent:
                result['nodes'][0]['value_omitted_chars'] = 1
            return result
        self.transport.inspect_tree = clipped
        result = self.registry.call('type_text', self.proposal())
        self.assertEqual(result['error'], 'verification_unavailable')
        self.assertIsNone(result['verified'])
        self.assertTrue(result['action_sent'])
        self.assertTrue(result['verification_attempted'])

    def test_native_posting_does_not_inflate_ax_success_metrics(self):
        self.registry.call('type_text', self.proposal())
        summary = self.runtime.summary()
        self.assertEqual(summary['counts']['native_actions_sent'], 1)
        self.assertIsNone(summary['rates']['ax_action_success_rate'])

    def test_native_close_is_idempotent_and_releases_lease(self):
        self.proposal()
        self.backend.close()
        self.backend.close()
        self.assertFalse(self.backend._states)
        self.assertFalse(self.backend._leases)

    def test_timeout_unknown_no_replay_and_cleanup_blocks_resume(self):
        self.transport.fault = 'timeout'
        args = self.proposal()
        result = self.registry.call('type_text', args)
        self.assertIsNone(result['action_sent'])
        self.assertIsNone(result['verified'])
        self.assertFalse(result['replay_allowed'])
        self.assertTrue(result['request_id'])
        self.assertEqual(result['postcondition'], args['postcondition'])
        self.assertEqual(result['owner'], self.backend.owner)
        self.assertEqual(result['input_cleanup']['cleanup'], 'UNKNOWN')
        self.assertEqual(self.runtime.take_over()['error'], 'input_cleanup_unknown')
        self.assertEqual(self.runtime.resume()['error'], 'input_cleanup_unknown')
        self.assertEqual(self.registry.call('type_text', args)['error'], 'computer_paused')
        self.assertEqual(sum(r['op'] == 'native_text' for r in self.transport.requests), 1)

    def test_unknown_cleanup_blocks_resume_before_dead_helper_environment_read(self):
        self.transport.fault = 'timeout'
        result = self.registry.call('type_text', self.proposal())
        self.assertIsNone(result['verified'])
        self.assertEqual(self.runtime.take_over()['error'], 'input_cleanup_unknown')
        def dead_helper():
            raise RuntimeError('helper process is dead')
        self.transport.environment = dead_helper
        self.assertEqual(self.runtime.resume()['error'], 'input_cleanup_unknown')
        self.assertTrue(self.runtime.paused)
        self.assertEqual(self.transport.sent, 0)

    def test_malformed_or_stale_native_receipt_is_unknown_and_not_replayed(self):
        for index, fault in enumerate(['wrong_id', 'missing_cleanup']):
            with self.subTest(fault=fault), patch('computer.local_native.BUILD', Path(self.tmp.name) / str(index) / 'build'):
                transport = NativeTransport()
                # Independent injected faults need separate recovery stores;
                # a fresh PID cannot clear an earlier app-wide quarantine.
                transport.pid += index + 1
                backend = LocalNativeBackend([APP], enabled=True, targets=[target()], transport=transport)
                runtime = ComputerRuntime(backend, allowed_apps=[APP], verification_timeout=0)
                try:
                    self.backend.quiesce()
                    tree = runtime.inspect_tree(APP)
                    transport.fault = fault
                    result = runtime.act('type_text', app=APP, element='input', observation=tree['observation'],
                                         text='new', postcondition=condition(value='oldnew'))
                    self.assertIsNone(result['verified'])
                    self.assertIsNone(result['action_sent'])
                    self.assertTrue(result['request_id'])
                    self.assertFalse(result['replay_allowed'])
                    self.assertEqual(backend.qualify_action('type_text', APP, {'handle': 'input'})['reason'], 'input_cleanup_unknown')
                    self.assertEqual(transport.sent, 1)
                finally:
                    backend.close()

    def test_readback_exception_keeps_applied_side_effect(self):
        self.transport.read_error = True
        args = self.proposal()
        result = self.registry.call('type_text', args)
        self.assertEqual(result['error'], 'action_outcome_unknown')
        self.assertEqual(result['postcondition'], args['postcondition'])
        self.assertEqual(result['owner'], self.backend.owner)
        self.assertEqual(result['posted_events'], 2)
        self.assertEqual(result['target_tap'], 'NOT_RUN')
        self.assertTrue(result['action_sent'])
        self.assertTrue(result['action_may_have_applied'])
        self.assertIsNone(result['verified'])
        self.assertFalse(result['replay_allowed'])

    def test_human_cursor_motion_allowed_only_for_qualified_native(self):
        self.transport.fault = 'mouse'
        result = self.registry.call('type_text', self.proposal())
        self.assertTrue(result['mouse_changed'])
        self.assertTrue(result['verified'])

    def test_target_foreground_pauses_after_possible_side_effect(self):
        self.transport.fault = 'front'
        result = self.registry.call('type_text', self.proposal())
        self.assertIsNone(result['verified'])
        self.assertTrue(result['action_sent'])
        self.assertEqual(result['error'], 'interference')

    def test_target_already_foreground_refuses_without_send(self):
        self.transport.env.update(frontmost_app=APP, frontmost_pid=self.transport.pid)
        self.assertEqual(self.registry.call('type_text', self.proposal())['error'], 'user_app_active')
        self.assertEqual(self.transport.sent, 0)

    def test_takeover_waits_cleanup_then_observes_and_revokes_targets(self):
        self.transport.block = True
        args = self.proposal()
        action_results = []; takeover_results = []
        worker = threading.Thread(target=lambda: action_results.append(self.registry.call('type_text', args)))
        worker.start()
        self.assertTrue(self.transport.entered.wait(1))
        takeover = threading.Thread(target=lambda: takeover_results.append(self.runtime.take_over()))
        takeover.start()
        self.assertTrue(self.backend._stopped.wait(1))
        self.assertTrue(self.backend._stop_path.exists())
        self.assertTrue(takeover.is_alive())
        self.assertFalse(takeover_results)
        self.transport.release.set()
        worker.join(2); takeover.join(2)
        self.assertFalse(worker.is_alive()); self.assertFalse(takeover.is_alive())
        self.assertTrue(self.transport.stop_seen.is_set())
        self.assertTrue(takeover_results[0]['quiescent'])
        self.assertEqual(self.runtime.state, ControlState.HUMAN)
        self.assertGreater(self.transport.trace.index('observe', 2), self.transport.trace.index('cleanup'))
        self.assertFalse(self.backend._states)
        self.assertFalse(self.backend._leases)
        self.assertTrue(action_results[0]['action_sent'])
        self.assertIsNone(action_results[0]['verified'])

    def test_resume_renews_identity_and_lease_and_rejects_old_proposal(self):
        args = self.proposal()
        state = deepcopy(self.backend._states[(APP, 'input')])
        self.assertEqual(self.runtime.take_over()['status'], 'ok')
        self.transport.birth = 'new-birth'
        self.transport.nodes[0]['value'] = 'human'
        self.assertEqual(self.runtime.resume()['status'], 'ok')
        fresh = self.backend._states[(APP, 'input')]
        self.assertNotEqual(fresh['identity'], state['identity'])
        self.assertNotEqual(fresh['lease'], state['lease'])
        self.assertFalse(self.backend._stop_path.exists())
        self.assertEqual(self.registry.call('type_text', args)['error'], 'stale_observation')
        self.assertTrue(self.runtime.paused)
        self.assertEqual(self.runtime.resume()['status'], 'ok')
        args.update(observation=self.runtime.observations[APP]['token'], postcondition=condition(value='humannew'))
        self.assertTrue(self.registry.call('type_text', args)['verified'])

    def test_unknown_cleanup_never_acknowledges_safe_takeover(self):
        self.transport.cleanup_unknown = True
        self.assertFalse(self.registry.call('type_text', self.proposal())['verified'])
        self.assertEqual(self.runtime.take_over()['error'], 'input_cleanup_unknown')
        self.assertEqual(self.runtime.resume()['error'], 'input_cleanup_unknown')

    def test_native_missing_target_pauses_before_model_can_claim_completed(self):
        self.runtime.observe(APP)
        backend = ScriptBackend(response('find_element', {'app': APP, 'selector': {'identifier': 'absent'}}, 'missing'), response())
        session = AgentSession(create_default_registry(self.tmp.name, permission_mode='full-permission'),
            backend=backend, policy='cloud-only', computer_runtime=self.runtime, streaming=False)
        result = session.run_turn('Insert only into the qualified native target')
        self.assertEqual(result.status, 'computer_paused')
        self.assertEqual(len(result.model_calls), 1)
        self.assertFalse(self.runtime.last_receipt['action_sent'])
        self.assertFalse(self.runtime.last_receipt['replay_allowed'])
        self.assertEqual(self.transport.sent, 0)

    def test_native_expired_approval_cannot_replay_or_complete(self):
        args = self.proposal()
        backend = ScriptBackend(response('type_text', args, 'old'), response())
        session = AgentSession(create_default_registry(self.tmp.name, permission_mode='approve-mutations'),
            backend=backend, policy='cloud-only', computer_runtime=self.runtime, streaming=False)
        self.assertEqual(session.run_turn('Insert native short text').status, 'approval_required')
        self.backend.clock = lambda: 10**12
        result = session.approve()
        self.assertEqual(result.status, 'computer_paused')
        self.assertEqual(len(result.model_calls), 1)
        self.assertEqual(self.transport.sent, 0)
        self.assertFalse(self.runtime.last_receipt['replay_allowed'])

    def test_session_existing_gateway_receipt_and_approval_handoff(self):
        def write(messages):
            return response('type_text', self.proposal(), 'native-write')
        session = AgentSession(create_default_registry(self.tmp.name, permission_mode='approve-mutations'),
            backend=ScriptBackend(write, response()), policy='cloud-only', computer_runtime=self.runtime, streaming=False)
        self.assertEqual(session.run_turn('Insert short text').status, 'approval_required')
        session.take_over_computer()
        session.resume_computer()
        self.assertEqual(self.transport.sent, 0)
        self.assertIsNone(session.pending_approval)
        self.assertEqual(session._computer_pending_actions()[0][0]['desired_text'], 'new')

    def test_session_applied_native_write_is_unknown_when_readback_breaks(self):
        self.transport.read_error = True
        session = AgentSession(create_default_registry(self.tmp.name, permission_mode='full-permission'),
            backend=ScriptBackend(lambda messages: response('type_text', self.proposal(), 'native-write')),
            policy='cloud-only', computer_runtime=self.runtime, streaming=False)
        self.assertEqual(session.run_turn('Insert short text').status, 'computer_paused')
        self.assertIn(session.tool_history[-1]['side_effect_status'], {'partial', 'unknown'})
        self.assertTrue(session.tool_history[-1]['payload']['result']['action_sent'])
        self.assertEqual(session.working.operations[-1]['verification'], 'unknown')


class NativeAPITests(unittest.TestCase):
    """Actual loopback HTTP, existing API/Session/Gateway, scripted keyboard transport."""
    from tests.test_runtime_api import APITests as Fixture
    responses = Fixture.responses
    task = Fixture.task
    host_action = Fixture.host_action
    assert_http = Fixture.assert_http

    def setUp(self):
        from tests.test_runtime_api import Backend, answer, call
        self.Fixture.setUp(self)
        self.addCleanup(self.Fixture.tearDown, self)
        patcher = patch('computer.local_native.BUILD', self.root / 'native-build')
        patcher.start(); self.addCleanup(patcher.stop)
        self.transport = NativeTransport()
        self.native = LocalNativeBackend([APP], enabled=True, targets=[target()], transport=self.transport)
        self.addCleanup(self.native.close)
        self.computer = ComputerRuntime(self.native, allowed_apps=[APP], verification_timeout=0)
        def write(messages):
            tree = self.computer.observations[APP]
            return answer(None, call('type_text', {'app': APP, 'element': 'input',
                'observation': tree['token'], 'text': 'new', 'postcondition': condition(value='oldnew')}, 'native-http-write'))
        self.backend = Backend(answer(None, call('inspect_tree', {'app': APP}, 'observe')), write, answer('done'))

    def test_native_approval_and_verified_receipt_over_real_http(self):
        waiting = self.task(self.responses('Insert native short text'))
        self.assertEqual(waiting['status'], 'requires_approval')
        self.assertEqual(self.transport.sent, 0)
        self.host_action(waiting)
        done = self.task(waiting)
        self.assertEqual(done['status'], 'completed')
        receipt = self.sessions[0].computer.last_receipt
        self.assertTrue(receipt['verified'])
        self.assertEqual(receipt['backend'], 'local_native_experimental')
        self.assertEqual(self.transport.sent, 1)

    def test_native_failed_target_lookup_requires_human_over_real_http(self):
        from tests.test_runtime_api import Backend, answer, call
        self.backend = Backend(answer(None, call('inspect_tree', {'app': APP}, 'observe')),
            answer(None, call('find_element', {'app': APP, 'selector': {'identifier': 'absent'}}, 'missing')),
            answer('Task incomplete: target unavailable'))
        done = self.task(self.responses('Insert native short text'))
        self.assertEqual(done['status'], 'requires_human')
        self.assertEqual(self.transport.sent, 0)
        self.assertFalse(self.sessions[0].computer.last_receipt['replay_allowed'])
        self.assertEqual(len(done['result']['model_calls']), 2)

    def test_native_takeover_invalidates_http_approval_and_prevents_replay(self):
        waiting = self.task(self.responses('Insert native short text'))
        paused = self.client.request(f'/localpilot/v1/tasks/{waiting["id"]}/computer/takeover', {}, control=True)
        self.assertTrue(paused['quiescent'])
        self.assertEqual(paused['status'], 'requires_human')
        self.assert_http(409, f'/localpilot/v1/tasks/{waiting["id"]}/approve',
                         {'action_id': waiting['required_action']['id']}, control=True)
        self.host_action(paused, 'computer/resume')
        done = self.task(waiting)
        self.assertEqual(done['status'], 'incomplete')
        self.assertEqual(self.transport.sent, 0)
        self.assertIn('human_handoff_invalidated', str(done['tools']))


if __name__ == '__main__':
    unittest.main()
