#!/usr/bin/env python3
"""Actual cross-provider parent/child probe using an owned llama-server."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.qualify_linux_model import Provider, save, task_summary
from scripts.qualify_openai_agent import CloudCore, source_identity
from localpilot_service import cli


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--llama-server', type=Path, required=True)
    parser.add_argument('--local-model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--direction', choices=('cloud-parent', 'local-parent'), required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, mode=0o700)
    provider_out = args.output / 'local-provider'
    provider_out.mkdir(mode=0o700)
    provider = Provider(args.llama_server, args.local_model, provider_out,
                        alias='qwen2.5-0.5b-qualified-worker', reasoning='off')
    core = CloudCore(args.output, args.key_file)
    report = {'direction': args.direction, 'source': source_identity(),
              'local_model_sha256': file_hash(args.local_model),
              'server_binary_sha256': file_hash(args.llama_server), 'passed': False}
    try:
        configure(core, provider, args.direction)
        provider.start()
        core.start()
        preference = 'local' if args.direction == 'cloud-parent' else 'cloud'
        session = core.operator.request('/localpilot/v1/desktop-sessions', {
            'client_subject': 'http', 'model': 'localpilot', 'source': 'balanced',
            'options': {'permission_mode': 'full', 'agent_profile': 'standard'}},
            key='heterogeneous-session')['id']
        prompt = (f'Use delegate exactly once with backend_preference {preference} and read_only true. '
            'The child task is: use read_file to read fact.txt and return its entire contents. '
            'Do not read fact.txt in the parent. Include the child answer in your final answer.')
        task = core.finish('heterogeneous', core.submit('heterogeneous', prompt,
            session=session, timeout=600), timeout=660)
        actual_child = any(child.get('backend') == preference and child.get('status') == 'completed'
            and any(receipt.get('name') == 'read_file' and receipt.get('status') == 'completed'
                    for receipt in child.get('receipts', []))
            for child in task.get('subagents', []))
        report.update(task_summary(task))
        report['requested_child_read_observed'] = actual_child
        report['passed'] = task['status'] == 'completed' and actual_child and core.marker in (
            (task.get('result') or {}).get('text') or '')
        report['scope'] = 'One synthetic file-read task per direction; not a general model capability score.'
    except Exception as error:
        report['error'] = {'type': type(error).__name__, 'message': str(error)[:1000]}
    finally:
        core.stop()
        provider.stop()
        report['owned_processes_stopped'] = core.process is None and provider.process is None
        report['provider_processes'] = provider.measurements
        save(args.output / 'RESULTS.json', report)
    print(json.dumps({key: value for key, value in report.items()
                      if key not in {'source', 'model_calls', 'runtime_metrics', 'subagents'}}), flush=True)
    return 0 if report['passed'] else 1


def configure(core, provider, direction):
    path = core.home / 'service.json'
    config = json.loads(path.read_text())
    primary, worker = config['routes']['default'], config['routes']['worker']
    cloud = deepcopy(primary['backend'])
    local = {'kind': 'local-openai', 'base_url': provider.origin + '/v1',
             'model': provider.alias, 'context_budget': 8192, 'timeout': 180,
             'include_stream_usage': True, 'generation_parameters': {'temperature': 0}}
    primary.update(backend=cloud if direction == 'cloud-parent' else local,
                   thinking='medium' if direction == 'cloud-parent' else None)
    worker.update(backend=local if direction == 'cloud-parent' else cloud,
                  thinking=None if direction == 'cloud-parent' else 'medium',
                  cloud_egress='LOCAL_ONLY' if direction == 'cloud-parent' else 'CLOUD_ALLOWED')
    primary['cooperation']['optimizer']['mode'] = 'cloud-first' if direction == 'cloud-parent' else 'local-first'
    primary['budgets'].update(max_steps=30, max_worker_steps=8, max_worker_tool_calls=12,
                             max_worker_output_tokens=512, max_output_tokens=1024)
    cli.save(path, config)


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


if __name__ == '__main__':
    raise SystemExit(main())
