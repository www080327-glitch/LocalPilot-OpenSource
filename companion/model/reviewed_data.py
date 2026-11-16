"""Load the same reviewed dataset contract for training and held-out evaluation."""
import hashlib
import json
from pathlib import Path

from companion.observers.files import read_regular_file


def load_dataset(directory, *, batch_size=1, require_test=False):
    directory = Path(directory)
    raw, _ = read_regular_file(directory / 'manifest.json', 8 * 1024 * 1024)
    manifest = json.loads(raw)
    if (not isinstance(manifest, dict) or manifest.get('schema') != 'companion-reviewed-training-v1'
            or not isinstance(manifest.get('sha256'), dict) or not isinstance(manifest.get('counts'), dict)):
        raise ValueError('Use a Companion reviewed training export')
    if require_test and not manifest['counts'].get('test'):
        raise ValueError('Final evaluation requires a held-out test split; export with --test-fraction')
    names = ['train', 'valid'] + (['test'] if manifest['counts'].get('test') else [])
    datasets = {}
    for split in names:
        filename = split + '.jsonl'
        content, _ = read_regular_file(directory / filename, 64 * 1024 * 1024)
        if hashlib.sha256(content).hexdigest() != manifest['sha256'].get(filename):
            raise ValueError('Dataset hash no longer matches the reviewed export: ' + filename)
        rows = [json.loads(line) for line in content.decode('utf-8').splitlines() if line.strip()]
        if not rows or len(rows) != manifest['counts'].get(split) or len(rows) < (1 if split == 'test' else batch_size):
            raise ValueError('Each reviewed split must contain at least one complete batch')
        for row in rows:
            messages = row.get('messages') if isinstance(row, dict) else None
            if (not isinstance(messages, list) or len(messages) != 3
                    or [message.get('role') for message in messages if isinstance(message, dict)] != ['system', 'user', 'assistant']
                    or any(not isinstance(message.get('content'), str) or not message['content'].strip() for message in messages)):
                raise ValueError('Training rows require complete system/user/reviewed-answer messages')
        datasets[split] = rows
    if require_test:
        _independent_groups(manifest, datasets)
    return manifest, datasets, hashlib.sha256(raw).hexdigest()


def _independent_groups(manifest, datasets):
    if (manifest.get('label_origin') != 'explicit_user_review' or not isinstance(manifest.get('samples'), list)
            or type(manifest.get('source_group_count')) is not int or manifest['source_group_count'] < 3):
        raise ValueError('Held-out evaluation requires reviewed source-group provenance')
    ownership, counts = {}, dict.fromkeys(datasets, 0)
    for sample in manifest['samples']:
        if (not isinstance(sample, dict) or sample.get('split') not in datasets
                or not isinstance(sample.get('groups'), list) or not sample['groups']
                or any(not isinstance(group, str) or not group for group in sample['groups'])):
            raise ValueError('Invalid reviewed source-group provenance')
        split = sample['split']
        counts[split] += 1
        for group in sample['groups']:
            if group in ownership and ownership[group] != split:
                raise ValueError('A source/scenario group crosses the training, validation or test boundary')
            ownership[group] = split
    if counts != {split: len(rows) for split, rows in datasets.items()}:
        raise ValueError('Source-group provenance does not match the exported examples')
