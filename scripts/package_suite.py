"""Explicit module source exports and artifact scanning; never exports Git history."""
import argparse,hashlib,json,re,zipfile,shutil,subprocess,tomllib
from pathlib import Path

DOCS=['LOCALPILOT_SUITE_RELEASE_REPORT.md','SUITE_API_COMPATIBILITY.md','SUITE_CLI.md','SUITE_INSTALL_UPGRADE_ROLLBACK.md','SUITE_CACHE_ACCEPTANCE.md']
EXT={'.py','.swift','.json','.toml','.entitlements','.sha256'}
DENIED={'evidence','.data','.git','__pycache__','build','dist','node_modules','.venv','secrets'}
SUMMARIES={'qualification-summary.json','failure-ledger.json','EVIDENCE_INDEX.md','cache-metrics.json','evidence-hashes.json','service-soak.json','publication.json'}
def curated_summary(path):
 parts=Path(path).parts
 return len(parts)>=4 and parts[-4:-1]==('docs','evidence','suite-release-20261021') and parts[-1] in SUMMARIES

SECRET=[re.compile(r'sk-[A-Za-z0-9_-]{24,}'),re.compile(r'gh[pousr]_[A-Za-z0-9]{30,}'),re.compile(r'github_pat_[A-Za-z0-9_]{30,}'),re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')]


def files(folder):
 return [p for p in folder.rglob('*') if p.is_file() and not p.is_symlink() and p.suffix in EXT and not any(x in DENIED or x.endswith('.egg-info') for x in p.relative_to(folder).parts)]


def sanitized_doc(data,root):
 text=data.decode().replace(str(root),'RELEASE_ROOT')
 return re.sub(r'/Users/[^/\s`"\)]+', '<user-home>', text).encode()


def main():
 parser=argparse.ArgumentParser();parser.add_argument('release_root',type=Path);args=parser.parse_args();root=args.release_root.resolve();output=root/'dist';exports=root/'exports';output.mkdir(exist_ok=True);exports.mkdir(exist_ok=True)
 core=root/'core';comp=root/'companion';suite=core/'suite';bundles={}
 versions={name:tomllib.loads(path.read_text())['project']['version'] for name,path in {'core':core/'pyproject.toml','companion':comp/'companion/pyproject.toml','suite':suite/'pyproject.toml'}.items()}
 corefiles=[core/'pyproject.toml',core/'requirements.txt',core/'README.md']+[core/n for n in DOCS]
 corefiles += [core/n for n in ['AGENT_SERVICE_API.md','COMPANION_CLIENT_CONTRACT.md','MODEL_BACKEND_API.md','MODEL_MANAGER_CONTRACT.md','SERVICE_DEPLOYMENT.md','LOCALPILOT_SERVICE_RELEASE_REPORT.md']]
 for d in ['agent','computer','localpilot_api','localpilot_service','localpilot-agent','tests','benchmarks','configs','scripts/suite_qualification']:corefiles+=files(core/d)
 corefiles += list((core/'docs/evidence/suite-release-20261021').glob('*.json')) + list((core/'docs/evidence/suite-release-20261021').glob('*.md'))
 # Skill prose is part of the independent distribution.
 corefiles += list((core/'localpilot-agent').rglob('*.md'))
 corefiles += [core/n for n in ['catalog.py','hardware.py','main.py','recommender.py','selector_mlp.py','text.py']]
 corefiles += [core/'scripts/package_suite.py'] + list((core/'scripts/suite_qualification').glob('*.md'))
 bundles['core-'+versions['core']]=(core,corefiles)
 compfiles=files(comp/'companion')+[core/n for n in DOCS]+[comp/'companion/README.md']
 bundles['companion-'+versions['companion']]=(comp/'companion',compfiles)
 suitefiles=files(suite)+list((suite/'docs').glob('*.md'))+[suite/'README.md']
 bundles['suite-'+versions['suite']]=(suite,suitefiles)
 findings=[];reviewed=[];archives=[]
 for name,(base,paths) in bundles.items():
  folder=exports/name
  if folder.exists():shutil.rmtree(folder)
  folder.mkdir();entries={}
  for path in sorted(set(paths)):
   rel=path.relative_to(base) if path.is_relative_to(base) else Path(path.name)
   if any(x in DENIED for x in rel.parts) and not curated_summary(rel):continue
   data=path.read_bytes()
   if path.suffix=='.md':data=sanitized_doc(data,root)
   entries[str(rel)]=data
   dest=folder/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
  version=versions[name.split('-')[0]]
  entries['.gitignore']=b'__pycache__/\n*.pyc\nbuild/\ndist/\n*.egg-info/\n.env*\n!.env.example\n*.sqlite*\n*.db*\n*.safetensors\n*.gguf\n.localpilot/\n.data/\n.venv/\n'
  (folder/'.gitignore').write_bytes(entries['.gitignore'])
  source_commit=subprocess.check_output(['git','-C',str(base),'rev-parse','HEAD'],text=True).strip()
  entries['MODULE_RELEASE.json']=(json.dumps({'version':version,'module':name.split('-')[0],'api':'1.0','companion_contract':'1.0','admission':'SCOPED_RC_GO_NOT_FULL_PRODUCTION','implementation_source_commit':source_commit,'source_history_exported':False,'weights_credentials_user_data_included':False,'publication':'user-authorized curated module source branches and main; see publication ledger'},indent=2)+'\n').encode()
  (folder/'MODULE_RELEASE.json').write_bytes(entries['MODULE_RELEASE.json'])
  archive=output/('localpilot-'+name+'-source.zip')
  with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
   for path,data in entries.items():z.writestr(name+'/'+path,data)
  archives.append({'name':archive.name,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':len(entries),'bytes':archive.stat().st_size})
 # Scan the exact archive members and wheels; findings reveal only filename/pattern, never matched bytes.
 for archive in [*output.glob('*.zip'),*output.glob('*.whl')]:
  with zipfile.ZipFile(archive) as z:
   for name in z.namelist():
    p=Path(name)
    if p.suffix in {'.sqlite','.sqlite3','.db','.safetensors','.gguf','.pem','.key'} or (any(x in DENIED for x in p.parts) and not curated_summary(p)):findings.append({'artifact':archive.name,'entry':name,'reason':'forbidden_entry'})
    data=z.read(name)
    try:text=data.decode()
    except UnicodeDecodeError:findings.append({'artifact':archive.name,'entry':name,'reason':'unreviewed_binary'});continue
    for index,pattern in enumerate(SECRET):
     if pattern.search(text):
      if index==3 and name.endswith('/tests/test_hybrid_runtime.py') and hashlib.sha256(data).hexdigest()=='1528497a0473f0a13bd628b2d4a626e82b3856e4f99063fb53656ef3baeb3cba':reviewed.append({'artifact':archive.name,'entry':name,'reason':'reviewed synthetic header-only egress-denial fixture','sha256':hashlib.sha256(data).hexdigest()})
      else:findings.append({'artifact':archive.name,'entry':name,'reason':'credential_pattern_'+str(index)})
    if str(Path.home())+'/' in text:findings.append({'artifact':archive.name,'entry':name,'reason':'private_host_path'})
 manifest={'archives':archives,'wheels':[{'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in output.glob('*.whl')],'scan':{'findings':findings,'reviewed_synthetic_markers':reviewed,'status':'PASS_WHITELIST_AND_PATTERN_SCAN' if not findings else 'BLOCKED','scope':'exact wheel/source archive members; not a proof of all historical Git objects','old_history_publication':'Only already-remote main ancestry retained; development histories excluded'}}
 (root/'evidence/artifact-manifest.json').write_text(json.dumps(manifest,indent=2));(output/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(output.iterdir()) if p.is_file() and p.name!='SHA256SUMS'))
 print(json.dumps({'archives':len(archives),'wheels':len(manifest['wheels']),'scan':manifest['scan']}))
 if findings:raise SystemExit(2)


if __name__=='__main__':main()
