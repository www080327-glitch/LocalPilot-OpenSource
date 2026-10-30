"""Explicit restore-only rebasing of private exclusion paths, never authority.

The old configuration digest must match exactly after reversing only the three
host-recorded private path replacements. Models, tools, policies, UNKNOWN and
receipt history are not migrated by this rule.
"""
from copy import deepcopy
from pathlib import Path
from agent.persistence import configuration, digest, dumps


def path_migration(spec):
    if spec is None:
        return None
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
