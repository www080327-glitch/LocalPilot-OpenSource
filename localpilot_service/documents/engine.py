"""Private content-addressed storage, durable parsing, FTS and citations.

Authorization belongs to each attachment and session, never to its shared blob.
No original bytes or source paths are copied into the Agent workspace.
"""
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from .model import Budgets, VERSION, PARSER_REVISION


class DocumentError(ValueError):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def digest_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def terms(text):
    return re.findall(r'[a-z0-9_]+|[\u3400-\u9fff]', text.casefold())


def vector(text):
    """Optional local hashed lexical vectors, explicitly not semantic embeddings."""
    values = [0.0] * 128
    for t in terms(text):
        values[int.from_bytes(hashlib.sha256(t.encode()).digest()[:2], 'big') % 128] += 1
    norm = math.sqrt(sum(v*v for v in values)) or 1
    return [v / norm for v in values]


class DocumentEngine:
    def __init__(self, root, budgets=None):
        self.root = Path(root).absolute()
        self.budgets = budgets or Budgets()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink() or self.root.stat().st_uid != os.getuid() or self.root.stat().st_mode & 0o077:
            raise DocumentError('document_store_must_be_private', 403)
        self.blobs = self.root / 'blobs'
        self.jobs = self.root / 'jobs'
        self.blobs.mkdir(exist_ok=True, mode=0o700)
        self.jobs.mkdir(exist_ok=True, mode=0o700)
        for p in (self.blobs, self.jobs):
            if p.is_symlink() or p.stat().st_mode & 0o077:
                raise DocumentError('document_store_must_be_private', 403)
        self.path = self.root / 'documents.sqlite3'
        if self.path.is_symlink():
            raise DocumentError('document_store_symlink', 403)
        self.lock = threading.RLock()
        self.slots = threading.BoundedSemaphore(1)
        self.cancelled = set()
        self.closed = False
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS attachments(
              id TEXT PRIMARY KEY, subject TEXT, session TEXT, name TEXT, size INTEGER,
              sha256 TEXT, source TEXT, origin TEXT, declared_mime TEXT,
              active INTEGER, status TEXT, created REAL, expires REAL, cache TEXT);
            CREATE INDEX IF NOT EXISTS attachment_owner ON attachments(subject,session,active);
            CREATE TABLE IF NOT EXISTS parses(
              cache TEXT PRIMARY KEY, sha256 TEXT, name TEXT, status TEXT, cursor INTEGER DEFAULT 0,
              format TEXT, mime TEXT, reason TEXT, seconds REAL DEFAULT 0, peak_rss INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS nodes(
              cache TEXT, seq INTEGER, kind TEXT, text TEXT, anchor TEXT, properties TEXT,
              sha256 TEXT, PRIMARY KEY(cache,seq));
            CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(cache UNINDEXED, seq UNINDEXED, text, tokenize='unicode61');
            CREATE TABLE IF NOT EXISTS bindings(session TEXT PRIMARY KEY, subject TEXT);
            CREATE TABLE IF NOT EXISTS vision_grants(
              digest TEXT PRIMARY KEY, subject TEXT, session TEXT, expires REAL, consumed INTEGER DEFAULT 0);
        ''')
        self.db.commit()
        self.path.chmod(0o600)
        with self.db:
            attachment_columns={r[1] for r in self.db.execute('PRAGMA table_info(attachments)')}
            for name in ('cloud_status','vision_status'):
                if name not in attachment_columns:
                    self.db.execute('ALTER TABLE attachments ADD COLUMN '+name+" TEXT DEFAULT 'not_submitted'")
            if 'cloud_confirmed' not in attachment_columns:
                self.db.execute('ALTER TABLE attachments ADD COLUMN cloud_confirmed INTEGER DEFAULT 0')
            columns={r[1] for r in self.db.execute('PRAGMA table_info(parses)')}
            for name in ('index_seconds','parser_seconds'):
                if name not in columns:
                    self.db.execute('ALTER TABLE parses ADD COLUMN '+name+' REAL DEFAULT 0')
            self.db.execute("UPDATE parses SET status='partial',reason='process_restart_checkpoint_available' WHERE status='processing'")

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.cancelled.update(r[0] for r in self.db.execute('SELECT id FROM attachments'))
        if not self.slots.acquire(timeout=10):
            raise DocumentError('parser_shutdown_pending', 503)
        try:
            with self.lock:
                self.closed = True
                self.db.close()
        finally:
            self.slots.release()

    def _size(self):
        return sum(p.stat().st_size for base in (self.blobs, self.jobs) for p in base.iterdir() if p.is_file()) + sum(p.stat().st_size for p in self.root.glob('documents.sqlite3*'))

    def _resources(self, extra=0):
        if self._size() + extra > self.budgets.storage_bytes or shutil.disk_usage(self.root).free < self.budgets.free_disk_bytes + extra:
            raise DocumentError('document_disk_budget', 413)

    @contextmanager
    def _query_budget(self):
        deadline = time.monotonic() + self.budgets.search_seconds
        self.db.set_progress_handler(lambda: time.monotonic() > deadline, 1000)
        try:
            yield deadline
        except sqlite3.OperationalError as e:
            if 'interrupted' in str(e):
                raise DocumentError('retrieval_time_budget', 413) from None
            raise
        finally:
            self.db.set_progress_handler(None, 0)

    def _source(self, raw):
        from localpilot_service.attachments import credential_source
        if not isinstance(raw, str) or not raw or len(raw) > 4096 or '\x00' in raw:
            raise DocumentError('invalid_source')
        p = Path(raw).expanduser()
        if not p.is_absolute() or any(x.is_symlink() for x in (p, *p.parents)):
            raise DocumentError('symbolic_or_relative_source_denied', 403)
        p = p.resolve(strict=True)
        if credential_source(p) or p.is_relative_to(self.root):
            raise DocumentError('protected_source_denied', 403)
        s = p.stat()
        if s.st_uid != os.getuid() or not (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)):
            raise DocumentError('source_owner_or_type_denied', 403)
        return p, s

    def ingest(self, subject, session, paths, *, origin='native_selection', origins=None, ttl_seconds=7*86400):
        if not isinstance(paths, list) or not paths or type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 365*86400:
            raise DocumentError('invalid_import')
        if origin not in {'native_selection', 'paste', 'drop', 'folder'}:
            raise DocumentError('invalid_origin')
        if origins is not None and (not isinstance(origins,list) or len(origins)!=len(paths) or any(o not in {'native_selection','paste','drop','folder'} for o in origins)):
            raise DocumentError('invalid_per_file_origins')
        started = time.monotonic()
        sources, skipped, total, metadata_bytes = [], [], 0, 0
        for selected_index, raw in enumerate(paths):
            p, s = self._source(raw)
            candidates = [(p, s)]
            if p.is_dir():
                candidates = []
                entries = 0
                pending = [p]
                while pending:
                    base = pending.pop()
                    with os.scandir(base) as children:
                        for child in children:
                            entries += 1
                            if entries > self.budgets.archive_entries or time.monotonic()-started > self.budgets.import_seconds:
                                raise DocumentError('folder_scan_budget', 413)
                            q = Path(child.path)
                            if child.name in {'.git','.venv','node_modules','__pycache__'}:
                                continue
                            try:
                                checked = self._source(str(q))
                                if stat.S_ISDIR(checked[1].st_mode):
                                    pending.append(q)
                                else:
                                    candidates.append(checked)
                            except (DocumentError, OSError):
                                skipped.append(str(q.relative_to(p)))
            for q, st in candidates:
                total += st.st_size
                metadata_bytes += len(str(q).encode()) + 1024
                if total > self.budgets.batch_bytes or metadata_bytes > 8*1024**2:
                    raise DocumentError('attachment_batch_budget', 413)
                sources.append((q, st, str(q.relative_to(p)) if p.is_dir() else q.name, origins[selected_index] if origins else origin))
        with self.lock:
            self._resources(total)
            copied = []
            try:
                for p, before, name, source_origin in sources:
                    if time.monotonic() - started > self.budgets.import_seconds:
                        raise DocumentError('attachment_import_time_budget', 413)
                    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    tmpfd, tmp = tempfile.mkstemp(dir=self.jobs)
                    h, count = hashlib.sha256(), 0
                    try:
                        with os.fdopen(fd, 'rb') as src, os.fdopen(tmpfd, 'wb') as out:
                            now = os.fstat(src.fileno())
                            if (now.st_dev, now.st_ino, now.st_size, now.st_mtime_ns) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
                                raise DocumentError('attachment_changed', 409)
                            while part := src.read(1024*1024):
                                count += len(part)
                                if count > before.st_size or time.monotonic() - started > self.budgets.import_seconds:
                                    raise DocumentError('attachment_changed_or_import_budget', 409)
                                h.update(part)
                                out.write(part)
                            after = os.fstat(src.fileno())
                            if count != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
                                raise DocumentError('attachment_changed', 409)
                            out.flush()
                            os.fsync(out.fileno())
                        sha = h.hexdigest()
                        blob = self.blobs / sha
                        if blob.exists():
                            if blob.is_symlink() or digest_file(blob) != sha:
                                raise DocumentError('blob_integrity_failure', 409)
                        else:
                            os.replace(tmp, blob)
                        copied.append((p, name, count, sha, source_origin))
                    finally:
                        Path(tmp).unlink(missing_ok=True)
                result = []
                with self.db:
                    self.db.execute('INSERT OR IGNORE INTO bindings VALUES(?,?)', (session, subject))
                    binding = self.db.execute('SELECT subject FROM bindings WHERE session=?', (session,)).fetchone()
                    if binding['subject'] != subject:
                        raise DocumentError('attachment_session_owner_denied', 403)
                    for p, name, size, sha, source_origin in copied:
                        ext = p.suffix.lower()
                        cache = hashlib.sha256((sha + ext + PARSER_REVISION + self.budgets.fingerprint()).encode()).hexdigest()
                        prior = self.db.execute('SELECT id FROM attachments WHERE subject=? AND session=? AND sha256=? AND name=? AND active=1 AND expires>?', (subject, session, sha, name, time.time())).fetchone()
                        if prior:
                            result.append(self.info(subject, session, prior['id']))
                            continue
                        aid = 'att_' + uuid.uuid4().hex
                        self.db.execute('INSERT OR IGNORE INTO parses(cache,sha256,name,status) VALUES(?,?,?,?)', (cache, sha, p.name, 'queued'))
                        self.db.execute('INSERT INTO attachments(id,subject,session,name,size,sha256,source,origin,declared_mime,active,status,created,expires,cache) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                        (aid, subject, session, name, size, sha, str(p), source_origin, mimetypes.guess_type(p.name)[0] or 'application/octet-stream',
                                         1, 'authorized', time.time(), time.time()+ttl_seconds, cache))
                        result.append(self.info(subject, session, aid))
                return {'version': VERSION, 'files': result, 'skipped': skipped, 'bytes': total,
                        'cloud_uploaded': False, 'parse_submitted': False, 'seconds': time.monotonic()-started}
            except BaseException:
                # Unreferenced blobs are bounded and reclaimed by explicit GC.
                raise

    def _get(self, subject, session, aid):
        if not isinstance(aid, str):
            raise DocumentError('invalid_attachment_id')
        r = self.db.execute('SELECT * FROM attachments WHERE id=? AND subject=? AND session=?', (aid, subject, session)).fetchone()
        if not r:
            raise DocumentError('attachment_not_found', 404)
        if not r['active'] or r['expires'] <= time.time():
            raise DocumentError('attachment_authorization_revoked_or_expired', 403)
        return r

    def info(self, subject, session, aid):
        with self.lock:
            r = self._get(subject, session, aid)
            parsed = dict(self.db.execute('SELECT * FROM parses WHERE cache=?', (r['cache'],)).fetchone())
            return {k: r[k] for k in ('id', 'name', 'size', 'sha256', 'origin', 'declared_mime', 'created', 'expires')} | {
                'version': VERSION, 'authorization': 'explicit_operator_session_selection', 'status': parsed['status'],
                'detected_format': parsed['format'], 'mime': parsed['mime'], 'parsed_nodes': parsed['cursor'],
                'reason': parsed['reason'], 'processing_seconds': parsed['seconds'], 'peak_worker_rss': parsed['peak_rss'],
                'index_seconds': parsed['index_seconds'], 'parser_seconds': parsed['parser_seconds'],
                'original_preserved': True, 'cloud_egress_status':r['cloud_status'], 'vision_submission_status':r['vision_status'],
                'cloud_uploaded': True if r['cloud_confirmed'] else False if r['cloud_status']=='not_submitted' else None,
                'trust': 'untrusted_document_data'}

    def list(self, subject, session, *, cursor=0, limit=100):
        if type(cursor) is not int or cursor<0 or type(limit) is not int or not 1<=limit<=1000:
            raise DocumentError('invalid_attachment_page')
        with self.lock:
            rows = self.db.execute('SELECT id FROM attachments WHERE subject=? AND session=? AND active=1 AND expires>? ORDER BY created,id LIMIT ? OFFSET ?', (subject, session, time.time(),limit,cursor)).fetchall()
            return [self.info(subject, session, r['id']) for r in rows]

    def list_page(self, subject, session, *, cursor=0, limit=100):
        with self.lock:
            files=self.list(subject,session,cursor=cursor,limit=limit)
            while len(files)>1 and len(json.dumps(files,ensure_ascii=False).encode())>self.budgets.preview_bytes:
                files.pop()
            count=self.db.execute('SELECT count(*) FROM attachments WHERE subject=? AND session=? AND active=1 AND expires>?',(subject,session,time.time())).fetchone()[0]
            return {'files':files,'count':count,'next_cursor':cursor+len(files),'has_more':cursor+len(files)<count}

    def revoke(self, subject, session, aid):
        with self.lock, self.db:
            # Repeated revocation is idempotent, and never revokes another owner.
            r = self.db.execute('SELECT id FROM attachments WHERE id=? AND subject=? AND session=?', (aid, subject, session)).fetchone()
            if not r:
                raise DocumentError('attachment_not_found', 404)
            self.cancelled.add(aid)
            self.db.execute('UPDATE attachments SET active=0,status=? WHERE id=?', ('revoked', aid))
            self.db.execute('DELETE FROM vision_grants WHERE subject=? AND session=?', (subject, session))
            return {'id': aid, 'status': 'revoked', 'new_reads_and_egress': 'denied', 'past_disclosures_retractable': False}

    def cancel(self, subject, session, aid):
        with self.lock:
            self._get(subject, session, aid)
            self.cancelled.add(aid)
        return {'id': aid, 'cancel_requested': True}

    def process(self, subject, session, aid, *, reindex=False):
        with self.lock:
            r = self._get(subject, session, aid)
            cached = self.db.execute('SELECT status FROM parses WHERE cache=?', (r['cache'],)).fetchone()['status']
            if cached in {'complete', 'unsupported'} and not reindex:
                return {**self.info(subject, session, aid), 'cache_hit': True}
        if not self.slots.acquire(blocking=False):
            raise DocumentError('parser_busy_retry', 429)
        started, peak, failure, proc = time.monotonic(), 0, None, None
        index_seconds, parser_seconds = 0.0, 0.0
        try:
            with self.lock, self.db:
                r = self._get(subject, session, aid)
                blob = self.blobs / r['sha256']
                if blob.is_symlink() or digest_file(blob) != r['sha256']:
                    raise DocumentError('original_integrity_failure', 409)
                if reindex:
                    self.db.execute('DELETE FROM nodes WHERE cache=?', (r['cache'],))
                    self.db.execute('DELETE FROM search WHERE cache=?', (r['cache'],))
                    self.db.execute('UPDATE parses SET cursor=0 WHERE cache=?', (r['cache'],))
                resume = self.db.execute('SELECT cursor FROM parses WHERE cache=?', (r['cache'],)).fetchone()['cursor']
                self.cancelled.discard(aid)
                self.db.execute('UPDATE parses SET status=?,reason=NULL WHERE cache=?', ('processing', r['cache']))
                self._resources(self.budgets.preview_bytes)
            fd, output = tempfile.mkstemp(dir=self.jobs)
            os.close(fd)
            completed, unsupported, committed = False, False, resume
            with open(output, 'wb') as out:
                # Environment is reduced; parser code never receives provider secrets.
                env = {k: v for k, v in os.environ.items() if k in {'PATH', 'SYSTEMROOT', 'LANG', 'LC_ALL', 'PYTHONPATH'}}
                proc = subprocess.Popen([sys.executable, '-m', 'localpilot_service.documents.worker', str(blob), r['name'], json.dumps(asdict(self.budgets))],
                                        stdout=out, stderr=subprocess.DEVNULL, env=env, cwd=str(Path(__file__).resolve().parents[2]))
                import psutil
                reader = psutil.Process(proc.pid)
                with open(output, 'rb') as stream:
                    pending, seq = b'', 0
                    while True:
                        alive = proc.poll() is None
                        if alive:
                            try:
                                peak = max(peak, reader.memory_info().rss)
                            except psutil.Error:
                                pass
                        with self.lock:
                            try:
                                self._get(subject, session, aid)
                            except DocumentError:
                                failure = 'authorization_revoked'
                            if aid in self.cancelled:
                                failure = failure or 'cancelled'
                        if time.monotonic()-started > self.budgets.worker_seconds:
                            failure = 'parser_time_budget'
                        if peak > self.budgets.worker_memory_bytes:
                            failure = 'parser_memory_budget'
                        if Path(output).stat().st_size > self.budgets.output_bytes:
                            failure = 'parser_output_budget'
                        if self._size() > self.budgets.storage_bytes:
                            failure = 'document_storage_budget'
                        if failure:
                            if alive:
                                proc.kill()
                            break
                        data = stream.read(65536)
                        pending += data
                        if len(pending) > 2*1024**2:
                            failure = 'parser_record_budget'
                            proc.kill()
                            break
                        while b'\n' in pending:
                            raw, pending = pending.split(b'\n', 1)
                            item = json.loads(raw)
                            if 'node' in item:
                                n = item['node']
                                seq += 1
                                if n['kind'] == 'document':
                                    props = n['properties']
                                    unsupported = props['detected_format'] == 'unknown'
                                    with self.lock, self.db:
                                        self.db.execute('UPDATE parses SET format=?,mime=? WHERE cache=?', (props['detected_format'], props['mime'], r['cache']))
                                if seq <= resume:
                                    continue
                                body = json.dumps(n, sort_keys=True, ensure_ascii=False)
                                sha = hashlib.sha256(body.encode()).hexdigest()
                                index_started=time.monotonic()
                                with self.lock, self.db:
                                    self._get(subject, session, aid)
                                    self.db.execute('INSERT INTO nodes VALUES(?,?,?,?,?,?,?)',
                                                    (r['cache'], seq, n['kind'], n['text'], json.dumps(n['anchor']), json.dumps(n['properties']), sha))
                                    if n['text']:
                                        self.db.execute('INSERT INTO search VALUES(?,?,?)', (r['cache'], seq, n['text']))
                                    self.db.execute('UPDATE parses SET cursor=? WHERE cache=?', (seq, r['cache']))
                                index_seconds += time.monotonic()-index_started
                                committed = seq
                            elif item.get('end'):
                                completed = True
                                parser_seconds = item.get('parser_seconds',0)
                            elif 'error' in item:
                                failure = 'parse_' + item['error'] + ':' + item['reason']
                        if not alive and not data:
                            break
                        if not data:
                            time.sleep(0.02)
                proc.wait(timeout=5)
            with self.lock, self.db:
                state = 'unsupported' if completed and unsupported else 'complete' if completed and not failure and proc.returncode == 0 else 'partial' if committed else 'failed'
                self.db.execute('UPDATE parses SET status=?,reason=?,seconds=seconds+?,peak_rss=max(peak_rss,?) WHERE cache=?',
                                (state, failure or (None if completed else 'parser_interrupted'), time.monotonic()-started, peak, r['cache']))
                self.db.execute('UPDATE parses SET index_seconds=index_seconds+?,parser_seconds=parser_seconds+? WHERE cache=?',(index_seconds,parser_seconds,r['cache']))
            return {**self.info(subject, session, aid), 'cache_hit': False, 'resumed_from': resume}
        except BaseException as error:
            with self.lock, self.db:
                if 'r' in locals():
                    self.db.execute("UPDATE parses SET status='partial',reason=? WHERE cache=? AND status='processing'", ('host_interrupted_'+type(error).__name__, r['cache']))
            raise
        finally:
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            if 'output' in locals():
                Path(output).unlink(missing_ok=True)
            self.slots.release()

    def _public_node(self, r, n):
        anchor = json.loads(n['anchor'])
        properties=json.loads(n['properties']) if len(n['properties'].encode())<self.budgets.preview_bytes//2 else {'omitted_for_output_budget':True}
        return {'kind': n['kind'], 'text': n['text'], 'anchor': anchor, 'properties': properties,
                'trust': 'untrusted_document_data', 'file': r['name'], 'attachment_id': r['id'], 'original_sha256': r['sha256'],
                'citation': f"lpdoc:{r['id']}:{n['seq']}:{n['sha256']}", 'node_sha256': n['sha256']}

    def read(self, subject, session, aid, *, cursor=0, limit=12):
        if type(cursor) is not int or cursor < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise DocumentError('invalid_document_page')
        with self.lock:
            r = self._get(subject, session, aid)
            rows = self.db.execute('SELECT * FROM nodes WHERE cache=? AND seq>? ORDER BY seq LIMIT ?', (r['cache'], cursor, limit)).fetchall()
            nodes=[];accepted=[];used=0
            for n in rows:
                public=self._public_node(r,n);size=len(json.dumps(public,ensure_ascii=False).encode())
                if accepted and used+size>self.budgets.preview_bytes:break
                nodes.append(public);accepted.append(n);used+=size
            rows=accepted
            return {'version': VERSION, 'document': self.info(subject, session, aid), 'nodes': nodes,
                    'next_cursor': rows[-1]['seq'] if rows else cursor, 'has_more': bool(rows and self.db.execute('SELECT 1 FROM nodes WHERE cache=? AND seq>?', (r['cache'], rows[-1]['seq'])).fetchone())}

    def search(self, subject, session, query, *, ids=None, limit=8, mode='fts'):
        if not isinstance(query, str) or not query.strip() or len(query) > 512 or type(limit) is not int or not 1 <= limit <= 30 or mode not in {'fts', 'hybrid'}:
            raise DocumentError('invalid_search')
        with self.lock, self._query_budget() as deadline:
            refs = self.db.execute('SELECT id FROM attachments WHERE subject=? AND session=? AND active=1 AND expires>? ORDER BY created,id',(subject,session,time.time()))
            if ids is not None:
                if not isinstance(ids, list) or not ids:
                    raise DocumentError('invalid_search_ids')
                if len(json.dumps(ids).encode())>self.budgets.preview_bytes:
                    raise DocumentError('search_reference_byte_budget',413)
                refs = [self.info(subject, session, aid) for aid in ids]
            # Each query is constrained to authorized caches; no global top-k starvation.
            scores, originals = {}, {}
            ts = terms(query)
            match = ' OR '.join('"' + t + '"' for t in ts[:32])
            scan_remaining = 10000
            byte_remaining = self.budgets.search_scan_bytes
            for ref in refs:
                if time.monotonic() > deadline:
                    raise DocumentError('retrieval_time_budget', 413)
                r = self._get(subject, session, ref['id'])
                originals[r['id']] = r
                rows = self.db.execute('SELECT seq,bm25(search) rank FROM search WHERE search MATCH ? AND cache=? ORDER BY rank LIMIT ?', (match or '""', r['cache'], limit*4)).fetchall()
                for rank, n in enumerate(rows, 1):
                    scores[(r['id'], int(n['seq']))] = 1 / (60 + rank)
                # CJK and exact phrases supplement FTS tokenizer coverage.
                literal = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
                rows = self.db.execute("SELECT seq FROM nodes WHERE cache=? AND text LIKE ? ESCAPE '\\' LIMIT ?", (r['cache'], literal, limit*4)).fetchall()
                for rank, n in enumerate(rows, 1):
                    key = r['id'], n['seq']
                    scores[key] = scores.get(key, 0) + 1/(60+rank)
                if mode == 'hybrid' and scan_remaining > 0:
                    qvec = vector(query)
                    nodes = self.db.execute("SELECT seq,text FROM nodes WHERE cache=? AND text<>'' ORDER BY seq LIMIT ?", (r['cache'], scan_remaining)).fetchall()
                    scan_remaining -= len(nodes)
                    candidates = []
                    for n in nodes:
                        byte_remaining -= len(n['text'].encode())
                        if byte_remaining < 0 or time.monotonic() > deadline:
                            break
                        candidates.append((sum(x*y for x,y in zip(qvec, vector(n['text']))), n['seq']))
                    ranked = sorted(candidates, reverse=True)[:limit*4]
                    for rank, (score, seq) in enumerate(ranked, 1):
                        if score > 0:
                            key = r['id'], seq
                            scores[key] = scores.get(key, 0) + 1/(60+rank)
                if len(scores)>limit*8:
                    scores=dict(sorted(scores.items(),key=lambda x:(-x[1],x[0]))[:limit*8])
                keep={key[0] for key in scores}
                originals={key:value for key,value in originals.items() if key in keep}
            hits = []
            output_bytes=0;output_limited=False
            for (aid, seq), score in sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:limit]:
                r = originals[aid]
                n = self.db.execute('SELECT * FROM nodes WHERE cache=? AND seq=?', (r['cache'], seq)).fetchone()
                public={**self._public_node(r, n), 'score': score}
                size=len(json.dumps(public,ensure_ascii=False).encode())
                if hits and output_bytes+size>self.budgets.preview_bytes:
                    output_limited=True;break
                hits.append(public);output_bytes+=size
            return {'version': VERSION, 'hits': hits, 'mode': mode,
                    'output_budget_limited':output_limited,
                    'vector_kind': 'local_hashed_lexical_not_semantic' if mode == 'hybrid' else None,
                    'vector_scan_budget': 10000 if mode == 'hybrid' else None, 'vector_scan_truncated': mode == 'hybrid' and (scan_remaining == 0 or byte_remaining < 0)}

    def verify(self, subject, session, citation, quote):
        m = re.fullmatch(r'lpdoc:(att_[0-9a-f]{32}):(\d+):([0-9a-f]{64})', citation) if isinstance(citation, str) else None
        if not m or not isinstance(quote, str) or not quote or len(quote) > self.budgets.node_chars:
            raise DocumentError('invalid_citation')
        with self.lock:
            r = self._get(subject, session, m[1])
            n = self.db.execute('SELECT * FROM nodes WHERE cache=? AND seq=?', (r['cache'], int(m[2]))).fetchone()
            blob = self.blobs / r['sha256']
            valid = bool(n and n['sha256'] == m[3] and quote in n['text'] and not blob.is_symlink() and digest_file(blob) == r['sha256'])
            return {'verified': valid, 'scope': 'exact_extracted_fragment_and_original_hash; no_model_answer_grade',
                    'source': self._public_node(r, n) if valid else None}

    def gc(self):
        """Explicit cache collection: no implicit erasure of selected originals."""
        with self.lock, self.db:
            if not self.slots.acquire(blocking=False):
                raise DocumentError('parser_busy_retry', 429)
            try:
                self.db.execute('UPDATE attachments SET active=0,status=? WHERE expires<=?', ('expired', time.time()))
                active = {r[0] for r in self.db.execute('SELECT DISTINCT sha256 FROM attachments WHERE active=1')}
                removed = 0
                for p in self.blobs.iterdir():
                    if p.name not in active:
                        removed += p.stat().st_size
                        p.unlink()
                caches = [r[0] for r in self.db.execute('SELECT cache FROM parses WHERE sha256 NOT IN (SELECT sha256 FROM attachments WHERE active=1)')]
                for cache in caches:
                    self.db.execute('DELETE FROM nodes WHERE cache=?', (cache,))
                    self.db.execute('DELETE FROM search WHERE cache=?', (cache,))
                    self.db.execute('DELETE FROM parses WHERE cache=?', (cache,))
                for p in self.jobs.iterdir():
                    if p.is_file():
                        p.unlink()
                self.db.execute('PRAGMA incremental_vacuum')
                return {'collected_blob_bytes': removed, 'collected_parses': len(caches)}
            finally:
                self.slots.release()

    def initialize_session(self, runtime, session, subject):
        # The Core checkpoint, not the separately committed document DB, decides
        # whether a restored session had this schema extension activated.
        flags=getattr(runtime,'_service_extensions',None)
        if flags is not None and flags.get('documents')!=2:
            return
        with self.lock:
            exists = self.db.execute('SELECT 1 FROM bindings WHERE session=? AND subject=?', (session, subject)).fetchone()
        if exists:
            from .tools import register
            register(self, runtime, session, subject)
