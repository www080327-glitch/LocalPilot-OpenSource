import os
import subprocess,sys
from pathlib import Path
root=Path(os.environ.get('LP_RELEASE_ROOT', Path(__file__).resolve().parents[3]));repo=root/'core';dest=root/'previous';dest.mkdir(exist_ok=True)
for name,ref,prefix in [('core','fed2409b',''),('companion','1b8783c9','companion/')]:
 target=dest/name;target.mkdir(exist_ok=True)
 paths=subprocess.check_output(['git','-C',str(repo),'ls-tree','-r','--name-only',ref],text=True).splitlines()
 for path in paths:
  p=Path(path)
  if name=='core':include=path=='pyproject.toml' or p.parts[0] in {'agent','computer','localpilot_api','localpilot_service'} and p.suffix in {'.py','.json','.swift'}
  else:include=path.startswith(prefix) and p.suffix in {'.py','.toml','.json','.swift','.entitlements','.sha256'} and not any(x in p.parts for x in ['evidence','.data','tests'])
  if not include:continue
  newpath=path[len(prefix):] if prefix else path
  out=target/newpath;out.parent.mkdir(parents=True,exist_ok=True)
  out.write_bytes(subprocess.check_output(['git','-C',str(repo),'show',ref+':'+path]))
 if name=='companion':(target/'tests').mkdir(exist_ok=True);(target/'tests/__init__.py').touch()
 r=subprocess.run([str(root/'validation-env/bin/python'),'-m','build','--wheel','--no-isolation','--outdir',str(dest/'dist')],cwd=target,capture_output=True,text=True)
 (root/('evidence/previous-'+name+'-build.log')).write_text(r.stdout+r.stderr)
 assert r.returncode==0,(name,r.stderr[-1000:])
print('Built actual previous-source wheels, not fabricated historical versions')
