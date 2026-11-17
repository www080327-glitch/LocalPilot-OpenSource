#!/usr/bin/env python3
"""Qualify real parent/child engineering with immutable, standard-library checks.

Use --preflight-only without a key for a local negative control. A funded run
requires --key-file and uses the actual Core imported from --source-root.
"""
import argparse
import ast
import difflib
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
DELIVERABLES = ('logstats/__init__.py', 'logstats/parser.py',
                'logstats/aggregate.py', 'logstats/__main__.py')
TASK_TIMEOUT = 1200


def main():
    args = arguments()
    args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
    modules = source_modules(args.source_root)
    source = source_identity(args.source_root, modules)
    original = fixture_files()
    write_files(args.output / 'acceptance-original', original)
    save(args.output / 'acceptance-manifest.json', hashes(original))
    prompt = instruction()
    (args.output / 'prompt.txt').write_text(prompt, encoding='utf-8')
    report = {'kind': 'SYNTHETIC_ENGINEERING_INTEGRATION', 'model': args.model,
              'protocol': 'responses', 'reasoning': args.reasoning, 'source': source,
              'protocol_status': 'NOT_RUN', 'orchestration_status': 'NOT_RUN',
              'semantic_status': 'NOT_RUN', 'engineering_status': 'NOT_RUN',
              'scope': 'One public synthetic Python project; not a model-quality benchmark.',
              'preflight_only': args.preflight_only}
    save(args.output / 'PROTOCOL.json', protocol(source, original, prompt))
    if args.preflight_only:
        write_files(args.output / 'workspace', original)
        report['preflight'] = preflight(args.output, original)
        report['passed'] = report['preflight']['passed']
    else:
        run_model(args, modules, original, prompt, report)
    save(args.output / 'RESULTS.json', report)
    print(json.dumps({k: report[k] for k in ('kind', 'preflight_only', 'protocol_status',
        'orchestration_status', 'semantic_status', 'engineering_status', 'passed')},
        ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--model', default='gpt-6-luna')
    parser.add_argument('--reasoning', default='medium')
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args(argv)
    args.output = args.output.resolve()
    args.source_root = args.source_root.resolve(strict=True)
    if not args.preflight_only and args.key_file is None:
        parser.error('--key-file is required for an actual model run')
    if args.output.exists():
        parser.error('--output must be a new directory; prior attempts are preserved')
    return args


def source_modules(source_root):
    sys.path.insert(0, str(source_root))
    modules = [importlib.import_module(name) for name in
               ('scripts.qualify_openai_agent', 'scripts.qualify_openai_superagent',
                'scripts.qualify_linux_model')]
    for module in modules:
        if Path(module.__file__).resolve().parent.parent != source_root:
            raise ValueError('Qualification helper was not imported from --source-root')
    return modules


def source_identity(source_root, modules):
    source = modules[0].source_identity()
    source['qualification_helpers'] = {
        str(Path(module.__file__).resolve().relative_to(source_root)):
        digest(Path(module.__file__).read_bytes()) for module in modules}
    source['runner_sha256'] = digest(Path(__file__).read_bytes())
    source['runtime_source_root'] = str(source_root)
    for label, revision in (('git_head', 'HEAD'), ('git_tree', 'HEAD^{tree}')):
        result = subprocess.run(['git', '-C', str(source_root), 'rev-parse', revision],
                                capture_output=True, text=True, timeout=10)
        source[label] = result.stdout.strip() if result.returncode == 0 else None
    return source


def protocol(source, original, prompt):
    return {'version': 1, 'source': source, 'task_timeout_seconds': TASK_TIMEOUT,
            'permission_mode': 'full', 'execution_budget': 'standard',
            'shell_timeout_unit': 'seconds', 'requested_shell_timeout_seconds': 60,
            'parent_limits': {'steps': 100, 'tools': 200},
            'requested_child_limits': {'steps': 20, 'tools': 40},
            'host_worker_limits': {'steps': 30, 'tools': 60},
            'max_children': 2, 'poll_interval_seconds': 1,
            'prompt_sha256': digest(prompt.encode()),
            'original_fixture_sha256': hashes(original),
            'expected_unittest_count': expected_test_count(),
            'expected_child_unittest_counts': {name: expected_test_count(name)
                for name in ('ParserTests', 'AggregateTests')},
            'criteria': {
                'protocol': 'Task completed and quiescent, no runner error, source unchanged.',
                'orchestration': 'Two completed/collected async children with model calls, '
                    'overlapping lifecycle intervals and changed-file apply_patch receipts '
                    'only for their assigned parser.py/aggregate.py, each with its successful '
                    'test-class Shell receipt; parent changed CLI and ran tests and CLI.',
                'semantic': 'Original acceptance files unchanged outside workspace; external '
                    'unittest count and success, all external CLI cases, and parent CLI artifact match.',
                'engineering': 'All three statuses above PASS; model self-report is not a criterion.'},
            'acceptance': 'After owned Core stops, copy only the four deliverable modules to a '
                'fresh directory and install the original tests/fixtures from runner memory. '
                'Workspace edits to tests cannot change external acceptance.',
            'no_external_dependencies': True, 'ranking_claim': False}


def run_model(args, modules, original, prompt, report):
    core, task = None, None
    started = time.monotonic()
    try:
        core = modules[0].CloudCore(args.output, args.key_file, args.model, args.reasoning)
        modules[1].configure_async(core)
        routes = json.loads((core.home / 'service.json').read_text())['routes']
        report['configured_inference'] = {name: {'model': route['backend']['model'],
            'protocol': route['backend']['protocol'], 'thinking': route['thinking']}
            for name, route in routes.items()}
        save(args.output / 'resolved-inference.json', report['configured_inference'])
        write_files(core.work, original)
        if Path(core.env['PYTHONPATH']).resolve() != args.source_root:
            raise ValueError('Actual Core PYTHONPATH does not match recorded source')
        core.start()
        session = core.session('engineering-session')
        task = core.submit('engineering-project', prompt, session=session, timeout=TASK_TIMEOUT)
        save(args.output / 'submission.json', task)
        task = core.finish('engineering', task, timeout=TASK_TIMEOUT + 60)
        report['task'] = modules[2].task_summary(task)
    except (Exception, KeyboardInterrupt) as error:
        report['error'] = {'type': type(error).__name__, 'message': str(error)[:1000]}
        if core is not None and task is not None:
            try:
                core.client.cancel(task['id'])
                task = core.client.status(task['id'])
                save(args.output / 'interrupted-task.json', task)
            except Exception as stop_error:
                report['cancel_error'] = {'type': type(stop_error).__name__}
    finally:
        if core is not None:
            core.stop()
        report['owned_core_stopped'] = core is None or core.process is None
        report['model_run_seconds'] = time.monotonic() - started
        report['source_after'] = source_identity(args.source_root, modules)
        report['source_unchanged'] = report['source'] == report['source_after']
    work = args.output / 'workspace'
    report['files'] = snapshot_files(work, args.output, original)
    report['original_acceptance_unchanged'] = original_matches(args.output, original)
    report['protocol_status'] = 'PASS' if task and task.get('status') == 'completed' and \
        task.get('quiescent') and not report.get('error') and report['source_unchanged'] else 'FAIL'
    report['orchestration'] = orchestration(task or {}, work)
    report['orchestration_status'] = 'PASS' if report['orchestration']['passed'] else 'FAIL'
    report['acceptance'] = external_acceptance(work, args.output, original)
    report['semantic_status'] = 'PASS' if report['acceptance']['passed'] and \
        report['original_acceptance_unchanged'] else 'FAIL'
    report['passed'] = all(report[name] == 'PASS' for name in
                          ('protocol_status', 'orchestration_status', 'semantic_status'))
    report['engineering_status'] = 'PASS' if report['passed'] else 'FAIL'


def orchestration(task, work):
    children = task.get('subagents', [])
    summaries, intervals, assigned = [], [], set()
    for child in children:
        starts = [row['at'] for row in child.get('timeline', []) if row['event'] == 'start']
        ends = [row['at'] for row in child.get('timeline', []) if row['event'] == 'completed']
        changed = patch_paths(child.get('receipts', []), work)
        interval = [min(starts), max(ends)] if starts and ends else None
        if interval is not None:
            intervals.append(interval)
        targets = changed & {'logstats/parser.py', 'logstats/aggregate.py'}
        single_module = len(targets) == 1 and changed == targets
        test_class = ({'logstats/parser.py': 'ParserTests',
                       'logstats/aggregate.py': 'AggregateTests'}[next(iter(targets))]
                      if single_module else None)
        shells = successful_shells(child.get('receipts', []))
        tests_ran = bool(test_class) and any('-m unittest' in row['command'] and
            test_class in row['command'] and row['tests_run'] == expected_test_count(test_class)
            for row in shells)
        if single_module:
            assigned.update(targets)
        summaries.append({'id': child['id'], 'status': child.get('status'),
            'async': child.get('async'), 'collected': child.get('collected'),
            'configured_model': child.get('configured_model'),
            'model_calls': child.get('model_calls', []), 'timeline': child.get('timeline', []),
            'reservation': child.get('reservation'), 'receipt_count': len(child.get('receipts', [])),
            'changed_paths': sorted(changed), 'lifecycle_interval': interval,
            'single_assigned_module': single_module, 'successful_shells': shells,
            'test_class': test_class, 'tests_ran': tests_ran,
            'completed': child.get('status') == 'completed' and child.get('async') is True
                and child.get('collected') is True and bool(child.get('model_calls'))})
    overlap = max(0, min(row[1] for row in intervals) - max(row[0] for row in intervals)) \
        if len(intervals) == 2 else 0
    parent = [row for row in task.get('tools', []) if not row.get('worker_id')]
    shells = successful_shells(parent)
    tests_ran = any('-m unittest discover' in row['command'] and 'test_acceptance.py' in row['command']
                    and row['tests_run'] == expected_test_count() for row in shells)
    cli_ran = any('-m logstats fixtures/basic.csv' in row['command'] and '--output result.json' in row['command']
                  for row in shells)
    parent_cli_changed = 'logstats/__main__.py' in patch_paths(parent, work)
    passed = len(summaries) == 2 and all(row['completed'] and row['single_assigned_module'] and row['tests_ran']
        for row in summaries) and assigned == {'logstats/parser.py', 'logstats/aggregate.py'} \
        and overlap > 0 and tests_ran and cli_ran and parent_cli_changed
    return {'passed': passed, 'children': summaries, 'async_lifecycle_overlap_seconds': overlap,
            'overlap_scope': 'Child start-to-completed lifecycles, including inference and tools; '
                'not proof of simultaneous CPU execution.',
            'parent_successful_shells': shells, 'parent_tests_ran': tests_ran,
            'parent_cli_ran': cli_ran, 'parent_cli_changed': parent_cli_changed,
            'aggregate_model_calls': (task.get('result') or {}).get('model_calls', []),
            'model_call_scope': 'Aggregate includes children; do not add child lists again.'}


def successful_shells(receipts):
    result = []
    for row in receipts:
        payload = row.get('payload', {}).get('result', {})
        if row.get('name') == 'shell' and row.get('status') == 'completed' and payload.get('exit_code') == 0:
            counts = re.findall(r'Ran (\d+) tests? in ', payload.get('stdout', '') + payload.get('stderr', ''))
            result.append({'receipt_id': row.get('receipt_id'),
                           'command': json.loads(row['arguments']).get('command', ''),
                           'tests_run': int(counts[-1]) if counts else 0})
    return result


def patch_paths(receipts, work):
    paths = set()
    for receipt in receipts:
        if receipt.get('name') != 'apply_patch' or receipt.get('status') != 'completed':
            continue
        for change in receipt.get('payload', {}).get('result', {}).get('changes', []):
            if change.get('before_sha256') == change.get('after_sha256'):
                continue
            path = Path(change['path'])
            paths.add(path.relative_to(work).as_posix() if path.is_absolute() else path.as_posix())
    return paths


def external_acceptance(work, output, original):
    check = output / 'external-acceptance'
    write_files(check, {name: content for name, content in original.items() if name not in DELIVERABLES})
    missing = []
    for name in DELIVERABLES:
        path = work / name
        if not path.is_file() or path.is_symlink():
            missing.append(name)
            continue
        target = check / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    unit = command([sys.executable, '-S', '-m', 'unittest', 'discover', '-s', 'tests',
                    '-p', 'test_acceptance.py', '-v'], check)
    matches = re.findall(r'Ran (\d+) tests? in ', unit['stdout'] + unit['stderr'])
    unit['tests_run'] = int(matches[-1]) if matches else 0
    unit['passed'] = unit['returncode'] == 0 and unit['tests_run'] == expected_test_count()
    save(output / 'external-unittest.json', unit)
    cases = {}
    for name, expected in (('basic', BASIC_EXPECTED), ('precision', PRECISION_EXPECTED), ('empty', EMPTY_EXPECTED)):
        result = command([sys.executable, '-S', '-m', 'logstats', f'fixtures/{name}.csv'], check)
        try:
            actual = json.loads(result['stdout'])
        except json.JSONDecodeError:
            actual = None
        result.update(expected=expected, actual=actual, passed=result['returncode'] == 0 and actual == expected)
        cases[name] = result
    invalid = command([sys.executable, '-S', '-m', 'logstats', 'fixtures/invalid.csv'], check)
    invalid['passed'] = invalid['returncode'] == 2 and not invalid['stdout'] and \
        bool(re.search(r'^error: row 2:', invalid['stderr'])) and 'Traceback' not in invalid['stderr']
    cases['invalid'] = invalid
    save(output / 'external-cli.json', cases)
    result_path = work / 'result.json'
    try:
        parent_artifact = json.loads(result_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        parent_artifact = None
    return {'passed': not missing and unit['passed'] and all(row['passed'] for row in cases.values())
                and parent_artifact == BASIC_EXPECTED,
            'missing_deliverables': missing, 'unit_passed': unit['passed'],
            'unit_test_count': unit['tests_run'], 'cli_cases': {k: v['passed'] for k, v in cases.items()},
            'parent_cli_artifact': parent_artifact,
            'parent_cli_artifact_matches': parent_artifact == BASIC_EXPECTED,
            'delivered_sha256': {name: digest((check / name).read_bytes()) for name in DELIVERABLES
                                 if name not in missing}}


def command(argv, cwd):
    started = time.monotonic()
    env = {'PATH': os.defpath, 'LANG': 'C.UTF-8', 'PYTHONIOENCODING': 'utf-8'}
    try:
        result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=45)
        return {'argv': argv, 'returncode': result.returncode, 'stdout': result.stdout,
                'stderr': result.stderr, 'seconds': time.monotonic() - started}
    except subprocess.TimeoutExpired as error:
        return {'argv': argv, 'returncode': None, 'stdout': (error.stdout or b'').decode(errors='replace'),
                'stderr': (error.stderr or b'').decode(errors='replace'),
                'seconds': time.monotonic() - started, 'error': 'timeout'}


def snapshot_files(work, output, original):
    before, after, diffs = hashes(original), {}, []
    final = output / 'final-project'
    final.mkdir()
    for name in (*original, 'result.json'):
        path = work / name
        if not path.is_file() or path.is_symlink():
            after[name] = None
            content = ''
        else:
            raw = path.read_bytes()
            after[name] = digest(raw)
            target = final / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            content = raw.decode('utf-8', errors='replace')
        if name in original and after[name] != before[name]:
            diffs.extend(difflib.unified_diff(original[name].splitlines(True), content.splitlines(True),
                         fromfile='before/' + name, tofile='after/' + name))
    (output / 'project.diff').write_text(''.join(diffs), encoding='utf-8')
    result = {'before_sha256': before, 'after_sha256': after,
              'changed_paths': [name for name in original if before[name] != after[name]],
              'scope': 'Fixed project, public acceptance fixtures, and requested CLI output.'}
    save(output / 'file-manifest.json', result)
    return result


def preflight(output, original):
    compiled = []
    for name, content in original.items():
        if name.endswith('.py'):
            compile(content, name, 'exec')
            compiled.append(name)
    acceptance = external_acceptance(output / 'workspace', output, original)
    unit = json.loads((output / 'external-unittest.json').read_text())
    rejected = not acceptance['passed'] and not acceptance['unit_passed'] and \
        acceptance['unit_test_count'] == expected_test_count() and 'NotImplementedError' in unit['stderr'] \
        and not any(acceptance['cli_cases'].values())
    return {'passed': rejected and original_matches(output, original), 'cloud_calls': 0,
            'core_started': False, 'compiled_files': compiled,
            'expected_unittest_count': expected_test_count(), 'stub_negative_control': acceptance,
            'stub_rejected': rejected, 'scope': 'Syntax and acceptance-harness negative control; '
                'no reference implementation or actual model result.'}


def original_matches(output, original):
    root = output / 'acceptance-original'
    return all((root / name).is_file() and (root / name).read_bytes() == content.encode('utf-8')
               for name, content in original.items())


def expected_test_count(class_name=None):
    counts = {node.name: sum(isinstance(method, ast.FunctionDef) and method.name.startswith('test_')
                            for method in node.body)
              for node in ast.parse(TESTS).body if isinstance(node, ast.ClassDef)}
    return counts[class_name] if class_name else sum(counts.values())


def write_files(root, files):
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')


def hashes(files):
    return {name: digest(content.encode('utf-8')) for name, content in sorted(files.items())}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    path.chmod(0o600)


def instruction():
    python = shlex.quote(sys.executable)
    return f'''Deliver the small standard-library Python project in this workspace.
Read SPEC.md and the public tests/fixtures. The existing modules are unfinished stubs.
Full permission is already granted. Use only this project; do not install dependencies,
access credentials/network services, or modify Core, qualification files outside the
workspace, SPEC.md, tests, or fixtures. Do not implement a lookup table of fixture answers.
The shell tool's timeout is measured in SECONDS. Use timeout 60 for the short test/CLI
commands here; it is not a millisecond value.

First delegate TWO independent cloud children in mode async, read_only false, each with
budget {{"steps":20,"tools":40}}. Start both before waiting. Child A owns only
logstats/parser.py: implement Record/parse_records per SPEC.md, and run ParserTests.
Child B owns only logstats/aggregate.py: implement summarize per the public Record
interface, and run AggregateTests. Children can select only their own test class with
unittest discover -s tests -p test_acceptance.py -k ParserTests (or -k AggregateTests).
Each child must use apply_patch to change its own
module, so the resulting per-file tool receipts prove actual implementation. Children
must not edit each other's module, CLI, tests, or fixtures. Do not do their work in the
parent instead of delegating. The Record data-class stub already supports imports while
the children work concurrently. Use wait_children to collect both results.

Then review/integrate their work and implement logstats/__main__.py in the parent using
apply_patch. Run real tests and CLI with shell (commands below). Fix genuine failures
within the task budget; report any integration repairs to child modules. Leave result.json
as the actual CLI output, not a manually written answer. Run:
{python} -S -m unittest discover -s tests -p test_acceptance.py -v
{python} -S -m logstats fixtures/basic.csv --output result.json
Read result.json and report changed modules, actual test outcome, CLI outcome, and any
remaining limitations. Completion prose alone does not pass: an external runner will
copy only the four delivered modules and run the original immutable tests/CLI cases.
The task deadline is 1200 seconds. Do not start background processes or wait for user input.
'''


SPEC = '''# logstats public contract

Implement a Python standard-library CSV event-log summarizer. No external dependency.
There are three implementation modules and the existing package __init__.py.

## parser.py
Keep the frozen dataclass Record(timestamp: datetime, category: str, value: Decimal).
parse_records(text: str) -> list[Record] accepts CSV with header timestamp,category,value
in exactly that order. Trim surrounding whitespace from header names and field values.
Use real CSV rules: quoted commas, doubled quote characters, and quoted field newlines
must work. Ignore empty lines and lines containing only whitespace, before/after the
header or between records; a row containing delimiters but empty fields is invalid.
Header-only input yields an empty list; missing or incorrect headers are errors.

Timestamps have the form YYYY-MM-DDTHH:MM:SSZ or YYYY-MM-DDTHH:MM:SS+HH:MM / -HH:MM,
represent a valid calendar time with seconds precision, and must include a timezone.
Normalize Record.timestamp to timezone.utc. Category must be nonempty after trimming.
Value is a signed or unsigned decimal number with ASCII digits, an optional decimal
point and one or two fractional digits; no exponent, NaN, Infinity, or empty value.
Store it as Decimal, never float. A row must have exactly three fields.

Any invalid header/record/CSV quoting raises ValueError with a message starting
"row N:", where N is the physical line on which the CSV record ends (csv.reader.line_num).
For completely missing input use row 1. Do not silently skip an invalid record.

## aggregate.py
summarize(records: Sequence[Record]) -> dict does not mutate the input. Return exactly:
{"record_count": integer, "groups": [{"category": string, "count": integer,
 "total": decimal-string, "first": UTC-string, "last": UTC-string}, ...]}
Group by exact category after parsing, sum values exactly, and sort groups by Python's
case-sensitive Unicode string order. total always has two fractional digits, no exponent
or leading plus; a zero total is "0.00". first/last are the minimum/maximum timestamp in
the group, formatted YYYY-MM-DDTHH:MM:SSZ in UTC. Empty input gives record_count 0 and
groups []. Do not infer any financial meaning from these generic event values.

## __main__.py
python -m logstats INPUT [--output PATH] reads UTF-8 CSV and uses the two public functions.
On success, exit 0. Without --output, write one JSON object and a newline to stdout.
With --output, write that JSON plus a newline to PATH and leave stdout empty. Unicode
data must round-trip; directories for PATH may be assumed to exist.
Invalid input or an input/output file error exits 2, writes one useful "error: ..." line
to stderr, leaves stdout empty, and does not print a traceback. CSV errors include the
parser's row number. Parse before opening the output file so invalid input does not
truncate an existing output. The CLI must not call external services or install anything.

## Public acceptance
tests/test_acceptance.py and fixtures/ are the fixed contract examples. They are visible
to both children and parent; do not edit them. Additional tests are allowed in another
file but cannot replace the fixed tests. The external runner restores the original
acceptance files beside only the four delivered package modules before checking them.
'''

BASIC_CSV = ('timestamp,category,value\n\n'
    '2026-01-02T01:30:00+02:00,"east, priority",0.10\n'
    '2026-01-01T22:00:00Z,"west ""desk""",-2.50\n'
    '2026-01-01T18:45:00-05:00,"east, priority",0.20\n  \n')
PRECISION_CSV = ('timestamp,category,value\n'
    '2026-02-03T10:00:00Z,zeta,9007199254740993.01\n'
    '2026-02-03T12:00:00+02:00,zeta,0.09\n'
    '2026-02-02T23:00:00-01:00,Alpha,-1.25\n'
    '2026-02-03T00:30:00Z,Alpha,1.25\n'
    '2026-02-03T03:00:00Z,北区,+2\n')
BASIC_EXPECTED = {'record_count': 3, 'groups': [
    {'category': 'east, priority', 'count': 2, 'total': '0.30',
     'first': '2026-01-01T23:30:00Z', 'last': '2026-01-01T23:45:00Z'},
    {'category': 'west "desk"', 'count': 1, 'total': '-2.50',
     'first': '2026-01-01T22:00:00Z', 'last': '2026-01-01T22:00:00Z'}]}
PRECISION_EXPECTED = {'record_count': 5, 'groups': [
    {'category': 'Alpha', 'count': 2, 'total': '0.00',
     'first': '2026-02-03T00:00:00Z', 'last': '2026-02-03T00:30:00Z'},
    {'category': 'zeta', 'count': 2, 'total': '9007199254740993.10',
     'first': '2026-02-03T10:00:00Z', 'last': '2026-02-03T10:00:00Z'},
    {'category': '北区', 'count': 1, 'total': '2.00',
     'first': '2026-02-03T03:00:00Z', 'last': '2026-02-03T03:00:00Z'}]}
EMPTY_EXPECTED = {'record_count': 0, 'groups': []}

TESTS = r'''import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from logstats.parser import Record, parse_records
from logstats.aggregate import summarize

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'fixtures'


class ParserTests(unittest.TestCase):
    def test_quoting_blank_lines_and_utc(self):
        rows = parse_records((FIXTURES / 'basic.csv').read_text(encoding='utf-8'))
        self.assertEqual(rows, [
            Record(datetime(2026, 1, 1, 23, 30, tzinfo=timezone.utc), 'east, priority', Decimal('0.10')),
            Record(datetime(2026, 1, 1, 22, 0, tzinfo=timezone.utc), 'west "desk"', Decimal('-2.50')),
            Record(datetime(2026, 1, 1, 23, 45, tzinfo=timezone.utc), 'east, priority', Decimal('0.20'))])
        self.assertTrue(all(isinstance(row.value, Decimal) for row in rows))
        self.assertTrue(all(row.timestamp.tzinfo is timezone.utc for row in rows))

    def test_trim_fields_and_multiline_category(self):
        rows = parse_records('\n timestamp , category , value \n2026-01-01T00:00:00Z," line\nname ", +2.5 \n')
        self.assertEqual(rows, [Record(datetime(2026, 1, 1, tzinfo=timezone.utc), 'line\nname', Decimal('2.5'))])

    def test_header_only(self):
        self.assertEqual(parse_records('\n timestamp,category,value\n \n'), [])

    def test_header_errors(self):
        for text in ('', '\n\n', 'category,timestamp,value\n', 'timestamp,category,value,extra\n'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, r'^row \d+:'):
                parse_records(text)

    def test_invalid_values(self):
        for value in ('NaN', 'Infinity', '1e3', '1.234', '', '.', '1.', '１２'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, r'^row 2:'):
                parse_records('timestamp,category,value\n2026-01-01T00:00:00Z,a,' + value + '\n')

    def test_invalid_timestamp_and_category(self):
        for row in ('2026-01-01T00:00:00,a,1', '2026-02-30T00:00:00Z,a,1',
                    '2026-01-01T00:00:00.5Z,a,1', '2026-01-01T00:00:00Z,  ,1'):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, r'^row 2:'):
                parse_records('timestamp,category,value\n' + row + '\n')

    def test_field_counts_and_empty_fields(self):
        for row in ('2026-01-01T00:00:00Z,a', '2026-01-01T00:00:00Z,a,1,extra', ',,'):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, r'^row 2:'):
                parse_records('timestamp,category,value\n' + row + '\n')

    def test_row_number_after_blanks(self):
        with self.assertRaisesRegex(ValueError, r'^row 4:'):
            parse_records('timestamp,category,value\n\n \n2026-01-01T00:00:00Z,a,bad\n')

    def test_malformed_csv(self):
        with self.assertRaisesRegex(ValueError, r'^row 2:'):
            parse_records('timestamp,category,value\n2026-01-01T00:00:00Z,"unfinished,1')


class AggregateTests(unittest.TestCase):
    def test_exact_totals_and_sorting(self):
        rows = [Record(datetime(2026, 1, 2, tzinfo=timezone.utc), 'z', Decimal('9007199254740993.01')),
                Record(datetime(2026, 1, 1, tzinfo=timezone.utc), 'A', Decimal('0.10')),
                Record(datetime(2026, 1, 3, tzinfo=timezone.utc), 'z', Decimal('0.09')),
                Record(datetime(2026, 1, 4, tzinfo=timezone.utc), 'A', Decimal('0.20'))]
        self.assertEqual(summarize(rows), {'record_count': 4, 'groups': [
            {'category': 'A', 'count': 2, 'total': '0.30', 'first': '2026-01-01T00:00:00Z', 'last': '2026-01-04T00:00:00Z'},
            {'category': 'z', 'count': 2, 'total': '9007199254740993.10', 'first': '2026-01-02T00:00:00Z', 'last': '2026-01-03T00:00:00Z'}]})

    def test_order_independence_and_no_mutation(self):
        rows = [Record(datetime(2026, 1, 2, tzinfo=timezone.utc), 'b', Decimal('-1.25')),
                Record(datetime(2026, 1, 1, tzinfo=timezone.utc), 'b', Decimal('1.25'))]
        before = list(rows)
        expected = {'record_count': 2, 'groups': [
            {'category': 'b', 'count': 2, 'total': '0.00', 'first': '2026-01-01T00:00:00Z', 'last': '2026-01-02T00:00:00Z'}]}
        self.assertEqual(summarize(rows), expected)
        self.assertEqual(rows, before)
        self.assertEqual(summarize(tuple(reversed(rows))), expected)

    def test_empty(self):
        self.assertEqual(summarize([]), {'record_count': 0, 'groups': []})


class CLITests(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run([sys.executable, '-S', '-m', 'logstats', *map(str, args)],
                              cwd=ROOT, capture_output=True, text=True, timeout=10)

    def test_stdout_json(self):
        result = self.invoke(FIXTURES / 'basic.csv')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), json.loads((FIXTURES / 'basic.expected.json').read_text()))
        self.assertTrue(result.stdout.endswith('\n'))
        self.assertEqual(result.stderr, '')

    def test_precision_and_unicode_file_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result.json'
            result = self.invoke(FIXTURES / 'precision.csv', '--output', output)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = output.read_text(encoding='utf-8')
            self.assertEqual(json.loads(text), json.loads((FIXTURES / 'precision.expected.json').read_text(encoding='utf-8')))
            self.assertTrue(text.endswith('\n'))
            self.assertEqual(result.stdout, '')
            self.assertEqual(result.stderr, '')

    def test_empty_input_dataset(self):
        result = self.invoke(FIXTURES / 'empty.csv')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'record_count': 0, 'groups': []})

    def test_invalid_row_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result.json'
            output.write_text('existing output\n')
            result = self.invoke(FIXTURES / 'invalid.csv', '--output', output)
            self.assertEqual(result.returncode, 2)
            self.assertRegex(result.stderr, r'^error: row 2:')
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(output.read_text(), 'existing output\n')

    def test_missing_file(self):
        result = self.invoke(FIXTURES / 'missing.csv')
        self.assertEqual(result.returncode, 2)
        self.assertRegex(result.stderr, r'^error: ')
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
'''


def fixture_files():
    return {'SPEC.md': SPEC, 'tests/test_acceptance.py': TESTS,
        'fixtures/basic.csv': BASIC_CSV, 'fixtures/precision.csv': PRECISION_CSV,
        'fixtures/empty.csv': 'timestamp,category,value\n\n',
        'fixtures/invalid.csv': 'timestamp,category,value\n2026-01-01T00:00:00Z,a,not-a-number\n',
        'fixtures/basic.expected.json': json.dumps(BASIC_EXPECTED, ensure_ascii=False, indent=2) + '\n',
        'fixtures/precision.expected.json': json.dumps(PRECISION_EXPECTED, ensure_ascii=False, indent=2) + '\n',
        'logstats/__init__.py': '"""Standard-library event-log statistics."""\n',
        'logstats/parser.py': 'from dataclasses import dataclass\nfrom datetime import datetime\n'
            'from decimal import Decimal\n\n\n@dataclass(frozen=True)\nclass Record:\n'
            '    timestamp: datetime\n    category: str\n    value: Decimal\n\n\n'
            'def parse_records(text: str) -> list[Record]:\n    raise NotImplementedError("Implement the public parser contract")\n',
        'logstats/aggregate.py': 'from collections.abc import Sequence\nfrom .parser import Record\n\n\n'
            'def summarize(records: Sequence[Record]) -> dict:\n    raise NotImplementedError("Implement exact aggregation")\n',
        'logstats/__main__.py': 'def main():\n    raise NotImplementedError("Implement the public CLI contract")\n\n\n'
            'if __name__ == "__main__":\n    raise SystemExit(main())\n'}


if __name__ == '__main__':
    raise SystemExit(main())
