"""Compare duplicate reference shapes and real parsers; no scoring or judge."""
from pathlib import Path
import hashlib
import json
import runpy
from urllib.request import urlopen

import yaml

BASE = Path('/workspace/scratch/c0f3ec78c621/validation/audit-20261117')
COHORT = BASE / 'itbench-aa-r2-transport-completed'
OLD = BASE / 'final-source-91dd87c/scripts/grade_itbench_aa.py'
NEW = Path('/workspace/scratch/2a488f6eabf5/LocalPilot-polish-final-20261116/scripts/grade_itbench_aa.py')
OUTPUT = BASE / 'itbench-reference-adapter-probe.json'
OLD_SHA = '26ca645748a5272409bbc74f92e366a7d2b95138a86e92fec2d94db86733f8f0'
NEW_SHA = '4cd3f405f7a4d1c05edb6bf5d5530657c69de6b934bf59c2cdf01df7e2f20b76'
REFERENCE_SHA = '6073f64edc4e011fbf4d4677ca04f5b4ff84d2041d1786c0f54b3e3e7392a745'
FIELDS = ('id', 'name', 'namespace', 'kind', 'filter')


def main():
    digest = lambda data: hashlib.sha256(data).hexdigest()
    assert digest(OLD.read_bytes()) == OLD_SHA
    assert digest(NEW.read_bytes()) == NEW_SHA
    old = runpy.run_path(str(OLD), run_name='old_reference_parser_probe')
    new = runpy.run_path(str(NEW), run_name='new_reference_parser_probe')
    summary = json.loads((COHORT / 'RUN_SUMMARY.json').read_text())
    receipts = [json.loads((COHORT / f'case-{i:03d}/case-result.json').read_text())
                for i in range(1, 41)]
    assert summary['planned'] == 40 and summary['cases'] == receipts
    assert all(row.get('owned_core_stopped') is True for row in receipts)
    assert all(row.get('task_status') not in {'running', 'queued', 'cancelling',
               'requires_approval', 'requires_human'} for row in receipts)
    assert not new['candidate_core_pids'](COHORT)
    assert not (COHORT / 'grading').exists()
    assert new['LABEL_SHA256'] == old['LABEL_SHA256'] == REFERENCE_SHA
    with urlopen(old['LABEL_URL'], timeout=90) as response:
        body = response.read()
    assert digest(body) == REFERENCE_SHA
    duplicates = []
    for line in body.splitlines():
        if not line.strip():
            continue
        value = yaml.safe_load(json.loads(line)['ground_truth_yaml'])
        value = value.get('spec', value)
        seen = {}
        for entity in value['groups']:
            entity_id = entity['id']
            if entity_id in seen:
                before = seen[entity_id]
                raw_equal = {field: (field in before, before.get(field)) ==
                             (field in entity, entity.get(field)) for field in FIELDS}
                left = {field: before[field] for field in FIELDS if field in before
                        and not (field == 'namespace' and before[field] is None)}
                right = {field: entity[field] for field in FIELDS if field in entity
                         and not (field == 'namespace' and entity[field] is None)}
                normalized_equal = {field: (field in left, left.get(field)) ==
                                    (field in right, right.get(field)) for field in FIELDS}
                root_equal = before.get('root_cause', False) == entity.get('root_cause', False)
                duplicates.append({'raw_identity_fields_equal': raw_equal,
                                   'normalized_identity_fields_equal': normalized_equal,
                                   'defaulted_root_flags_equal': root_equal,
                                   'all_allowed_fields_equal': all(normalized_equal.values()) and root_equal})
            else:
                seen[entity_id] = entity
    result = {'scope': 'Only field-equality booleans, counts and source hashes; no reference values or candidate answers.',
              'old_grader_sha256': OLD_SHA, 'new_grader_sha256': NEW_SHA,
              'reference_sha256': REFERENCE_SHA, 'reference_bytes': len(body),
              'candidate_receipts_verified': 40, 'candidate_active_core_count': 0,
              'duplicate_rows': len(duplicates), 'duplicate_comparisons': duplicates,
              'conflicting_duplicate_count': sum(not row['all_allowed_fields_equal'] for row in duplicates),
              'normalization_prompt_unchanged': new['NORMALIZATION_PROMPT'] == old['NORMALIZATION_PROMPT'],
              'judge_settings_unchanged': all(new[key] == old[key] for key in
                                             ('JUDGE_MODEL', 'JUDGE_REASONING', 'JUDGE_MAX_TOKENS'))}
    for name, parser in (('old', old), ('adapted', new)):
        try:
            labels = parser['parse_labels'](body)
            result[name + '_parse'] = 'PASS'
            result[name + '_parsed_cases'] = len(labels)
            result[name + '_scenario_set_matches'] = set(labels) == set(parser['PUBLIC_SCENARIOS'])
            result[name + '_identity_rows'] = sum(len(truth.judge_input['groups']) for truth in labels.values())
            result[name + '_judge_identity_has_no_root_flags'] = all(
                'root_cause' not in entity for truth in labels.values() for entity in truth.judge_input['groups'])
        except Exception as error:
            result[name + '_parse'] = type(error).__name__
    result.update(grading_directory_exists=(COHORT / 'grading').exists(),
                  judge_backend_constructed=False, external_model_api_calls=0,
                  raw_reference_written=False, candidate_answers_read=False)
    assert result['grading_directory_exists'] is False
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'probe_error_type': type(error).__name__,
                          'reference_or_candidate_values_emitted': False}))
        raise SystemExit(2)
