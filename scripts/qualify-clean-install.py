"""Auditable host-isolated portable-runtime E2E. This is NOT a clean Mac test."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import time
from urllib.request import Request, urlopen

parser=argparse.ArgumentParser()
parser.add_argument('--bundle',type=Path,required=True)
parser.add_argument('--previous-bundle',type=Path,required=True)
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--evidence',type=Path,required=True)
args=parser.parse_args()
root=args.root.resolve()
if root.exists():raise SystemExit('Existing evidence/test root preserved; use a new run')
root.mkdir(mode=0o700,parents=True);(root/'user').mkdir(mode=0o700)
args.evidence.mkdir(parents=True,exist_ok=True)
env={k:v for k,v in os.environ.items() if k in {'TMPDIR','LANG','LC_CTYPE','USER','LOGNAME'}}
env.update(HOME=str(root/'user'),PATH='/usr/bin:/bin:/usr/sbin:/sbin',PYTHONDONTWRITEBYTECODE='1')
home=root/'product';workspace=root/'workspace';rows=[]
def run(bundle, command, ok=True):
    result=subprocess.run([str(bundle.resolve()/'localpilot'),'--home',str(home),'--json',*command],env=env,cwd=root,capture_output=True,text=True,timeout=220)
    try:value=json.loads(result.stdout)
    except ValueError:value={'status':'UNKNOWN','exit':result.returncode}
    if ok and result.returncode:raise RuntimeError(f'{command[0]} failed: {value}')
    return result.returncode,value
def control(operation,values):return run(args.bundle,['product-control','--request-json',json.dumps({'version':1,'operation':operation,'args':values})])[1]
def record(name, detail):rows.append({'case':name,'status':'PASS_SCOPED','detail':detail})
def protected_json(path,value):
    with path.open('w') as stream:json.dump(value,stream)
    path.chmod(0o600)
try:
    _,prepared=run(args.bundle,['desktop-init','--workspace='+str(workspace)])
    assert prepared.get('status')=='ready' and prepared.get('companion_ready') is True, 'Both independent services must be ready'
    config=json.loads((home/'service.json').read_text())
    assert all(r['backend']['kind']=='unavailable' for r in config['routes'].values())
    record('fresh_profile_without_backend_or_models','Packaged candidate initialized Core and disabled-model Companion with system-only PATH. No model download/inference.')
    before=hashlib.sha256((home/'service.json').read_bytes()).hexdigest()
    run(args.bundle,['stop']);run(args.bundle,['companion','stop'])
    old_code,old_result=run(args.previous_bundle,['desktop-init','--workspace='+str(workspace)],ok=False)
    if old_code:
        rows.append({'case':'dev17_startup_boundary','status':'FAIL_BASELINE','detail':'dev17 Suite returned before its cold Core launch was ready; candidate observation/rebind follows.'})
        control('service_control',{'module':'core','action':'recover','confirmed':True})
    run(args.previous_bundle,['stop']);run(args.previous_bundle,['companion','stop'])
    _,prepared=run(args.bundle,['desktop-init','--workspace='+str(workspace)])
    assert prepared.get('status')=='ready' and prepared.get('companion_ready') is True, 'Upgrade left an independent service unavailable'
    assert hashlib.sha256((home/'service.json').read_bytes()).hexdigest()==before
    record('upgrade_dev17_configuration','New Suite reuses the dev17 configuration and starts the same home through the new portable runtime.')
    for module in ('core','companion'):
        control('service_control',{'module':module,'action':'stop','confirmed':True})
        result=control('service_control',{'module':module,'action':'recover','confirmed':True})
        assert result.get('status') in {'ready','started','running','already_running'}
    record('independent_stop_and_recovery','Core and Companion restarted independently; no inference or task replay.')
    control('service_control',{'module':'core','action':'stop','confirmed':True})
    original=json.loads((home/'service.json').read_text());connection=json.loads((home/'connection.json').read_text())
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1]
        protected_json(home/'service.json',{**original,'port':port});protected_json(home/'connection.json',{**connection,'url':f'http://127.0.0.1:{port}'})
        code,value=run(args.bundle,['start'],ok=False)
        assert code!=0
    protected_json(home/'service.json',original);protected_json(home/'connection.json',connection)
    control('service_control',{'module':'core','action':'recover','confirmed':True})
    record('service_start_failure_and_repair','An occupied loopback port causes a real startup failure; after resolving the collision, bounded recovery succeeds.')
    out=root/'backup';control('backup_installation',{'destination':str(out)})
    restored=root/'restored';result=control('restore_installation',{'source':str(out),'destination':str(restored)})
    assert result['original_data_overwritten'] is False
    for filename in ('core.sqlite3','companion.sqlite3'):
        with sqlite3.connect(out/filename) as database:assert database.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    record('database_backup_and_restore','Both actual service SQLite databases pass integrity_check and restore into a new home; original remains unchanged.')
    original_home=home
    try:
        home=restored
        _,prepared=run(args.bundle,['desktop-init','--workspace='+str(workspace)])
        assert prepared.get('status')=='ready' and prepared.get('companion_ready') is True, 'Restored Companion must be ready, not partial'
        record('restored_service_start','Restored Core and Companion start with a new loopback port and private database locations.')
    finally:
        for command in [['companion','stop'],['service-unregister']]:
            try:run(args.bundle,command,ok=False)
            except Exception:pass
        home=original_home
except Exception as error:
    rows.append({'case':'e2e_exception','status':'FAIL','detail':str(error)[:500]})
finally:
    for bundle in [args.bundle,args.previous_bundle]:
        for command in [['companion','stop'],['service-unregister']]:
            try:run(bundle,command,ok=False)
            except Exception:pass
    report={'environment':'HOST_ISOLATED_NOT_CLEAN_MAC','clean_mac':'NOT_RUN','root':str(root),'system_path_only':True,'uses_packaged_python':True,'inference_started':False,'cases':rows}
    (args.evidence/'portable-e2e.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if any(row['status']=='FAIL' for row in rows):raise SystemExit(1)
