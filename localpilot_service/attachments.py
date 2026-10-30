"""Operator-mediated local ingestion. No file contents or pixels go to a provider here."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
from localpilot_api.service import APIError
from agent.safety import sensitive_path
MAX_BATCH_BYTES=2*1024**3

def credential_source(path):
    return sensitive_path(path) or any(p in {'secrets','.aws','.gnupg','Keychains'} for p in path.parts) or path.name=='clients.env' or path.suffix.lower() in {'.key','.pem','.p12','.pfx'}

def ingest(server, principal, body):
    if not principal.operator or "control" not in principal.scopes:raise APIError("Host operator required","control_required",403)
    if not isinstance(body,dict) or set(body)!={"client_subject","model","paths"}:raise APIError("Exact attachment authorization required")
    subject=body["client_subject"]
    if subject not in principal.approval_for:raise APIError("Subject denied","scope_forbidden",403)
    client=server.access.principals[subject]
    if body['model'] not in client.routes:raise APIError("Unknown route","model_not_registered",404)
    paths=body['paths']
    if not isinstance(paths,list) or not paths or any(not isinstance(p,str) or not 0<len(p)<=4096 or '\x00' in p for p in paths):raise APIError("Valid file references required")
    store=getattr(server.service,'store',None)
    if store is None:raise APIError('Attachment provenance requires persistent Core storage','attachment_persistence_required',503)
    # Factory inspection creates no inference, tool execution or second Runtime.
    runtime=server.service.routes[client.routes[body['model']]](lambda e:None)
    try:workspace=runtime.workspace.resolve(strict=True)
    finally:runtime.close()
    sources=[];total=0
    for raw in paths:
        p=Path(raw).expanduser()
        if not p.is_absolute() or p.is_symlink() or credential_source(p):raise APIError("Protected or symbolic source denied","attachment_source_denied",403)
        p=p.resolve(strict=True)
        if not p.is_file() or credential_source(p):raise APIError("Ordinary files only","attachment_source_denied",403)
        st=p.stat()
        if st.st_uid!=os.getuid():raise APIError("Source ownership denied","attachment_source_denied",403)
        total+=st.st_size;sources.append((p,st))
    if total>MAX_BATCH_BYTES or shutil.disk_usage(workspace).free<total+2*1024**3:raise APIError("Attachment resource budget exceeded","attachment_budget_exceeded",413)
    if sum(len(str(p).encode())*3+len(p.name.encode())+900 for p,_ in sources)>8*1024**2:raise APIError('Attachment metadata exceeds the 8 MiB request budget; split this batch','attachment_metadata_budget_exceeded',413)
    base=workspace/'LocalPilot Attachments';base.mkdir(exist_ok=True,mode=0o700)
    if base.is_symlink():raise APIError("Attachment destination denied","attachment_source_denied",403)
    batch=base/uuid.uuid4().hex;batch.mkdir(mode=0o700)
    records=[]
    for p,before in sources:
        fid=uuid.uuid4().hex;dest=batch/(fid+p.suffix[:24]);digest=hashlib.sha256();count=0
        # O_NOFOLLOW and fd identity protect source replacement during selection.
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as src, dest.open('xb') as out:
            now=os.fstat(src.fileno())
            if (now.st_dev,now.st_ino,now.st_size)!=(before.st_dev,before.st_ino,before.st_size):raise APIError("Source changed; select again","attachment_changed",409)
            while chunk:=src.read(1024*1024):
                count+=len(chunk)
                if count>before.st_size:raise APIError("Source grew during ingestion","attachment_changed",409)
                digest.update(chunk);out.write(chunk)
            after=os.fstat(src.fileno())
            if count!=before.st_size or after.st_mtime_ns!=before.st_mtime_ns:raise APIError("Source changed during ingestion","attachment_changed",409)
        dest.chmod(0o600)
        records.append({'id':fid,'name':p.name,'size':count,'sha256':digest.hexdigest(),'source':str(p),'permission_source':'explicit_native_file_selection','workspace_path':str(dest.relative_to(workspace)),'representation':'controlled_local_file','parsed_text':False,'multimodal_submitted':False})
    manifest=batch/'manifest.json';payload={'version':1,'subject':subject,'files':records,'manifest':str(manifest.relative_to(workspace)),'batch_id':batch.name}
    manifest.write_text(json.dumps(payload,ensure_ascii=False));manifest.chmod(0o600)
    # The workspace manifest is untrusted model-visible data; keep immutable
    # provenance separately under Core's private persistence directory.
    from .cli import private_dir,save
    canonical=private_dir(Path(store.path).parent/'attachment-records')
    save(canonical/(batch.name+'.json'),payload)
    server.access.audit(operation='attachment_import',subject=principal.subject,client_subject=subject,count=len(records),bytes=total)
    return {'version':1,'batch_id':batch.name,'files':records,'manifest':str(manifest.relative_to(workspace)),'cloud_uploaded':False,'multimodal_submitted':False}
