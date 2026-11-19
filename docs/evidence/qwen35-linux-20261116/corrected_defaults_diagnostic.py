"""One new-source diagnostic after the observed worker-budget and schema fixes.

This is separate from the frozen original nine cases and three prescribed cases.
No public benchmark questions are repeated. No production runtime is replaced.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time


AUTONOMOUS_QUESTION = ('Use delegate once with backend_preference local and read_only true. '
    'Ask the child to read fact.txt and return the complete contents. '
    'Include the child result in your final answer.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--model-root', type=Path, required=True)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    source, model_root = args.source_root.resolve(strict=True), args.model_root.resolve(strict=True)
    sys.path.insert(0, str(source))
    from scripts.qualify_linux_model import Provider, Core, digest, record, save
    manifest = json.loads(args.source_manifest.read_text())
    changed = [row['path'] for row in manifest['files'] if digest(source / row['path']) != row['sha256']]
    if changed:
        raise ValueError('Frozen new source changed: ' + repr(changed))
    identity = json.loads((model_root / 'MODEL_IDENTITY.json').read_text())
    plan = json.loads((model_root / 'CONVERSION_PLAN.json').read_text())
    model = model_root / 'Qwen3.5-2B-text-Q8_0.gguf'
    binary = Path(plan['quantize_command'][0]).with_name('llama-server')
    if digest(model) != identity['model_sha256'] or digest(binary) != identity['runtime']['server_binary_sha256']:
        raise ValueError('Frozen model/provider identity changed')
    helper_path = source / 'docs/evidence/qwen35-linux-20261116/prescribed_diagnostic.py'
    spec = importlib.util.spec_from_file_location('_prescribed_model_helpers', helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    prescribed_read = helper.READ_QUESTION.replace(',"tokens":32768', '')
    helper.CANCEL_QUESTION = helper.CANCEL_QUESTION.replace(',"tokens":32768', '')
    out = args.evidence.resolve()
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    protocol = {'kind': 'CORRECTED_DEFAULTS_DIAGNOSTIC',
        'declared_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'source_freeze_sha256': digest(args.source_manifest), 'runner_sha256': digest(Path(__file__)),
        'previous_helper_sha256': digest(helper_path), 'model_identity': identity,
        'host_budgets': {'max_token_units': 262144, 'max_worker_token_units': 131072,
                        'max_steps': 6, 'max_worker_steps': 3, 'max_output_tokens': 512},
        'task_timeout_seconds': 300, 'marker_wait_seconds': 180,
        'configured_model_http_timeout_seconds': 90,
        'http_timeout_scope': 'transport configuration; not an asserted total streaming wall-clock bound',
        'sampling_profile': 'qwen35-nonthinking', 'reasoning': 'off',
        'context_tokens': 8192, 'threads': 2, 'repeats': 1, 'ranking_claim': False,
        'questions': {'autonomous_child_read': AUTONOMOUS_QUESTION,
                      'prescribed_child_read': prescribed_read,
                      'prescribed_child_cancel_restart': helper.CANCEL_QUESTION,
                      'prescribed_companion_relative_read': helper.COMPANION_QUESTION},
        'changes': ['new product parent/worker admission defaults; original 32768 override removed',
                    'no cloud-only tier field when no cloud route is available',
                    'essential file argument descriptions retained on model wire',
                    'new source snapshot; original outcomes remain unchanged'],
        'scope': 'bounded product integration after identified fixes, not a same-parameter model comparison'}
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
        if any(configured.get(key) != value for key, value in protocol['host_budgets'].items()):
            raise ValueError('Generated Core budgets do not match the declared new-default protocol')
        core.start()
        record(report, out, 'autonomous_child_read', lambda: child_read(core, helper, 'autonomous', AUTONOMOUS_QUESTION))
        record(report, out, 'prescribed_child_read', lambda: child_read(core, helper, 'prescribed', prescribed_read))
        record(report, out, 'prescribed_child_cancel_restart', lambda: helper.child_cancel_restart(core))
        record(report, out, 'prescribed_companion_relative_read', lambda: helper.companion_read(core))
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


def child_read(core, helper, name, question):
    from scripts.qualify_linux_model import task_summary
    initial = core.client.submit(question, session_id=core.session(name + '-child-session'),
        model='localpilot', idempotency_key=name + '-child', timeout_seconds=300)
    task = helper.wait_task(core, name + '-child', initial)
    children = task.get('subagents', [])
    read = len(children) == 1 and children[0]['status'] == 'completed' and children[0]['read_only'] is True and any(
        row['name'] == 'read_file' and row.get('status') == 'completed'
        and (row.get('read_receipt') or {}).get('version', {}).get('path') == 'fact.txt'
        for row in children[0].get('receipts', []))
    answer = (task.get('result') or {}).get('text', '')
    return {'passed': task['status'] == 'completed' and read and core.marker in answer,
            'completed_child_read': read, **task_summary(task)}


if __name__ == '__main__':
    raise SystemExit(main())
