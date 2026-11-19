#!/usr/bin/env python3
"""Complete only pre-candidate Tunnel 403 acquisition failures in a new cohort."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import sys


PUBLIC_CASE_FILES = ('case-result.json', 'resolved-runtime-budgets.json',
    'input-manifest.json', 'prompt.txt', 'candidate-started.json',
    'candidate-progress.json', 'candidate-task.json', 'candidate-task.json.gz',
    'agent_output.json', 'core.log')
STARTED_FILES = ('candidate-started.json', 'candidate-progress.json',
                 'candidate-task.json', 'candidate-task.json.gz', 'agent_output.json')
TRANSPORT_ERROR = {'type': 'URLError',
                   'message': '<urlopen error Tunnel connection failed: 403 Forbidden>'}


def main():
    args = arguments()
    study, summary, results, declaration = original_inputs(args)
    harness, source = frozen_harness(args)
    tree = read_json(args.tree)
    if tree['revision'] != study['revision']:
        raise ValueError('Dataset tree revision differs from the original study')
    selected = [row['index'] for row in results
                if eligible(row, args.original / f"case-{row['index']:03d}")]
    if not selected:
        raise ValueError('No eligible pre-candidate Tunnel 403 failures')
    args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
    receipts = {}
    for name in ('study.json', 'source.json', 'runner.json', 'RUN_SUMMARY.json'):
        target = 'original-RUN_SUMMARY.json' if name == 'RUN_SUMMARY.json' else name
        receipts[name] = copy_receipt(args.original / name, args.output / target)
    copy_receipt(args.protocol, args.output / 'transport-continuation-protocol.json')
    for row in results:
        case = f"case-{row['index']:03d}"
        target = args.output / ('original-transport-errors' if row['index'] in selected else '') / case
        for name in PUBLIC_CASE_FILES:
            path = args.original / case / name
            if path.is_file():
                receipts[f'{case}/{name}'] = copy_receipt(path, target / name)
    continuation = {
        'kind': 'PRE_CANDIDATE_TRANSPORT_CONTINUATION', 'original': str(args.original),
        'protocol_sha256': digest(args.protocol), 'protocol': declaration,
        'driver_sha256': digest(Path(__file__)), 'source': source,
        'python': sys.version, 'executable': sys.executable, 'tree_sha256': digest(args.tree),
        'eligible_indices': selected, 'original_receipt_sha256': receipts,
        'criteria': 'Exact URLError/Tunnel 403; no task status/id/model calls, candidate '
                    'start/progress/task receipt, or agent output; every original Core stopped.',
        'task_budget_unchanged': {name: study[name] for name in
            ('max_steps', 'max_tool_calls', 'max_output_tokens', 'task_timeout_seconds',
             'candidate', 'reasoning', 'protocol', 'repeats')},
        'scheduling': {'original_parallel_cases': study['parallel_cases'],
                       'continuation_parallel_cases': 1},
        'execution': 'One invocation of frozen run_case per eligible case; original download '
                     'URLs, inherited proxy/CA, and existing per-file retries unchanged. '
                     'Same instruction function; workspace path follows the new output.',
        'preservation': 'Started candidates receive zero additional candidate calls. '
                        'Original receipts remain unchanged; continuation failures are retained.',
        'grading': 'Only after all original and continuation Cores stop; no labels loaded here.'}
    harness.save(args.output / 'CONTINUATION.json', continuation)
    for index in selected:
        result = harness.run_case(args, study, tree, index, study['scenarios'][index - 1])
        print(json.dumps(result, ensure_ascii=False), flush=True)
    combined = [read_json(args.output / f'case-{index:03d}' / 'case-result.json')
                for index in range(1, 41)]
    summary = {'planned': 40, 'completed': sum(r.get('task_status') == 'completed' for r in combined),
               'outputs_valid': sum(r.get('output_valid', False) for r in combined),
               'errors': sum(bool(r.get('error')) for r in combined), 'graded': False,
               'cases': combined, 'comparison': study['comparison'],
               'provenance': 'CONTINUATION.json'}
    harness.save(args.output / 'RUN_SUMMARY.json', summary)
    return 0 if summary['outputs_valid'] == 40 else 1


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'original', 'output', 'tree', 'key-file', 'protocol'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ('source', 'original', 'output', 'tree', 'protocol'):
        setattr(args, name, getattr(args, name).resolve())
    if args.output.exists() or args.output.is_relative_to(args.original) or args.output.is_relative_to(args.source):
        parser.error('--output must be new and outside the original cohort and frozen source')
    return args


def original_inputs(args):
    if not (args.original / 'RUN_SUMMARY.json').is_file():
        raise ValueError('Wait externally until the original 40-case RUN_SUMMARY is finalized')
    study, summary = (read_json(args.original / name) for name in ('study.json', 'RUN_SUMMARY.json'))
    if len(study['scenarios']) != 40 or summary.get('planned') != 40 or len(summary.get('cases', [])) != 40:
        raise ValueError('Original study and summary must contain all 40 cases')
    results = [read_json(args.original / f'case-{index:03d}' / 'case-result.json') for index in range(1, 41)]
    for index, row in enumerate(results, 1):
        if (row != summary['cases'][index - 1] or row.get('index') != index
                or row.get('scenario') != study['scenarios'][index - 1]
                or row.get('dataset_revision') != study['revision'] or row.get('attempt') != 1
                or row.get('owned_core_stopped') is not True):
            raise ValueError('Original case identity/summary/confirmed Core stop mismatch')
    declaration = read_json(args.protocol)
    if (declaration['original_study_file_sha256'] != digest(args.original / 'study.json')
            or declaration['candidate_source_manifest_sha256'] != read_json(args.original / 'source.json')['manifest_sha256']):
        raise ValueError('Frozen declaration does not identify this original study/source')
    return study, summary, results, declaration


def frozen_harness(args):
    sys.path.insert(0, str(args.source))
    harness = importlib.import_module('scripts.qualify_itbench_aa')
    runner = read_json(args.original / 'runner.json')
    source = harness.source_identity()
    if (Path(harness.__file__).resolve() != args.source / 'scripts/qualify_itbench_aa.py'
            or source != read_json(args.original / 'source.json')
            or digest(Path(harness.__file__)) != runner['sha256'] or sys.version != runner['python']):
        raise ValueError('Frozen source, runner, or Python differs from the original R2 identity')
    return harness, source


def eligible(row, directory):
    return (row.get('error') == TRANSPORT_ERROR and row.get('output_valid') is False
            and all(row.get(name) is None for name in ('task_status', 'task_id', 'model_calls'))
            and not any((directory / name).exists() for name in STARTED_FILES)
            and not (directory / 'workspace' / 'agent_output.json').exists())


def read_json(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def copy_receipt(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return digest(source)


if __name__ == '__main__':
    raise SystemExit(main())
