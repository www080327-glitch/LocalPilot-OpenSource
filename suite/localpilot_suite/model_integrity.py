"""Read-only model integrity checks against public Hugging Face blob metadata."""
import hashlib
import json
from pathlib import Path,PurePosixPath
import re
import time
from urllib.parse import quote
from urllib.request import Request,urlopen
from localpilot_service.cli import private_dir,save
from localpilot_service.security import private_json


def metadata(repo,revision):
    url='https://huggingface.co/api/models/'+quote(repo,safe='/')+'/revision/'+quote(revision,safe='')+'?blobs=true'
    with urlopen(Request(url,headers={'User-Agent':'LocalPilot-Model-Manager/1'}),timeout=45) as response:
        payload=response.read(8*1024*1024+1)
    if len(payload)>8*1024*1024:raise ValueError('Model metadata exceeds the verification budget')
    return json.loads(payload)


def check_files(root,info):
    records=[];total=0
    for row in info.get('siblings',[]):
        name=row.get('rfilename','');relative=PurePosixPath(name)
        if not name or relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe repository filename')
        # Native model configuration, tokenizer and weights; no code is run.
        if not (name.endswith(('.safetensors','.json','.model','.txt','.tiktoken','.bin','.jinja'))):continue
        expected=(row.get('lfs') or {}).get('sha256')
        git_hash=row.get('blobId')
        path=root/str(relative)
        if not path.is_file():raise ValueError('Downloaded model is missing a required file: '+name)
        before=path.stat();size=before.st_size
        if expected and re.fullmatch('[0-9a-f]{64}',expected):digest=hashlib.sha256();kind='sha256'
        elif isinstance(git_hash,str) and re.fullmatch('[0-9a-f]{40}',git_hash):digest=hashlib.sha1();digest.update(('blob '+str(size)+'\0').encode());expected=git_hash;kind='git_blob_sha1'
        else:raise ValueError('Upstream hash is unavailable: '+name)
        with path.open('rb') as f:
            while data:=f.read(1024*1024):digest.update(data)
        after=path.stat()
        if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('Model changed during verification')
        actual=digest.hexdigest()
        if actual!=expected:raise ValueError('Model checksum mismatch: '+name)
        total+=size;records.append({'name':name,'bytes':size,'hash_type':kind,'hash':actual})
    if not any(r['name'].endswith(('.safetensors','.bin')) for r in records):raise ValueError('No verifiable model weights were found')
    return {'files':records,'bytes':total}


def verify(admin,home,repo):
    candidates=[m for m in admin.request('/admin/api/models').get('models',[]) if m.get('source_repo_id')==repo or m.get('id') in {repo.split('/')[-1],repo.replace('/','--')}]
    if not candidates:raise ValueError('Downloaded model has not been discovered; refresh model management first')
    model=next((m for m in candidates if m.get('source_repo_id')==repo),candidates[0])
    root=Path(model['model_path']).resolve(strict=True)
    revision=root.name if re.fullmatch('[0-9a-f]{40}',root.name) else 'main'
    path=private_dir(home)/'model-integrity.json';records=private_json(path) if path.exists() else {}
    record={'repo_id':repo,'model':model['id'],'at':time.time(),'status':'UNKNOWN','evidence_kind':'LOCAL_FILE_HASH_VS_UPSTREAM_METADATA','cloud_file_upload':False}
    try:
        info=metadata(repo,revision);record['revision']=info.get('sha')
        record.update(check_files(root,info),status='passed')
    except Exception as e:
        record.update(status='failed' if isinstance(e,ValueError) and any(k in str(e) for k in ['checksum mismatch','changed during','missing a required','Unsafe repository']) else 'UNKNOWN',error=str(e)[:300]);records[model['id']]=record;save(path,records);raise
    records[model['id']]=record;save(path,records)
    return record
