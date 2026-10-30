"""Read-only GitHub backup verification, including real restoration downloads."""
from pathlib import Path
import json,subprocess,hashlib,tempfile,zipfile
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'docs/evidence/maintenance-20261023';plan=json.loads((out/'archive-upload-plan.json').read_text());repo='www080327-glitch/LocalPilot';tag='desktop-archive-20261023'
releases=json.loads(subprocess.check_output(['gh','api',f'repos/{repo}/releases?per_page=100'],text=True));r=next(r for r in releases if r['tag_name']==tag)
assert r['draft'] is True
rows=[]
for f in plan['files']:
 a=next((a for a in r['assets'] if a['name']==f['name']),None);ok=bool(a and a.get('digest')=='sha256:'+f['sha256'] and a['size']==f['bytes']);assert ok,'Remote mismatch '+f['name']
 rows.append({'name':f['name'],'sha256':f['sha256'],'bytes':f['bytes'],'remote_asset_id':a['id'],'remote_digest':a['digest'],'verified':ok})
final=json.loads((out/'installation-receipt.json').read_text());roundtrips=[]
for pattern in ['LocalPilot-GUI-0.1.0-source.zip','d943b780aba9-LocalPilot-0.2.1-dev.1-arm64.app.zip']:
 with tempfile.TemporaryDirectory(prefix='lp-backup-restore-check-') as tmp:
  subprocess.run(['gh','release','download',tag,'--repo',repo,'--pattern',pattern,'--dir',tmp],check=True)
  p=Path(tmp)/pattern
  with p.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
  row=next(x for x in rows if x['name']==pattern);assert sha==row['sha256']
  proof={'name':pattern,'sha256':sha,'roundtrip':'PASS'}
  if 'app.zip' in pattern:
   with zipfile.ZipFile(p) as z:exe=hashlib.sha256(z.read('LocalPilot.app/Contents/MacOS/localpilot-desktop')).hexdigest()
   assert exe==final['executable_sha256'];proof['matches_installed_executable']=True
   dest=Path(tmp)/'unpacked';subprocess.run(['/usr/bin/ditto','-x','-k',str(p),str(dest)],check=True);subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(dest/'LocalPilot.app')],check=True);proof['restored_app_signature_valid']=True
  roundtrips.append(proof)
receipt={'status':'PASS','release_id':r['id'],'tag':tag,'release_url':r['html_url'],'draft':True,'expected_assets':len(plan['files']),'matched_assets':len(rows),'total_bytes':sum(f['bytes'] for f in rows),'assets':rows,'real_download_roundtrips':roundtrips,'source_push':False,'stable_tags_changed':False}
(out/'github-backup-verification.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({k:v for k,v in receipt.items() if k not in ['assets','real_download_roundtrips']}))
