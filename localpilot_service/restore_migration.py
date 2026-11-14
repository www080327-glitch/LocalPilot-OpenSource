"""Explicit restore of private paths and the reviewed pre-catalog Skill schema.

Full configuration hashes still match after reversing the declared changes.
Historical checkpoints, tool receipts and UNKNOWN effects are never rewritten.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
from agent.persistence import configuration, digest, dumps
from localpilot_plugins.security import digest as skill_digest


def path_migration(spec):
    if spec is None:
        return None
    reverse = private_path_replacements(spec)

    def matches(runtime, payload):
        old = deepcopy(configuration(runtime))
        scope = old.get('file_scope_policy')
        if not scope or not isinstance(scope.get('private_roots'), (tuple, list)):
            return False
        roots = scope['private_roots']
        changed = any(root in reverse for root in roots)
        scope['private_roots'] = tuple(reverse.get(root, root) for root in roots)
        return changed and digest(dumps(old)) == payload['configuration']
    return matches


def private_path_replacements(spec):
    if not isinstance(spec, dict) or set(spec) != {'version', 'private_roots'} or spec['version'] != 1:
        raise ValueError('Unsupported restore path migration')
    pairs = spec['private_roots']
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 3:
        raise ValueError('Restore migration requires bounded explicit root pairs')
    reverse = {}
    for pair in pairs:
        if (not isinstance(pair, dict) or set(pair) != {'source', 'destination'}
                or any(not isinstance(pair[k], str) or not Path(pair[k]).is_absolute() for k in pair)):
            raise ValueError('Invalid restore private root identity')
        old, new = (str(Path(pair[k]).resolve()) for k in ('source', 'destination'))
        if old == new or new in reverse:
            raise ValueError('Restore roots must be distinct and unambiguous')
        reverse[new] = old

    return reverse


def skill_catalog_migration(spec, path_spec=None):
    if spec is None:
        return None
    if (not isinstance(spec,dict) or set(spec)!={'version','sessions'} or spec['version']!=1
            or not isinstance(spec['sessions'],list) or not spec['sessions']):
        raise ValueError('Explicit Skill catalog migration sessions required')
    approved={}
    for row in spec['sessions']:
        if (not isinstance(row,dict) or set(row)!={'session_id','configuration_sha256','bundle_sha256'}
                or not isinstance(row['session_id'],str) or row['session_id'] in approved
                or not isinstance(row['configuration_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',row['configuration_sha256'])
                or not isinstance(row['bundle_sha256'],dict) or not row['bundle_sha256']
                or any(not isinstance(k,str) or not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) for k,v in row['bundle_sha256'].items())):
            raise ValueError('Invalid pinned Skill catalog migration record')
        approved[row['session_id']]=row
    reverse=private_path_replacements(path_spec) if path_spec is not None else {}

    def matches(runtime,payload):
        row=approved.get(payload['session']['id'])
        if not row or row['configuration_sha256']!=payload['configuration']:
            return False
        if getattr(runtime,'_selected_skill_bundle_digests',{})!=row['bundle_sha256']:
            return False
        prior=deepcopy(configuration(runtime))
        schemas=[s for s in prior['schemas'] if s['function']['name']=='load_skill']
        if len(schemas)!=1:
            return False
        schemas[0]['function']['description']='Load a host-selected reviewed Skill as user guidance; this grants no tool permissions.'
        if reverse:
            scope=prior.get('file_scope_policy')
            if not scope:return False
            scope['private_roots']=tuple(reverse.get(p,p) for p in scope['private_roots'])
        if digest(dumps(prior))!=payload['configuration']:
            return False
        pending=[payload['runtime']]
        while pending:
            snapshot=pending.pop();pending.extend(snapshot['children'].values())
            for receipt in snapshot['history']:
                if receipt['name']=='load_skill' and receipt['payload'].get('ok'):
                    skill=json.loads(receipt['arguments'])['skill']
                    if skill_digest(receipt['payload']['result'])!=runtime._selected_skill_legacy_bundle_digests.get(skill):
                        return False
        return True
    matches.checkpoint_point='host_restore_skill_catalog_migrated'
    return matches
