"""Private draft upload with actual download/hash checks and resumable receipts.
Only age chunks/public index are uploaded. No key, plaintext private metadata,
source deletion, asset replacement, publication or Latest mutation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

REPO='www080327-glitch/LocalPilot'
API='repos/'+REPO


def api(path,body=None):
    args=['gh','api',path]+(['--input','-'] if body is not None else [])
    for attempt in range(4 if body is None else 1):
        try:
            result=subprocess.run(args,input=None if body is None else json.dumps(body),capture_output=True,text=True,timeout=90)
            if result.returncode==0:return json.loads(result.stdout)
            detail=result.stderr[:300]
        except subprocess.TimeoutExpired:detail='request timed out'
        if body is not None or attempt==3:raise RuntimeError('GITHUB_API_FAILED:'+detail)
        time.sleep(3*(attempt+1))


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def private_json(path,value):
    temporary=path.with_name(path.name+'.new-'+uuid.uuid4().hex)
    temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.chmod(0o600);os.replace(temporary,path)


def main():
    parser=argparse.ArgumentParser()
    for name in ('input','download','producer-error'):parser.add_argument('--'+name,type=Path,required=True)
    for name in ('tag','target'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--deadline-seconds',type=int,default=14400)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();source=args.input.resolve(strict=True);out=args.download.resolve()
    if not re.fullmatch('[a-f0-9]{40}',args.target):raise ValueError('Use a verified full commit SHA')
    repository=api(API)
    if not repository['private'] or not repository['permissions']['push']:raise RuntimeError('Authorized private writable repository required')
    if api(API+'/commits/'+args.target)['sha']!=args.target:raise RuntimeError('Commit not present in authorized repository')
    out.mkdir(mode=0o700,parents=True,exist_ok=args.resume)
    if out.stat().st_mode&0o077 or out.stat().st_uid!=os.getuid():raise RuntimeError('Private owned download directory required')
    releases=api(API+'/releases?per_page=100');release=next((r for r in releases if r['tag_name']==args.tag),None)
    if release is None:
        release=api(API+'/releases',{'tag_name':args.tag,'target_commitish':args.target,'name':'LocalPilot encrypted backup 2026-10-28 — INCOMPLETE until restore verified','body':'Private encrypted recovery volume. Complete-set qualification requires fresh downloads, authenticated restoration and coverage receipts. Never upload the age identity. No source deletion authorized.','draft':True,'prerelease':True,'make_latest':'false'})
    if not release['draft'] or release['target_commitish']!=args.target:raise RuntimeError('Draft/target identity differs')
    identity={key:release[key] for key in ('id','tag_name','html_url','draft','target_commitish')}
    if (out/'release.json').exists() and json.loads((out/'release.json').read_text())!=identity:raise RuntimeError('Existing download belongs to another release')
    private_json(out/'release.json',identity)
    receipts=json.loads((out/'asset-receipts.json').read_text())['assets'] if args.resume and (out/'asset-receipts.json').exists() else []
    seen=set()
    for row in receipts:
        p=out/row['name']
        if not p.is_file() or p.stat().st_size!=row['bytes'] or sha(p)!=row['sha256']:raise RuntimeError('Resumed verified download differs')
        seen.add(row['name'])
    staging=out/'upload-staging';staging.mkdir(mode=0o700,exist_ok=True)
    deadline=time.monotonic()+args.deadline_seconds
    def transfer(path,expected=None):
        if not (path.name=='backup-index.json' or path.name.startswith('localpilot-full.tar.gz.age.part')):raise ValueError('Only ciphertext and public index are uploadable')
        size=path.stat().st_size;digest=sha(path)
        if expected and (size!=expected['bytes'] or digest!=expected['sha256']):raise RuntimeError('Local encrypted input differs')
        if size>=2*1024**3:raise RuntimeError('Asset exceeds bounded release limit')
        if not api(API)['private']:raise RuntimeError('Repository is no longer private')
        current=api(API+'/releases/'+str(release['id']))
        if not current['draft'] or len(current['assets'])>=1000:raise RuntimeError('Draft/asset capacity guard')
        asset=next((r for r in current['assets'] if r['name'].startswith(path.name) and r['size']==size and r['state']=='uploaded' and (not r.get('digest') or r['digest']=='sha256:'+digest)),None)
        for attempt in range(3):
            if asset:break
            names={r['name'] for r in current['assets']};upload=path
            if path.name in names or attempt:
                upload=staging/(path.name+'.retry-'+uuid.uuid4().hex[:10]);os.link(path,upload)
            try:result=subprocess.run(['gh','release','upload',args.tag,str(upload),'--repo',REPO],capture_output=True,text=True,timeout=3600)
            except subprocess.TimeoutExpired:result=None
            # An uncertain upload is reconciled by immutable name/size/digest.
            current=api(API+'/releases/'+str(release['id']));asset=next((r for r in current['assets'] if r['name']==upload.name and r['state']=='uploaded' and r['size']==size and (not r.get('digest') or r['digest']=='sha256:'+digest)),None)
            if not asset and attempt==2:raise RuntimeError('ENCRYPTED_ASSET_UPLOAD_FAILED; attempts retained')
        if not asset:raise RuntimeError('Uploaded asset not confirmed')
        final=out/path.name
        # Always obtain a new remote copy unless this run already has its receipt.
        for attempt in range(3):
            partial=out/(path.name+'.download-'+uuid.uuid4().hex[:10]);partial.touch(mode=0o600,exist_ok=False)
            try:
                with partial.open('wb') as stream:result=subprocess.run(['gh','api','-H','Accept: application/octet-stream',API+'/releases/assets/'+str(asset['id'])],stdout=stream,stderr=subprocess.PIPE,timeout=3600)
                good=result.returncode==0 and partial.stat().st_size==size and sha(partial)==digest
            except subprocess.TimeoutExpired:good=False
            if good:
                if final.exists():
                    # Preserve a pre-existing attempt, including a local descriptor.
                    final.rename(out/(final.name+'.previous-'+uuid.uuid4().hex[:10]))
                os.replace(partial,final);break
            if attempt==2:raise RuntimeError('REMOTE_DOWNLOAD_SIZE_OR_HASH_FAILED; attempts retained')
        row={'name':path.name,'remote_asset_name':asset['name'],'asset_id':asset['id'],'bytes':size,'sha256':digest,'remote_digest':asset.get('digest'),'fresh_download_sha256_verified':True}
        receipts.append(row);seen.add(path.name);private_json(out/'asset-receipts.json',{'release_id':release['id'],'repository':REPO,'private':True,'assets':receipts,'key_uploaded':False,'publication':False});print(json.dumps({'transferred':path.name,'bytes':size,'download_verified':True}),flush=True)
    while time.monotonic()<deadline:
        index=source/'backup-index.json'
        if index.exists():
            data=json.loads(index.read_text())
            if len(data['chunks'])+1>=1000:raise RuntimeError('Encrypted set exceeds release asset capacity')
            for row in data['chunks']:
                if row['name'] not in seen:transfer(source/row['name'],row)
            if index.name not in seen:transfer(index)
            print(json.dumps({'status':'REMOTE_DOWNLOAD_VERIFIED_RESTORE_STILL_REQUIRED','assets':len(receipts),'release_id':release['id']}),flush=True);return
        if args.producer_error.exists() and args.producer_error.stat().st_size:raise RuntimeError('LOCAL_PRODUCER_REPORTED_ERROR; draft incomplete')
        for path in sorted(source.glob('localpilot-full.tar.gz.age.part*')):
            if path.name not in seen and path.stat().st_size==1024**3 and time.time()-path.stat().st_mtime>5:transfer(path)
        time.sleep(10)
    raise RuntimeError('TRANSFER_DEADLINE; incomplete data retained')


if __name__=='__main__':main()
