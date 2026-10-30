"""Bounded descriptor-relative workspace operations; no shell or overwrite."""
from contextlib import contextmanager
import ctypes
import errno
import hashlib
import os
from pathlib import Path
import stat
import sys
from .safety import sensitive_path

MAX_FILE_BYTES = 64 * 1024 * 1024

@contextmanager
def entry(root, path):
    if not isinstance(path, str) or not path or Path(path).is_absolute() or '..' in Path(path).parts or '\x00' in path or sensitive_path(path):
        raise ValueError('Exact unprotected workspace-relative path required')
    parts = Path(path).parts
    fds = [os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
    try:
        for part in parts[:-1]:
            fds.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fds[-1]))
        yield fds[-1], parts[-1] if parts else '.'
    finally:
        for fd in reversed(fds): os.close(fd)

def identity(info):
    return dict(device=info.st_dev, inode=info.st_ino, size_bytes=info.st_size,
                modified_ns=info.st_mtime_ns, type='file' if stat.S_ISREG(info.st_mode) else 'directory' if stat.S_ISDIR(info.st_mode) else 'unsupported')

def digest_fd(fd):
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
        raise ValueError('Only regular files up to 64 MiB are supported')
    os.lseek(fd, 0, 0); sha = hashlib.sha256(); count = 0
    while True:
        chunk = os.read(fd, 65536)
        if not chunk: break
        count += len(chunk)
        if count > MAX_FILE_BYTES: raise ValueError('File grew beyond limit')
        sha.update(chunk)
    if identity(before) != identity(os.fstat(fd)): raise ValueError('File changed while inspecting')
    return {**identity(before), 'sha256':sha.hexdigest()}

def inspect_file(workspace_root, path):
    with entry(workspace_root, path) as (parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            return {'path':path, 'exists':True, **(digest_fd(fd) if stat.S_ISREG(info.st_mode) else identity(info))}
        finally: os.close(fd)

def list_entries(workspace_root, path='.'):
    with entry(workspace_root, path) as (parent,name):
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            names = os.listdir(fd)
            if len(names)>1000: raise ValueError('Choose a directory with at most 1000 entries')
            return [{'name':name, **identity(os.stat(name, dir_fd=fd, follow_symlinks=False))} for name in sorted(names) if not sensitive_path(name)]
        finally: os.close(fd)

def make_directory(workspace_root, path):
    sent = False
    try:
        with entry(workspace_root,path) as (parent,name):
            os.mkdir(name, 0o700, dir_fd=parent); sent=True
            after=identity(os.stat(name, dir_fd=parent, follow_symlinks=False))
            if after['type']!='directory': raise ValueError('Directory changed after creation')
            return {'status':'ok','operation':'mkdir','source':None,'destination':path,'before':None,'after':after,
                    'verification':'passed','action_sent':True,'undo':{'operation':'remove_empty_directory','path':path,'expected_identity':after}}
    except Exception as exc:
        return failure(sent, exc)

def failure(sent, exc):
    return {'status':'unknown' if sent else 'error','verification':'UNKNOWN' if sent else 'FAIL',
            'action_sent':sent,'action_may_have_applied':sent,'replay_allowed':False,'error_type':type(exc).__name__}

def rename_exclusive(sp,sn,dp,dn):
    libc=ctypes.CDLL(None,use_errno=True)
    if sys.platform=='darwin':
        fn=libc.renameatx_np; flags=4 # RENAME_EXCL; never replace an existing destination.
    elif sys.platform.startswith('linux') and hasattr(libc,'renameat2'):
        fn=libc.renameat2; flags=1
    else: raise ValueError('Atomic no-replace rename unavailable on this platform')
    fn.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    if fn(sp,os.fsencode(sn),dp,os.fsencode(dn),flags):
        err=ctypes.get_errno(); raise OSError(err,os.strerror(err))

def transfer(workspace_root, source, destination, expected_sha256, *, moving):
    sent=False; source_fd=None; target_fd=None
    try:
        if source==destination: raise ValueError('Source and destination must differ')
        with entry(workspace_root,source) as (sp,sn), entry(workspace_root,destination) as (dp,dn):
            source_fd=os.open(sn,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=sp)
            before=digest_fd(source_fd)
            if os.fstat(source_fd).st_nlink!=1 or before['sha256']!=expected_sha256:
                raise ValueError('Current source hash or link count differs; inspect again')
            if moving:
                if identity(os.stat(sn,dir_fd=sp,follow_symlinks=False))!={k:v for k,v in before.items() if k!='sha256'}:
                    raise ValueError('Source identity changed')
                rename_exclusive(sp,sn,dp,dn); sent=True
            else:
                target_fd=os.open(dn,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=dp); sent=True
                os.lseek(source_fd,0,0); count=0
                while True:
                    chunk=os.read(source_fd,65536)
                    if not chunk: break
                    count+=len(chunk)
                    if count>MAX_FILE_BYTES: raise ValueError('Source grew beyond limit')
                    view=memoryview(chunk)
                    while view: view=view[os.write(target_fd,view):]
                os.fsync(target_fd)
            fd=os.open(dn,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=dp)
            try: after=digest_fd(fd)
            finally: os.close(fd)
            if after['sha256']!=before['sha256'] or (moving and (after['device'],after['inode'])!=(before['device'],before['inode'])) or digest_fd(source_fd)!=before:
                raise ValueError('Post-operation content or identity differs')
            if moving:
                try: os.stat(sn,dir_fd=sp,follow_symlinks=False)
                except FileNotFoundError: pass
                else: raise ValueError('Source was recreated')
            return {'status':'ok','operation':'move' if moving else 'copy','source':source,'destination':destination,
                'before':before,'after':after,'verification':'passed','action_sent':True,
                'undo':{'operation':'move' if moving else 'remove_copy','source':destination,'destination':source if moving else None,'expected_identity':after}}
    except Exception as exc: return failure(sent,exc)
    finally:
        for fd in (target_fd,source_fd):
            if fd is not None: os.close(fd)

def move_file(workspace_root, source, destination, expected_sha256):
    return transfer(workspace_root,source,destination,expected_sha256,moving=True)

def copy_file(workspace_root, source, destination, expected_sha256):
    return transfer(workspace_root,source,destination,expected_sha256,moving=False)
