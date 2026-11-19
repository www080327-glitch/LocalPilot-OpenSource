#!/usr/bin/env bash
set -euo pipefail
export PATH="<task_python_env>/bin:$PATH"
exec <task_python_env>/bin/python -B - <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import time

source = Path('<validation_root>/final-source-b30')
output = Path('<validation_root>/engineering-luna-r5-b30-native')
job = output.with_name(output.name + '.job.sh')
runner = source / 'scripts/qualify_openai_engineering.py'
head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
tree = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD^{tree}'], text=True).strip()
runner_hash = hashlib.sha256(runner.read_bytes()).hexdigest()
assert head == '1dca93c5a6a2d0c557a9507ca020c07458dd92d1'
assert tree == '1457ce75f9134196c0c489f69bc4ee5b03467d4b'
assert runner_hash == '108f948c1b32fa9de95e48a1a84ede4b4b78a3d3ecfabe1c9977e4b7e21cc0fb'
assert not subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True)
assert sys.version_info[:3] == (3, 12, 14)
assert not output.exists()
start_path = output.with_name(output.name + '.EXECUTION_START.json')
end_path = output.with_name(output.name + '.EXECUTION_END.json')
runner_copy = output.with_name(output.name + '.runner.py')
log_path = output.with_name(output.name + '.log')
started = time.monotonic()
record = {'started_at': datetime.now(timezone.utc).isoformat(), 'source_head': head,
    'source_tree': tree, 'source_clean': True, 'runner_sha256': runner_hash,
    'job_sha256': hashlib.sha256(job.read_bytes()).hexdigest(),
    'interpreter': sys.executable, 'python_version': sys.version,
    'source_root': str(source), 'output': str(output), 'task_timeout_seconds': 1200,
    'entrypoint': 'Native Terminal foreground job',
    'environment_change': 'Prepend only the fixed task-tool Python directory to inherited PATH; proxy and TLS variables unchanged.',
    'credential_source': 'User-provided private key-file; contents not copied or logged.',
    'attempt_reason': 'New frozen b30 version-validation attempt after the async missing-directory completion change; R3 and R4 remain FAIL and R2 remains interrupted.',
    'single_attempt': True, 'fixture_prompt_budgets_runner_unchanged': True}
with start_path.open('x', encoding='utf-8') as f:
    json.dump(record, f, indent=2)
    f.write('\n')
shutil.copyfile(runner, runner_copy)
print(json.dumps({'event': 'engineering_started', 'started_at': record['started_at'],
    'source_head': head, 'output': str(output)}), flush=True)
with log_path.open('x', encoding='utf-8') as log:
    proc = subprocess.Popen([sys.executable, '-B', str(runner), '--source-root', str(source),
        '--output', str(output), '--key-file', '<private_root>/openai-api-key'],
        cwd=source, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in proc.stdout:
        log.write(line)
        log.flush()
        print(line, end='', flush=True)
    code = proc.wait()
end = {'finished_at': datetime.now(timezone.utc).isoformat(), 'exit_code': code,
    'elapsed_seconds': time.monotonic() - started,
    'runner_sha256_after': hashlib.sha256(runner.read_bytes()).hexdigest(),
    'git_status_after': subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True),
    'log_sha256': hashlib.sha256(log_path.read_bytes()).hexdigest(),
    'results_present': (output / 'RESULTS.json').is_file()}
with end_path.open('x', encoding='utf-8') as f:
    json.dump(end, f, indent=2)
    f.write('\n')
if output.is_dir():
    for original, name in ((start_path, 'EXECUTION_START.json'), (end_path, 'EXECUTION_END.json'),
                           (runner_copy, 'runner.py'), (log_path, 'execution.log'), (job, 'native-job.sh')):
        shutil.copyfile(original, output / name)
print(json.dumps({'event': 'engineering_finished', **end}), flush=True)
sys.exit(code)
PY
