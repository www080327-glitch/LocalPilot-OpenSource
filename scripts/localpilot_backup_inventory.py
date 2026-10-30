"""Read-only, name-scoped LocalPilot inventory. No unrelated file traversal.

The full manifest is private. It contains paths/hashes, never file contents.
No cleanup is implemented by this program.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import time

def discover(workspace, excluded=()):
    user=Path.home();found=[]
    for parent in (workspace, user/'Desktop', user/'Documents', user/'Applications', Path('/Applications'), user/'Downloads', user/'.Trash',
        user/'Library/Application Support',user/'Library/Caches',user/'Library/Preferences',user/'Library/WebKit',user/'Library/HTTPStorages',user/'Library/Saved Application State',user/'Library/Containers',user/'Library/Logs/DiagnosticReports',user/'.cache',user/'.local/share',user/'.config',user):
        if not parent.is_dir():continue
        for path in parent.iterdir():
            name=path.name.lower()
            if 'localpilot' not in name or name.startswith('.localpilot-backup-keys') or any(path==e or path.is_relative_to(e) for e in excluded):continue
            found.append((path,'LocalPilot name and known product location'))
    for relative in ('aic-submission',):
        path=workspace/relative
        if (path/'README.md').is_file() and 'LocalPilot' in (path/'README.md').read_text()[:4096]:found.append((path,'Verified LocalPilot AIC source/demo/materials package'))
    for name in ('COMPUTER_BACKEND_EXPANSION_PLAN.md','LONG_HORIZON_RUNTIME_REVIEW.md','EXTERNAL_AGENT_SKILL_V2.md'):
        path=workspace/name
        if path.is_file() and 'LocalPilot' in path.read_text()[:256]:found.append((path,'Verified LocalPilot planning/review document'))
    # Only Git repositories already identified as LocalPilot can reveal more worktrees.
    for path,_ in list(found):
        if not (path/'.git').exists():continue
        result=subprocess.run(['git','-C',str(path),'worktree','list','--porcelain'],capture_output=True,text=True)
        if result.returncode:continue
        for line in result.stdout.splitlines():
            if line.startswith('worktree '):
                tree=Path(line[9:])
                if tree.exists():found.append((tree,'Registered LocalPilot Git worktree'))
    launch=user/'Library/LaunchAgents'
    if launch.is_dir():
        found.extend((p,'LocalPilot launchd registration') for p in launch.glob('*localpilot*.plist'))
    # Spotlight supplies names only; no unrelated file contents are read.
    result=subprocess.run(['/usr/bin/mdfind','-onlyin',str(user),'kMDItemFSName == "*LocalPilot*"cd'],capture_output=True,text=True,timeout=60)
    if result.returncode==0:
        for name in result.stdout.splitlines():
            path=Path(name)
            if not path.exists() or any(path==e or path.is_relative_to(e) for e in excluded):continue
            if path.suffix=='.app' or (path/'.git').exists():found.append((path,'LocalPilot name from Spotlight; APP or Git identity candidate'))
    selected=[]
    for path,reason in sorted(set(found),key=lambda item:(len(item[0].parts),str(item[0]))):
        path=path.absolute()
        if any(path==root or path.is_relative_to(root) for root,_ in selected):continue
        selected.append((path,reason))
    return selected

def classify(path):
    text=str(path).lower()
    if path.suffix.lower() in {'.safetensors','.gguf','.pt','.pth'}:return 'model_weights'
    if path.suffix.lower() in {'.sqlite','.sqlite3','.db'} or '.sqlite' in path.name:return 'database_or_journal'
    if path.suffix.lower() in {'.key','.pem','.agekey'} or path.name in {'clients.env','.env'} or '/secrets/' in text:return 'credentials'
    if path.suffix.lower() in {'.dmg','.zip','.whl','.tar','.gz','.xz'}:return 'archive_or_package'
    if path.suffix.lower() in {'.py','.mjs','.js','.ts','.tsx','.rs','.swift','.md','.toml'}:return 'source_or_document'
    if '/.git/' in text:return 'git_history'
    if 'state' in text or 'checkpoint' in text or 'approval' in text:return 'private_state_possible'
    return 'product_file'

def inventory(workspace,out,excluded=()):
    out.mkdir(mode=0o700,parents=True,exist_ok=False)
    entries=out/'files.jsonl';roots=[];errors=[];models=[];git=[]
    with entries.open('x') as stream:
        for index,(root,reason) in enumerate(discover(workspace,excluded)):
            info=root.lstat();total=count=0;directory_hash=hashlib.sha256();possible=False
            pending=[root]
            while pending:
                path=pending.pop()
                if any(path==e or path.is_relative_to(e) for e in excluded):continue
                try:
                    info=path.lstat();relative=str(path.relative_to(root)) if path!=root else '.'
                    if stat.S_ISDIR(info.st_mode):
                        pending.extend(sorted(path.iterdir(),reverse=True));continue
                    record={'root':index,'relative':relative,'bytes':info.st_size,'uid':info.st_uid,
                        'mode':stat.S_IMODE(info.st_mode),'mtime_ns':info.st_mtime_ns,'type':classify(path)}
                    if stat.S_ISLNK(info.st_mode):
                        record['symlink']=os.readlink(path);record['followed']=False
                    elif stat.S_ISREG(info.st_mode):
                        with path.open('rb') as source:record['sha256']=hashlib.file_digest(source,'sha256').hexdigest()
                        after=path.stat();record['stable_during_hash']=(info.st_mtime_ns,info.st_size)==(after.st_mtime_ns,after.st_size)
                        if not record['stable_during_hash']:errors.append({'path':str(path),'code':'changed_during_hash'})
                        total+=info.st_size
                    else:
                        record['special_file_preserved_as_metadata']=True
                    count+=1;possible|=record['type'] in {'credentials','database_or_journal','private_state_possible'} or path.suffix=='.json'
                    line=json.dumps(record,ensure_ascii=True,sort_keys=True)
                    directory_hash.update(line.encode()+b'\n');stream.write(line+'\n')
                    if record['type']=='model_weights':models.append({'path':str(path),'bytes':info.st_size,'sha256':record.get('sha256'),'shared':False,'redownloadable':'UNKNOWN','license':'UNKNOWN'})
                except (OSError,ValueError) as error:
                    errors.append({'path':str(path),'code':type(error).__name__})
            owner=root.lstat().st_uid
            roots.append({'id':index,'path':str(root),'ownership_basis':reason,'owner':pwd.getpwuid(owner).pw_name,
                'bytes':total,'files':count,'directory_manifest_sha256':directory_hash.hexdigest(),
                'contains_credentials':'possible' if possible else 'not_identified','shared':False,
                'backup':'PENDING','redownloadable':'PARTIAL_OR_UNKNOWN','cleanup_class':'LocalPilot独有，备份前禁止清理',
                'deletion_authorized':False})
            if (root/'.git').exists():
                def command(args):
                    r=subprocess.run(['git','-C',str(root),*args],capture_output=True,text=True)
                    return {'exit':r.returncode,'output':r.stdout}
                git.append({'path':str(root),'head':command(['rev-parse','HEAD']),
                    'status':command(['status','--porcelain=v1','--untracked-files=all']),
                    'branches':command(['for-each-ref','--format=%(refname) %(objectname)','refs/heads']),
                    'stashes':command(['stash','list','--format=%gd %H']),'common_dir':command(['rev-parse','--path-format=absolute','--git-common-dir'])})
            print(json.dumps({'root':str(root),'files':count,'bytes':total}),flush=True)
    entries.chmod(0o600)
    summary={'version':1,'created':time.time(),'scope':'known LocalPilot names, locations, and registered worktrees only',
        'roots':roots,'total_bytes':sum(r['bytes'] for r in roots),'total_files':sum(r['files'] for r in roots),
        'errors':errors,'excluded_paths':[str(p) for p in excluded],'deletion_authorized':False,'shared_model_sources':'Separate explicit-reference manifest required'}
    for name,value in [('inventory.json',summary),('git-worktrees.json',git),('owned-models.json',models)]:
        path=out/name;path.write_text(json.dumps(value,ensure_ascii=True,indent=2)+'\n');path.chmod(0o600)
    return summary

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',required=True);parser.add_argument('--out',required=True);parser.add_argument('--exclude',action='append',default=[])
    args=parser.parse_args();result=inventory(Path(args.workspace).resolve(),Path(args.out).resolve(),tuple(Path(p).resolve() for p in args.exclude))
    print(json.dumps({'total_bytes':result['total_bytes'],'total_files':result['total_files'],'errors':len(result['errors'])}))
