#!/usr/bin/env python3
"""Real-model async, cancellation and Companion transport acceptance fixtures."""
import argparse
import json
import os
from pathlib import Path
import shlex
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.qualify_openai_agent import CloudCore, source_identity
from scripts.qualify_linux_model import record, save, task_summary
from localpilot_service import cli


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=('parallel_children', 'cancel_child_shell', 'cancel_stream', 'companion'),
                        default=['parallel_children', 'cancel_child_shell', 'cancel_stream', 'companion'])
    args = parser.parse_args()
    args.output.mkdir(parents=True, mode=0o700)
    report = {'source': source_identity(), 'model': 'gpt-6-luna',
              'protocol': 'responses', 'reasoning': 'medium', 'cases': {}}
    core = CloudCore(args.output, args.key_file)
    configure_async(core)
    try:
        core.start()
        cases = {'parallel_children': parallel_children, 'cancel_child_shell': cancel_child_shell,
                 'cancel_stream': cancel_stream, 'companion': companion}
        for name in args.cases:
            record(report, args.output, name, lambda: cases[name](core))
            if report['cases'][name]['status'] == 'ERROR':
                core.stop()
                core.start()
    finally:
        core.stop()
        report['owned_core_stopped'] = core.process is None
        save(args.output / 'RESULTS.json', report)
    return 0 if all(case['status'] == 'PASS' for case in report['cases'].values()) else 1


def configure_async(core):
    path = core.home / 'service.json'
    config = json.loads(path.read_text())
    config['async_policy'] = {'max_running_children': 2, 'max_running_per_session': 2,
        'max_children_per_turn': 2, 'max_model_requests': 3,
        'max_cloud_model_requests': 2, 'max_local_model_requests': 1,
        'cpu_slots': 2, 'ram_budget_mib': 256}
    cli.save(path, config)


def parallel_children(core):
    for label in ('a', 'b'):
        (core.work / f'child-{label}.py').write_text(
            'import json,time\nfrom pathlib import Path\n'
            'start=time.time()\ntime.sleep(12)\n'
            f'Path("child-{label}.json").write_text(json.dumps({{"start":start,"end":time.time(),"marker":"CHILD-{label.upper()}-DONE"}}))\n')
    python = shlex.quote(sys.executable)
    prompt = (f'Delegate TWO independent tasks in async mode before waiting. '
        f'Both use backend_preference cloud, mode async, read_only false. '
        f'Child A must use shell to run {python} child-a.py, then read_file child-a.json. '
        f'Child B must use shell to run {python} child-b.py, then read_file child-b.json. '
        'Do not execute the child scripts in the parent. After both delegates, use wait_children '
        'to collect them, then report CHILD-A-DONE and CHILD-B-DONE. Full permission is already granted.')
    task = core.finish('parallel-children', core.submit('parallel-children', prompt,
        session=core.session('parallel-session')), timeout=660)
    records = task.get('subagents', [])
    outputs = [json.loads((core.work / f'child-{label}.json').read_text())
               for label in ('a', 'b') if (core.work / f'child-{label}.json').exists()]
    overlap = max(0, min(row['end'] for row in outputs) - max(row['start'] for row in outputs)) if len(outputs) == 2 else 0
    actual = sum(any(receipt.get('name') == 'shell' and receipt.get('status') == 'completed'
        for receipt in child.get('receipts', [])) for child in records)
    return {'passed': task['status'] == 'completed' and len(records) == 2
        and all(child.get('status') == 'completed' for child in records)
        and actual == 2 and overlap > 0,
        'child_shell_overlap_seconds': overlap, 'completed_child_shells': actual,
        'timing_evidence': outputs, **task_summary(task)}


def cancel_child_shell(core):
    (core.work / 'long-child.py').write_text(
        'import json,os,time\nfrom pathlib import Path\n'
        'Path("long-child-start.json").write_text(json.dumps({"pid":os.getpid(),"time":time.time()}))\n'
        'time.sleep(180)\nPath("long-child-finished.txt").write_text("SHOULD_NOT_FINISH")\n')
    command = shlex.quote(sys.executable) + ' long-child.py'
    prompt = (f'Delegate one cloud child with mode async and read_only false. '
        f'The child must use shell to run exactly {command} with timeout 240. '
        'Then wait_children. Do not run the script in the parent.')
    session = core.session('cancel-child-session')
    task = core.submit('cancel-child', prompt, session=session, timeout=360)
    marker = core.work / 'long-child-start.json'
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline and not marker.exists():
        state = core.client.status(task['id'])
        if state['quiescent'] and state['status'] not in {'queued', 'running', 'cancelling'}:
            break
        time.sleep(1)
    started = time.monotonic()
    core.client.cancel(task['id'])
    final = core.finish('cancel-child', task, timeout=30)
    latency = time.monotonic() - started
    process_stopped = False
    if marker.exists():
        pid = json.loads(marker.read_text())['pid']
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            process_stopped = True
    child_receipt = any(receipt.get('name') == 'shell'
        for child in final.get('subagents', []) for receipt in child.get('receipts', []))
    core.stop()
    core.start()
    restored = core.submit('cancel-child', prompt, session=session, timeout=360)
    return {'passed': marker.exists() and child_receipt and process_stopped
        and not (core.work / 'long-child-finished.txt').exists()
        and final['status'] == 'cancelled' and final['quiescent']
        and restored['id'] == task['id'] and restored['status'] == 'cancelled',
        'cancellation_seconds': latency, 'child_process_stopped': process_stopped,
        'same_task_after_restart': restored['id'] == task['id'], **task_summary(final)}


def cancel_stream(core):
    task = core.submit('cancel-stream', 'Write the integers from 1 to 10000, one per line, without skipping any.',
                       model='companion-reasoning', timeout=360)
    events = core.client.events(task['id'])
    frames, observed = [], False
    started = time.monotonic()
    try:
        for event in events:
            frames.append(event)
            runtime = event['data'].get('data', {})
            if event['data'].get('type') == 'runtime.event' and runtime.get('type') == 'TextDelta':
                observed = True
                started = time.monotonic()
                core.client.cancel(task['id'])
                break
    finally:
        events.close()
    final = core.finish('cancel-stream', task, timeout=30)
    save(core.out / 'cancel-stream-sse.json', frames)
    return {'passed': observed and final['status'] == 'cancelled' and final['quiescent'],
        'text_delta_observed': observed, 'cancel_to_quiescence_seconds': time.monotonic() - started,
        **task_summary(final)}


def companion(core):
    from companion.config import Config
    from companion.escalation.provider import EscalationRequest
    from companion.escalation.service_v491 import LocalPilotProvider
    env_name = 'LP_QUALIFICATION_COMPANION'
    previous = os.environ.get(env_name)
    os.environ[env_name] = core.env['LOCALPILOT_COMPANION_TOKEN']
    try:
        config = Config(data_dir=str(core.out / 'companion-private'), backend='disabled',
            watch_dirs=(), native_observation_enabled=False, low_power_policy='system',
            localpilot_endpoint=core.client.base_url, localpilot_client_subject='companion',
            localpilot_route='localpilot', localpilot_analysis_route='companion-reasoning',
            localpilot_api_key_env=env_name, localpilot_host_local_only=False,
            localpilot_allow_cloud=True, localpilot_task_timeout_seconds=360)
        provider = LocalPilotProvider(config)
        session = core.operator.request('/localpilot/v1/desktop-sessions', {
            'client_subject': 'companion', 'model': 'localpilot', 'source': 'cloud_only',
            'options': {'permission_mode': 'full', 'agent_profile': 'standard'}},
            key='companion-full-session')['id']
        cases = {}
        for mode, question in (
            ('reasoning', 'Reply with COMPANION_LUNA_OK only.'),
            ('execution', 'Use read_file to read fact.txt. Return its complete contents.')):
            request = EscalationRequest(question, 'manual', 'explicit qualification', [], [], [],
                {'local_only': False, 'classification': 'PUBLIC'}, '')
            ticket = uuid4().hex
            submitted = provider.submit(request, approved=True, cloud_approved=True, mode=mode,
                session_id=session if mode == 'execution' else None,
                control_ticket=ticket, submission_id='companion-' + mode)
            save(core.out / ('companion-' + mode + '-submission.json'), submitted)
            task_id = submitted.get('task_id')
            if not task_id:
                cases[mode] = {'passed': False, 'submission': submitted}
                continue
            deadline, last_beat = time.monotonic() + 390, 0
            while time.monotonic() < deadline:
                if time.monotonic() - last_beat >= 8:
                    provider.control_heartbeat(task_id, ticket)
                    last_beat = time.monotonic()
                view = provider.status(task_id, cloud_approved=True)
                if view.get('quiescent') and view.get('status') not in {'queued', 'running', 'cancelling'}:
                    break
                time.sleep(1)
            save(core.out / ('companion-' + mode + '-view.json'), view)
            expected = 'COMPANION_LUNA_OK' if mode == 'reasoning' else core.marker
            task = view.get('task') or {}
            read = any(row['name'] == 'read_file' and row.get('status') == 'completed'
                       for row in task.get('tools', []))
            cases[mode] = {'passed': view.get('status') == 'completed'
                and expected in view.get('agent_response', '') and (mode == 'reasoning' or read),
                'ordinary_client_identity': provider.identity, 'read_receipt': read,
                'task_id': task_id, 'status': view.get('status'),
                'model_calls': (task.get('result') or {}).get('model_calls')}
        return {'passed': all(case['passed'] for case in cases.values()), 'cases': cases,
                'operator_credential_given_to_companion': False,
                'provider_credential_given_to_companion': False}
    finally:
        if previous is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = previous


if __name__ == '__main__':
    raise SystemExit(main())
