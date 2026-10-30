"""Fetch a published recovery descriptor's exact private GitHub assets.

No private key is used here. Every asset must match recorded size and SHA256;
partial attempts are retained. Restoration is a separate explicit operation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

REPO='www080327-glitch/LocalPilot'


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def api(path):
    for attempt in range(4):
        result=subprocess.run(['gh','api',path],capture_output=True,text=True,timeout=90)
        if result.returncode==0:return json.loads(result.stdout)
        if attempt==3:raise RuntimeError('GitHub metadata unavailable; no verification success')
        time.sleep(3*(attempt+1))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--descriptor',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();descriptor=json.loads(args.descriptor.read_text())
    if descriptor['repository']!=REPO:raise RuntimeError('Recovery destination repository differs')
    repository=api('repos/'+REPO)
    if not repository['private']:raise RuntimeError('Expected private repository')
    output=args.out.resolve();output.mkdir(mode=0o700,parents=True,exist_ok=args.resume)
    if output.stat().st_mode&0o077 or output.stat().st_uid!=os.getuid():raise RuntimeError('Private owned output required')
    receipts=[]
    for volume in descriptor['volumes']:
        root=output/volume['name'];root.mkdir(mode=0o700,exist_ok=args.resume)
        for item in volume['assets']:
            name=item['name']
            if Path(name).name!=name or name in {'.','..'}:raise RuntimeError('Unsafe recovery filename')
            path=root/name
            if path.exists():
                if not args.resume or path.stat().st_size!=item['bytes'] or sha(path)!=item['sha256']:raise RuntimeError('Existing recovery file differs')
            else:
                metadata=api('repos/'+REPO+'/releases/assets/'+str(item['asset_id']))
                if metadata['size']!=item['bytes'] or metadata['state']!='uploaded':raise RuntimeError('Remote asset incomplete')
                if metadata.get('digest') and metadata['digest']!='sha256:'+item['sha256']:raise RuntimeError('Remote digest differs')
                for attempt in range(3):
                    partial=root/(name+'.partial-'+uuid.uuid4().hex);partial.touch(mode=0o600,exist_ok=False)
                    try:
                        with partial.open('wb') as stream:r=subprocess.run(['gh','api','-H','Accept: application/octet-stream','repos/'+REPO+'/releases/assets/'+str(item['asset_id'])],stdout=stream,stderr=subprocess.PIPE,timeout=3600)
                        good=r.returncode==0 and partial.stat().st_size==item['bytes'] and sha(partial)==item['sha256']
                    except subprocess.TimeoutExpired:good=False
                    if good:os.replace(partial,path);break
                    if attempt==2:raise RuntimeError('Download validation failed; attempts preserved')
            receipts.append({'volume':volume['name'],'name':name,'sha256':item['sha256'],'verified':True})
            print(json.dumps(receipts[-1]),flush=True)
    result={'status':'RECOVERY_SET_DOWNLOAD_VERIFIED','repository':REPO,'assets':receipts,'private_key_used_or_uploaded':False,'restoration_performed':False}
    destination=output/('download-verification-'+str(time.time_ns())+'.json');destination.write_text(json.dumps(result,indent=2)+'\n');destination.chmod(0o600)


if __name__=='__main__':main()
