#!/bin/bash
set -eu
LP_GRADE_PYTHON=/workspace/scratch/2a488f6eabf5/LocalPilot-OpenSource/.venv/bin/python
"$LP_GRADE_PYTHON" -B - <<'PY_CHECK'
from pathlib import Path
import hashlib
import json
import subprocess
import sys

base = Path('/workspace/scratch/c0f3ec78c621/validation/audit-20261117')
job = json.loads((base / 'itbench-aa-r2-transport-native-grading-r2-job.json').read_text())
if job.get('status') != 'READY_FROZEN':
    raise SystemExit('Waiting for the owner-provided frozen checkout and commit; grading was not started.')
assert sys.version_info[:3] == (3, 12, 14)
source = Path(job['cwd']).resolve()
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip() == job['source_commit']
assert subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=source, text=True).strip() == job['source_tree']
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=source)
grader = source / 'scripts/grade_itbench_aa.py'
assert str(grader) == job['command'][1]
assert hashlib.sha256(grader.read_bytes()).hexdigest() == job['grader_sha256'] == '4cd3f405f7a4d1c05edb6bf5d5530657c69de6b934bf59c2cdf01df7e2f20b76'
assert hashlib.sha256(Path(job['supervisor']).read_bytes()).hexdigest() == job['supervisor_sha256']
assert not Path(job['log']).exists() and not Path(job['exit_receipt']).exists()
PY_CHECK
exec "$LP_GRADE_PYTHON" -B /workspace/scratch/c0f3ec78c621/validation/audit-20261117/run_qualification_job.py /workspace/scratch/c0f3ec78c621/validation/audit-20261117/itbench-aa-r2-transport-native-grading-r2-job.json
