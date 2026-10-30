"""Structured exact-match text patches with previews and hash receipts."""

import difflib
import hashlib
import json
import os
from pathlib import Path
import tempfile
import stat
import uuid
from .safe_files import entry, inspect_file

from .safety import PermissionGateway, resolve_workspace_path
from .file_locks import lock_paths

MAX_FILE_BYTES = 1_000_000
MAX_CHANGES = 20
MAX_PATCH_BYTES = 2_000_000


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _read_bytes(path):
    with entry('/',str(path).lstrip('/')) as (parent,name):
        fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        try:
            before=os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size>MAX_FILE_BYTES or before.st_nlink!=1:
                raise ValueError('Patch targets require a regular, singly linked file at most 1 MB')
            data=os.read(fd,MAX_FILE_BYTES+1)
            after=os.fstat(fd)
            if len(data)>MAX_FILE_BYTES or (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):
                raise ValueError('Patch target changed while reading')
            return data
        finally:os.close(fd)


def apply_patch(workspace_root, changes, *, gateway=None):
    """Preflight every change, authorize the whole batch, then write per file."""
    gateway = gateway or PermissionGateway(workspace_root)
    gateway._patch_effect_started = False
    if Path(workspace_root).resolve() != gateway.root:
        raise ValueError("Gateway workspace does not match tool workspace.")
    if not gateway.capabilities.write:
        # A disabled write capability must not expose file content through a diff preview.
        return gateway.decide("apply_patch", "medium", ["Write capability is disabled."], {}, blocked=True)
    if not isinstance(changes, list) or not 1 <= len(changes) <= MAX_CHANGES:
        raise ValueError(f"changes must contain 1 to {MAX_CHANGES} objects")
    if len(json.dumps(changes, ensure_ascii=False).encode("utf-8")) > MAX_PATCH_BYTES:
        raise ValueError("Patch request exceeds 2 MB total byte budget")
    prepared = []
    seen = set()
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("Each change must be an object")
        operation = change.get("operation")
        allowed = {"path", "operation", "expected_sha256"}
        allowed |= {"content"} if operation == "create" else ({"old_text", "new_text"} if operation == "update" else set())
        if set(change) - allowed or operation not in {"create", "update", "delete"}:
            raise ValueError("Unsupported patch operation or fields")
        target = resolve_workspace_path(gateway.root, change.get("path"), must_exist=False, writing=True)
        if target == gateway.root or target in seen:
            raise ValueError("Patch paths must be distinct files, not the workspace root")
        seen.add(target)
        if not target.parent.is_dir():
            raise ValueError("Parent directory must already exist")
        if operation == "create":
            if target.exists():
                raise FileExistsError(change["path"])
            before = b""
            content = change.get("content")
            if not isinstance(content, str):
                raise ValueError("create requires UTF-8 content")
            after = content.encode("utf-8")
        else:
            before = _read_bytes(target)
            text = before.decode("utf-8")
            if operation == "delete":
                if not change.get("expected_sha256"):
                    raise ValueError("delete requires expected_sha256 from an inspected file")
                after = None
            else:
                old, new = change.get("old_text"), change.get("new_text")
                if not isinstance(old, str) or not old or not isinstance(new, str):
                    raise ValueError("update requires non-empty old_text and string new_text")
                if text.count(old) != 1:
                    raise ValueError("old_text must match exactly once; re-read the file")
                after = text.replace(old, new, 1).encode("utf-8")
        if "expected_sha256" in change and change["expected_sha256"] != _hash(before):
            raise ValueError("Patch hash mismatch; re-read the file")
        if len(before) > MAX_FILE_BYTES or (after is not None and len(after) > MAX_FILE_BYTES):
            raise ValueError("Patch files must be at most 1 MB")
        receipt = {
            "path": target.relative_to(gateway.root).as_posix(), "operation": operation,
            "before_sha256": _hash(before) if operation != "create" else None,
            "before_identity":inspect_file(gateway.root,change["path"]) if operation!="create" else None,
            "after_sha256": _hash(after) if after is not None else None,
            "diff": "".join(difflib.unified_diff(before.decode("utf-8").splitlines(True),
                         (after or b"").decode("utf-8").splitlines(True),
                         fromfile=change["path"], tofile=change["path"]))[:4000],
        }
        prepared.append((target, before, after, receipt))
    deleting = any(item[3]["operation"] == "delete" for item in prepared)
    decision = gateway.decide("apply_patch", "high" if deleting else "medium",
        ["Deletes inspected files." if deleting else "Creates or changes workspace text files; changed code may execute later."],
        {"changes": changes, "versions": [{k:v for k,v in item[3].items() if k!="diff"} for item in prepared]})
    receipts = [item[3] for item in prepared]
    if decision["status"] != "allowed":
        return {**decision, "changes": receipts}
    applied = []
    try:
        with lock_paths(item[0] for item in prepared):
            # Revalidate the entire approved batch under ownership. A conflict
            # never retries/merges an old proposal or partially applies this batch.
            for target, before, after, receipt in prepared:
                resolve_workspace_path(gateway.root, receipt["path"], must_exist=False, writing=True)
                if receipt["operation"] == "create":
                    if target.exists():
                        raise FileExistsError("File appeared since patch preflight; re-read and request approval")
                elif _read_bytes(target) != before:
                    raise ValueError("File changed since patch preflight; re-read and request approval")
            gateway._patch_effect_started = True
            return _commit_prepared(gateway, prepared, decision, applied)
    except (OSError, ValueError) as error:
        return {"status": "error", "error": {"type": type(error).__name__, "message": str(error)},
                "applied": applied, "failed_path": receipt["path"], "risk_summary": decision["risk_summary"]}


def _commit_prepared(gateway, prepared, decision, applied):
    for target, before, after, receipt in prepared:
        temporary=None;sent=False
        try:
            with entry(gateway.root,receipt['path']) as (parent,name):
                if receipt['operation']!='create' and _read_bytes(target)!=before:
                    raise ValueError('File changed since patch preflight')
                if after is None:
                    os.unlink(name,dir_fd=parent);sent=True
                    try:os.stat(name,dir_fd=parent,follow_symlinks=False)
                    except FileNotFoundError:pass
                    else:raise ValueError('Deleted target was recreated')
                elif receipt['operation']=='create':
                    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent);sent=True
                    with os.fdopen(fd,'wb') as stream:stream.write(after);stream.flush();os.fsync(stream.fileno())
                else:
                    temporary='.localpilot-'+uuid.uuid4().hex
                    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
                    with os.fdopen(fd,'wb') as stream:
                        stream.write(after);stream.flush();os.fsync(stream.fileno())
                        info=os.stat(name,dir_fd=parent,follow_symlinks=False)
                        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('Target identity changed')
                        os.fchmod(stream.fileno(),info.st_mode&0o777)
                    os.replace(temporary,name,src_dir_fd=parent,dst_dir_fd=parent);sent=True;temporary=None
                if after is not None:
                    current=inspect_file(gateway.root,receipt['path'])
                    if current.get('sha256')!=receipt['after_sha256']:raise ValueError('Post-patch verification mismatch')
                    receipt['after_identity']=current
                receipt['verification']='passed'
                applied.append(receipt)
                gateway.record({'operation':'apply_patch','status':'applied',**{k:v for k,v in receipt.items() if k!='diff'}})
                if temporary is not None:os.unlink(temporary,dir_fd=parent);temporary=None
        except (OSError,ValueError) as error:
            return {'status':'unknown' if sent else 'error','error':{'type':type(error).__name__,'message':str(error)},
                'action_sent':sent or bool(applied),'action_may_have_applied':sent,'replay_allowed':False,
                'applied':applied,'failed_path':receipt['path'],'risk_summary':decision['risk_summary']}
        finally:
            if temporary is not None:
                try:
                    with entry(gateway.root,receipt['path']) as (parent,name):os.unlink(temporary,dir_fd=parent)
                except OSError:pass
    return {'status':'ok','changes':applied,'risk_summary':decision['risk_summary']}
