"""Build a relocatable, offline backend resource from reviewed local artifacts.

No user configuration, model cache, SQLite, credentials or site-wide packages
are copied. Each wheel remains an independent upgrade unit.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import csv
import base64
import hashlib
import re

parser=argparse.ArgumentParser()
parser.add_argument('--wheels',required=True)
parser.add_argument('--dependencies',required=True)
parser.add_argument('--channel-runtime',type=Path)
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
out=root/'src-tauri'/'bundled-backends'
if out.exists():raise SystemExit('Existing resource preserved; use a fresh staging path')
source=Path(sys.base_prefix)
if sys.platform!='darwin' or source.name!='3.14':raise SystemExit('Requires the reviewed macOS Python 3.14 framework')
target=out/'runtime'
def ignore(path,names):
    return [n for n in names if n in {'site-packages','__pycache__','test','tests','idlelib','tkinter','_CodeSignature'} or n.startswith('_tkinter')]
target.mkdir(parents=True)
for name in ['Python','lib']:
    src=source/name
    if src.is_dir():shutil.copytree(src,target/name,symlinks=True,ignore=ignore)
    else:shutil.copy2(src,target/name)
(target/'bin').mkdir()
shutil.copy2(source/'Resources/Python.app/Contents/MacOS/Python',target/'bin/python3.14')
# No Tcl/Tk or Python GUI launcher is needed by these headless modules.
site=target/'lib/python3.14/site-packages';site.mkdir(parents=True)
# Ensure pip is available for explicit per-module upgrades without network setup.
pip_wheel=next((source/'lib/python3.14/ensurepip/_bundled').glob('pip-*.whl'))
with zipfile.ZipFile(pip_wheel) as z:z.extractall(site)
wheels=out/'wheels';wheels.mkdir()
for directory in [Path(args.wheels), Path(args.dependencies)]:
    for src in directory.glob('*.whl'):
        if (wheels/src.name).exists() and (wheels/src.name).read_bytes()!=src.read_bytes():
            raise SystemExit('Conflicting wheel identity')
        shutil.copy2(src,wheels/src.name)
environment=dict(os.environ,PYTHONHOME=str(target),PYTHONPATH=str(site),PYTHONNOUSERSITE='1')
# Install into the generated resource only. This does not touch any user env.
subprocess.run([sys.executable,'-m','pip','install','--no-index','--no-compile','--find-links',args.dependencies,
    '--target',str(site),*map(str,wheels.glob('*.whl'))],check=True)
# pip's host-file origin records and absolute console shebangs are build data,
# not portable runtime provenance. Wheel hashes remain the source of truth.
origins=list(site.glob('*.dist-info/direct_url.json'))
for path in origins:path.unlink()
console=site/'bin';portable={}
if console.is_dir():
    bodies=console/'portable-entrypoints';bodies.mkdir()
    for path in list(console.iterdir()):
        if not path.is_file() or path.is_symlink():continue
        data=path.read_bytes()
        if not data.startswith(b'#!'):continue
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',path.name):raise ValueError('Invalid console entrypoint name')
        body=bodies/(path.name+'.py');body.write_bytes(data.split(b'\n',1)[1]);body.chmod(0o644)
        path.write_text('#!/bin/sh\nset -eu\nLP_ENTRY_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nLP_ENTRY_RUNTIME=$(CDPATH= cd -- "$LP_ENTRY_DIR/../../../.." && pwd)\nexport PYTHONHOME="$LP_ENTRY_RUNTIME"\nexport PYTHONPATH="$LP_ENTRY_RUNTIME/lib/python3.14/site-packages"\nexport PYTHONNOUSERSITE=1\nexport PYTHONDONTWRITEBYTECODE=1\nexec "$LP_ENTRY_RUNTIME/bin/python3.14" "$LP_ENTRY_DIR/portable-entrypoints/'+body.name+'" "$@"\n');path.chmod(0o755);portable[path.name]=body
for record in site.glob('*.dist-info/RECORD'):
    rows=[];owned=[]
    for name,digest,size in csv.reader(record.open()):
        if name.endswith('/direct_url.json'):continue
        if name.startswith('../../bin/'):name='bin/'+name.removeprefix('../../bin/');owned.append(Path(name).name)
        elif name.startswith('../../share/'):name='share/'+name.removeprefix('../../share/')
        path=site/name
        if path.is_file() and path!=record and path.resolve().is_relative_to(target):
            digest='sha256='+base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).decode().rstrip('=');size=str(path.stat().st_size)
        rows.append([name,digest,size])
    for name in owned:
        if name in portable:
            path=portable[name];rows.append([str(path.relative_to(site)),'sha256='+base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).decode().rstrip('='),str(path.stat().st_size)])
    with record.open('w',newline='') as stream:csv.writer(stream).writerows(rows)
# Rewrite only copied Mach-O dependencies. Every rewrite is relative to its
# containing file so moving the APP does not depend on /Library/Frameworks.
magic={b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca'}
for path in sorted(target.rglob('*')):
    if path.is_symlink() or not path.is_file():continue
    with path.open('rb') as f:header=f.read(4)
    if header not in magic:continue
    listing=subprocess.check_output(['otool','-L',str(path)],text=True)
    for line in listing.splitlines():
        dependency=line.strip().split(' (')[0]
        if dependency.startswith(str(source)+'/'):
            dest=target/dependency.removeprefix(str(source)+'/')
            relative=os.path.relpath(dest,path.parent)
            subprocess.run(['install_name_tool','-change',dependency,'@loader_path/'+relative,str(path)],check=True,capture_output=True)
    subprocess.run(['codesign','--force','--sign','-',str(path)],check=True,capture_output=True)
(out/'run_suite.py').write_text("from localpilot_suite.cli import main\nraise SystemExit(main())\n")
(out/'localpilot').write_text('#!/bin/sh\nset -eu\nLP_BUNDLE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexport PYTHONHOME="$LP_BUNDLE_ROOT/runtime"\nexport PYTHONPATH="$LP_BUNDLE_ROOT/runtime/lib/python3.14/site-packages"\nexport PYTHONNOUSERSITE=1\nexport PYTHONDONTWRITEBYTECODE=1\nif [ -z "${SSL_CERT_FILE:-}" ]; then export SSL_CERT_FILE="$LP_BUNDLE_ROOT/runtime/lib/python3.14/site-packages/pip/_vendor/certifi/cacert.pem"; fi\nexec "$LP_BUNDLE_ROOT/runtime/bin/python3.14" "$LP_BUNDLE_ROOT/run_suite.py" "$@"\n')
(out/'localpilot').chmod(0o755)
manifest={'kind':'OFFLINE_INDEPENDENT_MODULES','python':'3.14','weights_bundled':False,'credentials_bundled':False,
    'wheels':[p.name for p in wheels.glob('*.whl')],'python_license':'runtime/lib/python3.14/LICENSE.txt',
    'host_pip_origin_records_omitted':len(origins),'portable_console_entrypoints':sorted(portable)}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
subprocess.run([str((target/'bin/python3.14').resolve()),'-m','compileall','-q','-f','--invalidation-mode','checked-hash',
    '-s',str(target.resolve()),'-p','/LocalPilot/Python',str((target/'lib/python3.14').resolve())],env=environment,check=True)
subprocess.run([str(out/'localpilot'),'--version'],check=True)

if args.channel_runtime:
    archive=args.channel_runtime
    expected='c9e1dbc748b33ed2d14f42445191ecaf14c56259c7a9a26d0042c49ec2b66428'
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:raise ValueError('Pinned Node archive mismatch')
    directory=out/'channel-runtime';directory.mkdir()
    shutil.copyfile(archive,directory/'node-v22.23.4-darwin-arm64.tar.gz')
