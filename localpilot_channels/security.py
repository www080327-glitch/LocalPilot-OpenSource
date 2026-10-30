"""Private paths. Only fixed, root-owned Darwin filesystem aliases are trusted."""
import json
import os
from pathlib import Path
import stat
import sys

_DARWIN_ALIASES = {'/var': '/private/var', '/tmp': '/private/tmp', '/etc': '/private/etc'}


def canonical_path(value):
    raw = Path(value).expanduser()
    if '..' in raw.parts:
        raise ValueError('parent_traversal_rejected')
    raw = raw.absolute()
    current = Path(raw.anchor)
    for name in raw.parts[1:]:
        current = current / name
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            target = _DARWIN_ALIASES.get(str(current))
            if not (sys.platform == 'darwin' and target and info.st_uid == 0
                    and os.path.normpath(os.path.join(str(current.parent), os.readlink(current))) == target):
                raise ValueError('state_link_rejected')
            current = Path(target)
            trusted = current.lstat()
            if not stat.S_ISDIR(trusted.st_mode) or trusted.st_uid != 0 or trusted.st_mode & 0o022:
                raise ValueError('untrusted_system_alias')
        elif hasattr(current, 'is_junction') and current.is_junction():
            raise ValueError('state_link_rejected')
    return current


def private_directory(value, *, create=False):
    root = canonical_path(value)
    # Check ancestors BEFORE creating anything. Sticky root-owned system temp
    # directories are permitted; the final state directory must be owner-only.
    for parent in reversed((root, *root.parents)):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            if not create:
                raise
            parent.mkdir(mode=0o700)
            info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError('state_directory_required')
        if os.name != 'nt':
            if info.st_uid not in {0, os.getuid()}:
                raise ValueError('state_parent_owner_invalid')
            if info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
                raise ValueError('state_parent_writable')
    info = root.stat()
    if os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError('state_directory_must_be_owner_only')
    return root


def private_file(value, *, create=False):
    path = canonical_path(value)
    try:
        info = path.lstat()
    except FileNotFoundError:
        if not create:
            return path
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('state_private_regular_file_required')
    if os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError('state_file_must_be_owner_only')
    return path


def private_json(value):
    path = private_file(value)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1048576:
            raise ValueError('invalid_private_json')
        if os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise ValueError('invalid_private_json_permissions')
        with os.fdopen(fd, 'r', encoding='utf-8', closefd=False) as stream:
            return json.load(stream)
    finally:
        os.close(fd)
