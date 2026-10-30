"""Explicit operator backup after human cleanup authorization; no delete function.
Only known Desktop artifacts are copied into a staging folder. Credentials, user state,
repositories and arbitrary directories cannot be supplied as inputs.
"""
from pathlib import Path
import hashlib,json,os,plistlib,re,shutil,subprocess,zipfile
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/evidence/maintenance-20261023';STAGE=ROOT/'release/archive-staging/20261023'
if (OUT/'archive-upload-plan.json').exists():
    raise SystemExit('Preserve the existing backup manifest; this one-shot archive operation has already been prepared.')
STAGE.mkdir(parents=True,exist_ok=False)
def run(a):return subprocess.check_output(a,text=True).strip()
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
# Inventory script is read-only; prior evidence is retained as pre-cleanup baseline.
subprocess.run(['python3',str(ROOT/'scripts/audit-desktop.py')],cwd=ROOT,check=True)
v=json.loads((OUT/'desktop-inventory.json').read_text())
remote=json.loads(run(['gh','api','repos/www080327-glitch/LocalPilot/releases?per_page=100']))
remote_sha={a.get('digest','') for r in remote for a in r['assets']}
manifest=[];seen=set()
for i in v['items']:
 p=Path(i['path'])
 if i['symlink']:continue
 if i['kind']=='APP':
  key=i['bundle_manifest_sha256']
  if key in seen:continue
  seen.add(key)
  if i.get('release_correspondence','').startswith('PASS'):continue
  # Tar preserves the original bundle and macOS metadata; do not repair failed artifacts.
  bid=i['bundle_id'];version=i.get('version','unknown');name=f'APP-{bid}-{version}-{key[:12]}.tar.gz'
  dst=STAGE/name
  subprocess.run(['/usr/bin/tar','-czf',str(dst),'-C',str(p.parent),p.name],check=True)
  manifest.append({'name':name,'kind':'APP_ORIGINAL_BUNDLE_ARCHIVE','bundle_id':bid,'version':version,'original_bundle_manifest_sha256':key,'original_signature_valid':i['signature_valid'],'sha256':sha(dst),'bytes':dst.stat().st_size})
 else:
  digest=i['sha256']
  if 'sha256:'+digest in remote_sha or digest in seen:continue
  seen.add(digest)
  dst=STAGE/p.name
  if dst.exists():dst=STAGE/(digest[:12]+'-'+p.name)
  shutil.copy2(p,dst)
  manifest.append({'name':dst.name,'kind':i['kind'],'sha256':sha(dst),'bytes':dst.stat().st_size})
# Add reproducible GUI source from a reviewed commit. Do not upload machine inventory/config.
commit=run(['git','rev-parse','HEAD'])
source=STAGE/'LocalPilot-Desktop-0.2.1-dev.1-source.zip'
paths=run(['git','ls-tree','-r','--name-only','HEAD']).splitlines()
paths=[p for p in paths if not p.startswith('docs/evidence/maintenance-20261023/')]
subprocess.run(['git','archive','--format=zip','--prefix=LocalPilot-Desktop-0.2.1-dev.1/','--output='+str(source),'HEAD',*paths],cwd=ROOT,check=True)
with zipfile.ZipFile(source) as z:
 for info in z.infolist():
  blob=z.read(info)
  if re.search(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{24,}|AIza[0-9A-Za-z_-]{30,})',blob):raise RuntimeError('Credential-pattern block in '+info.filename)
manifest.append({'name':source.name,'kind':'GUI_SOURCE_ONLY','source_commit':commit,'sha256':sha(source),'bytes':source.stat().st_size})
# Record generated artifact provenance/metadata (no absolute paths in remote backup manifest).
for folder in [ROOT.parent/'LocalPilot-GUI/release',*(ROOT/'release/v0.2.1-dev.1').iterdir()]:
 for name in ['manifest.json','SHA256SUMS','publication-receipt.json','final-verification.json']:
  p=folder/name
  if not p.is_file():continue
  label=('published-0.2.0' if folder.name=='release' else folder.name)+'-'+name
  dst=STAGE/label
  if p.suffix=='.json':
   data=json.loads(p.read_text())
   if isinstance(data,dict):data.pop('app_path',None)
   dst.write_text(json.dumps(data,indent=2)+'\n')
  else:shutil.copy2(p,dst)
  manifest.append({'name':label,'kind':'ARTIFACT_METADATA','sha256':sha(dst),'bytes':dst.stat().st_size})
(STAGE/'ARCHIVE_MANIFEST.json').write_text(json.dumps({'purpose':'Private Desktop artifact recovery archive; original failures retained, not a supported release','gui_source_commit':commit,'files':manifest,'excluded':['user data','credentials','SQLite','model caches','git repositories','rebuildable compilation caches']},indent=2)+'\n')
files=[*manifest,{'name':'ARCHIVE_MANIFEST.json','sha256':sha(STAGE/'ARCHIVE_MANIFEST.json'),'bytes':(STAGE/'ARCHIVE_MANIFEST.json').stat().st_size}]
(STAGE/'ARCHIVE_SHA256SUMS').write_text(''.join(f'{i["sha256"]}  {i["name"]}\n' for i in files))
files.append({'name':'ARCHIVE_SHA256SUMS','sha256':sha(STAGE/'ARCHIVE_SHA256SUMS'),'bytes':(STAGE/'ARCHIVE_SHA256SUMS').stat().st_size})
(OUT/'archive-upload-plan.json').write_text(json.dumps({'stage':str(STAGE),'files':files},indent=2)+'\n')
print(json.dumps({'files':len(files),'bytes':sum(i['bytes'] for i in files),'source_commit':commit}))
