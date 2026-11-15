"""Fail the build unless reviewed wheels match the actual bundled modules."""
import hashlib,json,subprocess,zipfile,importlib.util,marshal,tomllib,re
from email.parser import Parser
from pathlib import Path
import argparse,os,platform
from macos_artifacts import architecture,runtime_lock,verify_macho
parser=argparse.ArgumentParser()
parser.add_argument("--arch",default=architecture(platform.machine()),choices=["arm64","x86_64"])
parser.add_argument("--dependency-lock",type=Path,default=os.environ.get("LP_GUI_DEPENDENCY_LOCK"))
args=parser.parse_args()
arch=architecture(args.arch)

root=Path(__file__).resolve().parents[1]/'src-tauri/bundled-backends'
manifest=json.loads((root/'manifest.json').read_text())
if sorted(manifest.get('wheels',[]))!=sorted(p.name for p in (root/'wheels').glob('*.whl')):
    raise SystemExit('Bundled manifest wheel list differs from actual files')
required={'localpilot-agent-service','localpilot-companion','localpilot-suite','localpilot-channels'}
lock=runtime_lock(args.dependency_lock or root.parents[1]/'runtime-dependencies.json',arch)
if manifest.get('architecture','arm64')!=arch:raise SystemExit('Bundled runtime architecture differs from build target')
if (root/'runtime-dependencies.json').exists():
    bundled_lock=(root/'runtime-dependencies.json').read_bytes()
    if json.loads(bundled_lock)!=lock or hashlib.sha256(bundled_lock).hexdigest()!=manifest.get('dependency_lock_sha256'):
        raise SystemExit('Bundled dependency lock differs from explicit reviewed source')
locked=lock['packages']
allowed=required|locked.keys()
expected={};verified_code={};wheel_hashes={};code_owners={}
site=root/'runtime/lib/python3.14/site-packages'
repo=root.parents[2]
for wheel in sorted((root/'wheels').glob('*.whl')):
    wheel_hashes[wheel.name]=hashlib.sha256(wheel.read_bytes()).hexdigest()
    with zipfile.ZipFile(wheel) as archive:
        metadata=[n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
        if len(metadata)!=1:raise SystemExit('Invalid wheel metadata')
        info=Parser().parsestr(archive.read(metadata[0]).decode())
        name=info['Name'].lower().replace('_','-')
        if name not in allowed or name in expected:raise SystemExit('Unexpected or duplicate distribution: '+name)
        if name in locked and (info['Version']!=locked[name]['version'] or wheel_hashes[wheel.name]!=locked[name]['sha256']):
            raise SystemExit('Runtime dependency differs from reviewed lock: '+name)
        expected[name]=info['Version']
        if name=='localpilot-agent-service':
            if any('/share/localpilot/channels/' in member for member in archive.namelist()):
                raise SystemExit('Core wheel must not own independent Channels assets')
            for member in archive.namelist():
                if member.endswith('.dist-info/entry_points.txt') and re.search(r'(?m)^localpilot-channels\s*=',archive.read(member).decode()):
                    raise SystemExit('Core wheel must not own the independent Channels entrypoint')
        if name in required:
            digest=hashlib.sha256();count=0
            for filename in sorted(archive.namelist()):
                if not filename.endswith('.py') or '.data/' in filename or '.dist-info/' in filename:continue
                owner=code_owners.setdefault(filename,name)
                if owner!=name:raise SystemExit('Independent component wheels overlap: '+filename+' in '+owner+' and '+name)
                source=archive.read(filename);installed=site/filename
                original=(repo/'suite' if name=='localpilot-suite' else repo)/filename
                if not original.is_file() or original.read_bytes()!=source:raise SystemExit('Component wheel differs from current source: '+filename)
                if not installed.is_file() or installed.read_bytes()!=source:raise SystemExit('Bundled code differs from wheel: '+filename)
                digest.update(filename.encode()+b'\0'+source);count+=1
            verified_code[name]={'python_files':count,'sha256':digest.hexdigest()}
if set(expected)!=allowed:raise SystemExit('A required independent module or locked dependency is missing')
source=root.parents[2]
for name,relative in [('localpilot-agent-service','pyproject.toml'),('localpilot-companion','companion/pyproject.toml'),('localpilot-suite','suite/pyproject.toml'),('localpilot-channels','channels/pyproject.toml')]:
    if expected[name]!=tomllib.loads((source/relative).read_text())['project']['version']:
        raise SystemExit('Bundled wheel differs from current independent module version: '+name)
actual=json.loads(subprocess.check_output([str(root/'localpilot'),'--version'],text=True))
for name in required:
    if name=='localpilot-channels':continue
    key='suite' if name=='localpilot-suite' else name
    if actual.get(key)!=expected[name]:raise SystemExit('Installed module version mismatch: '+name)
cache_hash=hashlib.sha256();cache_count=0
runtime=root/'runtime'
magic={b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca'}
for binary in runtime.rglob('*'):
    if binary.is_symlink() or not binary.is_file():continue
    with binary.open('rb') as stream:header=stream.read(4)
    if header in magic:verify_macho(binary,arch)
for cache in sorted(runtime.rglob('*.pyc')):
    source=Path(importlib.util.source_from_cache(str(cache)));payload=cache.read_bytes()
    if (payload[:4]!=importlib.util.MAGIC_NUMBER or int.from_bytes(payload[4:8],'little')!=3
        or payload[8:16]!=importlib.util.source_hash(source.read_bytes())):raise SystemExit('Invalid or stale bundled bytecode')
    normalized='/LocalPilot/Python/'+str(source.relative_to(runtime))
    if marshal.loads(payload[16:]).co_filename!=normalized:raise SystemExit('Private or unexpected bytecode source filename')
    cache_hash.update(str(cache.relative_to(runtime)).encode()+b'\0'+payload);cache_count+=1
if cache_count==0:raise SystemExit('Precompiled portable runtime required for first launch')
report={'architecture':arch,'expected_wheel_versions':expected,'actual_module_versions':actual,'verified_code':verified_code,'wheel_hashes':wheel_hashes,
    'runtime_bytecode':{'files':cache_count,'sha256':cache_hash.hexdigest(),'invalidation':'checked-hash','source_filename_prefix':'/LocalPilot/Python'},'passed':True}
(root/'verified-modules.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
