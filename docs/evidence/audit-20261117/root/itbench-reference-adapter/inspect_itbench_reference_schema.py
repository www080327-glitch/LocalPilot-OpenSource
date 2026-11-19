"""Read-only schema diagnosis: fixed public bytes stay in memory; no judge or key."""
from collections import Counter
from pathlib import Path
import hashlib
import json
import runpy
from urllib.request import urlopen

import yaml

BASE = Path('/workspace/scratch/c0f3ec78c621/validation/audit-20261117')
OUTPUT = BASE / 'itbench-reference-schema-probe.json'
COHORT = BASE / 'itbench-aa-r2-transport-completed'
GRADER = BASE / 'final-source-91dd87c/scripts/grade_itbench_aa.py'
GRADER_SHA256 = '26ca645748a5272409bbc74f92e366a7d2b95138a86e92fec2d94db86733f8f0'
REFERENCE_SHA256 = '6073f64edc4e011fbf4d4677ca04f5b4ff84d2041d1786c0f54b3e3e7392a745'
KNOWN_ERRORS = {
    'Ground truth must be an object',
    'Ground truth must contain entity groups',
    'Invalid or duplicate ground-truth entity',
    'Entity identifying metadata must be text',
    'Entity filters must be a list of text',
    'Aliases must reference existing entity IDs',
    'A scoring case must identify at least one root-cause group',
}


def main():
    assert hashlib.sha256(GRADER.read_bytes()).hexdigest() == GRADER_SHA256
    grading = runpy.run_path(str(GRADER), run_name='reference_schema_probe_grader')
    summary = json.loads((COHORT / 'RUN_SUMMARY.json').read_text())
    receipts = [json.loads((COHORT / f'case-{i:03d}/case-result.json').read_text())
                for i in range(1, 41)]
    assert summary['planned'] == 40 and summary['cases'] == receipts
    assert all(row.get('owned_core_stopped') is True for row in receipts)
    assert all(row.get('task_status') not in {'running', 'queued', 'cancelling',
               'requires_approval', 'requires_human'} for row in receipts)
    assert not grading['candidate_core_pids'](COHORT)
    assert not (COHORT / 'grading').exists()
    assert grading['LABEL_SHA256'] == REFERENCE_SHA256
    with urlopen(grading['LABEL_URL'], timeout=90) as response:
        body = response.read()
    actual_digest = hashlib.sha256(body).hexdigest()
    assert actual_digest == REFERENCE_SHA256
    rows = [json.loads(line) for line in body.splitlines() if line.strip()]
    result = {
        'scope': 'Structure and types only; no entity IDs, names, root values, reference text, candidate answers, or judge requests are emitted or saved.',
        'grader_sha256': GRADER_SHA256,
        'reference_sha256': actual_digest,
        'reference_bytes': len(body),
        'candidate_receipts_verified': 40,
        'candidate_active_core_count': 0,
        'grading_directory_before': False,
        'jsonl_row_count': len(rows),
        'outer_rows_matching_public_sre': sum(row.get('source_split') == 'public'
                                            and row.get('category') == 'sre' for row in rows),
        'scenario_set_matches_frozen_40': {row.get('scenario_id') for row in rows}
                                        == set(grading['PUBLIC_SCENARIOS']),
        'duplicate_scenario_count': len(rows) - len({row.get('scenario_id') for row in rows}),
    }
    counts = {name: Counter() for name in (
        'yaml_document_types', 'effective_document_types', 'group_container_types',
        'entity_types', 'alias_container_types', 'alias_entry_types', 'alias_member_types',
        'filter_member_types', 'strict_ground_truth_errors')}
    fields = {name: Counter() for name in ('id', 'root_cause', 'name', 'namespace', 'kind', 'filter')}
    passed = 0
    empty_ids = duplicate_ids = unknown_alias_members = spec_wrappers = 0
    for row in rows:
        try:
            value = yaml.safe_load(row['ground_truth_yaml'])
        except yaml.YAMLError:
            counts['strict_ground_truth_errors']['YAMLError'] += 1
            continue
        counts['yaml_document_types'][type(value).__name__] += 1
        spec_wrappers += isinstance(value, dict) and 'spec' in value
        effective = value.get('spec', value) if isinstance(value, dict) else value
        counts['effective_document_types'][type(effective).__name__] += 1
        if isinstance(effective, dict):
            groups = effective.get('groups')
            counts['group_container_types'][type(groups).__name__] += 1
            ids = []
            if isinstance(groups, list):
                for entity in groups:
                    counts['entity_types'][type(entity).__name__] += 1
                    if not isinstance(entity, dict):
                        continue
                    for name in fields:
                        fields[name]['missing' if name not in entity else type(entity[name]).__name__] += 1
                    if isinstance(entity.get('id'), str):
                        ids.append(entity['id'])
                        empty_ids += not entity['id']
                    if isinstance(entity.get('filter'), list):
                        counts['filter_member_types'].update(type(item).__name__ for item in entity['filter'])
            duplicate_ids += len(ids) - len(set(ids))
            aliases = effective.get('aliases', [])
            counts['alias_container_types'][type(aliases).__name__] += 1
            if isinstance(aliases, list):
                for alias in aliases:
                    counts['alias_entry_types'][type(alias).__name__] += 1
                    if isinstance(alias, list):
                        counts['alias_member_types'].update(type(item).__name__ for item in alias)
                        unknown_alias_members += sum(isinstance(item, str) and item not in ids for item in alias)
        try:
            grading['ground_truth'](value)
            passed += 1
        except Exception as error:
            category = str(error) if type(error) is ValueError and str(error) in KNOWN_ERRORS else type(error).__name__
            counts['strict_ground_truth_errors'][category] += 1
    result.update({name: dict(counter) for name, counter in counts.items()})
    result.update(entity_field_types={name: dict(counter) for name, counter in fields.items()},
                  strict_ground_truth_cases_passed=passed, spec_wrapper_cases=spec_wrappers,
                  empty_string_id_count=empty_ids, duplicate_id_count=duplicate_ids,
                  unknown_alias_member_count=unknown_alias_members)
    try:
        grading['parse_labels'](body)
        result['strict_parse_labels'] = 'PASS'
    except Exception as error:
        result['strict_parse_labels'] = type(error).__name__
    result.update(grading_directory_after=(COHORT / 'grading').exists(),
                  judge_backend_constructed=False, external_model_api_calls=0,
                  raw_reference_written=False, candidate_answers_read=False)
    assert result['grading_directory_after'] is False
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
