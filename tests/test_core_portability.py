"""Portable Core I/O with real processes and HTTP; scripted replies are not model quality evidence."""
import contextlib
import io
import json
import os
from pathlib import Path
import platform
import select
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import hardware
import main as source_cli
from localpilot_service import cli as core_cli
from localpilot_service.sdk import Client
from tests.test_local_http_backend import MockServer, completion, sse, tool_call


ROOT = Path(__file__).resolve().parents[1]


class CorePortabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.server = MockServer()
        self.process = None
        self.process_error = None

    def tearDown(self):
        self.stop_service()
        self.server.close()
        self.tmp.cleanup()

    def arguments(self, *task):
        return ['--workspace', str(self.workspace), '--local-only',
                '--local-base-url', self.server.base_url, '--local-model', 'mock-local',
                '--no-stream', '--permission-mode', 'full-permission', *task]

    @unittest.skipUnless(platform.system() == 'Linux', 'requires actual Linux process')
    def test_linux_source_entry_runs_real_http_file_tools(self):
        self.server.add(completion(calls=[tool_call('apply_patch', {'changes': [
            {'path': 'portable.txt', 'operation': 'create', 'content': 'portable-core-731'}]})]))
        self.server.add(completion(calls=[tool_call('read_file', {'path': 'portable.txt'}, 'read-1')]))
        self.server.add(completion('Verified portable-core-731'))
        result = subprocess.run([sys.executable, str(ROOT / 'main.py'),
            *self.arguments('Create portable.txt and read it back.')], cwd=ROOT,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.server.requests), 3, result.stdout + result.stderr)
        self.assertEqual((self.workspace / 'portable.txt').read_text(), 'portable-core-731')
        sent = self.server.requests[-1]['messages']
        self.assertTrue(any(m['role'] == 'tool' and 'portable-core-731' in str(m.get('content')) for m in sent))

    @unittest.skipUnless(platform.system() == 'Linux', 'requires actual Linux process')
    def test_source_entry_propagates_unavailable_model_exit_status(self):
        self.server.models = []
        result = subprocess.run([sys.executable, str(ROOT / 'main.py'),
            *self.arguments('hello')], cwd=ROOT, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.server.requests, [])

    def test_intel_identity_uses_existing_http_agent_without_mlx_questionnaire(self):
        self.server.add(completion('configured endpoint answered'))
        identity = {'os': 'macOS', 'arch': 'x86_64', 'chip': 'Intel Core i7',
                    'computer': 'Mac mini', 'memory': 16, 'platform_status': 'deferred',
                    'platform_reason': 'MLX requires Apple Silicon'}
        output = io.StringIO()
        with patch.object(source_cli, 'get_hardware', return_value=identity), \
             patch('builtins.input', side_effect=AssertionError('MLX questionnaire is inapplicable')), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status = source_cli.main(self.arguments('hello'))
        self.assertEqual(status, 0, output.getvalue())
        self.assertEqual(len(self.server.requests), 1)
        self.assertIn('configured endpoint answered', output.getvalue())

    @unittest.skipUnless(platform.system() == 'Linux', 'requires actual Linux hardware discovery')
    def test_linux_hardware_names_the_host_without_claiming_acceleration(self):
        result = hardware.get_hardware()
        self.assertEqual(result['os'], 'Linux')
        self.assertEqual(result['arch'], hardware.get_arch())
        self.assertEqual(result['platform_status'], 'deferred')
        self.assertEqual(result['mps_availability'], 'NOT_PROBED')

    def initialize_service(self, *options):
        self.home = self.root / 'service'
        with contextlib.redirect_stdout(io.StringIO()):
            status = core_cli.main(['--home', str(self.home), '--json', 'init',
                '--workspace', str(self.workspace), '--model', 'mock-local',
                '--base-url', self.server.base_url, '--port', '0', *options])
        self.assertEqual(status, 0)

    def start_service(self):
        env = core_cli.environment(self.home)
        self.process_error = (self.root / 'service-stderr.log').open('a+')
        self.process = subprocess.Popen([sys.executable, '-m', 'localpilot_service',
            '--config', str(self.home / 'service.json')], cwd=ROOT, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=self.process_error, text=True)
        readable, _, _ = select.select([self.process.stdout], [], [], 10)
        self.assertTrue(readable, 'Core did not report readiness')
        line = self.process.stdout.readline()
        if not line:
            self.process_error.seek(0)
            self.fail('Core exited before readiness: ' + self.process_error.read())
        ready = json.loads(line)
        self.assertEqual(ready['status'], 'ready')
        self.url = 'http://127.0.0.1:' + str(ready['port'])
        self.client = Client(self.url, token=env['LOCALPILOT_HTTP_TOKEN'], timeout=5)
        self.operator = Client(self.url, token=env['LOCALPILOT_OPERATOR_TOKEN'], timeout=5)
        connection = json.loads((self.home / 'connection.json').read_text())
        core_cli.save(self.home / 'connection.json', {**connection, 'url': self.url})
        self.assertEqual(self.client.request('/healthz')['status'], 'ready')

    def stop_service(self):
        if self.process is not None:
            process, self.process = self.process, None
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                self.fail('Core failed to stop after SIGTERM')
            finally:
                process.stdout.close()
                self.process_error.close()

    def settled(self, task):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = self.client.status(task['id'])
            if result['status'] not in {'queued', 'running', 'cancelling'}:
                return result
            time.sleep(.02)
        self.fail('Core task did not settle: ' + json.dumps(result))

    def add_stream(self, *, text=None, call=None):
        delta = {'tool_calls': [{'index': 0, **call}]} if call else {'content': text}
        self.server.add(sse({'choices': [{'index': 0, 'delta': delta,
            'finish_reason': 'tool_calls' if call else 'stop'}]}), content_type='text/event-stream')

    def test_configured_process_file_approval_sse_and_sqlite_restart(self):
        self.initialize_service('--context-budget', '8192', '--model-timeout', '120', '--stream-usage')
        config = json.loads((self.home / 'service.json').read_text())
        for route in config['routes'].values():
            self.assertEqual(route['backend']['context_budget'], 8192)
            self.assertEqual(route['backend']['timeout'], 120)
            self.assertTrue(route['backend']['include_stream_usage'])
        self.start_service()
        self.assertEqual(self.server.requests, [], 'startup must not run model inference')
        change = tool_call('apply_patch', {'changes': [
            {'path': 'verified.txt', 'operation': 'create', 'content': 'file-evidence-452'}]}, 'write-452')
        self.add_stream(call=change)
        self.add_stream(call=tool_call('read_file', {'path': 'verified.txt'}, 'read-452'))
        self.add_stream(text='Verified file-evidence-452')
        submitted = self.client.submit('Create verified.txt and read it back.', idempotency_key='portable-process')
        waiting = self.settled(submitted)
        self.assertEqual(waiting['status'], 'requires_approval', waiting)
        self.assertFalse((self.workspace / 'verified.txt').exists())
        self.operator.continue_task(waiting['id'], waiting['required_action']['id'], action='approve')
        completed = self.settled(submitted)
        self.assertEqual(completed['status'], 'completed', completed)
        self.assertEqual((self.workspace / 'verified.txt').read_text(), 'file-evidence-452')
        self.assertEqual(len(self.server.requests), 3)
        self.assertTrue(all(r['stream_options'] == {'include_usage': True} for r in self.server.requests))
        self.assertTrue(any(m['role'] == 'tool' and 'file-evidence-452' in str(m.get('content'))
                            for m in self.server.requests[-1]['messages']))
        events = list(self.client.events(submitted['id']))
        sequences = [event['data']['sequence'] for event in events]
        self.assertEqual(sequences, sorted(set(sequences)))
        self.assertGreater(len(events), 2)
        self.assertEqual(list(self.client.events(submitted['id'], after=sequences[-2]))[-1], events[-1])
        with self.assertRaises(HTTPError) as invalid_cursor:
            list(self.client.events(submitted['id'], after=sequences[-1] + 1))
        self.assertEqual(invalid_cursor.exception.code, 409)
        invalid_cursor.exception.close()
        self.stop_service()
        with sqlite3.connect(self.home / 'data' / 'runtime.sqlite3') as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.start_service()
        restored = self.client.status(submitted['id'])
        self.assertEqual(restored['status'], 'completed')
        self.assertEqual(restored['receipt_summary'], completed['receipt_summary'])
        replay = self.client.submit('Create verified.txt and read it back.', idempotency_key='portable-process')
        self.assertEqual(replay['id'], submitted['id'])
        self.assertEqual(len(self.server.requests), 3, 'restart or duplicate submission replayed inference')

    def test_configured_process_cancels_approval_without_file_effect(self):
        self.initialize_service()
        self.start_service()
        self.add_stream(call=tool_call('apply_patch', {'changes': [
            {'path': 'never.txt', 'operation': 'create', 'content': 'must not be written'}]}))
        submitted = self.client.submit('Request a write then cancel.', idempotency_key='portable-cancel')
        waiting = self.settled(submitted)
        self.assertEqual(waiting['status'], 'requires_approval', waiting)
        self.client.cancel(submitted['id'])
        self.assertEqual(self.settled(submitted)['status'], 'cancelled')
        self.assertFalse((self.workspace / 'never.txt').exists())
        self.stop_service()
        self.start_service()
        self.assertEqual(self.client.status(submitted['id'])['status'], 'cancelled')
        self.assertFalse((self.workspace / 'never.txt').exists())
        self.assertEqual(len(self.server.requests), 1)

    @unittest.skipUnless(sys.platform == 'linux' and shutil.which('bwrap'), 'actual Linux scoped Shell required')
    def test_linux_shell_over_http_keeps_unknown_receipt_across_restart(self):
        self.initialize_service()
        self.start_service()
        session = self.operator.request('/localpilot/v1/desktop-sessions', {
            'client_subject': 'http', 'model': 'localpilot', 'source': 'local_only',
            'options': {'permission_mode': 'workspace', 'agent_profile': 'standard'}}, key='linux-shell-session')
        self.add_stream(call=tool_call('shell', {'command': 'printf linux-http-762 > persisted.txt; cat persisted.txt'}, 'shell-first'))
        self.add_stream(text='Read back linux-http-762')
        task = self.client.submit('Create persisted.txt and read it back.', session_id=session['id'], idempotency_key='linux-shell-first')
        completed = self.settled(task)
        self.assertEqual(completed['status'], 'completed', completed)
        self.assertEqual((self.workspace / 'persisted.txt').read_text(), 'linux-http-762')
        self.add_stream(call=tool_call('shell', {'command': 'printf partial >> partial.txt; sleep 60'}, 'shell-cancel'))
        cancelled = self.client.submit('Start the cancel fixture.', session_id=session['id'], idempotency_key='linux-shell-cancel')
        deadline = time.monotonic() + 5
        while not (self.workspace / 'partial.txt').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue((self.workspace / 'partial.txt').exists())
        self.client.cancel(cancelled['id'])
        terminal = self.settled(cancelled)
        self.assertEqual(terminal['status'], 'cancelled', terminal)
        self.assertTrue(terminal['quiescent'])
        self.assertEqual(terminal['receipt_summary']['unknown_effects'], 1)
        requests_before_restart = len(self.server.requests)
        self.stop_service()
        self.start_service()
        restored = self.client.status(cancelled['id'])
        self.assertEqual(restored['receipt_summary'], terminal['receipt_summary'])
        replay = self.client.submit('Start the cancel fixture.', session_id=session['id'], idempotency_key='linux-shell-cancel')
        self.assertEqual(replay['id'], cancelled['id'])
        self.assertEqual((self.workspace / 'partial.txt').read_text(), 'partial')
        self.assertEqual(len(self.server.requests), requests_before_restart)

    @unittest.skipUnless(sys.platform == 'linux' and shutil.which('bwrap'), 'actual Linux scoped child Shell required')
    def test_linux_child_shell_cancel_keeps_unknown_and_never_replays_after_restart(self):
        from copy import deepcopy
        self.initialize_service()
        config = json.loads((self.home / 'service.json').read_text())
        config['routes']['worker'] = deepcopy(config['routes']['default'])
        config['routes']['default']['cooperation'] = {'routes': ['worker'], 'optimizer': {'mode': 'local-only'}}
        core_cli.save(self.home / 'service.json', config)
        self.start_service()
        session = self.operator.request('/localpilot/v1/desktop-sessions', {
            'client_subject': 'http', 'model': 'localpilot', 'source': 'local_only',
            'options': {'permission_mode': 'workspace', 'agent_profile': 'standard'}}, key='child-shell-session')
        self.add_stream(call=tool_call('delegate', {
            'task': 'Run the child cancellation fixture once.', 'backend_preference': 'local',
            'read_only': False}, 'spawn-child'))
        self.add_stream(call=tool_call('shell', {
            'command': 'printf child-http-partial >> child-partial.txt; sleep 60'}, 'child-shell'))
        question = 'Delegate the child cancellation fixture.'
        initial = self.client.submit(question, session_id=session['id'], idempotency_key='child-cancel')
        marker = self.workspace / 'child-partial.txt'
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(marker.exists(), self.client.status(initial['id']))
        self.client.cancel(initial['id'])
        terminal = self.client.status(initial['id'])
        deadline = time.monotonic() + 5
        while not terminal['quiescent'] and time.monotonic() < deadline:
            time.sleep(.2)
            terminal = self.client.status(initial['id'])
        self.assertEqual(terminal['status'], 'cancelled', terminal)
        self.assertTrue(terminal['quiescent'])
        self.assertEqual(len(terminal['subagents']), 1)
        child = terminal['subagents'][0]
        self.assertEqual(child['status'], 'cancelled')
        shell = [row for row in child['receipts'] if row['name'] == 'shell']
        self.assertEqual(len(shell), 1)
        self.assertEqual(shell[0]['side_effect_status'], 'unknown')
        self.assertFalse(any(row['name'] == 'shell' and not row.get('worker_id') for row in terminal['tools']))
        self.assertGreater(terminal['receipt_summary']['unknown_effects'], 0)
        requests_before_restart = len(self.server.requests)
        self.assertEqual(requests_before_restart, 2)
        self.stop_service()
        self.start_service()
        restored = self.client.status(initial['id'])
        self.assertEqual(restored['receipt_summary'], terminal['receipt_summary'])
        self.assertEqual(restored['subagents'], terminal['subagents'])
        replay = self.client.submit(question, session_id=session['id'], idempotency_key='child-cancel')
        self.assertEqual(replay['id'], initial['id'])
        self.assertEqual(marker.read_text(), 'child-http-partial')
        self.assertEqual(len(self.server.requests), requests_before_restart)

    def test_inflight_http_cancel_does_not_dispatch_a_late_tool(self):
        self.initialize_service('--model-timeout', '10')
        self.start_service()
        started, release = threading.Event(), threading.Event()
        change = tool_call('apply_patch', {'changes': [
            {'path': 'late.txt', 'operation': 'create', 'content': 'must not run after cancel'}]})

        def delayed_response(payload):
            started.set()
            if not release.wait(8):
                return b'data: [DONE]\n\n'
            return sse({'choices': [{'index': 0,
                'delta': {'tool_calls': [{'index': 0, **change}]}, 'finish_reason': 'tool_calls'}]})

        self.server.add(delayed_response, content_type='text/event-stream')
        submitted = self.client.submit('A slow local model response.', idempotency_key='inflight-cancel')
        try:
            self.assertTrue(started.wait(5), 'model HTTP request never began')
            before = time.monotonic()
            self.client.cancel(submitted['id'])
            self.assertLess(time.monotonic() - before, 2, 'stop intent blocked on model HTTP')
            self.assertFalse((self.workspace / 'late.txt').exists())
        finally:
            release.set()
        self.assertEqual(self.settled(submitted)['status'], 'cancelled')
        self.assertFalse((self.workspace / 'late.txt').exists())
        self.assertEqual(len(self.server.requests), 1)

    def test_shared_http_control_interrupts_active_stream_and_keeps_provider_alive(self):
        self.initialize_service('--model-timeout', '10')
        self.start_service()
        registry = self.client.request('/localpilot/v1/model-registry')['models']
        entry = next(model for model in registry if model['id'] == 'localpilot')
        lifecycle = entry['local_model_lifecycle']
        self.assertTrue(lifecycle['shared_external_service'])
        self.assertTrue(lifecycle['request_cancel_supported'])
        self.assertFalse(lifecycle['release_after_task'])
        self.assertFalse(lifecycle['heartbeat_lease'])
        self.assertEqual(lifecycle['provider_compute_stop'], 'UNKNOWN')
        self.assertEqual(entry['provenance'], 'operator_configuration_not_live_health')
        started, release = threading.Event(), threading.Event()
        late = tool_call('apply_patch', {'changes': [
            {'path': 'late-stream.txt', 'operation': 'create', 'content': 'must not run'}]})
        first = ('data: ' + json.dumps({'choices': [{'index': 0,
            'delta': {'content': 'Waiting for provider work'}}]}) + '\n\n').encode()

        def finish():
            started.set()
            release.wait(8)
            return sse({'choices': [{'index': 0,
                'delta': {'tool_calls': [{'index': 0, **late}]}, 'finish_reason': 'tool_calls'}]})

        self.server.add([first, finish], content_type='text/event-stream')
        self.client.control_ticket = 'portable-active-stream-ticket'
        submitted = self.client.submit('A streamed model response.', idempotency_key='stream-cancel')
        try:
            self.assertTrue(started.wait(5))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                pending = self.client.status(submitted['id'])
                if 'Waiting for provider work' in pending.get('streamed_text', ''):
                    break
                time.sleep(.02)
            else:
                self.fail('Core did not receive the first streaming fragment')
            heartbeat = self.client.request('/localpilot/v1/inference/heartbeat', {
                'task_id': submitted['id'], 'ticket_id': self.client.control_ticket})
            self.assertEqual(heartbeat['status'], 'ok')
            before = time.monotonic()
            stopped = self.client.request('/localpilot/v1/inference/stop', {'task_id': submitted['id']})
            terminal = self.settled(submitted)
            self.assertLess(time.monotonic() - before, 2, 'active stream was not disconnected')
            self.assertEqual(terminal['status'], 'cancelled')
            self.assertTrue(terminal['quiescent'])
            self.assertEqual(stopped['models_stopped'], [])
            self.assertFalse(release.is_set(), 'fixture released the HTTP stream before cancellation')
            self.assertFalse((self.workspace / 'late-stream.txt').exists())
            self.add_stream(text='Provider still serves a new request')
            next_task = self.client.submit('A separate new request.', idempotency_key='after-stream-cancel')
            self.assertEqual(self.settled(next_task)['status'], 'completed')
        finally:
            release.set()
        self.stop_service()
        self.start_service()
        self.assertEqual(self.client.status(submitted['id'])['status'], 'cancelled')
        replay = self.client.submit('A streamed model response.', idempotency_key='stream-cancel')
        self.assertEqual(replay['id'], submitted['id'])
        self.assertEqual(len(self.server.requests), 2)
        self.assertFalse((self.workspace / 'late-stream.txt').exists())

    def test_cli_explicit_unknown_power_request_and_operator_disable(self):
        self.initialize_service('--context-budget', '8192', '--model-timeout', '120')
        self.start_service()
        self.add_stream(text='Explicit local request completed')
        arguments = ['--home', str(self.home), '--json', 'ask', '--detach', 'hello']
        with patch.object(hardware, 'external_power', return_value=None), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(core_cli.main(arguments), 2)
            self.assertEqual(self.server.requests, [])
            with patch.dict(os.environ, {'LOCALPILOT_DISABLE_LOCAL_MODELS': '1'}):
                self.assertEqual(core_cli.main([*arguments, '--allow-local-on-battery']), 2)
            self.assertEqual(self.server.requests, [])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(core_cli.main([*arguments, '--allow-local-on-battery']), 0)
        task = json.loads(output.getvalue())
        self.assertEqual(self.settled(task)['status'], 'completed')
        self.assertEqual(len(self.server.requests), 1)
        self.assertNotIn('stream_options', self.server.requests[0])
        persisted = json.loads((self.home / 'service.json').read_text())
        self.assertNotIn('allow_local_on_battery', json.dumps(persisted))


class CoreEndpointInputTests(unittest.TestCase):
    def test_invalid_context_and_timeout_never_create_credentials(self):
        from localpilot_service.configure import main as configure
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / 'workspace'
            workspace.mkdir()
            for flag, value in [('--context-budget', '0'), ('--context-budget', '-1'),
                                ('--model-timeout', 'nan'), ('--model-timeout', 'inf'),
                                ('--model-timeout', '0')]:
                home = root / 'service'
                with self.subTest(flag=flag, value=value), \
                     contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    configure(['--workspace', str(workspace), '--directory', str(home),
                               '--model', 'configured-cpu-model', flag, value])
                self.assertFalse(home.exists())

    def test_mac_desktop_power_fallback_requires_observed_ac_source(self):
        with patch('psutil.sensors_battery', return_value=None), \
             patch.object(hardware.platform, 'system', return_value='Darwin'), \
             patch.object(hardware.subprocess, 'run') as pmset:
            for output, expected in [("Now drawing from 'AC Power'\n", True),
                                     ("Now drawing from 'Battery Power'\n", False),
                                     ('unrecognized power source\n', None)]:
                with self.subTest(output=output):
                    pmset.return_value = SimpleNamespace(stdout=output)
                    self.assertIs(hardware.external_power(), expected)
            pmset.side_effect = FileNotFoundError
            self.assertIsNone(hardware.external_power())

    def test_observed_battery_is_not_overridden_and_linux_unknown_stays_unknown(self):
        with patch('psutil.sensors_battery', return_value=SimpleNamespace(power_plugged=False)), \
             patch.object(hardware.subprocess, 'run', side_effect=AssertionError('no fallback for observed battery')):
            self.assertIs(hardware.external_power(), False)
        with patch('psutil.sensors_battery', return_value=None), \
             patch.object(hardware.platform, 'system', return_value='Linux'), \
             patch.object(hardware.subprocess, 'run', side_effect=AssertionError('never run pmset on Linux')):
            self.assertIsNone(hardware.external_power())


if __name__ == '__main__':
    unittest.main()
