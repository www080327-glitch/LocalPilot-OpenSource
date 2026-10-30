"""Fail the build unless reviewed wheels match the actual bundled modules."""
import hashlib,json,subprocess,zipfile,importlib.util,marshal,tomllib
from email.parser import Parser
from pathlib import Path

root=Path(__file__).resolve().parents[1]/'src-tauri/bundled-backends'
manifest=json.loads((root/'manifest.json').read_text())
if sorted(manifest.get('wheels',[]))!=sorted(p.name for p in (root/'wheels').glob('*.whl')):
    raise SystemExit('Bundled manifest wheel list differs from actual files')
required={'localpilot-agent-service','localpilot-companion','localpilot-suite','localpilot-channels'}
locked=json.loads((root.parents[1]/'runtime-dependencies.json').read_text())['packages']
allowed=required|locked.keys()
expected={};verified_code={};wheel_hashes={}
site=root/'runtime/lib/python3.14/site-packages'
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
        if name in required:
            digest=hashlib.sha256();count=0
            for filename in sorted(archive.namelist()):
                if not filename.endswith('.py') or '.data/' in filename or '.dist-info/' in filename:continue
                source=archive.read(filename);installed=site/filename
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
for cache in sorted(runtime.rglob('*.pyc')):
    source=Path(importlib.util.source_from_cache(str(cache)));payload=cache.read_bytes()
    if (payload[:4]!=importlib.util.MAGIC_NUMBER or int.from_bytes(payload[4:8],'little')!=3
        or payload[8:16]!=importlib.util.source_hash(source.read_bytes())):raise SystemExit('Invalid or stale bundled bytecode')
    normalized='/LocalPilot/Python/'+str(source.relative_to(runtime))
    if marshal.loads(payload[16:]).co_filename!=normalized:raise SystemExit('Private or unexpected bytecode source filename')
    cache_hash.update(str(cache.relative_to(runtime)).encode()+b'\0'+payload);cache_count+=1
if cache_count==0:raise SystemExit('Precompiled portable runtime required for first launch')
report={'expected_wheel_versions':expected,'actual_module_versions':actual,'verified_code':verified_code,'wheel_hashes':wheel_hashes,
    'runtime_bytecode':{'files':cache_count,'sha256':cache_hash.hexdigest(),'invalidation':'checked-hash','source_filename_prefix':'/LocalPilot/Python'},'passed':True}
(root/'verified-modules.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
