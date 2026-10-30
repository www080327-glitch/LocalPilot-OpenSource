"""Prepare a new offline runtime from a reviewed bundle and an independent Suite wheel."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

p=argparse.ArgumentParser()
p.add_argument('--baseline',type=Path,required=True)
p.add_argument('--suite-wheel',type=Path,required=True)
p.add_argument('--destination',type=Path,required=True)
a=p.parse_args()
if a.destination.exists():raise SystemExit('Existing bundle preserved; use a new destination')
manifest=json.loads((a.baseline/'manifest.json').read_text())
if manifest.get('credentials_bundled') is not False or manifest.get('weights_bundled') is not False:raise SystemExit('Reviewed resource manifest required')
def ignore(folder,names):
    return [n for n in names if n=='localpilot_suite' or n.startswith('localpilot_suite-') or n=='__pycache__']
shutil.copytree(a.baseline,a.destination,symlinks=True,ignore=ignore)
site=a.destination/'runtime/lib/python3.14/site-packages'
env={**os.environ,'PYTHONHOME':str((a.destination/'runtime').resolve()),'PYTHONPATH':str(site.resolve()),'PYTHONNOUSERSITE':'1'}
subprocess.run([str((a.destination/'runtime/bin/python3.14').resolve()),'-m','pip','install','--no-deps','--no-index','--no-compile','--target',str(site),str(a.suite_wheel.resolve())],env=env,check=True)
shutil.copy2(a.suite_wheel,a.destination/'wheels'/a.suite_wheel.name)
manifest['wheels']=sorted(p.name for p in (a.destination/'wheels').glob('*.whl'))
(a.destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
# Compile once with checked hashes and normalized filenames; resources stay read-only.
subprocess.run([str((a.destination/'runtime/bin/python3.14').resolve()),'-m','compileall','-q','-f',
    '--invalidation-mode','checked-hash','-s',str((a.destination/'runtime').resolve()),
    '-p','/LocalPilot/Python',str((a.destination/'runtime/lib/python3.14').resolve())],env=env,check=True)
subprocess.run([str((a.destination/'localpilot').resolve()),'--version'],check=True)
