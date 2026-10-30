"""Operator-only Desktop cleanup. Dry-run by default; exact fixed roots, never unlink.
Requires the owner's explicit authorization, all backup digests verified on GitHub,
and the sole retained signed APP already installed. No WebView IPC invokes this file.
"""
from pathlib import Path
import hashlib,json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/evidence/maintenance-20261023';H=Path.home();KEEP=H/'Applications/LocalPilot.app'
original=ROOT.parent/'LocalPilot-GUI'
allowed=[]
for repo in dict.fromkeys([original,ROOT]):
    allowed += [repo/'release',repo/'src-tauri/target/debug',repo/'src-tauri/target/release',repo/'dist',repo/'test-results',repo/'tsconfig.tsbuildinfo',repo/'scripts/__pycache__']
allowed += [H/'.local/share/localpilot-desktop-builds'/v for v in ['0.2.0','0.2.1-dev.1','acceptance-maintenance-20261023']]

def fingerprint(path):
    entries=0;logical=0;allocated=0;h=hashlib.sha256()
    stack=[path]
    while stack:
        p=stack.pop();m=p.lstat();entries+=1;logical+=m.st_size;allocated+=m.st_blocks*512
        h.update(str(p.relative_to(path)).encode());h.update(str((m.st_dev,m.st_ino,m.st_mode,m.st_size,m.st_mtime_ns)).encode())
        if p.is_symlink():continue
        if p.is_dir():
            children=sorted(p.iterdir());stack.extend(reversed(children))
        elif p.is_file():
            if p.suffix.lower() in {'.db','.sqlite','.sqlite3','.safetensors','.gguf','.env','.pem','.key'} or p.name in {'clients.env','connection.json','runtime.json','preferences-v1.json'}:raise RuntimeError('Protected data found: '+str(p))
        if p.name=='.git':raise RuntimeError('Git data found: '+str(p))
    return {'entries':entries,'logical_bytes':logical,'allocated_bytes':allocated,'metadata_fingerprint':h.hexdigest()}

def running_check(paths):
    text=subprocess.check_output(['/bin/ps','-axo','pid=,command='],text=True)
    for line in text.splitlines():
        if 'trash-approved-desktop.py' in line:continue
        if any(str(p)+'/' in line for p in paths):raise RuntimeError('Running process references candidate; preserve: '+line)
        if any(x in line for x in ['cargo build','cargo check','cargo test','tauri build']):raise RuntimeError('Build/test active; preserve until idle')

def plan():
    assert KEEP.is_dir() and not KEEP.is_symlink(),'Verified keeper missing'
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(KEEP)],check=True)
    rows=[]
    for p in allowed:
        if not p.exists() and not p.is_symlink():continue
        assert p.is_absolute() and p!=KEEP and not KEEP.is_relative_to(p)
        for repo in dict.fromkeys([original,ROOT]):
            if p.is_relative_to(repo):
                tracked=subprocess.check_output(['git','-C',str(repo),'ls-files','--',str(p)],text=True)
                assert not tracked,'Tracked source protected: '+str(p)
        rows.append({'path':str(p),**fingerprint(p),'reason':'Desktop artifacts backed up by digest or reproducible generated cache from saved source/locks'})
    running_check([Path(r['path']) for r in rows])
    return {'at':int(time.time()),'mode':'DRY_RUN','keeper':str(KEEP),'candidate_count':len(rows),'allocated_upper_bytes':sum(r['allocated_bytes'] for r in rows),'logical_bytes':sum(r['logical_bytes'] for r in rows),'items':rows,'authorization':'User: 把别的全删了，要是不在GitHub上就往GitHub传一份','exclusions':['all source and worktrees','Core/Companion/Suite','user data/config/SQLite/credentials/models','unrelated projects'],'space_note':'Trash move does not immediately reclaim disk space; APFS shared extents make size an upper estimate'}

if '--execute' not in sys.argv:
    p=plan();(OUT/'approved-cleanup-dry-run.json').write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in p.items() if k!='items'},ensure_ascii=False));sys.exit()
if (OUT/'cleanup-receipt.json').exists() and json.loads((OUT/'cleanup-receipt.json').read_text()).get('status')=='PASS':
    raise SystemExit('This authorized cleanup is already complete; refuse replay. A future cleanup requires a fresh inventory and human authorization.')
backup=json.loads((OUT/'github-backup-verification.json').read_text());assert backup['status']=='PASS' and backup['matched_assets']==backup['expected_assets']
p=json.loads((OUT/'approved-cleanup-dry-run.json').read_text());assert p['mode']=='DRY_RUN' and p['authorization'].startswith('User:')
current=plan();assert current['items']==p['items'],'Candidates changed since dry-run; re-audit'
trash=H/'.Trash'/('LocalPilot-Desktop-cleanup-'+time.strftime('%Y%m%d-%H%M%S'));trash.mkdir(mode=0o700,exist_ok=False)
receipt={'at':int(time.time()),'status':'IN_PROGRESS','keeper':str(KEEP),'trash_folder':str(trash),'backup_release':backup['release_url'],'permanent_deletions':0,'items':[]}
for index,row in enumerate(p['items']):
    src=Path(row['path']);assert src in allowed;running_check([src]);assert fingerprint(src)['metadata_fingerprint']==row['metadata_fingerprint']
    dst=trash/(f'{index+1:02d}-'+('GUI-maintenance-' if src.is_relative_to(ROOT) else 'GUI-original-' if src.is_relative_to(original) else 'APP-store-')+src.name)
    assert not dst.exists();os.rename(src,dst)
    receipt['items'].append({**row,'trash_path':str(dst),'moved':True})
    (OUT/'cleanup-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
receipt['status']='PASS';receipt['moved_allocated_upper_bytes']=sum(i['allocated_bytes'] for i in receipt['items']);receipt['disk_reclaimed_now']=0
(OUT/'cleanup-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');(trash/'RESTORE-MAP.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':'PASS','moved':len(receipt['items']),'trash':str(trash),'permanent_deletions':0},ensure_ascii=False))
