"""Bounded upgrade backup through Core's SQLite snapshot interface."""
from pathlib import Path
import shutil
import json
import time
import hashlib
import os
import stat
import re
import sqlite3
from contextlib import closing
from localpilot_service.security import private_json
from localpilot_service.cli import private_dir,save
from localpilot_service.backup import copy_database

def private_snapshot(source,destination,allow_legacy=False):
    """Legacy Companion files may be 0644 inside 0700; never chmod originals."""
    info=source.lstat()
    if not info.st_mode&0o077:return copy_database(source,destination)
    parent=source.parent.stat()
    if not allow_legacy or not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or parent.st_uid!=os.getuid() or parent.st_mode&0o077:
        raise ValueError('Database source is not protected by a private owned directory')
    fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
    old=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True);new=sqlite3.connect(destination)
    try:
        old.backup(new)
        if new.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database snapshot integrity failed')
        new.commit()
    finally:old.close();new.close()
    with destination.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'status':'ok','destination':str(destination),'sha256':checksum,'original_permissions_changed':False}

def backup_channels(home,destination):
    copied=[]
    for name in ('message-platforms','message-state'):
        root=home/name
        if not root.exists():continue
        if root.is_symlink():raise ValueError('Linked channel private root rejected')
        for path in root.rglob('*'):
            relative=path.relative_to(home)
            if any(part in {'runtime','code-archives'} for part in relative.parts):continue
            if path.is_symlink():raise ValueError('Linked channel state rejected')
            if not path.is_file() or path.name in {'owner.sqlite3','bridge.lock','lifecycle.lock'} or path.name.endswith(('-wal','-shm','-journal')):continue
            info=path.lstat()
            if info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_nlink!=1:raise ValueError('Unsafe channel state source')
            target=destination/relative
            from .channel_paths import private_directory
            private_directory(target.parent,create=True)
            with path.open('rb') as stream:header=stream.read(16)
            if header==b'SQLite format 3\x00':private_snapshot(path,target)
            else:shutil.copy2(path,target);target.chmod(0o600)
            copied.append(str(relative))
    return copied

def backup(home,destination):
    home=Path(home).resolve(strict=True);destination=Path(destination).expanduser().resolve()
    if destination.exists() or not destination.is_absolute() or destination.is_relative_to(home):raise ValueError('Backup requires a new separate private directory')
    config=private_json(home/'service.json');companion=private_json(home/'companion.json')
    sources=[('core',Path(config['data_dir'])/'runtime.sqlite3'),('companion',Path(companion['data_dir'])/'memory.sqlite3')]
    needed=sum(p.stat().st_size for _,p in sources if p.exists())
    parent=destination.parent
    while not parent.exists():parent=parent.parent
    if shutil.disk_usage(parent).free<needed+2*1024**3:raise ValueError('备份目标磁盘空间不足，未改动原数据')
    destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    destination.mkdir(mode=0o700,exist_ok=False)
    destination=private_dir(destination);files=[]
    for name in ['service.json','connection.json','companion.json','clients.env','model-preferences.json','model-downloads.json','model-integrity.json']:
        p=home/name
        if p.exists():
            # Validate ownership/privacy without logging credentials.
            import os,stat
            st=p.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077:raise ValueError('Unsafe configuration source; upgrade paused')
            shutil.copy2(p,destination/name);(destination/name).chmod(0o600)
    for label,path in sources:
        if path.exists():files.append({'module':label,**private_snapshot(path,destination/(label+'.sqlite3'),allow_legacy=label=='companion')})
    channel_files=backup_channels(home,destination)
    metadata=Path(config['data_dir'])/'attachment-records'
    if metadata.is_dir() and not metadata.is_symlink():
        target=private_dir(destination/'attachment-records')
        for p in metadata.glob('*.json'):
            if p.is_file() and not p.is_symlink():shutil.copy2(p,target/p.name);(target/p.name).chmod(0o600)
    grants=Path(config['data_dir'])/'workspace-grants.json'
    if grants.exists():
        # Keep stable historical IDs for reconciliation; restore revokes access.
        save(destination/'workspace-grants.json',private_json(grants))
    documents=Path(config['data_dir'])/'documents-v2'
    document_db=documents/'documents.sqlite3'
    if document_db.exists():
        target=private_dir(destination/'documents-v2')
        copy_database(document_db,target/'documents.sqlite3')
        with closing(sqlite3.connect((target/'documents.sqlite3').as_uri()+'?mode=ro&immutable=1',uri=True)) as database:
            hashes={r[0] for r in database.execute('SELECT DISTINCT sha256 FROM attachments WHERE active=1 AND expires>?',(time.time(),))}
        blob_dir=private_dir(target/'blobs')
        for sha in hashes:
            if not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha):raise ValueError('Invalid document blob identity')
            source=documents/'blobs'/sha
            fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
            try:
                info=os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('Unsafe document blob')
                if shutil.disk_usage(destination).free<info.st_size+256*1024**2:raise ValueError('附件备份空间不足，原数据保留')
                h=hashlib.sha256()
                with os.fdopen(os.dup(fd),'rb') as old,(blob_dir/sha).open('xb') as new:
                    for block in iter(lambda:old.read(1024*1024),b''):h.update(block);new.write(block)
                (blob_dir/sha).chmod(0o600)
                if h.hexdigest()!=sha:raise ValueError('Document blob changed; retry a fresh backup after parsing/GC settles')
            finally:os.close(fd)
    # Credential files referenced by routes must survive APP replacement or data restoration.
    credentials={}
    for route in config.get('routes',{}).values():
        key=route.get('backend',{}).get('key_file')
        if key and key not in credentials:
            source=Path(key).expanduser();st=source.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077 or st.st_size>65536:
                raise ValueError('Unsafe credential source; backup paused')
            target=private_dir(destination/'secrets')/(str(len(credentials))+'.key')
            shutil.copy2(source,target);target.chmod(0o600);credentials[key]=str(target.relative_to(destination))
    inventory={}
    for path in destination.rglob('*'):
        if path.is_file():
            with path.open('rb') as stream:inventory[str(path.relative_to(destination))]=hashlib.file_digest(stream,'sha256').hexdigest()
    manifest={'version':2,'created':time.time(),'source_home':str(home),'databases':files,'files':inventory,'credential_refs':credentials,
        'restoration':'new directory only; workspace and model weights remain at their original locations',
        'workspace_bundled':False,'model_weights_bundled':False,'credentials_private':True,
        'channel_files':channel_files,'channel_restore_policy':'quarantined; no platform or owned PID is reused automatically'}
    save(destination/'manifest.json',manifest)
    return {'status':'backed_up','destination':str(destination),'databases':len(files),'data_overwritten':False}


def restore(source,destination):
    """Verify everything before creating a new installation; never overwrite a user home."""
    from pathlib import PurePosixPath
    import socket
    source=Path(source).expanduser()
    if source.is_symlink():raise ValueError('Symbolic backup directory refused')
    source=source.resolve(strict=True);destination=Path(destination).expanduser()
    if destination.exists() or destination.is_symlink():raise ValueError('恢复必须使用新的目录；不会覆盖已有数据')
    destination=destination.resolve()
    if destination.is_relative_to(source) or source.is_relative_to(destination):raise ValueError('备份与恢复目录必须独立')
    manifest=private_json(source/'manifest.json')
    if manifest.get('version')!=2 or not isinstance(manifest.get('files'),dict):
        raise ValueError('此备份缺少完整校验清单，请使用原版恢复工具；原数据保留')
    inventory=manifest['files']
    if not {'service.json','companion.json','connection.json','clients.env'}<=inventory.keys():raise ValueError('备份配置不完整')
    needed=0
    for name,digest in inventory.items():
        relative=PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or str(relative)!=name:raise ValueError('Unsafe backup path')
        path=source/name;st=path.lstat()
        if (not path.resolve().is_relative_to(source) or not stat.S_ISREG(st.st_mode)
            or st.st_uid!=os.getuid() or st.st_mode&0o077):raise ValueError('Unsafe backup file')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=digest:raise ValueError('备份校验失败，未恢复或覆盖数据')
        needed+=st.st_size
    if shutil.disk_usage(destination.parent).free<needed+256*1024**2:raise ValueError('恢复空间不足，未改动数据')
    config=private_json(source/'service.json');conn=private_json(source/'connection.json');pet=private_json(source/'companion.json')
    for route in config.get('routes',{}).values():
        key=route.get('backend',{}).get('key_file')
        if key:
            ref=manifest.get('credential_refs',{}).get(key)
            if ref not in inventory:raise ValueError('备份缺少云端凭据；未恢复')
            route['backend']['key_file']=str(destination/ref)
    destination.mkdir(mode=0o700,exist_ok=False)
    destination=private_dir(destination)
    # mkdir(parents=True, mode=700) applies mode only to the leaf. Prepare each
    # fixed private level before nested document/blob inventory entries arrive.
    private_dir(destination/'core-data')
    if any(name.startswith('documents-v2/') for name in inventory):
        private_dir(destination/'core-data/documents-v2')
        private_dir(destination/'core-data/documents-v2/blobs')
    for name in inventory:
        if name in {'core.sqlite3','companion.sqlite3','service.json','companion.json','connection.json'}:continue
        target=destination/('core-data/'+name if name.startswith(('attachment-records/','documents-v2/')) or name=='workspace-grants.json' else name)
        from .channel_paths import private_directory
        private_directory(target.parent,create=True);shutil.copy2(source/name,target);target.chmod(0o600)
    original_data=Path(config['data_dir']).resolve()
    original_logs=Path(config.get('log_dir',str(original_data/'logs'))).resolve()
    original_home=Path(manifest['source_home']).resolve()
    config['data_dir']=str(private_dir(destination/'core-data'))
    config['restore_path_migration']={'version':1,'private_roots':[
        {'source':str(original_data),'destination':config['data_dir']},
        {'source':str(original_logs),'destination':str(Path(config['data_dir'])/'logs')},
        {'source':str(original_home),'destination':str(destination)}]}
    grants_path=destination/'core-data/workspace-grants.json'
    if grants_path.exists():
        grants=private_json(grants_path)
        for grant in grants.values():grant['revoked']=True
        save(grants_path,grants)
    pet['data_dir']=str(private_dir(destination/'companion-data'))
    # Let Companion establish its own ownership marker before placing a snapshot.
    from companion.config import PrivateData
    PrivateData(pet['data_dir'])
    with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    config.update(host='127.0.0.1',port=port)
    config.pop('process_manager',None)
    if 'log_dir' in config:config['log_dir']=str(destination/'core-data/logs')
    conn['url']=f'http://127.0.0.1:{port}';pet['localpilot_endpoint']=conn['url']
    for name,folder,target in [('core.sqlite3','core-data','runtime.sqlite3'),('companion.sqlite3','companion-data','memory.sqlite3')]:
        if name in inventory:copy_database(source/name,destination/folder/target)
    for name,value in [('service.json',config),('connection.json',conn),('companion.json',pet)]:save(destination/name,value)
    quarantined=bool(manifest.get('channel_files'))
    if quarantined:
        # Migrate only fixed native-control references inside this restored home.
        # Copied process records are retained as forensics, never used to signal originals.
        forensic=private_dir(destination/'restoration-forensics')
        for path in destination.glob('message-platforms/*/generations/*/channels/configuration.json'):
            value=private_json(path);state_path=Path(value['state'])
            if not state_path.is_relative_to(original_home):raise ValueError('Channel state requires separate explicit restore; no original path is followed')
            value['state']=str(destination/state_path.relative_to(original_home))
            value['adapter']['service_url']=conn['url']
            with socket.socket() as listener:listener.bind(('127.0.0.1',0));value['port']=listener.getsockname()[1]
            save(path,value);save(path.with_name('adapter.json'),value['adapter'])
        for path in destination.glob('message-platforms/*/generations/*/channels/*.process.json'):
            relative=path.relative_to(destination);target=forensic/relative
            private_directory(target.parent,create=True);path.rename(target)
    # Channel copies are forensic data until explicitly reviewed in the new home.
    # No PID, authentication state or old service URL is activated here.
    save(destination/'restoration.json',{'version':1,'status':'restored','source':str(source),'source_home':str(original_home),
        'service_started':False,'original_data_overwritten':False,'channels_quarantined':{kind:any(name.startswith('message-platforms/'+kind+'/') or name.startswith('message-state/'+kind+'/') for name in manifest.get('channel_files',[])) for kind in ('qq','wechat')} if quarantined else False})
    return {'status':'restored','home':str(destination),'service_started':False,'original_data_overwritten':False,
            'workspace_and_models':'original locations; permissions and availability must be checked'}
