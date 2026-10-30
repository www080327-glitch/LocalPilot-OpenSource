"""Read-only full-machine Desktop inventory. Writes only the requested docs evidence.
No deletion, model access, database reads, process control, or credentials in output.
"""
from pathlib import Path
import hashlib,json,os,plistlib,re,subprocess,sys,time,tempfile
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/evidence/maintenance-20261023'
if '--post-cleanup' in sys.argv:
    OUT=OUT/'post-cleanup';OUT.mkdir(exist_ok=True)

def cmd(args,timeout=20):
    try:
        r=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
        return {'exit':r.returncode,'stdout':r.stdout,'stderr':r.stderr}
    except Exception as e:return {'exit':None,'error':type(e).__name__}
def digest(p):
    try:
        with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
    except OSError:return None
def sizes(p):
    m=p.lstat();logical=m.st_size;allocated=m.st_blocks*512
    if p.is_dir() and not p.is_symlink():
        for d,ds,fs in os.walk(p,followlinks=False):
            for n in ds+fs:
                m=(Path(d)/n).lstat();logical+=m.st_size;allocated+=m.st_blocks*512
    return logical,allocated

def bundle_files(p):
    rows=[]
    for d,ds,fs in os.walk(p,followlinks=False):
        for n in ds+fs:
            q=Path(d)/n
            if q.is_symlink():rows.append([str(q.relative_to(p)),'symlink',os.readlink(q)])
            elif q.is_file():rows.append([str(q.relative_to(p)),oct(q.stat().st_mode & 0o777),digest(q)])
    return hashlib.sha256(json.dumps(sorted(rows),separators=(',',':')).encode()).hexdigest()
release=cmd(['gh','api','repos/www080327-glitch/LocalPilot/releases?per_page=100'])
releases=json.loads(release['stdout']) if release.get('exit')==0 else []
assets=[{'tag':r['tag_name'],'name':a['name'],'url':a['browser_download_url'],'digest':a.get('digest'),'bytes':a['size']} for r in releases for a in r['assets']]
(OUT/'github-releases-authenticated.json').write_text(json.dumps({'at':int(time.time()),'releases':[{'tag':r['tag_name'],'url':r['html_url'],'draft':r['draft'],'prerelease':r['prerelease']} for r in releases],'assets':assets},indent=2)+'\n')
process=cmd(['/bin/ps','-axo','pid=,command='])
process_text=process.get('stdout','')
roots=[Path('/Applications'),Path.home()/'Applications',Path.home()/'Downloads',Path.home()/'.local/share/localpilot-desktop-builds']
for p in ROOT.parent.iterdir():
    if p.is_dir() and p.name.startswith('LocalPilot'):
        for q in [p/'release',p/'src-tauri/target/release/bundle',p/'src-tauri/target/debug/bundle',p/'desktop/release',p/'desktop/src-tauri/target/release/bundle',p/'desktop/src-tauri/target/debug/bundle']:
            if q.exists():roots.append(q)
spotlight=cmd(['/usr/bin/mdfind',"kMDItemCFBundleIdentifier == 'io.localpilot.desktop' || kMDItemCFBundleIdentifier == 'io.localpilot.desktop.acceptance.*'"])
spotlight_paths=[Path(p) for p in spotlight.get('stdout','').splitlines() if p.endswith('.app')]
paths=set(spotlight_paths);warnings=[]
for root in roots:
    if not root.exists():continue
    for d,ds,fs in os.walk(root,followlinks=False):
        ds[:]=[n for n in ds if n not in {'.git','node_modules','Application Support','Caches'}]
        for n in list(ds):
            if n.endswith('.app'):paths.add(Path(d)/n);ds.remove(n)
        for n in fs:
            if 'localpilot' in n.lower() and n.endswith(('.dmg','.zip')):paths.add(Path(d)/n)
items=[]
for p in sorted(paths):
    if not p.exists():warnings.append('missing indexed path '+str(p));continue
    item={'path':str(p),'canonical_path':str(p.resolve()),'symlink':p.is_symlink(),'protected':True,'cleanup_candidate':False}
    if p.suffix=='.app':
        try:info=plistlib.loads((p/'Contents/Info.plist').read_bytes())
        except Exception:warnings.append('unreadable plist '+str(p));continue
        bid=info.get('CFBundleIdentifier','')
        if bid!='io.localpilot.desktop' and not bid.startswith('io.localpilot.desktop.acceptance.'):continue
        exe=p/'Contents/MacOS'/info.get('CFBundleExecutable','')
        sign=cmd(['/usr/bin/codesign','--verify','--deep','--strict',str(p)])
        desc=cmd(['/usr/bin/codesign','-dvv',str(p)])
        item.update(kind='APP',bundle_id=bid,version=info.get('CFBundleShortVersionString'),signature_valid=sign['exit']==0,signature_details='\n'.join(l for l in desc.get('stderr','').splitlines() if l.startswith(('Identifier=','Signature=','CDHash=','TeamIdentifier=','Authority='))),signature_error=sign.get('stderr',''),executable_sha256=digest(exe),bundle_manifest_sha256=bundle_files(p),running=(str(exe) in process_text or str(exe.resolve()) in process_text),release_correspondence='UNKNOWN: APP executable hash cannot equal archive hash',notarization='NOT_RUN')
    else:
        sha=digest(p);a=next((a for a in assets if a['digest']=='sha256:'+str(sha)),None)
        item.update(kind='SOURCE_ARCHIVE' if 'source' in p.name.lower() else 'DMG' if p.suffix=='.dmg' else 'APP_ZIP',sha256=sha,release_asset=a,version=a['tag'].removeprefix('desktop-v') if a else 'UNKNOWN: filename only')
    item['logical_bytes'],item['allocated_bytes']=sizes(p) if not p.is_symlink() else (0,0)
    item['reason']='Symbolic reference; preserve and count zero bytes' if p.is_symlink() else 'Identity/recovery/reference review required; preserve'
    items.append(item)
keeper_path=Path.home()/'.local/share/localpilot-desktop-builds/0.2.0/LocalPilot.app'
keeper=next((i for i in items if i['path']==str(keeper_path) and i.get('signature_valid')),None)
# Verify the exact preserved APP against a SHA256-matched released APP ZIP.
release_app_proof={'status':'UNKNOWN'}
archive=next((i for i in items if i['kind']=='APP_ZIP' and i.get('release_asset') and i['release_asset']['tag']=='desktop-v0.2.0'),None)
if keeper and archive:
    with tempfile.TemporaryDirectory(prefix='lp-release-identity-') as temp:
        extraction=cmd(['/usr/bin/ditto','-x','-k',archive['path'],temp])
        extracted=Path(temp)/'LocalPilot.app'
        if extraction.get('exit')==0 and extracted.exists():
            sign=cmd(['/usr/bin/codesign','--verify','--deep','--strict',str(extracted)])
            manifest=bundle_files(extracted)
            release_app_proof={'status':'PASS' if sign['exit']==0 and manifest==keeper['bundle_manifest_sha256'] else 'FAIL','archive':archive['path'],'archive_sha256':archive['sha256'],'release_asset':archive['release_asset'],'extracted_signature_valid':sign['exit']==0,'extracted_bundle_manifest_sha256':manifest,'preserved_app':keeper['path'],'preserved_bundle_manifest_sha256':keeper['bundle_manifest_sha256']}
            for i in items:
                if i.get('bundle_manifest_sha256')==manifest:i['release_correspondence']=release_app_proof['status']+': whole bundle matches hash-verified released APP ZIP'
(OUT/'released-app-identity.json').write_text(json.dumps(release_app_proof,indent=2)+'\n')
if keeper and release_app_proof['status']=='PASS':
    for i in items:
        if i['kind']=='APP' and not i['symlink'] and '/LocalPilot-GUI/release/retained-' in i['path'] and not i['running'] and i['bundle_manifest_sha256']==keeper['bundle_manifest_sha256']:
            i.update(cleanup_candidate=True,protected=False,reason='Exact whole-bundle content/modes/symlink manifest duplicate of preserved signed v0.2.0 APP. Pending exact-path human approval and final running/reference recheck.')
# Preserve all history; only metadata about obvious generated incremental caches is considered.
caches=[]
for name in ['debug/incremental','release/incremental']:
    p=ROOT.parent/'LocalPilot-GUI/src-tauri/target'/name
    if p.exists():
        logical,allocated=sizes(p);caches.append({'path':str(p),'logical_bytes':logical,'allocated_bytes':allocated,'kind':'REBUILDABLE_INCREMENTAL_CACHE','cleanup_candidate':False,'protected':True,'reason':'Not part of current deletion proposal: build references and cache provenance require final review.'})
# Search workflow source text only. Historical evidence may reference old paths without being executable dependencies.
references=[]
for module in [ROOT,ROOT.parent/'LocalPilot-GUI',ROOT.parent/'LocalPilot-desktop-publish/desktop']:
    if not module.exists():continue
    for folder in ['scripts','.github','src','src-tauri']:
        base=module/folder
        if not base.exists():continue
        for d,ds,fs in os.walk(base):
            ds[:]=[n for n in ds if n not in {'target','icons','gen','node_modules','__pycache__'}]
            for n in fs:
                p=Path(d)/n
                if p.suffix not in {'.py','.sh','.rs','.ts','.tsx','.json','.toml','.yml','.yaml'}:continue
                try:s=p.read_text()
                except (UnicodeError,OSError):continue
                for i in items:
                    if not i['cleanup_candidate']:continue
                    relative=str(Path(i['path']).relative_to(ROOT.parent/'LocalPilot-GUI'))
                    if i['path'] in s or relative in s:references.append({'candidate':i['path'],'source':str(p)})
for i in items:
    if any(r['candidate']==i['path'] for r in references):i.update(cleanup_candidate=False,protected=True,reason='Workflow source references this artifact; preserve')
if '--post-cleanup' in sys.argv:
    receipt=json.loads((OUT.parent/'installation-receipt.json').read_text())
    backup=json.loads((OUT.parent/'github-backup-verification.json').read_text())
    for i in items:
        if i.get('executable_sha256')==receipt['executable_sha256'] and i.get('signature_valid') and backup['status']=='PASS':
            i['release_correspondence']='PASS: exact executable restored from SHA256-verified private recovery draft APP ZIP; not a formal stable release'
            i['recovery_archive']=backup['release_url']
report={'at':int(time.time()),'dry_run':True,'files_deleted':0,'scope_roots':[str(r) for r in roots],'spotlight_query_exit':spotlight.get('exit'),'scope_limits':['Spotlight indexing may omit paths; all explicit installation and known Desktop release/bundle roots were enumerated','Other users, mounted backup volumes and unknown private directories not recursively searched','APFS cloned/shared blocks mean allocated size is an upper bound, not guaranteed reclaimed disk space'],'items':items,'build_caches':caches,'workflow_references':references,'review_candidate_bytes':sum(i['allocated_bytes'] for i in items if i['cleanup_candidate']),'warnings':warnings}
(OUT/'desktop-inventory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'apps':sum(i['kind']=='APP' for i in items),'archives':sum(i['kind']!='APP' for i in items),'candidates':[i['path'] for i in items if i['cleanup_candidate']],'candidate_bytes':report['review_candidate_bytes'],'files_deleted':0},ensure_ascii=False))
