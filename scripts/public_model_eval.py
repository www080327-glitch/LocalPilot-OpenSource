"""Small preregistered MMLU-Pro model probe using the existing product transport.

This zero-shot subset is not an Artificial Analysis score or an Agent ranking.
Dataset files and answer keys stay in private evaluation storage, outside Git.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.backends import Message
from localpilot_service.backend_contract import ServiceOpenAIBackend

SELECTION_SEED = 20261116
QUESTION_COUNT = 32
PROMPT = ('Choose the best option for this question. Keep any explanation concise. '
          'End with exactly one line formatted "Answer: X", replacing X with the selected letter.\n\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-jsonl', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = args.dataset_jsonl.read_bytes()
    source = json.loads(args.source.read_text())
    source['input_jsonl_sha256'] = hashlib.sha256(data).hexdigest()
    protocol = freeze_questions([json.loads(line) for line in data.splitlines() if line.strip()], source, args.output)
    print(json.dumps({'protocol_sha256': protocol['sha256'], 'questions': len(protocol['questions']),
                      'question_ids': [row['question_id'] for row in protocol['questions']]}))


def freeze_questions(rows, source, output):
    questions = checked_questions(rows)
    if (not isinstance(source, dict) or source.get('repository') != 'TIGER-Lab/MMLU-Pro'
            or not re.fullmatch('[0-9a-f]{40}', source.get('revision', ''))
            or not re.fullmatch('[0-9a-f]{64}', source.get('sha256', ''))):
        raise ValueError('Pinned upstream revision and downloaded file SHA256 are required')
    groups = defaultdict(list)
    for row in questions:
        groups[row['category']].append(row)
    if len(groups) != 14 or any(len(group) < 2 for group in groups.values()) or len(questions) < QUESTION_COUNT:
        raise ValueError('This fixed probe requires 14 categories and at least 32 questions')
    def rank(row):
        return hashlib.sha256(f"{SELECTION_SEED}:{row['question_id']}".encode()).hexdigest()
    chosen = [row for category in sorted(groups) for row in sorted(groups[category], key=rank)[:2]]
    selected_ids = {row['question_id'] for row in chosen}
    remaining = sorted((row for row in questions if row['question_id'] not in selected_ids), key=rank)
    chosen = sorted(chosen + remaining[:QUESTION_COUNT-len(chosen)], key=rank)
    protocol = {'schema_version': 1, 'kind': 'PUBLIC_MODEL_SUBSET', 'benchmark': 'MMLU-Pro',
        'frozen_at': now(), 'source': source, 'source_rows': len(questions),
        'selection': {'seed': SELECTION_SEED, 'per_category': 2, 'total': QUESTION_COUNT,
                      'rule': 'sha256(seed:question_id); two per category, then four lowest remaining hashes'},
        'inference': {'shots': 0, 'repeats': 1, 'max_output_tokens': 512, 'timeout_seconds': 120,
                      'prompt_prefix': PROMPT, 'tools': False, 'retry_attempts': 0},
        'grading': 'Exact final nonempty line Answer: A through J, in-range option, finish_reason=stop',
        'ranking_claim': False, 'questions': chosen}
    protocol['sha256'] = value_hash(protocol)
    write_json(Path(output), protocol, exclusive=True)
    return protocol


def checked_questions(rows):
    if not isinstance(rows, list):
        raise ValueError('Dataset must be a JSONL question list')
    result, ids = [], set()
    for row in rows:
        if (not isinstance(row, dict) or type(row.get('question_id')) is not int
                or row['question_id'] in ids or not isinstance(row.get('question'), str) or not row['question'].strip()
                or not isinstance(row.get('category'), str) or not row['category']
                or not isinstance(row.get('options'), list) or not 2 <= len(row['options']) <= 10
                or any(not isinstance(option, str) for option in row['options'])
                or type(row.get('answer_index')) is not int or not 0 <= row['answer_index'] < len(row['options'])
                or row.get('answer') != chr(65+row['answer_index'])):
            raise ValueError('Malformed or duplicate MMLU-Pro question')
        ids.add(row['question_id'])
        result.append({key: row[key] for key in ('question_id', 'category', 'question', 'options', 'answer', 'answer_index')})
    return result


def run_study(protocol_path, *, endpoint, evidence, model_identity, generation_parameters):
    protocol = read_protocol(protocol_path)
    identity = checked_identity(model_identity)
    out = Path(evidence).resolve()
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    backend = RecordedModelBackend(base_url=endpoint, model=identity['model_name'],
        timeout=protocol['inference']['timeout_seconds'], effective_context=8192,
        supports_tool_calling=False, supports_streaming=False,
        generation_parameters=generation_parameters)
    contract = {'protocol_sha256': protocol['sha256'], 'protocol_file_sha256': file_hash(protocol_path),
        'runner_sha256': file_hash(__file__), 'frozen_before_inference_at': now(),
        'model_identity': identity, 'generation_parameters': dict(backend.generation_parameters),
        'endpoint': endpoint, 'inference': protocol['inference'], 'ranking_claim': False}
    write_json(out/'RUN_CONTRACT.json', contract, exclusive=True)
    rows = [{'question_id': row['question_id'], 'category': row['category'], 'status': 'NOT_RUN'}
            for row in protocol['questions']]
    try:
        for question, row in zip(protocol['questions'], rows):
            prompt = question_prompt(question, protocol['inference']['prompt_prefix'])
            write_json(out/f"question-{row['question_id']}-request.json", {'messages': [{'role': 'user', 'content': prompt}],
                'max_tokens': protocol['inference']['max_output_tokens']}, exclusive=True)
            started = time.monotonic()
            backend.raw_response = None
            try:
                reply = backend.request([Message('user', prompt)], max_tokens=protocol['inference']['max_output_tokens'])
                raw = {'provider_response': backend.raw_response, 'parsed_response': asdict(reply)}
                write_json(out/f"question-{row['question_id']}-response.json", raw, exclusive=True)
                parsed = final_answer(reply.message.content, len(question['options']))
                if reply.model != identity['model_name']:
                    raise ValueError('Returned model differs from the frozen configured model')
                row.update(status='PASS' if reply.finish_reason == 'stop' and parsed == question['answer'] else 'FAIL',
                    predicted=parsed, expected=question['answer'], finish_reason=reply.finish_reason,
                    usage=reply.usage, returned_model=reply.model,
                    response_sha256=value_hash(raw), prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
            except Exception as error:
                row.update(status='ERROR', error_type=type(error).__name__, error=str(error)[:500],
                           usage='UNKNOWN', provider_completion='UNKNOWN')
                write_json(out/f"question-{row['question_id']}-error.json", {
                    'provider_response': backend.raw_response, 'error_type': type(error).__name__,
                    'error': str(error)[:500]}, exclusive=True)
            row['seconds'] = time.monotonic()-started
            row['finished_at'] = now()
            summary = summarize(rows, contract)
            write_json(out/'RESULTS.json', summary)
            print(json.dumps({'public_model_question': row['question_id'], 'status': row['status'],
                              'seconds': row['seconds']}, ensure_ascii=False), flush=True)
    finally:
        summary = summarize(rows, contract)
        write_json(out/'RESULTS.json', summary)
    return summary


class RecordedModelBackend(ServiceOpenAIBackend):
    def _choice(self, data):
        self.raw_response = data
        return super()._choice(data)


def checked_identity(value):
    names = ('model_name', 'model_revision', 'model_sha256', 'server_commit', 'server_binary_sha256')
    if not isinstance(value, dict) or any(not isinstance(value.get(name), str) or not value[name] for name in names):
        raise ValueError('Frozen model and provider identity required')
    if any(not re.fullmatch('[0-9a-f]{64}', value[name]) for name in ('model_sha256', 'server_binary_sha256')):
        raise ValueError('Model and provider binary require full SHA256 values')
    return dict(value)


def read_protocol(path):
    protocol = json.loads(Path(path).read_text())
    expected = protocol.pop('sha256')
    if value_hash(protocol) != expected or protocol.get('schema_version') != 1 or protocol.get('kind') != 'PUBLIC_MODEL_SUBSET':
        raise ValueError('Frozen public model protocol changed')
    protocol['sha256'] = expected
    return protocol


def question_prompt(question, prefix):
    options = '\n'.join(f'{chr(65+index)}) {text}' for index, text in enumerate(question['options']))
    return prefix + question['question'] + '\n\n' + options


def final_answer(text, option_count):
    lines = (text or '').strip().splitlines()
    match = re.fullmatch(r'Answer: ([A-J])', lines[-1].strip()) if lines else None
    return match.group(1) if match and ord(match.group(1))-65 < option_count else None


def summarize(rows, contract):
    counts = dict(Counter(row['status'] for row in rows))
    usage = {}
    for name in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        values = [row.get('usage', {}).get(name) if isinstance(row.get('usage'), dict) else None for row in rows]
        present = [value for value in values if type(value) is int and value >= 0]
        usage[name] = {'known_sum': sum(present), 'reported_questions': len(present),
                       'missing_questions': len(rows)-len(present)}
    return {'kind': 'PUBLIC_MODEL_SUBSET', 'benchmark': 'MMLU-Pro', 'contract': contract,
        'counts': counts, 'planned': len(rows), 'complete': not counts.get('NOT_RUN'),
        'accuracy_all_planned': counts.get('PASS', 0)/len(rows), 'rows': rows, 'usage': usage,
        'api_cost_usd': 0, 'energy_cost': 'UNKNOWN', 'ranking_claim': False,
        'limits': ['32-question zero-shot subset, one attempt each; not full MMLU-Pro or AA methodology',
                   'Model-only evidence; no Agent tools, reference arm, non-inferiority claim, or official ranking',
                   'Public-data pretraining contamination is unknown; timeouts and format failures remain in denominator']}


def now():
    return datetime.now(timezone.utc).isoformat()


def value_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value, exclusive=False):
    with Path(path).open('x' if exclusive else 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    Path(path).chmod(0o600)


if __name__ == '__main__':
    main()
