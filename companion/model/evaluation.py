"""Explicit local evaluation of reviewed, held-out answers; no training or promotion."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time
from urllib.error import HTTPError

from companion.config import PrivateData
from companion.escalation.provider import request_chat, validate_endpoint
from companion.model.reviewed_data import load_dataset
from companion.observers.events import redact_text
from companion.observers.files import read_regular_file


def evaluate(dataset, endpoint, model, output, *, max_tokens=256, timeout_seconds=90, label='candidate'):
    endpoint = validate_endpoint(endpoint)
    if not isinstance(model, str) or not model.strip() or len(model) > 200:
        raise ValueError('An explicit local model name is required')
    if type(max_tokens) is not int or not 1 <= max_tokens <= 8192:
        raise ValueError('Use an output budget between 1 and 8192 tokens')
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 90:
        raise ValueError('Use a model deadline between 0 and 90 seconds')
    if not isinstance(label, str) or not label.strip() or len(label) > 100:
        raise ValueError('Use a short evaluation label')
    dataset, output = Path(dataset).expanduser().resolve(), Path(output).expanduser().resolve()
    if output.exists() or output.is_relative_to(dataset) or dataset.is_relative_to(output):
        raise ValueError('Choose a new evaluation directory separate from the dataset')
    manifest, splits, manifest_hash = load_dataset(dataset, require_test=True)
    private = PrivateData(output)
    report = {'schema': 'companion-held-out-evaluation-v1', 'label': label, 'status': 'running',
              'created_at': time.time(), 'dataset_manifest_sha256': manifest_hash,
              'test_sha256': manifest['sha256']['test.jsonl'], 'source_group_count': manifest['source_group_count'],
              'endpoint': endpoint, 'model': model, 'max_tokens': max_tokens, 'temperature': 0,
              'timeout_seconds': timeout_seconds, 'cases': [], 'contains_private_text': True,
              'training': 'NOT_RUN', 'model_promoted': False, 'weights_identity': 'NOT_VERIFIED',
              'quality_claim': 'Exact answer match on this reviewed test set only; no semantic or benchmark ranking claim'}
    private.write('evaluation.json', json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    try:
        for index, sample in enumerate(splits['test']):
            messages = sample['messages'][:-1]
            target = sample['messages'][-1]['content']
            row = {'index': index, 'prompt_sha256': hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                   'expected': target, 'usage': 'UNKNOWN', 'exact_match': False}
            started = time.monotonic()
            try:
                result = request_chat(endpoint, model, messages, max_tokens, timeout_seconds=timeout_seconds)
                row.update(status='completed', answer=result['text'], reported_model=result.get('reported_model'),
                           usage=result.get('usage') or 'UNKNOWN', exact_match=result['text'].strip() == target.strip())
            except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
                if isinstance(error, HTTPError):
                    error.close()
                row.update(status='error', error=redact_text(str(error))[:800])
            row['latency_seconds'] = time.monotonic() - started
            report['cases'].append(row)
            private.write('evaluation.json', json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        report['status'] = 'completed' if all(row['status'] == 'completed' for row in report['cases']) else 'completed_with_errors'
    except KeyboardInterrupt:
        report['status'] = 'interrupted'
    report.update(finished_at=time.time(), total=len(splits['test']), attempted=len(report['cases']),
                  exact_matches=sum(row['exact_match'] for row in report['cases']),
                  errors=sum(row['status'] == 'error' for row in report['cases']))
    private.write('evaluation.json', json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


def compare(baseline, candidate):
    reports = []
    for path in (baseline, candidate):
        raw, _ = read_regular_file(Path(path), 64 * 1024 * 1024)
        report = json.loads(raw)
        if (not isinstance(report, dict) or report.get('schema') != 'companion-held-out-evaluation-v1'
                or report.get('status') not in {'completed', 'completed_with_errors'}
                or not isinstance(report.get('cases'), list) or not report['cases']
                or any(not isinstance(row, dict) or type(row.get('exact_match')) is not bool for row in report['cases'])):
            raise ValueError('Use completed held-out evaluation reports')
        reports.append(report)
    base, selected = reports
    for key in ('dataset_manifest_sha256', 'test_sha256', 'max_tokens', 'temperature', 'timeout_seconds', 'total'):
        if key not in base or base[key] != selected.get(key):
            raise ValueError('Evaluation conditions differ: ' + key)
    left, right = base['cases'], selected['cases']
    if len(left) != len(right) or len(left) != base['total'] or any(
            (a.get('index'), a.get('prompt_sha256'), a.get('expected')) != (b.get('index'), b.get('prompt_sha256'), b.get('expected'))
            for a, b in zip(left, right)):
        raise ValueError('Evaluation reports must cover the same complete ordered test cases')
    improved = sum(not a['exact_match'] and b['exact_match'] for a, b in zip(left, right))
    regressed = sum(a['exact_match'] and not b['exact_match'] for a, b in zip(left, right))
    return {'schema': 'companion-held-out-comparison-v1', 'total': len(left),
            'baseline_exact_matches': sum(row['exact_match'] for row in left),
            'candidate_exact_matches': sum(row['exact_match'] for row in right),
            'improved_cases': improved, 'regressed_cases': regressed,
            'baseline_errors': sum(row.get('status') == 'error' for row in left),
            'candidate_errors': sum(row.get('status') == 'error' for row in right),
            'model_promoted': False, 'statistical_superiority': 'NOT_ESTABLISHED',
            'quality_claim': 'Descriptive exact-match comparison; review answers and verify model weights before an adoption decision'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    for option in ('data', 'endpoint', 'model', 'output'):
        run.add_argument('--' + option, required=True)
    run.add_argument('--label', default='candidate')
    run.add_argument('--max-tokens', type=int, default=256)
    run.add_argument('--timeout-seconds', type=float, default=90)
    pair = sub.add_parser('compare')
    pair.add_argument('--baseline', required=True)
    pair.add_argument('--candidate', required=True)
    args = parser.parse_args()
    try:
        result = (compare(args.baseline, args.candidate) if args.command == 'compare' else
                  evaluate(args.data, args.endpoint, args.model, args.output, label=args.label,
                           max_tokens=args.max_tokens, timeout_seconds=args.timeout_seconds))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('status', 'completed') == 'completed' else 2
    except (OSError, ValueError) as error:
        print(json.dumps({'status': 'error', 'error': redact_text(str(error))[:800]}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
