"""Read-only filesystem tools restricted to a configured workspace root."""

import fnmatch
import os
import stat
from pathlib import Path

from .safety import resolve_workspace_path, sensitive_path


DEFAULT_SEARCH_MAX_RESULTS = 50
DEFAULT_SEARCH_MAX_FILE_BYTES = 1_000_000
MAX_SEARCH_ENTRIES = 5000
IGNORED_SEARCH_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules"}


def _resolve_inside_root(workspace_root, relative_path):
    return resolve_workspace_path(workspace_root, relative_path)


def read_file(workspace_root, path):
    """Read a UTF-8 text file using a path relative to workspace_root."""
    from .safe_files import entry
    resolved=resolve_workspace_path(workspace_root,path).relative_to(Path(workspace_root).resolve()).as_posix()
    with entry(workspace_root,resolved) as (parent,name):
        fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size>DEFAULT_SEARCH_MAX_FILE_BYTES:
                raise ValueError('read_file requires a regular file up to 1 MB')
            content=os.read(fd,DEFAULT_SEARCH_MAX_FILE_BYTES+1)
            after=os.fstat(fd)
            if len(content)>DEFAULT_SEARCH_MAX_FILE_BYTES or (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
                raise ValueError('File changed while reading')
            return content.decode('utf-8')
        finally: os.close(fd)


def list_directory(workspace_root, path="."):
    """List the immediate child names of a directory inside workspace_root."""
    from .safe_files import list_entries
    resolved=resolve_workspace_path(workspace_root,path).relative_to(Path(workspace_root).resolve()).as_posix()
    return [item['name'] for item in list_entries(workspace_root,resolved)]


def search_text(
    workspace_root,
    query,
    path=".",
    file_pattern="*",
    case_sensitive=True,
    max_results=DEFAULT_SEARCH_MAX_RESULTS,
):
    """Find literal text in reasonably sized UTF-8 files under the workspace."""
    if not isinstance(query, str) or not query:
        raise ValueError("query must be a non-empty string.")
    if not isinstance(file_pattern, str) or not file_pattern:
        raise ValueError("file_pattern must be a non-empty glob pattern.")
    if not isinstance(case_sensitive, bool):
        raise TypeError("case_sensitive must be a boolean.")
    if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results < 1:
        raise ValueError("max_results must be a positive integer.")

    limit = min(max_results, DEFAULT_SEARCH_MAX_RESULTS)
    root = Path(workspace_root).resolve(strict=True)
    start = _resolve_inside_root(root, path)
    if IGNORED_SEARCH_DIRS.intersection(start.relative_to(root).parts):
        return []
    if start.is_file():
        candidates = [start]
    elif start.is_dir():
        candidates = []
        entries = 0
        for current, directory_names, file_names in os.walk(start, followlinks=False):
            entries += len(directory_names) + len(file_names)
            if entries > MAX_SEARCH_ENTRIES:
                raise ValueError("Search exceeds 5000 entries; choose a smaller directory.")
            current_path = Path(current)
            directory_names[:] = [
                name
                for name in directory_names
                if name not in IGNORED_SEARCH_DIRS and not sensitive_path(current_path.relative_to(root) / name)
                and not (current_path / name).is_symlink()
            ]
            candidates.extend(current_path / name for name in file_names)
    else:
        raise FileNotFoundError(f"Not a file or directory: {path}")

    needle = query if case_sensitive else query.casefold()
    matches = []
    seen = set()
    for candidate in sorted(candidates, key=lambda item: str(item)):
        try:
            resolved = resolve_workspace_path(root, candidate.relative_to(root).as_posix())
        except (OSError, ValueError):
            continue
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        relative = resolved.relative_to(root).as_posix()
        if not fnmatch.fnmatch(Path(relative).name, file_pattern):
            continue
        try:
            if resolved.stat().st_size > DEFAULT_SEARCH_MAX_FILE_BYTES:
                continue
            content = read_file(root, resolved.relative_to(root).as_posix())
        except (OSError, UnicodeError):
            continue
        for line_number, line in enumerate(content.splitlines(), 1):
            haystack = line if case_sensitive else line.casefold()
            if needle in haystack:
                matches.append({"path": relative, "line": line_number, "text": line[:500]})
                if len(matches) >= limit:
                    return matches
    return matches


def file_info(workspace_root, path):
    from .safe_files import inspect_file
    try:
        target=resolve_workspace_path(workspace_root,path,must_exist=False)
        info=inspect_file(workspace_root,target.relative_to(Path(workspace_root).resolve()).as_posix())
        return {'path':path,'type':info['type'],'size_bytes':info['size_bytes'] if info['type']=='file' else None}
    except FileNotFoundError:
        return {"path":path,"exists":False,"observation":"target_not_found",
                "scope":"filesystem observation only; no goal verification"}
