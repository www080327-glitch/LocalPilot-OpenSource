#!/usr/bin/env python3
"""Run the pinned ITBench-AA public split through the actual LocalPilot Core.

This is a separate LocalPilot evaluation, not an official AA leaderboard run.
Reference labels are fetched only after every candidate task has stopped.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.qualify_openai_agent import CloudCore, source_identity
from scripts.qualify_linux_model import save

DATASET = 'https://huggingface.co/datasets/ArtificialAnalysis/ITBench-AA'


def main():
    args = arguments()
    study = json.loads(args.study.read_text())
    tree = json.loads(args.tree.read_text())
    if tree['revision'] != study['revision']:
        raise ValueError('Dataset tree and frozen study refer to different revisions')
    args.output.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not (args.output / 'study.json').exists():
        save(args.output / 'study.json', study)
        save(args.output / 'source.json', source_identity())
        save(args.output / 'runner.json', {'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                         'python': sys.version})
    elif json.loads((args.output / 'study.json').read_text()) != study:
        raise ValueError('Refusing to replace a previously frozen study')
    with ThreadPoolExecutor(max_workers=study['parallel_cases']) as pool:
        pending = {pool.submit(run_case, args, study, tree, index, scenario): scenario
                   for index, scenario in enumerate(study['scenarios'], 1)}
        for future in as_completed(pending):
            result = future.result()
            print(json.dumps(result, ensure_ascii=False), flush=True)
    results = [json.loads((args.output / f'case-{index:03d}' / 'case-result.json').read_text())
               for index in range(1, len(study['scenarios']) + 1)]
    summary = {'planned': len(results), 'completed': sum(r.get('task_status') == 'completed' for r in results),
               'outputs_valid': sum(r.get('output_valid', False) for r in results),
               'errors': sum(bool(r.get('error')) for r in results), 'graded': False,
               'cases': results, 'comparison': study['comparison']}
    save(args.output / 'RUN_SUMMARY.json', summary)
    return 0 if summary['outputs_valid'] == summary['planned'] else 1


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    return parser.parse_args()


def run_case(args, study, tree, index, scenario):
    directory = args.output / f'case-{index:03d}'
    result_path = directory / 'case-result.json'
    if result_path.exists():
        return json.loads(result_path.read_text())
    directory.mkdir(mode=0o700, exist_ok=True)
    result = {'index': index, 'scenario': scenario, 'dataset_revision': study['revision'],
              'attempt': 1, 'output_valid': False, 'task_status': None}
    core = None
    started = time.monotonic()
    try:
        if (directory / 'candidate-started.json').exists():
            raise RuntimeError('Interrupted candidate attempt retained; not rerun under pass@1')
        if (directory / 'core-private').exists():
            shutil.rmtree(directory / 'core-private')
        if (directory / 'workspace').exists():
            shutil.rmtree(directory / 'workspace')
        core = CloudCore(directory, args.key_file, reasoning=study['reasoning'])
        (core.work / 'fact.txt').unlink()
        prefix = f'sre/{scenario}/'
        files = [row for row in tree['entries'] if row['type'] == 'file'
                 and row['path'].startswith(prefix) and 'ground_truth' not in row['path']]
        with ThreadPoolExecutor(max_workers=6) as downloads:
            receipts = list(downloads.map(lambda row: download(row, study['revision'], prefix, core.work), files))
        save(directory / 'input-manifest.json', receipts)
        result['input_bytes'] = sum(row['bytes'] for row in receipts)
        result['input_files'] = len(receipts)
        result['download_seconds'] = time.monotonic() - started
        prompt = instruction(core.work)
        (directory / 'prompt.txt').write_text(prompt)
        save(directory / 'candidate-started.json', {'time_unix': time.time(),
            'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(), 'attempt': 1})
        core.start()
        task = core.submit('itbench-candidate', prompt,
                           session=core.session('itbench-session'), timeout=study['task_timeout_seconds'])
        task = core.finish('candidate', task, timeout=study['task_timeout_seconds'] + 60)
        result.update(task_status=task['status'], task_id=task['id'],
            task_error=task.get('error'), required_action=task.get('required_action'),
            task_seconds=time.monotonic() - started - result['download_seconds'],
            model_calls=(task.get('result') or {}).get('model_calls', []),
            runtime_metrics=(task.get('result') or {}).get('runtime_metrics'),
            tools=[{'name': row['name'], 'status': row.get('status'),
                    'arguments': row.get('arguments')} for row in task.get('tools', [])])
        output = core.work / 'agent_output.json'
        if output.is_file():
            shutil.copyfile(output, directory / 'agent_output.json')
            prediction = json.loads(output.read_text())
            factors = prediction.get('contributing_factors') if isinstance(prediction, dict) else None
            result['output_valid'] = (isinstance(factors, list) and all(
                isinstance(item, dict) and all(isinstance(item.get(key), str)
                for key in ('name', 'reasoning', 'evidence')) for item in factors))
        task_path = directory / 'candidate-task.json'
        with gzip.open(directory / 'candidate-task.json.gz', 'wb', compresslevel=9) as stream:
            stream.write(task_path.read_bytes())
        task_path.unlink()
    except Exception as error:
        result['error'] = {'type': type(error).__name__, 'message': str(error)[:1000]}
    finally:
        if core is not None:
            core.stop()
        result['total_seconds'] = time.monotonic() - started
        result['owned_core_stopped'] = core is None or core.process is None
        save(result_path, result)
        if core is not None and result['owned_core_stopped'] and core.work.exists():
            shutil.rmtree(core.work)
    return {key: value for key, value in result.items()
            if key not in {'model_calls', 'runtime_metrics', 'tools'}}


def download(row, revision, prefix, workspace):
    relative = row['path'][len(prefix):]
    target = workspace / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    expected_sha256 = row.get('lfs', {}).get('oid')
    for attempt in range(3):
        digest = hashlib.sha256()
        git_digest = hashlib.sha1(f"blob {row['size']}\0".encode())
        received = 0
        try:
            with urlopen(f"{DATASET}/resolve/{revision}/{row['path']}", timeout=90) as response:
                with target.open('wb') as stream:
                    for chunk in iter(lambda: response.read(1024 * 1024), b''):
                        stream.write(chunk)
                        digest.update(chunk)
                        git_digest.update(chunk)
                        received += len(chunk)
            if received != row['size'] or (digest.hexdigest() != expected_sha256
                    if expected_sha256 else git_digest.hexdigest() != row['oid']):
                raise ValueError('Immutable dataset content digest did not match the published tree')
            return {'path': relative, 'bytes': received, 'sha256': digest.hexdigest(),
                    'source_oid': row['oid']}
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def instruction(workspace):
    return f'''Investigate the Kubernetes incident recorded in this offline snapshot.
Use only the files in your working directory: {workspace}
Do not use the network, lookup a benchmark answer, inspect sibling directories, or
read any evaluator or service configuration. No reference diagnosis is provided.

Find the smallest set of independent Kubernetes resources whose faults explain
the incident. Support each selected resource with concrete observations from the
snapshot. Inspect the alerts, event records, object state, logs, metrics, traces,
and topology as relevant. Use shell and Python to filter the large tabular files;
avoid dumping entire data files. Available Python includes numpy and pandas.
The snapshot is historical: do not contact a cluster or try to repair one.

Trace each symptom upstream. Omit a resource if a cause already in your answer
fully explains its failure. Include multiple resources only when they introduce
independent failures. A resource needs evidence during the incident, such as a
firing alert, a warning event, abnormal metric, failing trace, or error log.
An exhausted quota is a possible upstream cause; a deployment unable to create
pods solely because of that quota is a resulting symptom.

Write agent_output.json in the working directory. It must be a JSON object with
one field, contributing_factors, containing a list of objects. Every object must
have three string fields: name, reasoning, and evidence. Use resource identifiers
in the form namespace/Kind/name; use cluster as the namespace for cluster-wide
resources, and never append an object UID. The reasoning must explain causation;
the evidence must identify the observations supporting it. Finish by stating that
the file is ready. Do not ask for approval: this diagnostic work is authorized.
You have at most 100 model steps and 20 minutes for this attempt.'''


if __name__ == '__main__':
    raise SystemExit(main())
