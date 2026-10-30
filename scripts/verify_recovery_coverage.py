"""Reconcile initial inventory against the authenticated combined snapshot.

Transient process records, consistent SQLite sidecars and ownership mutexes are
accounted as metadata, never silently counted as restored user files.
"""
import argparse
import json
from pathlib import Path
import sqlite3
from collections import Counter
from localpilot_encrypted_backup import private_json


def verify(spec_path, combined, output):
    spec = json.loads(spec_path.read_text())
    receipt = json.loads((combined / 'combination-verification.json').read_text())
    if receipt['status'] != 'COMBINED_SNAPSHOT_VERIFIED':
        raise RuntimeError('Combined snapshot is not verified')
    overlay = sqlite3.connect((combined / 'recovery-overlay.sqlite3').as_uri() + '?mode=ro&immutable=1', uri=True)
    policy = sqlite3.connect(':memory:')
    policy.execute('CREATE TABLE records(source TEXT PRIMARY KEY,type TEXT,row TEXT)')
    for path in spec['authenticated_manifests']:
        for line in Path(path).open():
            row = json.loads(line)
            policy.execute('INSERT INTO records VALUES(?,?,?) ON CONFLICT(source) DO UPDATE SET type=excluded.type,row=excluded.row',
                           (row['source'], row['type'], json.dumps(row)))
    policy.commit()
    removed = {}
    for path in spec.get('reconciliations', []):
        data = json.loads(Path(path).read_text())
        for row in data.get('initial_missing_reconciled', data.get('tombstones', [])):
            if row.get('accepted_ephemeral_only') is True:
                removed[row['source']] = row['policy']
    counts = Counter()
    failures = []
    total = changed = roots_count = 0
    for item in spec['initial_inventories']:
        inventory = json.loads(Path(item['inventory']).read_text())
        roots = {row['id']: Path(row['path']) for row in inventory['roots']}
        roots_count += len(roots)
        for line in Path(item['files']).open():
            row = json.loads(line)
            source = roots[row['root']]
            if row['relative'] != '.':
                source = source / row['relative']
            name = str(source)
            total += 1
            found = overlay.execute('SELECT type,row FROM entries WHERE source=?', (name,)).fetchone()
            if found:
                record = json.loads(found[1])
                if found[0] == 'file':
                    counts['verified_regular_data'] += 1
                    if row.get('sha256') and row['sha256'] != record['sha256']:
                        changed += 1
                elif found[0] == 'symlink':
                    counts['verified_symlinks'] += 1
                else:
                    failures.append({'source': name, 'reason': 'original file became unexpected directory'})
                continue
            if name in removed:
                counts['explicit_owned_ephemeral_tombstones'] += 1
                continue
            record = policy.execute('SELECT type,row FROM records WHERE source=?', (name,)).fetchone()
            if record and record[0] == 'ownership_lock_metadata_only':
                counts['ownership_mutex_metadata'] += 1
                continue
            if record and record[0] == 'sqlite_sidecar_metadata_only':
                database = name.rsplit('-', 1)[0]
                main = overlay.execute('SELECT row FROM entries WHERE source=?', (database,)).fetchone()
                if main and json.loads(main[0]).get('sqlite_snapshot'):
                    counts['sidecars_replaced_by_consistent_main_snapshot'] += 1
                    continue
            if record and record[0] == 'special_file_metadata_only':
                counts['special_file_metadata'] += 1
                continue
            failures.append({'source': name, 'reason': 'unaccounted original inventory entry'})
    result = {'status': 'COVERAGE_VERIFIED' if not failures else 'COVERAGE_FAILED',
              'original_roots': roots_count, 'inventory_entries': total, 'accounted_entries': sum(counts.values()),
              'counts': dict(counts), 'newer_captured_versions_differing_initial_sha256': changed,
              'unresolved_entries': len(failures), 'failures': failures,
              'source_data_overwritten': False, 'services_started': False,
              'scope': 'Specified initial inventories; later user activity still requires a final incremental before cleanup'}
    private_json(output, result)
    overlay.close()
    policy.close()
    print(json.dumps({key: value for key, value in result.items() if key != 'failures'}, indent=2))
    return 0 if not failures else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--combined', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(verify(args.spec.resolve(strict=True), args.combined.resolve(strict=True), args.out.resolve()))
