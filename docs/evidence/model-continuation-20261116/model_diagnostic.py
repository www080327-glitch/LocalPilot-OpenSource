"""One predeclared continuation of the remaining real CPU model cases.

This is guided product-path evidence, not a retry replacing the original scores.
It reuses the actual qualifier, Core, Companion client and persisted task API.
"""
import argparse
import json
from pathlib import Path
import sys
import time


SHELL_QUESTION = ('Use delegate exactly once with this argument object: '
    '{"backend_preference":"local","read_only":false,"task":"Use shell once with the command '
    'printf child-started >> child-cancel.txt; sleep 60. Wait for the command to finish.",'
    '"budget":{"steps":3,"tools":2}}. '
    'Omit tier, backend_id and model. Do not execute the command in the parent.')
COMPANION_QUESTION = ('Use read_file exactly once with {"path":"fact.txt"}. '
    'The path is relative to the workspace. After the tool returns the complete file '
    'contents, return them directly in your final answer without calling another tool.')
TASK_SECONDS = 600
MARKER_SECONDS = 450


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--model-root', type=Path, required=True)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    source = args.source_root.resolve(strict=True)
    model_root = args.model_root.resolve(strict=True)
    sys.path.insert(0, str(source))
    from scripts.qualify_linux_model import Core, Provider, digest, record, save

    manifest = json.loads(args.source_manifest.read_text())
    changed = [row['path'] for row in manifest['files'] if digest(source / row['path']) != row['sha256']]
    if changed:
        raise ValueError('Frozen source changed: ' + repr(changed))
    identity = json.loads((model_root / 'MODEL_IDENTITY.json').read_text())
    plan = json.loads((model_root / 'CONVERSION_PLAN.json').read_text())
    model = model_root / 'Qwen3.5-2B-text-Q8_0.gguf'
    binary = Path(plan['quantize_command'][0]).with_name('llama-server')
    if digest(model) != identity['model_sha256'] or digest(binary) != identity['runtime']['server_binary_sha256']:
        raise ValueError('Previously verified model/provider identity changed')
    out = args.evidence.resolve()
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    protocol = {
        'kind': 'GUIDED_COMPLETION_DIAGNOSTIC_R3',
        'declared_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'source_freeze_sha256': digest(args.source_manifest),
        'runner_sha256': digest(Path(__file__)), 'model_identity': identity,
        'source_versions': manifest['versions'],
        'task_timeout_seconds': TASK_SECONDS, 'marker_wait_seconds': MARKER_SECONDS,
        'host_budgets': {'max_steps': 6, 'max_tool_calls': 8, 'max_output_tokens': 512,
            'max_token_units': 262144, 'max_subagents_per_turn': 2, 'max_worker_steps': 3,
            'max_worker_tool_calls': 4, 'max_worker_token_units': 131072},
        'sampling_profile': 'qwen35-nonthinking', 'reasoning': 'off',
        'context_tokens': 8192, 'threads': 2, 'repeats': 1,
        'questions': {'child_shell_cancel_restart': SHELL_QUESTION,
                      'companion_single_read': COMPANION_QUESTION},
        'oracles': {
            'child_shell_cancel_restart': 'Real child Shell receipt with unknown effect, exact once-only marker, parent/child cancelled and quiescent; Core restart retains receipts and same-key submit returns same task without new append.',
            'companion_single_read': 'Companion task status completed, exactly one completed physical full-file read of fact.txt, and complete file marker in final answer.'},
        'changes_from_r2': ['Core/Companion source update with explicit manifests',
            'Shell wait 180 to 450 seconds, task timeout 300 to 600 seconds',
            'Companion prompt explicitly requests one read then final answer'],
        'ranking_claim': False,
        'scope': 'Guided path diagnostic; no autonomous planning or same-parameter quality comparison. All earlier FAIL results retained.'}
    save(out / 'PROTOCOL.json', protocol)
    report = {'kind': protocol['kind'], 'protocol_sha256': digest(out / 'PROTOCOL.json'),
              'cases': {}, 'cloud_calls': 0, 'api_cost_usd': 0, 'energy_cost': 'UNKNOWN'}
    provider = Provider(binary, model, out, alias=identity['runtime_alias'], reasoning='off',
                        sampling_profile='qwen35-nonthinking')
    core = None
    try:
        provider.start()
        core = Core(provider, out)
        configured = json.loads((core.home / 'service.json').read_text())['routes']['default']['budgets']
        if configured != protocol['host_budgets']:
            raise ValueError('Runtime budgets differ from predeclared protocol')
        core.start()
        record(report, out, 'child_shell_cancel_restart', lambda: child_shell_cancel_restart(core))
        record(report, out, 'companion_single_read', lambda: companion_single_read(core))
        (out / 'provider-metrics-final.txt').write_text(provider.request('/metrics', raw=True))
    except Exception as error:
        report['setup_error'] = {'type': type(error).__name__, 'message': str(error)[:500]}
    finally:
        if core is not None:
            core.stop()
        provider.stop()
        report['provider_processes'] = provider.measurements
        report['owned_processes_stopped'] = (core is None or core.process is None) and provider.process is None
        report['sources_changed_during_run'] = [row['path'] for row in manifest['files']
            if digest(source / row['path']) != row['sha256']]
        save(out / 'RESULTS.json', report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 1 if report.get('setup_error') or report['sources_changed_during_run'] or any(
        row['status'] != 'PASS' for row in report['cases'].values()) else 0


def child_shell_cancel_restart(core):
    from scripts.qualify_linux_model import save, task_summary
    session = core.session('continuation-child-cancel-session')
    initial = core.client.submit(SHELL_QUESTION, session_id=session, model='localpilot',
        idempotency_key='continuation-child-cancel', timeout_seconds=TASK_SECONDS)
    marker = core.work / 'child-cancel.txt'
    deadline = time.monotonic() + MARKER_SECONDS
    while time.monotonic() < deadline and not marker.exists():
        task = core.client.status(initial['id'])
        if task['quiescent'] and task['status'] not in {'queued', 'running', 'cancelling'}:
            break
        time.sleep(1)
    marker_seen = marker.exists()
    core.client.cancel(initial['id'])
    terminal = core.finish('child-cancel', initial)
    if not marker_seen:
        return {'passed': False, 'reason': 'Child Shell marker absent at the declared boundary',
                **task_summary(terminal)}
    before = marker.read_bytes()
    children = terminal.get('subagents', [])
    child_unknown = len(children) == 1 and children[0]['status'] == 'cancelled' and any(
        row['name'] == 'shell' and row.get('side_effect_status') == 'unknown'
        for row in children[0].get('receipts', []))
    parent_shell = any(row['name'] == 'shell' and not row.get('worker_id') for row in terminal.get('tools', []))
    old_pid = core.process.pid
    core.stop()
    core.start()
    restored = core.client.status(initial['id'])
    save(core.out / 'child-cancel-restored.json', restored)
    replay = core.client.submit(SHELL_QUESTION, session_id=session, model='localpilot',
        idempotency_key='continuation-child-cancel', timeout_seconds=TASK_SECONDS)
    save(core.out / 'child-cancel-resubmitted.json', replay)
    return {'passed': terminal['status'] == 'cancelled' and terminal['quiescent'] and child_unknown
        and not parent_shell and before == b'child-started' and terminal['receipt_summary']['unknown_effects'] > 0
        and restored['receipt_summary'] == terminal['receipt_summary']
        and restored['subagents'] == terminal['subagents'] and replay['id'] == initial['id']
        and marker.read_bytes() == before,
        'child_unknown_receipt': child_unknown, 'parent_executed_shell': parent_shell,
        'core_pid_changed': core.process.pid != old_pid, 'file_contents': before.decode(),
        'same_task_after_resubmit': replay['id'] == initial['id'],
        'receipts_preserved': restored['receipt_summary'] == terminal['receipt_summary'],
        'subagents_preserved': restored['subagents'] == terminal['subagents'], **task_summary(restored)}


def companion_single_read(core):
    from companion.config import Config
    from companion.escalation.service_v491 import LocalPilotProvider
    from scripts.qualify_linux_model import cli, save, task_summary
    config = Config(data_dir=str(core.out / 'companion-single-read'), backend='disabled',
        low_power_policy='off', allow_local_on_battery=True, localpilot_endpoint=core.client.base_url,
        localpilot_client_subject='companion', localpilot_route='localpilot',
        localpilot_analysis_route='companion-reasoning', localpilot_host_local_only=True,
        localpilot_task_timeout_seconds=TASK_SECONDS, desktop_control_enabled=False)
    with cli.temporary_environment({'LOCALPILOT_COMPANION_TOKEN': core.env['LOCALPILOT_COMPANION_TOKEN']}):
        provider = LocalPilotProvider(config)
        initial = provider.submit({'user_request': COMPANION_QUESTION,
            'privacy_scope': {'local_only': True}}, approved=True, submission_id='continuation-companion-read')
        save(core.out / 'companion-submit.json', initial)
        if not initial.get('task_id'):
            return {'status': 'BLOCKED', 'submission': initial}
        deadline = time.monotonic() + TASK_SECONDS + 10
        while time.monotonic() < deadline:
            result = provider.status(initial['task_id'])
            task = result.get('task', {})
            if task.get('quiescent') and result.get('status') not in {'queued', 'running', 'cancelling'}:
                break
            time.sleep(1)
        else:
            provider.cancel(initial['task_id'])
            raise TimeoutError('Companion exceeded the declared deadline; cancellation requested')
        save(core.out / 'companion-final.json', result)
        reads = [row for row in task.get('tools', []) if row['name'] == 'read_file']
        complete_read = len(reads) == 1 and reads[0].get('status') == 'completed' and (
            reads[0].get('read_receipt') or {}).get('version', {}).get('path') == 'fact.txt' and (
            reads[0].get('read_receipt') or {}).get('coverage', {}).get('kind') == 'full_file'
        answer = (task.get('result') or {}).get('text', '')
        return {'passed': result.get('status') == 'completed' and complete_read and core.marker in answer,
                'complete_single_read': complete_read, 'read_call_count': len(reads), **task_summary(task)}


if __name__ == '__main__':
    raise SystemExit(main())
