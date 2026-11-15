"""Admission quota for explicitly owned, rebuildable provider caches.

No directory discovery or file deletion. Provider LRU owns entry eviction and
live KV references; persistent reservations also cover inactive cache roots.
"""
from pathlib import Path
import os

from .cli import lock, private_dir, save
from .security import private_json

LIMIT_BYTES = 50 * 1024**3


def budget_home():
    return private_dir(os.environ.get('LOCALPILOT_CACHE_BUDGET_HOME',
        str(Path.home()/'.local/share/localpilot-owned-cache-budget')))


def reserve(cache_root, maximum_bytes, *, home=None):
    root = private_dir(cache_root)
    if type(maximum_bytes) is not int or not 0 < maximum_bytes <= LIMIT_BYTES:
        raise ValueError('Owned cache reservation must be positive and at most 50 GiB')
    home = budget_home() if home is None else private_dir(home)
    with lock(home, 'cache-budget.lock'):
        path = home/'reservations.json'
        state = private_json(path) if path.exists() else {'version':1,'limit_bytes':LIMIT_BYTES,'entries':{}}
        if state.get('version') != 1 or state.get('limit_bytes') != LIMIT_BYTES:
            raise ValueError('Unsupported owned cache ledger')
        entries = {name:row for name,row in state['entries'].items() if Path(name).exists()}
        prior = entries.get(str(root))
        if prior and prior['maximum_bytes'] != maximum_bytes:
            raise ValueError('Existing cache reservation is immutable; review a separate cache root before changing capacity')
        entries[str(root)] = {'kind':'omlx_prefix_cache','maximum_bytes':maximum_bytes,
            'eviction':'provider_lru_with_live_reference_protection','user_data':False}
        total = sum(row['maximum_bytes'] for row in entries.values())
        if total > LIMIT_BYTES:
            raise ValueError('Owned rebuildable cache reservations exceed 50 GiB; no files were removed')
        save(path, {**state,'entries':entries})
    return {'maximum_bytes':maximum_bytes,'global_limit_bytes':LIMIT_BYTES,'reserved_bytes':total}


def status(*, home=None):
    home = budget_home() if home is None else private_dir(home)
    path = home/'reservations.json'
    state = private_json(path) if path.exists() else {'version':1,'limit_bytes':LIMIT_BYTES,'entries':{}}
    rows=[]
    for name, entry in state['entries'].items():
        root=Path(name)
        size=sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink()) if root.exists() else 0
        rows.append({'cache_root':name,**entry,'logical_file_bytes':size,
                     'within_reservation':size <= entry['maximum_bytes']})
    return {'limit_bytes':LIMIT_BYTES,'reserved_bytes':sum(x['maximum_bytes'] for x in rows),
        'entries':rows,'cleanup':'NO_DELETION_API','unknown_roots':'excluded',
        'excluded':['model_weights','shared_provider_caches','memory','tasks','receipts','credentials','APP','release_and_rollback_archives']}
