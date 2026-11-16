#!/usr/bin/env python3
"""Exercise the real Core over HTTP with an explicitly funded OpenAI key.

Only synthetic fixtures enter the model. Credentials remain in a private file;
the evidence directory contains no copied key or client bearer tokens.
"""
from copy import deepcopy
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.qualify_linux_model import Core, save, task_summary
from localpilot_service import cli


def main():
    args = arguments()
    args.output.mkdir(parents=True, mode=0o700)
    report = {'model': args.model, 'protocol': 'responses', 'reasoning': args.reasoning,
              'case': args.case, 'source': source_identity(), 'results': {}}
    core = CloudCore(args.output, args.key_file, args.model, args.reasoning)
    try:
        core.start()
        if args.case == 'smoke':
            smoke(core, report)
        else:
            soak(core, report, args.soak_seconds)
    except Exception as error:
        report['error'] = {'type': type(error).__name__, 'message': str(error)[:1000]}
    finally:
        core.stop()
        report['owned_core_stopped'] = core.process is None
        report['passed'] = not report.get('error') and bool(report['results']) and all(
            result['passed'] for result in report['results'].values())
        save(args.output / 'RESULTS.json', report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


class CloudCore(Core):
    def __init__(self, out, key_file, model='gpt-6-luna', reasoning='medium', *, work=None):
        super().__init__(SimpleNamespace(alias=model, origin='http://127.0.0.1:1',
                                         generation_parameters={}), out)
        if work is not None:
            self.work = Path(work).resolve()
        config = json.loads((self.home / 'service.json').read_text())
        backend = {'kind': 'openai', 'protocol': 'responses', 'model': model,
                   'key_file': str(Path(key_file).resolve()), 'context_budget': 1050000,
                   'timeout': 180}
        for route in config['routes'].values():
            route.update(workspace=str(self.work), backend=deepcopy(backend),
                         thinking=reasoning, cloud_egress='CLOUD_ALLOWED')
            route['budgets'].update(max_steps=100, max_tool_calls=200,
                max_output_tokens=8192, max_token_units=64 * 1024 * 1024,
                max_worker_steps=30, max_worker_tool_calls=60,
                max_worker_output_tokens=4096, max_worker_token_units=8 * 1024 * 1024)
        config['routes']['default']['cooperation']['optimizer']['mode'] = 'cloud-only'
        cli.save(self.home / 'service.json', config)
        self.env['PYTHONPATH'] = str(ROOT)
        self.client.timeout = self.operator.timeout = 30
        save(out / 'resolved-runtime-budgets.json', {
            name: route['budgets'] for name, route in config['routes'].items()})

    def session(self, name, *, extended=False, profile='standard'):
        return self.operator.request('/localpilot/v1/desktop-sessions', {
            'client_subject': 'http', 'model': 'localpilot', 'source': 'cloud_only',
            'options': {'permission_mode': 'full', 'agent_profile': profile,
                        'execution_budget': 'extended' if extended else 'standard'}}, key=name)['id']

    def submit(self, name, question, *, session=None, model='localpilot', timeout=600):
        return self.client.submit(question, session_id=session, model=model,
                                  idempotency_key=name, timeout_seconds=timeout)

    def finish(self, name, task, *, timeout=660, checkpoint_seconds=15):
        started = time.monotonic()
        last_checkpoint = -checkpoint_seconds
        while time.monotonic() - started < timeout:
            task = self.client.status(task['id'])
            elapsed = time.monotonic() - started
            if elapsed - last_checkpoint >= checkpoint_seconds:
                save(self.out / (name + '-progress.json'), {
                    'elapsed_seconds': elapsed, 'task_id': task['id'],
                    'status': task['status'], 'quiescent': task['quiescent'],
                    'tools': [row['name'] for row in task.get('tools', [])]})
                last_checkpoint = elapsed
            if task['quiescent'] and task['status'] not in {'queued', 'running', 'cancelling'}:
                save(self.out / (name + '-task.json'), task)
                return task
            time.sleep(1)
        self.client.cancel(task['id'])
        raise TimeoutError('Qualification deadline exceeded; cancellation requested')


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', default='gpt-6-luna')
    parser.add_argument('--reasoning', default='medium')
    parser.add_argument('--case', choices=('smoke', 'soak'), default='smoke')
    parser.add_argument('--soak-seconds', type=int, default=7200)
    args = parser.parse_args()
    if not 65 <= args.soak_seconds <= 82800:
        parser.error('--soak-seconds must be between 65 and 82800')
    from agent.cloud_credentials import resolve_openai_key
    resolve_openai_key(key_file=args.key_file)
    return args


def source_identity():
    paths = [*ROOT.glob('agent/**/*.py'), *ROOT.glob('localpilot_api/**/*.py'),
             *ROOT.glob('localpilot_service/**/*.py'), Path(__file__)]
    entries = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in sorted(paths)}
    return {'files': entries, 'manifest_sha256': hashlib.sha256(
        json.dumps(entries, sort_keys=True).encode()).hexdigest()}


def smoke(core, report):
    session = core.session('cloud-smoke-session')
    prompt = ('Use shell to run exactly: printf 7319 > computed.txt . '
              'Then use read_file to read computed.txt and fact.txt. '
              'Return both complete contents. Do not ask for another approval.')
    task = core.finish('shell-read', core.submit('cloud-shell-read', prompt, session=session))
    names = [row['name'] for row in task.get('tools', [])]
    text = (task.get('result') or {}).get('text', '')
    report['results']['shell_read'] = {'passed': task['status'] == 'completed'
        and 'shell' in names and 'read_file' in names and '7319' in text
        and core.marker in text and (core.work / 'computed.txt').read_text() == '7319',
        **task_summary(task)}
    child_prompt = ('Use delegate once with backend_preference cloud and read_only true. '
        'Ask the child to read fact.txt and return its complete contents. '
        'Include the child result in your final answer. Do not read fact.txt yourself.')
    child = core.finish('delegate', core.submit('cloud-delegate', child_prompt,
                                              session=core.session('cloud-child-session')))
    child_read = any(row.get('status') == 'completed' and any(
        receipt.get('name') == 'read_file' and receipt.get('status') == 'completed'
        for receipt in row.get('receipts', [])) for row in child.get('subagents', []))
    report['results']['delegate'] = {'passed': child['status'] == 'completed' and child_read
        and core.marker in (child.get('result') or {}).get('text', ''),
        'completed_child_read_observed': child_read, **task_summary(child)}
    original_id = task['id']
    core.stop()
    core.start()
    restored = core.submit('cloud-shell-read', prompt, session=session)
    report['results']['restart_idempotency'] = {'passed': restored['id'] == original_id
        and restored['status'] == 'completed' and len(restored.get('tools', [])) == len(names),
        'task_id': restored['id'], 'task_status': restored['status'],
        'same_task': restored['id'] == original_id}


def soak(core, report, seconds):
    script = core.work / 'heartbeat.py'
    script.write_text('import json,time\nfrom pathlib import Path\n'
        'start=time.monotonic()\n'
        'with Path("heartbeat.jsonl").open("a") as stream:\n'
        f'    while time.monotonic()-start < {seconds}:\n'
        '        stream.write(json.dumps({"elapsed":time.monotonic()-start})+"\\n")\n'
        '        stream.flush()\n'
        f'        time.sleep(min(30,max(0,{seconds}-(time.monotonic()-start))))\n'
        'Path("soak-finished.txt").write_text("LOCALPILOT_SOAK_COMPLETE")\n'
        'print("LOCALPILOT_SOAK_COMPLETE",flush=True)\n')
    command = shlex.quote(sys.executable) + ' heartbeat.py'
    prompt = (f'Run exactly this shell command with timeout {seconds + 120}: {command}\n'
        f'This is an authorized {seconds}-second runtime soak. Let it finish; do not background it. '
        'After shell returns, use read_file to read soak-finished.txt and report the exact contents. '
        'The task has already been approved with full permissions and the extended execution budget.')
    started = time.monotonic()
    task = core.finish('soak', core.submit('cloud-soak', prompt,
        session=core.session('cloud-soak-session', extended=True), timeout=seconds + 600),
        timeout=seconds + 660)
    elapsed = time.monotonic() - started
    heartbeat = core.work / 'heartbeat.jsonl'
    rows = [json.loads(line) for line in heartbeat.read_text().splitlines()] if heartbeat.exists() else []
    marker = core.work / 'soak-finished.txt'
    result = {'passed': task['status'] == 'completed' and elapsed >= seconds
        and marker.exists() and marker.read_text() == 'LOCALPILOT_SOAK_COMPLETE'
        and 'LOCALPILOT_SOAK_COMPLETE' in (task.get('result') or {}).get('text', '')
        and len(rows) >= seconds // 30, 'requested_seconds': seconds,
        'elapsed_seconds': elapsed, 'heartbeat_count': len(rows),
        'last_heartbeat_seconds': rows[-1]['elapsed'] if rows else None,
        'approval_interventions': 0, **task_summary(task)}
    report['results']['full_extended_soak'] = result


if __name__ == '__main__':
    raise SystemExit(main())
