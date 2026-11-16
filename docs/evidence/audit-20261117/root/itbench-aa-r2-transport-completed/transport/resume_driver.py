import argparse
import hashlib
import json
from pathlib import Path
import runpy
import sys
import time


BASE = Path('/workspace/scratch/c0f3ec78c621/validation/audit-20261117')
DRIVER = Path('/workspace/scratch/2a488f6eabf5/LocalPilot-polish-final-20261116/scripts/continue_itbench_transport.py')
EXPECTED_DRIVER = '17fe9d34b492e00e788393d2f2ce35df262658d9ccfb5ec058a74f72683221d6'
SELECTED = [23, 25, 26, 27, 28, 29]


def main():
    check_only = '--check-only' in sys.argv[1:]
    assert hashlib.sha256(DRIVER.read_bytes()).hexdigest() == EXPECTED_DRIVER
    driver = runpy.run_path(str(DRIVER), run_name='frozen_transport_driver')
    args = argparse.Namespace(source=BASE/'qualification-source-r2', original=BASE/'itbench-aa-r2',
        output=BASE/'itbench-aa-r2-transport-completed', tree=BASE/'itbench-aa-source/tree.json',
        key_file=Path('<private_key_file>'),
        protocol=BASE/'transport-continuation-protocol.json')
    study, original_summary, original_results, declaration = driver['original_inputs'](args)
    harness, source = driver['frozen_harness'](args)
    read, digest = driver['read_json'], driver['digest']
    continuation = read(args.output/'CONTINUATION.json')
    assert continuation['eligible_indices'] == SELECTED
    assert continuation['source'] == source
    assert read(args.output/'study.json') == study
    assert read(args.output/'source.json') == source
    tree = read(args.tree)
    assert tree['revision'] == study['revision']
    existing = {f'case-{i:03d}/case-result.json': digest(args.output/f'case-{i:03d}/case-result.json')
                for i in range(1, 41) if (args.output/f'case-{i:03d}/case-result.json').exists()}
    interrupted = [i for i in SELECTED if (args.output/f'case-{i:03d}/candidate-started.json').exists()
                   and not (args.output/f'case-{i:03d}/case-result.json').exists()]
    assert not (args.output/'RUN_SUMMARY.json').exists()
    receipt = {'kind':'RESUME_AFTER_EXECUTOR_SESSION_LOSS', 'time_unix':time.time(),
        'driver_sha256':digest(Path(__file__)), 'original_transport_driver_sha256':EXPECTED_DRIVER,
        'continuation_sha256':digest(args.output/'CONTINUATION.json'), 'source':source,
        'python':sys.version, 'executable':sys.executable, 'eligible_indices':SELECTED,
        'existing_result_sha256':existing, 'started_without_result':interrupted,
        'execution_surface':'Existing native desktop Terminal; its current environment is inherited without network/proxy/TLS changes.',
        'environment_change':'Native Terminal has a different PID/network namespace from per-call exec. Candidate source, Python, prompt, budgets, input URLs and run_case are unchanged.',
        'attempt_rule':'Frozen run_case reuses completed receipts, retains started interruptions without model retry, and starts only never-started cases.',
        'references_loaded':False}
    if check_only:
        print(json.dumps({'check':'PASS','existing_results':len(existing),'started_without_result':interrupted,
                          'driver_sha256':receipt['driver_sha256']}))
        return 0
    resume = args.output/'RESUME_AFTER_SESSION_LOSS.json'
    with resume.open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    for index in SELECTED:
        result = harness.run_case(args, study, tree, index, study['scenarios'][index-1])
        print(json.dumps(result, ensure_ascii=False), flush=True)
    assert all(digest(args.output/name) == sha for name, sha in existing.items())
    combined = [read(args.output/f'case-{i:03d}/case-result.json') for i in range(1, 41)]
    summary = {'planned':40, 'completed':sum(row.get('task_status') == 'completed' for row in combined),
        'outputs_valid':sum(row.get('output_valid', False) for row in combined),
        'errors':sum(bool(row.get('error')) for row in combined), 'graded':False,
        'cases':combined, 'comparison':study['comparison'], 'provenance':'CONTINUATION.json',
        'resumption':'RESUME_AFTER_SESSION_LOSS.json'}
    harness.save(args.output/'RUN_SUMMARY.json', summary)
    return 0 if summary['outputs_valid'] == 40 else 1


if __name__ == '__main__':
    raise SystemExit(main())
