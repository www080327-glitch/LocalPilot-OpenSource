"""Combine authenticated volume snapshots in a NEW directory, without services.

Later volumes supersede earlier copies of the same absolute source path. Hard
links refer only to verified files inside isolated restore outputs. Original
paths are labels under output/filesystem; they are never opened for writing.
"""
import argparse
import base64
import errno
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import time
import xattr

from localpilot_encrypted_backup import portable_attribute, private_json, sha, isolated_link_or_copy


def safe_relative(value):
    path = Path(value)
    if path.is_absolute() or '..' in path.parts:
        raise RuntimeError('Unsafe recovery member')
    return path


def safe_source(value):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise RuntimeError('Invalid original-path label')
    return path


def parent_directory(target, boundary, checked=None):
    relative = target.parent.relative_to(boundary)
    current = boundary
    for part in relative.parts:
        current = current / part
        # This single writer creates symlinks only after all file writes. A
        # checked parent therefore cannot become a link within this phase.
        if checked is not None and current in checked:
            continue
        if current.is_symlink():
            raise RuntimeError('Recovery parent is a symlink')
        current.mkdir(mode=0o700, exist_ok=True)
        if checked is not None:
            checked.add(current)


def combine(spec_path, output):
    spec = json.loads(spec_path.read_text())
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    filesystem = output / 'filesystem'
    filesystem.mkdir(mode=0o700)
    database = output / 'recovery-overlay.sqlite3'
    db = sqlite3.connect(database)
    database.chmod(0o600)
    db.execute('CREATE TABLE entries(source TEXT PRIMARY KEY, volume INTEGER, member TEXT, type TEXT, row TEXT)')
    volumes = []
    for number, item in enumerate(spec['volumes']):
        directory = Path(item['directory']).resolve(strict=True)
        receipt = json.loads((directory / 'restore-verification.json').read_text())
        if not receipt.get('encrypted_archive_authenticated') or receipt.get('services_started') or receipt.get('source_data_overwritten'):
            raise RuntimeError('Volume has not passed isolated authenticated restoration')
        manifest = Path(item['manifest']).resolve(strict=True)
        index = json.loads(Path(item['index']).read_text())
        if sha(manifest) != index['manifest_sha256']:
            raise RuntimeError('Volume manifest changed')
        inventory = json.loads(Path(item['inventory']).read_text())
        roots = {int(row['id']): safe_source(row['path']) for row in inventory['roots']}
        excluded = set(item.get('metadata_root_ids', []))
        for line in manifest.open():
            row = json.loads(line)
            member = safe_relative(row['name'])
            if len(member.parts) < 2 or member.parts[0] != 'roots':
                raise RuntimeError('Unexpected data namespace')
            root_id = int(member.parts[1])
            if root_id in excluded:
                continue
            original = safe_source(row['source'])
            if root_id not in roots or not (original == roots[root_id] or original.is_relative_to(roots[root_id])):
                raise RuntimeError('Original path is outside its declared inventory root')
            if row['type'] not in {'file', 'directory', 'symlink'}:
                continue
            # A newer non-directory cannot retain descendants of an old directory.
            if row['type'] in {'file', 'symlink'}:
                prefix = str(original) + '/'
                db.execute('DELETE FROM entries WHERE source>=? AND source<?', (prefix, str(original)+'0'))
            db.execute('INSERT INTO entries VALUES(?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET volume=excluded.volume,member=excluded.member,type=excluded.type,row=excluded.row',
                       (str(original), number, str(member), row['type'], json.dumps(row)))
        db.commit()
        volumes.append({'directory': directory, 'name': item['name'], 'receipt': receipt})
    files = links = directories = sqlite_count = security_copies = hardlink_copies = 0
    checked_parents = set()
    fingerprint = hashlib.sha256()
    for original, number, member, kind, encoded in db.execute('SELECT source,volume,member,type,row FROM entries ORDER BY length(source),source'):
        row = json.loads(encoded)
        destination = filesystem / str(Path(original)).lstrip('/')
        parent_directory(destination, filesystem, checked_parents)
        if kind == 'directory':
            destination.mkdir(mode=0o700, exist_ok=True)
            directories += 1
        elif kind == 'file':
            source = volumes[number]['directory'] / safe_relative(member)
            if source.is_symlink() or not source.resolve(strict=True).is_relative_to(volumes[number]['directory']):
                raise RuntimeError('Verified file points outside restore staging')
            if not stat.S_ISREG(source.lstat().st_mode) or source.stat().st_size != row['bytes'] or sha(source) != row['sha256']:
                raise RuntimeError('Verified volume file changed before combination')
            # Older extraction code may have copied inode-specific OS grants.
            # Copy bytes to a fresh inode in that case; preserve quarantine and
            # other portable attributes, without changing the donor or original.
            attrs=xattr.listxattr(str(source),symlink=True)
            if any(key in {'com.apple.macl','com.apple.rootless'} for key in attrs):
                with source.open('rb') as old,destination.open('xb') as new:
                    while block:=old.read(1024*1024):new.write(block)
                destination.chmod(row['mode'])
                for attribute,encoded in row.get('xattrs',{}).items():
                    if portable_attribute(attribute):xattr.setxattr(str(destination),attribute,base64.b64decode(encoded))
                os.utime(destination,ns=(row['mtime_ns'],row['mtime_ns']))
                if sha(destination)!=row['sha256']:raise RuntimeError('Fresh security-neutral copy differs')
                security_copies+=1
            else:
                # The donor was resolved and hashed above. Avoid a second
                # full ancestor walk for each of a million ordinary links.
                copied=False
                try:
                    os.link(source,destination,follow_symlinks=False)
                except OSError as error:
                    if error.errno not in {errno.EPERM,errno.EXDEV,errno.EMLINK,errno.ENOTSUP,errno.EOPNOTSUPP}:raise
                    copied=isolated_link_or_copy(source,destination,output.parent)
                hardlink_copies+=int(copied)
                if not copied and destination.stat().st_ino != source.stat().st_ino:
                    raise RuntimeError('Combined data does not refer to verified inode')
            if row.get('sqlite_snapshot'):
                connection = sqlite3.connect(destination.as_uri() + '?mode=ro&immutable=1', uri=True)
                try:
                    if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                        raise RuntimeError('Combined SQLite failed integrity check')
                finally:
                    connection.close()
                sqlite_count += 1
            files += 1
            if files % 10000 == 0:
                print(json.dumps({'combined_files_verified': files, 'services_started': False}), flush=True)
        # Symlinks are postponed until every regular-file write is finished.
        fingerprint.update(json.dumps([original, kind, row.get('bytes'), row.get('sha256'), row.get('target')], sort_keys=True).encode() + b'\n')
    for original, encoded in db.execute("SELECT source,row FROM entries WHERE type='symlink' ORDER BY source"):
        row = json.loads(encoded)
        destination = filesystem / str(Path(original)).lstrip('/')
        parent_directory(destination, filesystem, checked_parents)
        destination.symlink_to(row['target'])
        links += 1
    for original,encoded in db.execute("SELECT source,row FROM entries WHERE type='directory' ORDER BY length(source) DESC,source"):
        row=json.loads(encoded);destination=filesystem/str(Path(original)).lstrip('/')
        for attribute,encoded in row.get('xattrs',{}).items():
            if portable_attribute(attribute):xattr.setxattr(str(destination),attribute,base64.b64decode(encoded),symlink=True)
        destination.chmod(row['mode']);os.utime(destination,ns=(row['mtime_ns'],row['mtime_ns']))
    report = {'status': 'COMBINED_SNAPSHOT_VERIFIED', 'created': time.time(),
              'authenticated_volumes': [v['name'] for v in volumes], 'regular_files_sha256_verified': files,
              'sqlite_quick_checks': sqlite_count, 'directories': directories, 'symlinks_preserved_without_execution': links,
              'logical_snapshot_fingerprint_sha256': fingerprint.hexdigest(),
              'original_paths_are_labels_under_filesystem': True, 'original_source_data_overwritten': False,
              'services_started': False, 'unknown_policy': 'Snapshot data retained; no resume, status reset or replay',
              'directory_metadata': 'Portable attributes/modes/timestamps restored; all metadata retained in ledger',
              'system_security_grants_copied_to_fresh_inodes':False,'fresh_inodes_for_security_tagged_donors':security_copies,
              'independent_copies_for_os_hardlink_restrictions':hardlink_copies,
              'coverage_gate': 'Requires independent original-inventory coverage reconciliation'}
    db.close()
    private_json(output / 'combination-verification.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    arguments = parser.parse_args()
    combine(arguments.spec.resolve(strict=True), arguments.out.resolve())
