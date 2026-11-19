"""Owned CPU llama.cpp qualification using real weights and synthetic local tasks.

This is a product integration probe, not a public benchmark or an Agent ranking.
It never attaches to another model service, downloads weights, or uses cloud keys.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from localpilot_service import cli
from localpilot_service.sdk import Client
from agent.session_types import SessionBudgets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-binary', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--model-sha256', required=True)
    parser.add_argument('--model-revision', required=True)
    parser.add_argument('--model-alias', default='localpilot-qualified')
    parser.add_argument('--reasoning', choices=('auto', 'on', 'off'), default='auto')
    parser.add_argument('--sampling-profile', choices=('greedy', 'qwen35-nonthinking'), default='greedy')
    parser.add_argument('--server-commit', required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--public-study-protocol', type=Path)
    args = parser.parse_args()
    binary, model = args.server_binary.resolve(strict=True), args.model.resolve(strict=True)
    actual = digest(model)
    if actual != args.model_sha256:
        parser.error('Model SHA256 does not match the reviewed source')
    out = args.evidence.resolve()
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {'kind': 'REAL_CPU_MODEL_SYNTHETIC_INPUTS', 'model': model.name,
              'model_sha256': actual, 'model_revision': args.model_revision,
              'server_commit': args.server_commit, 'server_binary_sha256': digest(binary),
              'model_alias': args.model_alias, 'reasoning': args.reasoning,
              'sampling_profile': args.sampling_profile,
              'integration_budget': {'context_tokens': 8192, 'output_tokens': 512,
                                     'threads': 2, 'max_steps': 6,
                                     'max_token_units': SessionBudgets().max_token_units,
                                     'max_worker_token_units': SessionBudgets().max_worker_token_units},
              'companion_sampling': {'temperature': 0, 'source': 'unchanged production request_chat default'},
              'model_count': 1, 'cloud_calls': 0, 'api_cost_usd': 0,
              'energy_cost': 'UNKNOWN', 'ranking_claim': False, 'cases': {}}
    provider = Provider(binary, model, out, alias=args.model_alias, reasoning=args.reasoning,
                        sampling_profile=args.sampling_profile)
    report['main_agent_generation_parameters'] = provider.generation_parameters
    core = None
    try:
        provider.start()
        version = subprocess.run([str(binary), '--version'], capture_output=True, text=True, timeout=10)
        report['provider_version'] = (version.stdout + version.stderr).strip()
        if args.server_commit[:9] not in report['provider_version']:
            raise ValueError('Provider version does not match the reviewed server commit')
        record(report, out, 'kv_cold_hot_restart', lambda: cache_probe(provider, out))
        record(report, out, 'direct_arithmetic', lambda: arithmetic(provider, out))
        core = Core(provider, out)
        core.start()
        record(report, out, 'real_file_read', lambda: file_read(core))
        record(report, out, 'real_shell', lambda: shell_task(core))
        record(report, out, 'real_child_agent', lambda: child_task(core))
        record(report, out, 'real_stream_cancellation', lambda: stream_cancel(core, provider))
        record(report, out, 'real_shell_unknown_restart', lambda: unknown_restart(core))
        record(report, out, 'companion_lightweight', lambda: companion_lightweight(provider, out))
        record(report, out, 'companion_core_delegation', lambda: companion_delegation(core, out))
        if args.public_study_protocol:
            from scripts.public_model_eval import run_study
            report['public_study'] = run_study(args.public_study_protocol,
                endpoint=provider.origin + '/v1', evidence=out / 'public-study',
                model_identity={'model_name': provider.alias, 'model_revision': args.model_revision,
                                'model_sha256': actual, 'server_commit': args.server_commit,
                                'server_binary_sha256': report['server_binary_sha256'],
                                'reasoning': args.reasoning, 'context_tokens': 8192},
                generation_parameters=provider.generation_parameters)
        save(out / 'provider-slots-final.json', provider.request('/slots'))
        (out / 'provider-metrics-final.txt').write_text(provider.request('/metrics', raw=True))
    except Exception as error:
        report['setup_error'] = {'type': type(error).__name__, 'message': str(error)[:500]}
    finally:
        if core is not None:
            core.stop()
        provider.stop()
        report['provider_processes'] = provider.measurements
        report['owned_processes_stopped'] = (core is None or core.process is None) and provider.process is None
        save(out / 'RESULTS.json', report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 1 if report.get('setup_error') or any(row['status'] != 'PASS' for row in report['cases'].values()) else 0


def digest(path):
    sha = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    path.chmod(0o600)


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def record(report, out, name, operation):
    started = time.monotonic()
    try:
        value = operation()
        value.setdefault('status', 'PASS' if value.pop('passed', False) else 'FAIL')
    except Exception as error:
        value = {'status': 'ERROR', 'error_type': type(error).__name__, 'message': str(error)[:500]}
        if isinstance(error, HTTPError):
            value['http_status'] = error.code
            with error:
                value['http_body'] = error.read(4096).decode(errors='replace')
    value['seconds'] = time.monotonic() - started
    report['cases'][name] = value
    save(out / 'RESULTS.json', report)
    print(json.dumps({'case': name, **value}, ensure_ascii=False), flush=True)


class Provider:
    def __init__(self, binary, model, out, *, alias='localpilot-qualified', reasoning='auto', sampling_profile='greedy'):
        self.out, self.binary, self.model = out, binary, model
        self.cache = out / 'owned-slot-cache'
        self.cache.mkdir(mode=0o700)
        self.port = port()
        self.origin = f'http://127.0.0.1:{self.port}'
        self.alias, self.reasoning = alias, reasoning
        self.sampling_profile = sampling_profile
        self.generation_parameters = ({'temperature': 1.0, 'top_p': 1.0,
                                       'presence_penalty': 2.0, 'seed': 42}
                                      if sampling_profile == 'qwen35-nonthinking' else {'temperature': 0})
        self.measurements = []
        self.process = self.log = None
        self.opener = build_opener(ProxyHandler({}))

    def start(self):
        command = [str(self.binary), '--model', str(self.model), '--host', '127.0.0.1',
                   '--port', str(self.port), '--alias', self.alias, '--offline', '--no-webui',
                   '--jinja', '--ctx-size', '8192', '--parallel', '1', '--threads', '2',
                   '--threads-batch', '2', '-ngl', '0', '--cache-ram', '256', '--metrics',
                   '--slots', '--slot-save-path', str(self.cache), '--reasoning', self.reasoning]
        if self.sampling_profile == 'qwen35-nonthinking':
            command.extend(['--temp', '1.0', '--top-p', '1.0', '--top-k', '20', '--min-p', '0.0',
                            '--presence-penalty', '2.0', '--repeat-penalty', '1.0', '--seed', '42'])
        save(self.out / 'provider-command.json', command)
        self.log = (self.out / 'provider.log').open('a')
        self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log)
        self.started = time.monotonic()
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError('Owned llama-server exited during startup; inspect provider.log')
            try:
                if self.request('/health')['status'] == 'ok':
                    return
            except (OSError, URLError):
                pass
            time.sleep(.1)
        raise TimeoutError('Owned llama-server did not become healthy')

    def request(self, path, body=None, *, raw=False):
        request = Request(self.origin + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json'})
        with self.opener.open(request, timeout=90) as response:
            data = response.read()
        return data.decode() if raw else json.loads(data)

    def chat(self, messages, max_tokens=32):
        return self.request('/v1/chat/completions', {'model': self.alias, 'messages': messages,
            **self.generation_parameters, 'max_tokens': max_tokens, 'cache_prompt': True})

    def stop(self):
        if self.process is not None:
            process, self.process = self.process, None
            measurement = {'pid': process.pid, 'wall_seconds': time.monotonic() - self.started,
                           'peak_rss_kib': 'UNKNOWN', 'source': '/proc/PID/status VmHWM before termination'}
            if process.poll() is None:
                try:
                    for line in Path(f'/proc/{process.pid}/status').read_text().splitlines():
                        if line.startswith('VmHWM:'):
                            measurement['peak_rss_kib'] = int(line.split()[1])
                except FileNotFoundError:
                    pass
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            measurement['returncode'] = process.returncode
            self.measurements.append(measurement)
        if self.log is not None:
            self.log.close()
            self.log = None


def cache_probe(provider, out):
    from agent.profiles import prompt_text
    prefix = prompt_text('standard') + '\n' + (ROOT / 'localpilot-agent' / 'SKILL.md').read_text()
    messages = [{'role': 'system', 'content': prefix}, {'role': 'user', 'content': 'Reply with READY only.'}]
    responses = {}
    for stage in ('cold', 'hot'):
        responses[stage] = provider.chat(messages, 16)
        save(out / ('kv-' + stage + '.json'), responses[stage])
    saved = provider.request('/slots/0?action=save', {'filename': 'fixed-prefix.bin'})
    save(out / 'kv-save.json', saved)
    cache_hash = digest(provider.cache / 'fixed-prefix.bin')
    old_pid = provider.process.pid
    provider.stop()
    provider.start()
    restored = provider.request('/slots/0?action=restore', {'filename': 'fixed-prefix.bin'})
    save(out / 'kv-restore.json', restored)
    responses['restart'] = provider.chat(messages, 16)
    save(out / 'kv-restart.json', responses['restart'])
    cached = {name: value.get('usage', {}).get('prompt_tokens_details', {}).get('cached_tokens')
              for name, value in responses.items()}
    return {'passed': saved.get('n_saved', 0) > 0 and restored.get('n_restored') == saved.get('n_saved')
            and all(isinstance(cached[name], int) and cached[name] > 0 for name in ('hot', 'restart')),
            'prefix_sha256': hashlib.sha256(prefix.encode()).hexdigest(), 'cached_tokens': cached,
            'usage': {name: value.get('usage', 'UNKNOWN') for name, value in responses.items()},
            'timings': {name: value.get('timings', 'UNKNOWN') for name, value in responses.items()},
            'saved_tokens': saved.get('n_saved'), 'restored_tokens': restored.get('n_restored'),
            'cache_sha256': cache_hash, 'provider_pid_changed': provider.process.pid != old_pid,
            'scope': 'owned llama.cpp slot with fixed actual prompt and Skill; not all providers or permanent cache'}


def arithmetic(provider, out):
    response = provider.chat([{'role': 'user', 'content': 'What is 8 * 7? Reply with the integer only.'}], 32)
    save(out / 'direct-arithmetic.json', response)
    text = response['choices'][0]['message'].get('content', '')
    return {'passed': text.strip() == '56', 'answer': text, 'usage': response.get('usage', 'UNKNOWN')}


class Core:
    def __init__(self, provider, out):
        self.out, self.home = out, out / 'core-private'
        self.work = out / 'workspace'
        self.work.mkdir(mode=0o700)
        self.marker = 'LP-LINUX-REAL-7319'
        (self.work / 'fact.txt').write_text(self.marker + '\n')
        core_port = port()
        initialized = subprocess.run([sys.executable, '-m', 'localpilot_service.cli', '--home', str(self.home),
            '--json', 'init', '--workspace', str(self.work), '--model', provider.alias,
            '--base-url', provider.origin + '/v1', '--context-budget', '8192',
            '--model-timeout', '90', '--stream-usage', '--port', str(core_port)],
            cwd=ROOT, capture_output=True, text=True, timeout=10)
        if initialized.returncode:
            raise RuntimeError('Core initialization failed: ' + initialized.stdout[:500])
        config = json.loads((self.home / 'service.json').read_text())
        for route in config['routes'].values():
            route.update(engine='v5', tool_profile='compact')
            route['budgets'] = {'max_steps': 6, 'max_tool_calls': 8, 'max_output_tokens': 512,
                'max_token_units': SessionBudgets().max_token_units, 'max_subagents_per_turn': 2,
                'max_worker_steps': 3, 'max_worker_tool_calls': 4,
                'max_worker_token_units': SessionBudgets().max_worker_token_units}
            route['backend']['generation_parameters'] = dict(provider.generation_parameters)
        config['routes']['worker'] = deepcopy(config['routes']['default'])
        config['routes']['default']['cooperation'] = {'routes': ['worker'], 'optimizer': {'mode': 'local-only'}}
        save(out / 'resolved-runtime-budgets.json', {name: route['budgets'] for name, route in config['routes'].items()})
        cli.save(self.home / 'service.json', config)
        self.env = cli.environment(self.home)
        self.env['PYTHONPATH'] = str(ROOT)
        self.client = Client(f'http://127.0.0.1:{core_port}', token=self.env['LOCALPILOT_HTTP_TOKEN'], timeout=15)
        self.operator = Client(self.client.base_url, token=self.env['LOCALPILOT_OPERATOR_TOKEN'], timeout=15)
        self.process = self.log = None

    def start(self):
        self.log = (self.out / 'core.log').open('a')
        self.process = subprocess.Popen([sys.executable, '-m', 'localpilot_service',
            '--config', str(self.home / 'service.json')], cwd=ROOT, env=self.env,
            stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError('Core exited during startup; inspect core.log')
            try:
                if self.client.request('/healthz')['status'] == 'ready':
                    return
            except OSError:
                pass
            time.sleep(.1)
        raise TimeoutError('Core startup did not finish')

    def session(self, name):
        return self.operator.request('/localpilot/v1/desktop-sessions', {
            'client_subject': 'http', 'model': 'localpilot', 'source': 'local_only',
            'options': {'permission_mode': 'workspace', 'agent_profile': 'standard'}}, key=name)['id']

    def submit(self, name, question, *, session=None, model='localpilot'):
        return self.client.submit(question, session_id=session, model=model, idempotency_key=name, timeout_seconds=150)

    def finish(self, name, task):
        deadline = time.monotonic() + 160
        while time.monotonic() < deadline:
            task = self.client.status(task['id'])
            if task['quiescent'] and task['status'] not in {'queued', 'running', 'cancelling'}:
                save(self.out / (name + '-task.json'), task)
                return task
            time.sleep(1)
        self.client.cancel(task['id'])
        raise TimeoutError('Task exceeded qualification deadline; cancel requested')

    def stop(self):
        if self.process is not None:
            process, self.process = self.process, None
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if self.log is not None:
            self.log.close()
            self.log = None


def task_summary(task):
    result = task.get('result') or {}
    return {'task_id': task['id'], 'task_status': task['status'],
            'answer': result.get('text'),
            'tools': [row['name'] for row in task.get('tools', [])],
            'subagents': task.get('subagents', []), 'model_calls': result.get('model_calls', 'UNKNOWN'),
            'runtime_metrics': result.get('runtime_metrics', 'UNKNOWN'),
            'receipt_summary': task.get('receipt_summary'), 'quiescent': task.get('quiescent')}


def file_read(core):
    task = core.finish('read', core.submit('read', 'Read fact.txt with read_file and return its contents exactly.', session=core.session('read-session')))
    summary = task_summary(task)
    readback = any(row['name'] == 'read_file' and row.get('status') == 'completed'
        and (row.get('read_receipt') or {}).get('version', {}).get('path') == 'fact.txt'
        for row in task.get('tools', []))
    return {'passed': task['status'] == 'completed' and readback and core.marker in (summary['answer'] or ''),
            'requested_read_observed': readback, **summary}


def shell_task(core):
    task = core.finish('shell', core.submit('shell', 'Use shell to run exactly: printf 7319 > computed.txt . Then use read_file to read computed.txt and report its contents.', session=core.session('shell-session')))
    summary = task_summary(task)
    target = core.work / 'computed.txt'
    readback = any(row['name'] == 'read_file' and row.get('status') == 'completed'
        and (row.get('read_receipt') or {}).get('version', {}).get('path') == 'computed.txt'
        for row in task.get('tools', []))
    return {'passed': task['status'] == 'completed' and 'shell' in summary['tools'] and readback
            and target.is_file() and target.read_text() == '7319' and '7319' in (summary['answer'] or ''),
            'requested_readback_observed': readback, **summary}


def child_task(core):
    task = core.finish('child', core.submit('child', 'Use delegate once with backend_preference local and read_only true. Ask the child to read fact.txt and return the complete contents. Include the child result in your final answer.', session=core.session('child-session')))
    summary = task_summary(task)
    child_read = any(child.get('status') == 'completed'
        and any(row['name'] == 'read_file' and row.get('status') == 'completed'
            and (row.get('read_receipt') or {}).get('version', {}).get('path') == 'fact.txt'
            for row in child.get('receipts', []))
        for child in task.get('subagents', []))
    return {'passed': task['status'] == 'completed' and child_read and core.marker in (summary['answer'] or ''),
            'requested_child_read_observed': child_read,
            'scope': 'real parent and child requests to one local model, not different-model or cloud qualification', **summary}


def stream_cancel(core, provider):
    started = time.monotonic()
    task = core.submit('stream-cancel', 'Write the integers from 1 to 5000, one per line.', model='companion-reasoning')
    frames, observed = [], False
    events = core.client.events(task['id'])
    try:
        for event in events:
            frames.append(event)
            if event['data'].get('type') == 'runtime.event' and event['data'].get('data', {}).get('type') == 'TextDelta':
                observed = True
                first_text_seconds = time.monotonic() - started
                core.client.cancel(task['id'])
                break
    finally:
        events.close()
    save(core.out / 'cancel-sse.json', frames)
    terminal = core.finish('stream-cancel', task)
    slots = provider.request('/slots')
    save(core.out / 'provider-after-cancel.json', slots)
    cursor_status = None
    try:
        list(core.client.events(task['id'], after=1000000000))
    except HTTPError as error:
        cursor_status = error.code
        error.close()
    return {'passed': observed and terminal['status'] == 'cancelled' and terminal['quiescent'] and cursor_status == 409,
            'sse_text_observed': observed, 'provider_alive': provider.process.poll() is None,
            'submit_to_first_text_seconds': first_text_seconds if observed else 'UNKNOWN',
            'first_text_scope': 'Core submit through first SSE TextDelta, including admission and queue; not provider-only TTFT',
            'invalid_cursor_http_status': cursor_status, 'provider_slots': slots, **task_summary(terminal)}


def unknown_restart(core):
    session = core.session('unknown-session')
    question = 'Use shell to run exactly this one command: printf partial >> partial.txt; sleep 60 . Wait for it to finish.'
    task = core.submit('unknown', question, session=session)
    marker = core.work / 'partial.txt'
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not marker.exists():
        state = core.client.status(task['id'])
        if state['quiescent'] and state['status'] not in {'queued', 'running', 'cancelling'}:
            break
        time.sleep(1)
    if not marker.exists():
        core.client.cancel(task['id'])
        terminal = core.finish('unknown', task)
        return {'passed': False, 'reason': 'real model did not execute the requested shell before cancellation', **task_summary(terminal)}
    core.client.cancel(task['id'])
    terminal = core.finish('unknown', task)
    before = marker.read_bytes()
    old_pid = core.process.pid
    core.stop()
    core.start()
    restored = core.client.status(task['id'])
    save(core.out / 'unknown-restored.json', restored)
    replay = core.submit('unknown', question, session=session)
    return {'passed': terminal['status'] == 'cancelled' and terminal['receipt_summary']['unknown_effects'] > 0
            and restored['receipt_summary'] == terminal['receipt_summary'] and replay['id'] == task['id']
            and marker.read_bytes() == before,
            'core_pid_changed': core.process.pid != old_pid, 'file_contents': before.decode(),
            'same_task_after_resubmit': replay['id'] == task['id'], **task_summary(restored)}


def companion_lightweight(provider, out):
    from companion.config import Config
    from companion.model import ModelManager
    from companion.runtime.service import SYSTEM
    config = Config(data_dir=str(out / 'companion-private'), backend='local-http',
        http_model_endpoint=provider.origin + '/v1', http_model_name=provider.alias,
        http_model_host_local_only=True, low_power_policy='off', allow_local_on_battery=True,
        max_output_tokens=64, desktop_control_enabled=False)
    manager = ModelManager(config)
    try:
        answer = manager.complete([{'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': 'What is 8 * 7? Reply with the integer only.'}])
        save(out / 'companion-lightweight.json', answer)
        return {'passed': answer.get('status') == 'ok' and str(answer.get('text', '')).strip() == '56',
                'response': answer, 'scope': 'actual Companion model backend, explicit test power grant; no native observation claim'}
    finally:
        manager.unload()


def companion_delegation(core, out):
    from companion.config import Config
    from companion.escalation.service_v491 import LocalPilotProvider
    config = Config(data_dir=str(out / 'companion-delegation'), backend='disabled',
        low_power_policy='off', allow_local_on_battery=True, localpilot_endpoint=core.client.base_url,
        localpilot_client_subject='companion', localpilot_route='localpilot',
        localpilot_analysis_route='companion-reasoning', localpilot_host_local_only=True,
        localpilot_task_timeout_seconds=150, desktop_control_enabled=False)
    with cli.temporary_environment({'LOCALPILOT_COMPANION_TOKEN': core.env['LOCALPILOT_COMPANION_TOKEN']}):
        provider = LocalPilotProvider(config)
        result = provider.submit({'user_request': 'Read fact.txt using read_file and return the exact complete contents.',
            'privacy_scope': {'local_only': True}}, approved=True, submission_id='companion-real-read')
        save(out / 'companion-submit.json', result)
        if not result.get('task_id'):
            return {'status': 'BLOCKED', 'submission': result}
        deadline = time.monotonic() + 160
        while time.monotonic() < deadline:
            result = provider.status(result['task_id'])
            if result.get('task', {}).get('quiescent') and result.get('status') not in {'queued', 'running', 'cancelling'}:
                break
            time.sleep(1)
        save(out / 'companion-delegation.json', result)
        task = result.get('task', {})
        answer = (task.get('result') or {}).get('text', '')
        readback = any(row['name'] == 'read_file' and row.get('status') == 'completed'
            and (row.get('read_receipt') or {}).get('version', {}).get('path') == 'fact.txt'
            for row in task.get('tools', []))
        return {'passed': result.get('status') == 'completed' and readback and core.marker in answer,
                'requested_read_observed': readback,
                'task_status': result.get('status'), 'answer': answer,
                'scope': 'real Companion Task API adapter plus Core and model; native control window not exercised'}


if __name__ == '__main__':
    raise SystemExit(main())
