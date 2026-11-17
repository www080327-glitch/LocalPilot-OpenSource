#!/usr/bin/env python3
"""Qualify configured search/review roles through the existing Core and persistence.

The fixture is synthetic. Use --preflight-only without a key; an actual run uses
the caller's private key file and never copies credentials or the runtime DB.
"""
import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from localpilot_service import cli
from localpilot_service.deployment import build
from scripts.qualify_linux_model import save, task_summary
from scripts.qualify_openai_agent import CloudCore, source_identity
from scripts.qualify_openai_superagent import configure_async

MODELS = {'parent': {'model': 'gpt-6.1-sol', 'thinking': 'medium'},
          'search': {'model': 'gpt-6-luna', 'thinking': 'high'},
          'review': {'model': 'gpt-6.1-sol', 'thinking': 'medium'}}
MARKER = 'LP-ROLE-OBSERVED-742901'
FIXTURES = {'role-marker.txt': MARKER + '\n',
    'role-fixture.py': 'def clamp(value, lower=0, upper=10):\n    return max(lower, min(value, upper))\n'}
TIMEOUT = 600
PROMPT = '''Use the configured worker roles to inspect only the two synthetic files
role-marker.txt and role-fixture.py. Keep Super Agent as the coordinator.
Delegate exactly TWO children, one with role="search" and one with role="review".
Both must use backend_preference="cloud", mode="async", read_only=true and
budget={"steps":8,"tools":8}. Do not specify tier, model or backend_id.
Start both children before waiting. Each child must independently use read_file
on BOTH files, then report the marker verbatim and the function's name, defaults
and behavior. The reviewer should check the function's boundary behavior.
Children must not edit files or execute code. Do not read or perform their work
in the parent. Use wait_children to collect the real receipts and outcomes.
Then give a short final summary naming both roles, the exact observed marker
and function name, and any failed or incomplete work. Do not create replacement
children, switch models, access other files, credentials or the network, or
claim that this small fixture proves general model quality.
'''


def main():
    args = arguments()
    args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
    before = identity()
    (args.output / 'prompt.txt').write_text(PROMPT)
    save(args.output / 'PROTOCOL.json', {'version': 1, 'models': MODELS,
        'max_children': 2, 'output_tokens': 4096, 'child_steps': 8, 'child_tools': 8,
        'task_timeout_seconds': TIMEOUT, 'fixture_sha256': fixture_hashes(),
        'prompt_sha256': digest(PROMPT), 'provider_effort_echo': False,
        'usage_scope': 'The parent aggregate already includes children; sum it once.'})
    report = {'kind': 'SYNTHETIC_HETEROGENEOUS_WORKER_ROLE_INTEGRATION',
        'source': before, 'models': MODELS, 'preflight_only': args.preflight_only,
        'inference_status': 'NOT_RUN', 'ranking_claim': False}
    if args.preflight_only:
        compile(FIXTURES['role-fixture.py'], 'role-fixture.py', 'exec')
        report['passed'] = not all(acceptance({}, {}, {}).values())
        report['preflight'] = {'cloud_calls': 0, 'core_started': False,
            'fixture_compiles': True, 'missing_evidence_rejected': report['passed']}
    else:
        core = None
        try:
            core = CloudCore(args.output, args.key_file, **{
                'model': MODELS['parent']['model'], 'reasoning': MODELS['parent']['thinking']})
            configure_roles(core)
            report.update(run_case(core))
        except (Exception, KeyboardInterrupt) as error:
            report.update(passed=False, error={'type': type(error).__name__, 'message': str(error)[:1000]})
        finally:
            if core is not None:
                core.stop()
            report['owned_core_stopped'] = core is None or core.process is None
        report['inference_status'] = 'PASS' if report['passed'] else 'FAIL'
    report['source_after'] = identity()
    report['source_unchanged'] = before == report['source_after']
    report['passed'] = report['passed'] and report['source_unchanged']
    if not args.preflight_only and not report['passed']:
        report['inference_status'] = 'FAIL'
    report['private_exclusions'] = ['core-private/', 'workspace/', 'core.log']
    save(args.output / 'RESULTS.json', report)
    print(json.dumps({k: report[k] for k in ('kind', 'preflight_only', 'inference_status', 'passed')}))
    return 0 if report['passed'] else 1


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args(argv)
    args.output = args.output.resolve()
    if args.output.exists():
        parser.error('--output must be a new directory; prior attempts are preserved')
    if not args.preflight_only and args.key_file is None:
        parser.error('--key-file is required for an actual model run')
    return args


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fixture_hashes():
    return {path: digest(text) for path, text in FIXTURES.items()}


def identity():
    result = source_identity()
    result['runner_sha256'] = digest(Path(__file__).read_text())
    for key, revision in [('git_head', 'HEAD'), ('git_tree', 'HEAD^{tree}')]:
        command = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', revision],
            capture_output=True, text=True, timeout=10)
        result[key] = command.stdout.strip() if command.returncode == 0 else None
    return result


def configure_roles(core):
    configure_async(core)
    path = core.home / 'service.json'
    config = json.loads(path.read_text())
    primary = config['routes']['default']
    primary['budgets'].update(max_steps=40, max_tool_calls=48, max_token_units=4 * 1024 * 1024,
        max_output_tokens=4096, max_subagents_per_turn=2, max_worker_steps=8,
        max_worker_tool_calls=8, max_worker_token_units=1024 * 1024, max_worker_output_tokens=4096)
    for role in ('search', 'review'):
        route = deepcopy(primary)
        route.pop('cooperation', None)
        route['backend']['model'] = MODELS[role]['model']
        route['thinking'] = MODELS[role]['thinking']
        config['routes']['role-' + role] = route
    primary['cooperation'] = {'routes': ['role-search', 'role-review'],
        'roles': {'search': 'role-search', 'review': 'role-review'}, 'optimizer': {'mode': 'cloud-only'}}
    cli.save(path, config)
    save(core.out / 'resolved-runtime-budgets.json', {name: route['budgets']
        for name, route in config['routes'].items()})


def run_case(core):
    for path, text in FIXTURES.items():
        (core.work / path).write_text(text)
    started = time.monotonic()
    core.start()
    session = core.session('worker-roles-session')
    task = core.finish('worker-roles', core.submit('worker-roles-task', PROMPT,
        session=session, timeout=TIMEOUT), timeout=TIMEOUT + 30)
    core.stop()
    before = restored_evidence(core, task['session_id'])
    save(core.out / 'ROLE_EVIDENCE_BEFORE_RESTART.json', before)
    core.start()
    restored = core.submit('worker-roles-task', PROMPT, session=session, timeout=TIMEOUT)
    save(core.out / 'worker-roles-restored-task.json', restored)
    core.stop()
    after = restored_evidence(core, session)
    save(core.out / 'ROLE_EVIDENCE_AFTER_RESTART.json', after)
    files = {path: digest((core.work / path).read_text()) if (core.work / path).is_file() else None
        for path in FIXTURES}
    checks = acceptance(task, before, files)
    checks.update(same_task_after_restart=restored['id'] == task['id'],
        same_session_after_restart=restored['session_id'] == session,
        same_receipts_after_restart=restored.get('tools') == task.get('tools'),
        same_children_after_restart=restored.get('subagents') == task.get('subagents'),
        same_result_after_restart=restored.get('result') == task.get('result'),
        same_runtime_evidence_after_restart=before == after)
    calls = before['aggregate_model_calls']
    totals = {name: sum(call[name] for call in calls) if all(type(call[name]) is int for call in calls) else None
        for name in ('input_tokens', 'output_tokens', 'prompt_cache_hit_tokens')}
    return {'passed': all(checks.values()), 'checks': checks, 'model_run_seconds': time.monotonic() - started,
        'task': task_summary(task), 'model_call_count': len(calls), 'provider_usage_once': totals,
        'product_verification_unchanged': {key: (task.get('result') or {}).get(key) for key in
            ('verification_status', 'engineering_status', 'task_outcome', 'task_succeeded')},
        'provider_usage_scope': 'Parent aggregate only; it already includes both children. This is not a billing statement.',
        'effort_scope': 'ModelRequestStarted records actual host request model/effort. Provider responses echo model, not effort.',
        'fixture_sha256_after': files, 'database_exported': False}


def restored_evidence(core, session_id):
    if core.process is not None:
        raise ValueError('Stop the owned Core before checkpoint inspection')
    config = json.loads((core.home / 'service.json').read_text())
    names = [client['token_env'] for client in config['clients']]
    previous = {name: os.environ.get(name) for name in names}
    server = None
    try:
        os.environ.update({name: core.env[name] for name in names})
        server = build(core.home / 'service.json')
        runtime = server.service.sessions[session_id].runtime
        children = {record['id']: record for record in runtime.subagents}
        aggregate = [asdict(call) for call in runtime._usage]
        child_calls = Counter(json.dumps(asdict(call), sort_keys=True)
            for child in runtime._children.values() for call in child._usage)
        parent_calls = []
        for call in aggregate:
            key = json.dumps(call, sort_keys=True)
            if child_calls[key]:
                child_calls[key] -= 1
            else:
                parent_calls.append(call)
        nodes = {}
        for worker_id, node in [('parent', runtime), *runtime._children.items()]:
            record = children.get(worker_id, {})
            nodes[worker_id] = {'role': record.get('role', 'parent'),
                'backend_id': node.hybrid.state['backend_id'], 'model': node.current_primary_model,
                'thinking': node._effective_thinking(), 'capabilities': asdict(node.registry.gateway.capabilities),
                'advertised_tools': [tool['function']['name'] for tool in node._schemas()],
                'receipt_sha256': digest(json.dumps(node.tool_history, sort_keys=True)),
                'request_events': [{'sequence': event.sequence, 'timestamp': event.timestamp, **event.data}
                    for event in node.events.events if event.type == 'ModelRequestStarted'],
                'provider_calls': parent_calls if worker_id == 'parent' else [asdict(call) for call in node._usage]}
        return {'session_id': session_id, 'configuration_sha256': runtime._persistence_config,
            'worker_roles': runtime.worker_roles, 'aggregate_model_calls': aggregate, 'nodes': nodes}
    finally:
        if server is not None:
            server.service.suspend()
            server.server_close()
            server.access.close()
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def acceptance(task, evidence, files):
    children = task.get('subagents', [])
    nodes = evidence.get('nodes', {})
    checks = {'completed_and_quiescent': task.get('status') == 'completed' and task.get('quiescent') is True,
        'two_named_children': len(children) == 2 and {child.get('role') for child in children} == {'search', 'review'},
        'three_runtime_nodes': len(nodes) == 3,
        'fixtures_unchanged': files == fixture_hashes(),
        'parent_collected_summary': MARKER in (task.get('result') or {}).get('text', '')
            and 'clamp' in (task.get('result') or {}).get('text', ''),
        'parent_did_not_read_or_mutate': all(row['name'] in {'delegate', 'wait_children', 'child_status', 'list_goals', 'update_goals'}
            for row in task.get('tools', []) if not row.get('worker_id'))}
    for worker_id, node in nodes.items():
        role = node['role']
        expected = MODELS.get(role, {})
        events, calls = node['request_events'], node['provider_calls']
        checks[worker_id + '_inference'] = bool(events) and len(events) == len(calls) and bool(expected) \
            and all(event['model'] == expected['model'] and event['thinking'] == expected['thinking'] for event in events) \
            and all(call['reported_model'] == expected['model'] for call in calls)
        if role != 'parent':
            caps = node['capabilities']
            checks[worker_id + '_read_only'] = caps['read_only'] and caps['read'] and not caps['write'] and not caps['execute'] \
                and not {'shell', 'apply_patch', 'request_model_switch'} & set(node['advertised_tools'])
    for child in children:
        receipts = child.get('receipts', [])
        reads = {row.get('read_receipt', {}).get('version', {}).get('path'):
            row.get('read_receipt', {}).get('version', {}).get('sha256') for row in receipts
            if row['name'] == 'read_file' and row.get('status') == 'completed'}
        checks[child['id'] + '_read_receipts'] = reads == fixture_hashes() and all(row['name'] == 'read_file' for row in receipts)
        checks[child['id'] + '_completed_collected'] = child.get('status') == 'completed' \
            and child.get('async') is True and child.get('collected') is True and child.get('read_only') is True
    checks['aggregate_count_once'] = bool(nodes) and len(evidence.get('aggregate_model_calls', [])) == sum(
        len(node['provider_calls']) for node in nodes.values())
    return checks


if __name__ == '__main__':
    raise SystemExit(main())
