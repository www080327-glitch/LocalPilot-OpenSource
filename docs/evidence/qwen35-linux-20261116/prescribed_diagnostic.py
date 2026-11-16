"""One declared diagnostic of legal tool arguments, separate from autonomous cases.

Uses the existing qualifier's owned provider, Core, SDK and receipt summaries.
The file marker is not included in any read prompt. No model tuning or retries.
"""
import argparse
import json
from pathlib import Path
import sys
import time


READ_QUESTION = ('Use delegate exactly once with this argument object: '
    '{"backend_preference":"local","read_only":true,"task":"Use read_file with exactly '
    '{\\"path\\":\\"fact.txt\\"}. Return the complete file contents.",'
    '"budget":{"steps":3,"tools":2,"tokens":32768}}. '
    'Omit tier, backend_id and model. Include the actual child result in your final answer.')
CANCEL_QUESTION = ('Use delegate exactly once with this argument object: '
    '{"backend_preference":"local","read_only":false,"task":"Use shell once with the command '
    'printf child-started >> child-cancel.txt; sleep 60. Wait for the command to finish.",'
    '"budget":{"steps":3,"tools":2,"tokens":32768}}. '
    'Omit tier, backend_id and model. Do not execute the command in the parent.')
COMPANION_QUESTION = ('Use read_file with exactly {"path":"fact.txt"}. The path is relative to '
    'the workspace; do not prepend an absolute directory or change the filename. '
    'Return the complete file contents.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--model-root', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    source, model_root = args.source_root.resolve(strict=True), args.model_root.resolve(strict=True)
    sys.path.insert(0, str(source))
    from scripts.qualify_linux_model import Provider, Core, digest, record, save
    identity = json.loads((model_root / 'MODEL_IDENTITY.json').read_text())
    plan = json.loads((model_root / 'CONVERSION_PLAN.json').read_text())
    freeze = json.loads((model_root / 'SOURCE_FREEZE.json').read_text())
    changed = [row['path'] for row in freeze['files'] if digest(source / row['path']) != row['sha256']]
    if changed:
        raise ValueError('Frozen runtime changed: ' + repr(changed))
    model = model_root / 'Qwen3.5-2B-text-Q8_0.gguf'
    if digest(model) != identity['model_sha256']:
        raise ValueError('Model hash changed')
    binary = Path(plan['quantize_command'][0]).with_name('llama-server')
    out = args.evidence.resolve()
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    protocol = {'kind': 'PRESCRIBED_ARGUMENT_DIAGNOSTIC', 'model_identity': identity,
        'declared_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'source_freeze_sha256': digest(model_root / 'SOURCE_FREEZE.json'),
        'runner_sha256': digest(Path(__file__)), 'task_timeout_seconds': 300,
        'single_model_timeout_seconds': 90, 'marker_wait_seconds': 180,
        'sampling_profile': 'qwen35-nonthinking', 'reasoning': 'off',
        'context_tokens': 8192, 'max_output_tokens': 512, 'threads': 2,
        'questions': {'child_read': READ_QUESTION, 'child_cancel_restart': CANCEL_QUESTION,
                      'companion_relative_read': COMPANION_QUESTION},
        'repeats': 1, 'ranking_claim': False,
        'scope': 'explicit legal arguments and longer wall deadline; not autonomous planning acceptance'}
    save(out / 'PROTOCOL.json', protocol)
    report = {'kind': protocol['kind'], 'protocol_sha256': digest(out / 'PROTOCOL.json'),
              'cases': {}, 'cloud_calls': 0, 'api_cost_usd': 0, 'energy_cost': 'UNKNOWN'}
    provider = Provider(binary, model, out, alias=identity['runtime_alias'], reasoning='off',
                        sampling_profile='qwen35-nonthinking')
    core = None
    try:
        provider.start()
        core = Core(provider, out)
        core.start()
        record(report, out, 'prescribed_child_read', lambda: child_read(core))
        record(report, out, 'prescribed_child_cancel_restart', lambda: child_cancel_restart(core))
        record(report, out, 'prescribed_companion_relative_read', lambda: companion_read(core))
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


def wait_task(core, name, initial):
    from scripts.qualify_linux_model import save
    deadline = time.monotonic() + 310
    while time.monotonic() < deadline:
        task = core.client.status(initial['id'])
        if task['quiescent'] and task['status'] not in {'queued', 'running', 'cancelling'}:
            save(core.out / (name + '-task.json'), task)
            return task
        time.sleep(1)
    core.client.cancel(initial['id'])
    save(core.out / (name + '-timeout-task.json'), core.client.status(initial['id']))
    raise TimeoutError('Diagnostic exceeded its declared deadline; cancellation requested')


def child_read(core):
    from scripts.qualify_linux_model import task_summary
    initial = core.client.submit(READ_QUESTION, session_id=core.session('prescribed-read-session'),
        model='localpilot', idempotency_key='prescribed-read', timeout_seconds=300)
    task = wait_task(core, 'prescribed-read', initial)
    children = task.get('subagents', [])
    read = len(children) == 1 and children[0]['status'] == 'completed' and children[0]['read_only'] is True and any(
        row['name'] == 'read_file' and row.get('status') == 'completed'
        and (row.get('read_receipt') or {}).get('version', {}).get('path') == 'fact.txt'
        for row in children[0].get('receipts', []))
    answer = (task.get('result') or {}).get('text', '')
    return {'passed': task['status'] == 'completed' and read and core.marker in answer,
            'completed_child_read': read, **task_summary(task)}


def child_cancel_restart(core):
    from scripts.qualify_linux_model import save, task_summary
    session = core.session('prescribed-cancel-session')
    initial = core.client.submit(CANCEL_QUESTION, session_id=session, model='localpilot',
        idempotency_key='prescribed-cancel', timeout_seconds=300)
    marker = core.work / 'child-cancel.txt'
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline and not marker.exists():
        task = core.client.status(initial['id'])
        if task['quiescent'] and task['status'] not in {'queued', 'running', 'cancelling'}:
            break
        time.sleep(1)
    core.client.cancel(initial['id'])
    terminal = core.finish('prescribed-cancel', initial)
    if not marker.exists():
        return {'passed': False, 'reason': 'No child Shell marker before the declared cancellation boundary',
                **task_summary(terminal)}
    before = marker.read_bytes()
    children = terminal.get('subagents', [])
    child_unknown = len(children) == 1 and children[0]['status'] == 'cancelled' and any(
        row['name'] == 'shell' and row.get('side_effect_status') == 'unknown'
        for row in children[0].get('receipts', []))
    old_pid = core.process.pid
    core.stop()
    core.start()
    restored = core.client.status(initial['id'])
    save(core.out / 'prescribed-cancel-restored.json', restored)
    replay = core.client.submit(CANCEL_QUESTION, session_id=session, model='localpilot',
        idempotency_key='prescribed-cancel', timeout_seconds=300)
    return {'passed': terminal['status'] == 'cancelled' and terminal['quiescent'] and child_unknown
            and before == b'child-started' and terminal['receipt_summary']['unknown_effects'] > 0
            and restored['receipt_summary'] == terminal['receipt_summary']
            and restored['subagents'] == terminal['subagents'] and replay['id'] == initial['id']
            and marker.read_bytes() == before,
            'child_unknown_receipt': child_unknown, 'core_pid_changed': core.process.pid != old_pid,
            'file_contents': before.decode(), 'same_task_after_resubmit': replay['id'] == initial['id'],
            **task_summary(restored)}


def companion_read(core):
    from companion.config import Config
    from companion.escalation.service_v491 import LocalPilotProvider
    from scripts.qualify_linux_model import cli, save, task_summary
    config = Config(data_dir=str(core.out / 'companion-relative-read'), backend='disabled',
        low_power_policy='off', allow_local_on_battery=True, localpilot_endpoint=core.client.base_url,
        localpilot_client_subject='companion', localpilot_route='localpilot',
        localpilot_analysis_route='companion-reasoning', localpilot_host_local_only=True,
        localpilot_task_timeout_seconds=300, desktop_control_enabled=False)
    with cli.temporary_environment({'LOCALPILOT_COMPANION_TOKEN': core.env['LOCALPILOT_COMPANION_TOKEN']}):
        provider = LocalPilotProvider(config)
        initial = provider.submit({'user_request': COMPANION_QUESTION,
            'privacy_scope': {'local_only': True}}, approved=True, submission_id='prescribed-companion-read')
        save(core.out / 'prescribed-companion-submit.json', initial)
        if not initial.get('task_id'):
            return {'status': 'BLOCKED', 'submission': initial}
        deadline = time.monotonic() + 310
        while time.monotonic() < deadline:
            result = provider.status(initial['task_id'])
            task = result.get('task', {})
            if task.get('quiescent') and result.get('status') not in {'queued', 'running', 'cancelling'}:
                break
            time.sleep(1)
        save(core.out / 'prescribed-companion-final.json', result)
        read = any(row['name'] == 'read_file' and row.get('status') == 'completed'
            and (row.get('read_receipt') or {}).get('version', {}).get('path') == 'fact.txt'
            for row in task.get('tools', []))
        answer = (task.get('result') or {}).get('text', '')
        return {'passed': result.get('status') == 'completed' and read and core.marker in answer,
                'completed_relative_read': read, **task_summary(task)}


if __name__ == '__main__':
    raise SystemExit(main())
