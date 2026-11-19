"""Incremental canonical sequences inside the existing SQLite checkpoint transaction."""
from copy import deepcopy
from dataclasses import dataclass
import json


class JournalList(list):
    """Canonical entries are immutable after insertion; structural edits mark a suffix."""
    def __init__(self, values=()):
        super().__init__(values)
        self.changed_from = 0

    def changed(self, position):
        self.changed_from = position if self.changed_from is None else min(position, self.changed_from)

    def append(self, value):
        self.changed(len(self)); super().append(value)

    def extend(self, values):
        self.changed(len(self)); super().extend(values)

    def insert(self, position, value):
        self.changed(max(0, min(len(self), position if position >= 0 else len(self) + position)))
        super().insert(position, value)

    def __setitem__(self, key, value):
        if isinstance(key, slice):
            selected = range(*key.indices(len(self)))
            position = min(selected[0], selected[-1]) if selected else key.indices(len(self))[0]
        else:
            position = key % len(self)
        self.changed(position)
        super().__setitem__(key, value)

    def __delitem__(self, key):
        if isinstance(key, slice):
            selected = range(*key.indices(len(self)))
            if not selected:
                return
            position = min(selected[0], selected[-1])
        else:
            position = key % len(self)
        self.changed(position); super().__delitem__(key)

    def pop(self, position=-1):
        value = self[position]; del self[position]; return value

    def clear(self):
        del self[:]

    def remove(self, value):
        del self[self.index(value)]

    def __iadd__(self, values):
        self.extend(values); return self

    def __imul__(self, count):
        self.changed(0); super().__imul__(count); return self

    def reverse(self):
        self.changed(0); super().reverse()

    def sort(self, **options):
        self.changed(0); super().sort(**options)

    def __deepcopy__(self, memo):
        return deepcopy(list(self), memo)


class JournalMap(dict):
    def __init__(self, values=()):
        super().__init__(values)
        self.order = list(self)
        self.positions = {key: index for index, key in enumerate(self.order)}
        self.changed_from = 0

    def __setitem__(self, key, value):
        if key not in self:
            self.positions[key] = len(self.order); self.order.append(key)
        position = self.positions[key]
        self.changed_from = position if self.changed_from is None else min(position, self.changed_from)
        super().__setitem__(key, value)

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]

    def __delitem__(self, key):
        position = self.positions[key]
        super().__delitem__(key)
        self.order = list(self)
        self.positions = {key: index for index, key in enumerate(self.order)}
        self.changed_from = position if self.changed_from is None else min(position, self.changed_from)

    def pop(self, key, *default):
        if key not in self:
            if default: return default[0]
            raise KeyError(key)
        value = self[key]; del self[key]; return value

    def clear(self):
        super().clear(); self.order.clear(); self.positions.clear(); self.changed_from = 0

    def update(self, values=(), **kwargs):
        for key, value in dict(values, **kwargs).items():
            self[key] = value

    def __deepcopy__(self, memo):
        return deepcopy(dict(self), memo)


@dataclass(frozen=True)
class BlockReference:
    stream: str
    kind: str
    count: int
    head: str
    bytes: int


class CheckpointBatch:
    def __init__(self, store, session_id):
        self.store, self.session_id = store, session_id
        self.cache = store._block_cache.setdefault(session_id, {})
        self.pending = {}

    def sequence(self, owner, name, encode, path):
        value = owner[name] if isinstance(owner, dict) else getattr(owner, name)
        if not isinstance(value, JournalList):
            value = JournalList(value)
            if isinstance(owner, dict): owner[name] = value
            else: setattr(owner, name, value)
        return self._capture(value, encode, path, 'list')

    def mapping(self, owner, name, path):
        from .persistence import pack
        value = getattr(owner, name)
        if not isinstance(value, JournalMap):
            value = JournalMap(value); setattr(owner, name, value)
        return self._capture(value, lambda pair: [pack(pair[0]), pack(pair[1])], path, 'map')

    def _capture(self, source, encode, path, kind):
        from .persistence import digest, dumps
        stream = dumps(path)
        old = self.cache.get(stream)
        start = (min(len(source), old['count'], source.changed_from if source.changed_from is not None else len(source))
                 if old and old['source'] is source else 0)
        if start == 0:
            head, size = digest(''), 0
        elif start == old['count']:
            head, size = old['head'], old['bytes']
        else:
            head, size = self.store.connection.execute(
                'SELECT chain,bytes FROM checkpoint_blocks WHERE session_id=? AND stream=? AND position=?',
                (self.session_id, stream, start - 1)).fetchone()
        entries = ((key, source[key]) for key in source.order[start:]) if kind == 'map' else iter(source[start:])
        rows = []
        for position, value in enumerate(entries, start):
            raw = dumps(encode(value)); checksum = digest(raw)
            head = digest(dumps([head, position, checksum])); size += len(raw.encode())
            rows.append((self.session_id, stream, position, raw, checksum, head, size))
        ref = BlockReference(stream, kind, len(source), head, size)
        self.pending[stream] = {'source': source, 'count': len(source), 'head': head, 'bytes': size,
                                'start': start, 'rows': rows, 'reference': ref}
        return ref

    def envelope(self, payload):
        from dataclasses import asdict
        leaves = []
        def visit(value, path):
            if isinstance(value, BlockReference):
                leaves.append({'path': path, **asdict(value)})
                return None
            if isinstance(value, dict): return {key: visit(item, path + [key]) for key, item in value.items()}
            if isinstance(value, list): return [visit(item, path + [index]) for index, item in enumerate(value)]
            return value
        result = visit(payload, [])
        result['_block_checkpoint'] = {'version': 1, 'leaves': leaves}
        return result

    def write(self):
        db = self.store.connection
        for stream in self.cache.keys() - self.pending.keys():
            db.execute('DELETE FROM checkpoint_blocks WHERE session_id=? AND stream=?', (self.session_id, stream))
        for stream, data in self.pending.items():
            if data['rows'] or self.cache.get(stream, {}).get('count') != data['count']:
                db.execute('DELETE FROM checkpoint_blocks WHERE session_id=? AND stream=? AND position>=?',
                           (self.session_id, stream, data['start']))
                db.executemany('INSERT INTO checkpoint_blocks VALUES(?,?,?,?,?,?,?)', data['rows'])
        db.execute('PRAGMA user_version=4')

    def committed(self):
        for stream in self.cache.keys() - self.pending.keys():
            del self.cache[stream]
        for stream, data in self.pending.items():
            data['source'].changed_from = None
            self.cache[stream] = {key: data[key] for key in ('source', 'count', 'head', 'bytes')}


def materialize(db, session_id, payload):
    from .persistence import PersistenceError, digest, dumps, pack, unpack
    marker = payload.pop('_block_checkpoint', None)
    if marker is None:
        return payload
    if marker.get('version') != 1:
        raise PersistenceError('Unsupported checkpoint block manifest')
    restored = {}
    for reference in marker['leaves']:
        stream = reference['stream']
        if stream not in restored:
            values, head, size = [], digest(''), 0
            for position, raw, checksum, chain, cumulative in db.execute(
                    'SELECT position,payload,sha256,chain,bytes FROM checkpoint_blocks '
                    'WHERE session_id=? AND stream=? ORDER BY position', (session_id, stream)):
                head = digest(dumps([head, position, checksum])); size += len(raw.encode())
                if position != len(values) or digest(raw) != checksum or head != chain or size != cumulative:
                    raise PersistenceError('Checkpoint block integrity mismatch')
                values.append(json.loads(raw))
            if (len(values), head, size) != (reference['count'], reference['head'], reference['bytes']):
                raise PersistenceError('Checkpoint block manifest mismatch')
            if reference['kind'] == 'map':
                values = pack({unpack(key): unpack(value) for key, value in values})
            elif reference['kind'] != 'list':
                raise PersistenceError('Unsupported checkpoint block kind')
            restored[stream] = values
        target = payload
        for key in reference['path'][:-1]: target = target[key]
        key = reference['path'][-1]
        if target[key] is not None:
            raise PersistenceError('Checkpoint block target is not a host placeholder')
        target[key] = restored[stream]
    return payload
