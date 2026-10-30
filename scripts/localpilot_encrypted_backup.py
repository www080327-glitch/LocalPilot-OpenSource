"""Private, deduplicated tar/gzip -> official age -> bounded encrypted chunks.

Never deletes a source, logs private content, uploads a key, or starts services.
SQLite is captured with the online read-only backup API. WAL sidecars are not
replayed over restored snapshots. Only the inventory's exact roots are read.
"""
import argparse
import base64
import errno
import xattr
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import shutil
import tarfile
import threading
import time
import uuid

CHUNK=1024**3

def portable_attribute(name):
    return name not in {'com.apple.provenance','com.apple.macl','com.apple.rootless'} and not name.startswith('com.apple.fileprovider.')

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def isolated_link_or_copy(source,target,boundary):
    """Honor OS hardlink restrictions by copying into a new owned inode.

    Never change security attributes or flags on the donor. Both paths must be
    under the caller's isolated restore staging, not original user locations.
    """
    boundary=boundary.resolve(strict=True)
    info=source.lstat()
    if (source.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid()
        or not source.resolve(strict=True).is_relative_to(boundary)
        or not target.parent.resolve(strict=True).is_relative_to(boundary)):
        raise RuntimeError('Hardlink donor/target is outside owned restore staging')
    try:
        os.link(source,target,follow_symlinks=False)
        return False
    except OSError as error:
        if error.errno not in {errno.EPERM,errno.EXDEV,errno.EMLINK,errno.ENOTSUP,errno.EOPNOTSUPP}:raise
    digest=sha(source)
    with source.open('rb') as old,target.open('xb') as new:shutil_copy(old,new)
    if target.stat().st_size!=info.st_size or sha(target)!=digest or sha(source)!=digest:
        raise RuntimeError('Independent copy differs; incomplete output retained')
    target.chmod(stat.S_IMODE(info.st_mode))
    for name in xattr.listxattr(str(source),symlink=True):
        if portable_attribute(name):xattr.setxattr(str(target),name,xattr.getxattr(str(source),name,symlink=True))
    os.utime(target,ns=(info.st_atime_ns,info.st_mtime_ns))
    return True

def private_json(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(value,stream,ensure_ascii=True,indent=2);stream.write('\n')

def sqlite_private_copy(source,directory):
    """Copy a stable main/WAL/journal set; never open original SQLite.

    Even mode=ro can write SHM read marks. Recovery and backup now happen only
    inside private staging. Busy or symlinked sets fail closed.
    """
    paths=[source,source.with_name(source.name+'-wal'),source.with_name(source.name+'-journal')]
    def signature(path):
        try:
            info=path.lstat()
            if not stat.S_ISREG(info.st_mode):raise RuntimeError('SQLite source/sidecar is not regular')
            return (info.st_ino,info.st_size,info.st_mtime_ns)
        except FileNotFoundError:return None
    for attempt in range(3):
        stage=directory/('sqlite-source-copy-'+uuid.uuid4().hex);stage.mkdir(mode=0o700)
        before={path:signature(path) for path in paths}
        for path,info in before.items():
            if info is not None:
                target=stage/path.name;shutil.copyfile(path,target);target.chmod(0o600)
        if before=={path:signature(path) for path in paths}:return stage/source.name
        time.sleep(.1)
    raise RuntimeError('SQLITE_BUSY_STABLE_COPY_UNAVAILABLE; original preserved')

def make_bundles(inventory,out):
    trees=json.loads((inventory/'git-worktrees.json').read_text());groups={};result=[]
    for tree in trees:
        if tree['common_dir']['exit'] or tree['head']['exit']:continue
        common=tree['common_dir']['output'].strip();group=groups.setdefault(common,{'heads':set(),'stashes':[],'trees':[]})
        group['heads'].add(tree['head']['output'].strip());group['trees'].append(tree['path'])
        for line in tree['stashes']['output'].splitlines():
            ref,commit=line.split(' ',1);group['heads'].add(commit);group['stashes'].append({'ref':ref,'commit':commit,'worktree':tree['path']})
    directory=out/'git-bundles';directory.mkdir(mode=0o700)
    for index,(common,group) in enumerate(groups.items()):
        path=directory/f'history-{index:03}.bundle'
        run=subprocess.run(['git','--git-dir',common,'bundle','create',str(path),'--all',*sorted(group['heads'])],capture_output=True,text=True)
        if run.returncode:raise RuntimeError('Git bundle creation failed; original repository preserved')
        path.chmod(0o600)
        verify=subprocess.run(['git','--git-dir',common,'bundle','verify',str(path)],capture_output=True,text=True)
        if verify.returncode:raise RuntimeError('Git bundle verification failed')
        result.append({'file':path.name,'sha256':sha(path),'bytes':path.stat().st_size,'common_dir':common,
            'heads':sorted(group['heads']),'stashes':group['stashes'],'worktrees':group['trees']})
    private_json(out/'git-bundles.json',result)
    return result

def create(inventory,out,age,recipient,key_path):
    out.mkdir(mode=0o700,parents=True,exist_ok=False)
    description=json.loads((inventory/'inventory.json').read_text());roots={r['id']:Path(r['path']) for r in description['roots']}
    for root in roots.values():
        if key_path==root or key_path.is_relative_to(root):raise ValueError('Key is inside backup scope')
        if out==root or out.is_relative_to(root):raise ValueError('Backup destination overlaps source')
    directory_paths=description.get('directory_paths')
    if directory_paths is not None:
        if (not isinstance(directory_paths,list) or len(directory_paths)>200000
            or any(not isinstance(value,str) for value in directory_paths)):
            raise ValueError('Invalid bounded incremental directory list')
        directory_paths=sorted(set(Path(value) for value in directory_paths))
        for path in directory_paths:
            owner=next((root for root in roots.values() if path==root or path.is_relative_to(root)),None)
            if not path.is_absolute() or '..' in path.parts or owner is None:
                raise ValueError('Incremental directory is outside inventory roots')
            for ancestor in [owner,*[owner/Path(*path.relative_to(owner).parts[:n]) for n in range(1,len(path.relative_to(owner).parts)+1)]]:
                if not stat.S_ISDIR(ancestor.lstat().st_mode):
                    raise ValueError('Incremental directory must not follow links')
    bundles=make_bundles(inventory,out)
    snapshots=out/'sqlite-snapshots';snapshots.mkdir(mode=0o700)
    stderr=(out/'age.error').open('xb')
    encrypt=subprocess.Popen([str(age),'-r',recipient],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr)
    chunks=[];failures=[]
    def split_output():
        try:
            part=0;stream=None;digest=None;written=0
            while True:
                block=encrypt.stdout.read(1024*1024)
                if not block:break
                if stream is None:
                    part+=1;path=out/f'localpilot-full.tar.gz.age.part{part:03}';stream=path.open('xb');path.chmod(0o600);digest=hashlib.sha256();written=0
                stream.write(block);digest.update(block);written+=len(block)
                if written>=CHUNK:
                    stream.flush();os.fsync(stream.fileno());stream.close();chunks.append({'name':path.name,'bytes':written,'sha256':digest.hexdigest()});stream=None
            if stream:
                stream.flush();os.fsync(stream.fileno());stream.close();chunks.append({'name':path.name,'bytes':written,'sha256':digest.hexdigest()})
        except Exception as error:failures.append(type(error).__name__)
    reader=threading.Thread(target=split_output);reader.start()
    manifest_path=out/'archive-files.jsonl';seen={};databases=[];sqlite_failures=[];changes=[];count=0;logical=0;stored=0
    try:
        with manifest_path.open('x') as manifest,tarfile.open(mode='w|gz',fileobj=encrypt.stdin,compresslevel=3) as archive:
            # Empty directories and directory permissions are part of user state.
            # Never follow a directory symlink out of the inventoried roots.
            for root_id,root in roots.items():
                if not root.is_dir() or root.is_symlink():continue
                if directory_paths is None:
                    def walk_directories():
                        for directory,children,_ in os.walk(root,followlinks=False):
                            children[:]=[name for name in children if not (Path(directory)/name).is_symlink()]
                            yield directory
                    directories=walk_directories()
                else:
                    # Incremental captures use the authenticated base index and
                    # an explicit changed/new directory list, never a full walk.
                    directories=(path for path in directory_paths if path==root or path.is_relative_to(root))
                for directory in directories:
                    source=Path(directory);info=source.lstat()
                    relative=source.relative_to(root)
                    name=f'roots/{root_id:03}/'+(str(relative) if relative.parts else 'root-directory')
                    # Root contents live directly under roots/NNN.
                    if not relative.parts:name=f'roots/{root_id:03}'
                    row={'name':name,'source':str(source),'type':'directory','mode':stat.S_IMODE(info.st_mode),'uid':info.st_uid,'gid':info.st_gid,'mtime_ns':info.st_mtime_ns,
                        'file_flags_metadata':getattr(info,'st_flags',0),'xattrs':{key:base64.b64encode(xattr.getxattr(str(source),key,symlink=True)).decode() for key in xattr.listxattr(str(source),symlink=True)}}
                    member=tarfile.TarInfo(name);member.type=tarfile.DIRTYPE;member.mode=0o700;archive.addfile(member)
                    manifest.write(json.dumps(row,ensure_ascii=True)+'\n')
            for line in (inventory/'files.jsonl').open():
                record=json.loads(line);source=roots[record['root']]
                if record['relative']!='.':source=source/record['relative']
                name=f"roots/{record['root']:03}/"+(record['relative'] if record['relative']!='.' else 'root-file')
                info=source.lstat();row={'name':name,'source':str(source),'mode':stat.S_IMODE(info.st_mode),'uid':info.st_uid,'gid':info.st_gid,'mtime_ns':info.st_mtime_ns,'file_flags_metadata':getattr(info,'st_flags',0)}
                row['xattrs']={key:base64.b64encode(xattr.getxattr(str(source),key,symlink=True)).decode() for key in xattr.listxattr(str(source),symlink=True)}
                if source==key_path:raise RuntimeError('Key path rejected')
                if source.name=='owner.sqlite3' and source.parent.name=='adapter':
                    row.update(type='ownership_lock_metadata_only',bytes=info.st_size,sha256=record.get('sha256'));manifest.write(json.dumps(row)+'\n');continue
                if stat.S_ISLNK(info.st_mode):
                    row.update(type='symlink',target=os.readlink(source));member=tarfile.TarInfo(name);member.type=tarfile.SYMTYPE;member.linkname=row['target'];member.mode=row['mode'];archive.addfile(member)
                elif stat.S_ISREG(info.st_mode):
                    # Snapshot SQLite first, then omit its recovery sidecars from the archive.
                    if not record.get('preserve_raw_file_bytes') and source.name.endswith(('-wal','-shm','-journal')) and any(source.with_name(source.name[:-len(suffix)]).exists() for suffix in ('-wal','-shm','-journal') if source.name.endswith(suffix)):
                        row.update(type='sqlite_sidecar_metadata_only',bytes=info.st_size);manifest.write(json.dumps(row)+'\n');continue
                    current=source
                    with source.open('rb') as check:header=check.read(16)
                    if record.get('preserve_raw_file_bytes'):
                        row['raw_forensic_file_bytes']=True
                    if header==b'SQLite format 3\x00' and not record.get('preserve_raw_file_bytes'):
                        current=snapshots/f'db-{len(databases):05}.sqlite3'
                        old=new=None
                        try:
                            copied=sqlite_private_copy(source,snapshots)
                            old=sqlite3.connect(copied,timeout=10);new=sqlite3.connect(current)
                            old.backup(new);check=new.execute('PRAGMA quick_check').fetchall();new.commit()
                            if check!=[('ok',)]:raise sqlite3.DatabaseError('integrity')
                            current.chmod(0o600);databases.append({'name':name,'source':str(source),'snapshot':current.name,'sha256':sha(current),'quick_check':'ok'})
                            row['sqlite_snapshot']=True
                        except sqlite3.Error:
                            sqlite_failures.append({'name':name,'source':str(source),'policy':'original bytes preserved; corruption not repaired'})
                            current=source
                        finally:
                            if new:new.close()
                            if old:old.close()
                    data_info=current.stat();digest=sha(current);size=data_info.st_size
                    row.update(type='file',bytes=size,sha256=digest)
                    portable={key:value for key,value in row['xattrs'].items() if portable_attribute(key)}
                    logical+=size;key=(digest,size,row['mode'],row['mtime_ns'],hashlib.sha256(json.dumps(portable,sort_keys=True).encode()).hexdigest())
                    member=tarfile.TarInfo(name);member.mode=row['mode'];member.mtime=info.st_mtime
                    if key in seen:
                        member.type=tarfile.LNKTYPE;member.linkname=seen[key];archive.addfile(member);row['hardlink']=seen[key]
                    else:
                        member.size=size
                        with current.open('rb') as source_stream:archive.addfile(member,source_stream)
                        if sha(current)!=digest:raise RuntimeError('Source changed while archiving; preserve partial backup and retry')
                        seen[key]=name;stored+=size
                    if not row.get('sqlite_snapshot') and (record.get('sha256')!=digest or record.get('mtime_ns')!=info.st_mtime_ns):changes.append({'name':name,'reason':'newer_than_inventory','archived_sha256':digest})
                else:
                    row['type']='special_file_metadata_only'
                manifest.write(json.dumps(row,ensure_ascii=True)+'\n');count+=1
                if count%10000==0:print(json.dumps({'files':count,'logical_bytes':logical,'unique_bytes':stored,'encrypted_chunks':len(chunks)}),flush=True)
            manifest.flush();os.fsync(manifest.fileno())
            for path in [inventory/'inventory.json',inventory/'files.jsonl',inventory/'git-worktrees.json',inventory/'owned-models.json',*[p for p in inventory.glob('*.json') if p.name not in {'inventory.json','git-worktrees.json','owned-models.json'}],manifest_path,out/'git-bundles.json',*sorted((out/'git-bundles').glob('*.bundle'))]:
                archive.add(path,arcname='metadata/'+path.name,recursive=False)
        encrypt.stdin.close();reader.join();code=encrypt.wait();stderr.close()
        if code or failures:raise RuntimeError('Encryption output failed')
        report={'version':1,'status':'LOCAL_ENCRYPTED_NOT_REMOTE_VERIFIED','created':time.time(),
            'encryption':'age v1.3.1 X25519; private identity retained separately','key_uploaded':False,
            'files':count,'logical_bytes':logical,'unique_bytes':stored,'root_count':len(roots),
            'sqlite_snapshots':databases,'sqlite_invalid_originals_preserved':sqlite_failures,'source_changed_since_inventory':changes,'chunks':chunks,
            'git_bundles':bundles,'restore':'new isolated directory only; no service auto-start; UNKNOWN preserved',
            'manifest_sha256':sha(manifest_path),'source_deletion_authorized':False}
        private_json(out/'backup-private.json',report)
        public={key:report[key] for key in ('version','status','created','encryption','key_uploaded','files','logical_bytes','unique_bytes','root_count','chunks','restore','manifest_sha256','source_deletion_authorized')}
        private_json(out/'backup-index.json',public)
        print(json.dumps(public,indent=2))
    except Exception:
        encrypt.stdin.close();reader.join(timeout=30)
        if encrypt.poll() is None:encrypt.terminate()
        raise

def restore(parts,out,age,key,external_metadata=None,wait_parts_seconds=0,resume_prefix=False):
    if not resume_prefix:out.mkdir(mode=0o700,parents=True,exist_ok=False)
    index=json.loads((parts/'backup-index.json').read_text())
    if index.get('external_metadata_required'):
        if external_metadata is None:raise RuntimeError('Authenticated tail metadata required for interrupted prefix')
        metadata_root=external_metadata.resolve(strict=True)
        if json.loads((metadata_root/'prefix-index.json').read_text())!=index:
            raise RuntimeError('Authenticated prefix descriptor differs from downloaded index')
        if sha(metadata_root/'archive-files.jsonl')!=index['manifest_sha256']:
            raise RuntimeError('Authenticated prefix manifest hash differs')
    else:
        if external_metadata is not None:raise RuntimeError('External metadata is only valid for declared prefix volumes')
        metadata_root=out/'metadata'
    session={'kind':'ISOLATED_RESTORE_STAGING','uid':os.getuid(),'index_sha256':sha(parts/'backup-index.json'),
        'manifest_sha256':index['manifest_sha256'],'source_data_overwritten':False}
    expected={}
    if resume_prefix:
        old=json.loads((out/'restore-session.json').read_text())
        if (not index.get('external_metadata_required') or any(old.get(k)!=v for k,v in session.items())
            or out.stat().st_mode&0o077 or out.stat().st_uid!=os.getuid()
            or (out/'restore-session.json').stat().st_mode&0o077):raise RuntimeError('Prefix resume requires its matching private restore staging')
        for line in (metadata_root/'archive-files.jsonl').open():
            row=json.loads(line)
            if row['type']=='file':expected[row['name']]=(row['bytes'],row['sha256'])
    else:private_json(out/'restore-session.json',session)
    def retained_existing(target,name,stream=None):
        if not (target.exists() or target.is_symlink()):return False
        if not resume_prefix:raise RuntimeError('Existing restore member rejected')
        if target.is_symlink() or not target.is_file():raise RuntimeError('Unexpected existing prefix member type')
        proof=expected.get(name)
        if proof and target.stat().st_size==proof[0] and sha(target)==proof[1]:
            if stream is not None and hashlib.file_digest(stream,'sha256').hexdigest()!=proof[1]:raise RuntimeError('Replayed remote archive member differs')
            return True
        # Preserve an interrupted output fragment; never overwrite or delete it.
        directory=out/'abandoned-partial-files';directory.mkdir(mode=0o700,exist_ok=True)
        preserved=directory/uuid.uuid4().hex
        target.rename(preserved)
        private_json(directory/(preserved.name+'.json'),{'member':name,'bytes':preserved.stat().st_size,'original_data':False})
        return False
    abort=threading.Event();deadline=time.monotonic()+wait_parts_seconds
    def verified_part(item):
        path=parts/item['name']
        while not path.exists() or path.stat().st_size!=item['bytes']:
            if abort.is_set():raise RuntimeError('Restore aborted')
            if time.monotonic()>=deadline:raise RuntimeError('Remote chunk missing or wrong size; restore incomplete')
            time.sleep(1)
        if sha(path)!=item['sha256']:raise RuntimeError('Remote chunk hash mismatch')
        return path
    if not wait_parts_seconds:
        for item in index['chunks']:verified_part(item)
    errors=[];links=[];file_count=0;hardlink_copies=0
    decrypt=subprocess.Popen([str(age),'-d','-i',str(key)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    def feed():
        try:
            for item in index['chunks']:
                with verified_part(item).open('rb') as stream:
                    while block:=stream.read(1024*1024):decrypt.stdin.write(block)
        except Exception as error:errors.append(type(error).__name__)
        finally:
            try:decrypt.stdin.close()
            except (BrokenPipeError,OSError):pass
    feeder=threading.Thread(target=feed);feeder.start()
    try:
        with tarfile.open(mode='r|gz',fileobj=decrypt.stdout) as archive:
            for member in archive:
                relative=Path(member.name)
                if relative.is_absolute() or '..' in relative.parts:raise RuntimeError('Unsafe archive member')
                ancestor=out
                for part in relative.parts[:-1]:
                    ancestor=ancestor/part
                    if ancestor.is_symlink():raise RuntimeError('Archive parent is a symlink')
                target=out/relative;target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                if member.issym():
                    if target.is_symlink():
                        if not resume_prefix or os.readlink(target)!=member.linkname:raise RuntimeError('Existing link differs')
                    elif target.exists():raise RuntimeError('Unexpected existing link target')
                    else:links.append((target,member.linkname))
                    continue
                if member.islnk():
                    link=Path(member.linkname)
                    if link.is_absolute() or '..' in link.parts:raise RuntimeError('Unsafe hardlink')
                    if not retained_existing(target,member.name):
                        hardlink_copies+=int(isolated_link_or_copy(out/link,target,out))
                elif member.isfile():
                    with archive.extractfile(member) as source:
                        if not retained_existing(target,member.name,source):
                            with target.open('xb') as destination:shutil_copy(source,destination)
                    target.chmod(member.mode&0o777);file_count+=1
                    if file_count%10000==0:print(json.dumps({'restore_members_processed':file_count,'archive_authenticated_complete':False,'resume_prefix':resume_prefix}),flush=True)
                elif member.isdir():target.mkdir(mode=0o700,exist_ok=True)
                else:raise RuntimeError('Unsupported archive member')
    except BaseException:
        abort.set()
        if decrypt.poll() is None:decrypt.terminate()
        feeder.join(timeout=5)
        try:decrypt.wait(timeout=10)
        except subprocess.TimeoutExpired:decrypt.kill();decrypt.wait()
        raise
    feeder.join();code=decrypt.wait()
    if code or errors:raise RuntimeError('Encrypted archive authentication failed')
    authentication=out/'archive-authentication.json'
    if authentication.exists():authentication=out/('archive-authentication-resume-'+str(time.time_ns())+'.json')
    private_json(authentication,{'authenticated':True,'chunks':len(index['chunks']),'index_sha256':sha(parts/'backup-index.json')})
    # Symlinks are created only after all writes. Nothing follows or executes them.
    for path,target in links:path.symlink_to(target)
    if hardlink_copies:
        private_json(out/'hardlink-copy-receipt.json',{'independent_copies_for_os_hardlink_restrictions':hardlink_copies,'donor_security_flags_or_attributes_changed':False,'source_data_overwritten':False})
    verify_extracted(out,index,metadata_root)

def verify_extracted(out,index,metadata_root):
    manifest=metadata_root/'archive-files.jsonl'
    if sha(manifest)!=index['manifest_sha256']:raise RuntimeError('Recovered manifest hash mismatch')
    databases=0;verified=0;xattrs_restored=0;nonportable=[];directories=[];link_count=0
    for line in manifest.open():
        row=json.loads(line);relative=Path(row['name'])
        if relative.is_absolute() or '..' in relative.parts:raise RuntimeError('Unsafe manifest member')
        path=out/relative
        if row['type'] in {'file','directory'} and not path.resolve().is_relative_to(out.resolve()):raise RuntimeError('Manifest path escapes restore staging')
        if row['type'] in {'file','directory','symlink'}:
            for attribute,encoded in row.get('xattrs',{}).items():
                if not portable_attribute(attribute):
                    nonportable.append({'name':row['name'],'attribute':attribute,'policy':'retained as metadata, not forged on restored files'});continue
                value=base64.b64decode(encoded);xattr.setxattr(str(path),attribute,value,symlink=True)
                if xattr.getxattr(str(path),attribute,symlink=True)!=value:raise RuntimeError('Restored extended attribute differs')
                xattrs_restored+=1
            if row['type']=='directory':
                directories.append((path,row));continue
            if row['type']=='symlink':
                if os.readlink(path)!=row['target']:raise RuntimeError('Recovered link differs')
                link_count+=1
                continue
            if path.stat().st_size!=row['bytes'] or sha(path)!=row['sha256']:raise RuntimeError('Recovered file differs')
            if row.get('sqlite_snapshot'):
                db=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)
                try:
                    if db.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:raise RuntimeError('Recovered SQLite invalid')
                finally:db.close()
                databases+=1
            verified+=1
            os.utime(path,ns=(row['mtime_ns'],row['mtime_ns']))
    for path,row in reversed(directories):
        path.chmod(row['mode']);os.utime(path,ns=(row['mtime_ns'],row['mtime_ns']))
    git_reports=[]
    for bundle in json.loads((metadata_root/'git-bundles.json').read_text()):
        path=metadata_root/bundle['file']
        if sha(path)!=bundle['sha256']:raise RuntimeError('Recovered Git bundle hash differs')
        target=out/'git-restoration'/bundle['file'].removesuffix('.bundle')
        if not target.exists():
            run=subprocess.run(['git','clone','--mirror',str(path),str(target)],capture_output=True,text=True)
            if run.returncode:raise RuntimeError('Git bundle re-clone failed')
        elif target.is_symlink() or not target.resolve().is_relative_to(out.resolve()):raise RuntimeError('Unsafe existing Git restoration target')
        for commit in bundle['heads']:
            if subprocess.run(['git','--git-dir',str(target),'cat-file','-e',commit+'^{commit}'],capture_output=True).returncode:raise RuntimeError('Git history commit missing')
        git_reports.append({'bundle':bundle['file'],'commits_and_stashes_verified':len(bundle['heads'])})
    report={'status':'RESTORE_VERIFIED','remote_chunks_hash_verified':len(index['chunks']),
        'encrypted_archive_authenticated':True,'restored_files_verified':verified,'sqlite_quick_check_passed':databases,
        'git_history':git_reports,'symlinks_preserved_without_execution':link_count,'extended_attributes_restored':xattrs_restored,'nonportable_attributes_retained_as_metadata':len(nonportable),
        'directories_preserved':len(directories),'external_metadata_used':index.get('external_metadata_required') is True,
        'complete_backup_set':False,'scope':'Single archive volume; complete recovery set requires coverage and combination verification',
        'services_started':False,'source_data_overwritten':False,'unknown_data_policy':'byte-preserved snapshots; no status reset or replay'}
    receipt=out/'restore-verification.json'
    if receipt.exists():receipt=out/('restore-verification-followup-'+str(time.time_ns())+'.json')
    private_json(receipt,report);print(json.dumps(report,indent=2))

def finish_existing(parts,out,age,key,external_metadata=None):
    """Re-authenticate ciphertext and validate an already extracted private staging.

    Never extracts again, deletes a file, or accepts an unmarked original folder.
    OS security grants stay as metadata and must be granted anew by the user.
    """
    marker=json.loads((out/'restore-session.json').read_text());index=json.loads((parts/'backup-index.json').read_text())
    if (marker.get('kind')!='ISOLATED_RESTORE_STAGING' or marker.get('uid')!=os.getuid()
        or marker.get('index_sha256')!=sha(parts/'backup-index.json') or out.stat().st_mode&0o077
        or (out/'restore-session.json').stat().st_mode&0o077 or out.stat().st_uid!=os.getuid()):
        raise RuntimeError('Existing output is not the matching private restore staging')
    metadata_root=external_metadata.resolve(strict=True) if external_metadata else out/'metadata'
    if index.get('external_metadata_required'):
        if not external_metadata or json.loads((metadata_root/'prefix-index.json').read_text())!=index:raise RuntimeError('Authenticated external descriptor required')
    for item in index['chunks']:
        path=parts/item['name']
        if path.stat().st_size!=item['bytes'] or sha(path)!=item['sha256']:raise RuntimeError('Downloaded chunk differs')
    process=subprocess.Popen([str(age),'-d','-i',str(key)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        for item in index['chunks']:
            with (parts/item['name']).open('rb') as stream:shutil_copy(stream,process.stdin)
        process.stdin.close();code=process.wait()
        if code:raise RuntimeError('Ciphertext authentication failed during follow-up verification')
    finally:
        if process.poll() is None:process.terminate();process.wait()
    private_json(out/('archive-authentication-followup-'+str(time.time_ns())+'.json'),{'authenticated':True,'chunks':len(index['chunks']),'index_sha256':sha(parts/'backup-index.json')})
    verify_extracted(out,index,metadata_root)

def shutil_copy(source,target):
    while block:=source.read(1024*1024):target.write(block)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['create','restore','verify-staging']);parser.add_argument('--input',required=True);parser.add_argument('--out',required=True);parser.add_argument('--age',required=True);parser.add_argument('--key-location',required=True);parser.add_argument('--external-metadata');parser.add_argument('--wait-for-parts-seconds',type=int,default=0);parser.add_argument('--resume-prefix',action='store_true')
    args=parser.parse_args();location=json.loads(Path(args.key_location).read_text());key=Path(location['path']).resolve(strict=True)
    if args.action=='create':create(Path(args.input).resolve(strict=True),Path(args.out).resolve(),Path(args.age).resolve(strict=True),location['public_recipient'],key)
    elif args.action=='restore':restore(Path(args.input).resolve(strict=True),Path(args.out).resolve(),Path(args.age).resolve(strict=True),key,Path(args.external_metadata) if args.external_metadata else None,args.wait_for_parts_seconds,args.resume_prefix)
    else:finish_existing(Path(args.input).resolve(strict=True),Path(args.out).resolve(strict=True),Path(args.age).resolve(strict=True),key,Path(args.external_metadata) if args.external_metadata else None)
