"""Do not print credential values; inspect the full introduced Git object graph."""
from pathlib import Path
import hashlib,io,json,os,re,subprocess,zipfile
root=Path(__file__).resolve().parents[1]
def git(*args):return subprocess.check_output(['git','-C',str(root),*args])
known=[]
for p in [Path.home()/'.omlx/settings.json',root.parent/'LocalPilot/.localpilot/secrets/deepseek.key']:
 if p.is_file():
  raw=p.read_text().strip()
  if p.suffix=='.json':raw=(json.loads(raw).get('auth')or{}).get('api_key','')
  if raw and len(raw)>=12:known.append(raw.encode())
rows=git('rev-list','--objects','36b6b72b..HEAD').decode().splitlines();objects={r.split(' ',1)[0]:r.split(' ',1)[1] if ' ' in r else '' for r in rows}
info=git('cat-file','--batch-check=%(objectname) %(objecttype) %(objectsize)',*[]) if False else subprocess.check_output(['git','-C',str(root),'cat-file','--batch-check=%(objectname) %(objecttype) %(objectsize)'],input=('\n'.join(objects)+'\n').encode()).decode()
findings=[];count=0
patterns=[('private_key',re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')),('github_token',re.compile(rb'\bgh[pousr]_[A-Za-z0-9]{30,}\b')),('deepseek_style_token',re.compile(rb'\bsk-[A-Za-z0-9]{32,}\b'))]
def inspect(data,name):
 for secret in known:
  if secret in data:findings.append({'path':name,'kind':'known_native_credential'})
 for label,pattern in patterns:
  if pattern.search(data):findings.append({'path':name,'kind':label,'review_required':True})
 if name.endswith('.whl'):
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   for entry in z.namelist():
    if entry.endswith(('.py','.json','.txt','.md')):
     for secret in known:
      if secret in z.read(entry):findings.append({'path':name+'!'+entry,'kind':'known_native_credential'})
for line in info.splitlines():
 oid,typ,size=line.split()
 if typ=='blob':inspect(git('cat-file','blob',oid),objects[oid]);count+=1
for name in git('ls-files','--others','--exclude-standard').decode().splitlines():
 p=root/name
 if p.is_file():inspect(p.read_bytes(),name);count+=1
report={'git_blobs_and_untracked_files_checked':count,'known_native_credentials_checked':len(known),'findings':findings,'credential_values_printed':False,'user_databases_or_models_in_round_docs':any(p.suffix in {'.sqlite3','.db','.safetensors','.env'} for p in (root/'docs/integration/20261025').rglob('*') if p.is_file()),'personal_sprite_bytes_excluded':not any(p.name=='spritesheet.webp' for p in root.rglob('spritesheet.webp') if '.venv' not in p.parts),'status':'PASS' if not findings else 'REVIEW_REQUIRED'}
(root/'docs/integration/20261025/SOURCE_SECRET_SCAN.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
