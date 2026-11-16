#!/usr/bin/env python3
"""Reuse every unchanged case cache; forbid any new judge backend."""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
import sys
import time


BASE = Path('/workspace/scratch/c0f3ec78c621/validation/audit-20261117')
SOURCE = BASE / 'final-source-b29'
OUTPUT = BASE / 'itbench-aa-r2-original-score'
COMMIT = '8e92deb8b6a0acbba1d139851b1d805246304c61'
TREE = '813a2544f1553d9c6a5e8a01982f2f512eec5e5b'
GRADER_SHA = '4cd3f405f7a4d1c05edb6bf5d5530657c69de6b934bf59c2cdf01df7e2f20b76'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(directory):
    return {p.name: {'bytes': p.stat().st_size, 'sha256': digest(p)}
            for p in sorted(directory.iterdir()) if p.is_file()}


def main():
    assert sys.version_info[:3] == (3, 12, 14)
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True).strip() == COMMIT
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=SOURCE, text=True).strip() == TREE
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=SOURCE)
    grader_path = SOURCE / 'scripts/grade_itbench_aa.py'
    assert digest(grader_path) == GRADER_SHA
    prepared_path = OUTPUT / 'CACHE_REUSE_PREPARED.json'
    prepared = json.loads(prepared_path.read_text())
    result_path = OUTPUT / 'CACHE_REUSE.json'
    assert not result_path.exists() and not (OUTPUT / 'grading/SUMMARY.json').exists()
    assert hashes(OUTPUT / 'grading') == prepared['copied_cache_before']
    for relative, expected in prepared['input_hashes'].items():
        assert digest(OUTPUT / relative) == expected
    combined = Path(prepared['combined_directory'])
    assert hashes(combined / 'grading') == prepared['combined_grading_before']
    spec = importlib.util.spec_from_file_location('frozen_cache_only_grader', grader_path)
    grader = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = grader
    spec.loader.exec_module(grader)
    judge_backend_attempts = 0

    def forbid_new_judge(_key_file):
        nonlocal judge_backend_attempts
        judge_backend_attempts += 1
        raise RuntimeError('Cache-only verification forbids new judge requests')

    started = time.time()
    summary = None
    error = None
    try:
        summary = grader.grade_run(
            OUTPUT, Path('/__no_credentials_for_cache_reuse__'),
            backend_factory=forbid_new_judge)
    except Exception as caught:
        error = {'type': type(caught).__name__, 'message': str(caught)}
    cache_after = hashes(OUTPUT / 'grading')
    combined_after = hashes(combined / 'grading')
    copied_cache_unchanged = all(cache_after.get(name) == entry
                                 for name, entry in prepared['copied_cache_before'].items())
    inputs_unchanged = all(digest(OUTPUT / relative) == expected
                           for relative, expected in prepared['input_hashes'].items())
    originals_unchanged = all(digest(Path(entry['source'])) == entry['sha256']
                              for entry in prepared['source_files'].values())
    combined_unchanged = combined_after == prepared['combined_grading_before']
    passed = (error is None and judge_backend_attempts == 0 and copied_cache_unchanged
              and inputs_unchanged and originals_unchanged and combined_unchanged
              and summary['grading_complete'] and summary['denominator'] == 40
              and summary['graded_cases'] == 26 and summary['candidate_zero_cases'] == 14)
    record = {
        'status': 'PASS' if passed else 'FAIL', 'started_unix': started,
        'finished_unix': time.time(), 'source_commit': COMMIT, 'source_tree': TREE,
        'grader_sha256': GRADER_SHA, 'script_sha256': digest(Path(__file__)),
        'prepared_sha256': digest(prepared_path), 'backend_factory_attempts': judge_backend_attempts,
        'new_judge_requests': 0, 'private_key_read': False, 'reference_storage': 'Memory only',
        'candidate_reruns': 0, 'reused_case_indices': prepared['reused_case_indices'],
        'excluded_transport_indices': prepared['excluded_transport_indices'],
        'reuse_policy': prepared['reuse_policy'], 'copied_cache_unchanged': copied_cache_unchanged,
        'copied_cache_before': prepared['copied_cache_before'], 'cache_after': cache_after,
        'combined_cache_unchanged': combined_unchanged,
        'combined_cache_before': prepared['combined_grading_before'],
        'combined_cache_after': combined_after, 'copied_candidate_inputs_unchanged': inputs_unchanged,
        'original_source_files_unchanged': originals_unchanged, 'error': error,
        'summary': {key: value for key, value in summary.items() if key != 'cases'} if summary else None,
    }
    result_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: record[key] for key in (
        'status', 'backend_factory_attempts', 'new_judge_requests', 'copied_cache_unchanged',
        'combined_cache_unchanged', 'copied_candidate_inputs_unchanged', 'summary', 'error')},
        ensure_ascii=False), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
