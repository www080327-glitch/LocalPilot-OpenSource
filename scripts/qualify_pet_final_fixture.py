"""Owned native pet acceptance fixture. Real released Core, synthetic files only.

No approval capability is offered here. `reject` uses a separate host identity to
exercise denial; the pet itself never receives host credentials.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

ROOT = Path.home()/'.local/share/localpilot-pet-final-20261026'
HOME = ROOT/'core'
WORK = ROOT/'workspace'
EVIDENCE = Path(__file__).resolve().parents[1]/'docs/evidence/pet-final-20261026'
BUNDLE = Path.home()/'.cache/localpilot-desktop/target/release/bundle/macos/LocalPilot DeepSeek Pet Test.app/Contents/Resources/bundled-backends'


def private(path, obj):
    from localpilot_service.cli import save
    save(path, obj)


def load():
    from localpilot_service.cli import connection
    from localpilot_service.security import private_json
    return connection(HOME), private_json(HOME/'connection.json')


def snapshot():
    client, _ = load()
    tasks = client.request('/localpilot/v1/tasks')
    result = {'health':client.request('/healthz'), 'tasks':tasks,
              'files':{p.name:p.read_text() for p in WORK.iterdir() if p.is_file()}}
    raw=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    (EVIDENCE/'core-latest.json').write_text(raw)
    (EVIDENCE/('core-snapshot-'+str(time.time_ns())+'.json')).write_text(raw)
    rows = tasks.get('tasks',tasks.get('items',[])) if isinstance(tasks,dict) else tasks
    print(json.dumps({'tasks':[{k:t.get(k) for k in ['id','status','session_id','receipt_summary','verification_summary']} for t in rows], 'files':list(result['files'])},ensure_ascii=False))


def resource(operation):
    from localpilot_service.cli import environment
    from localpilot_service.security import Principal,private_json
    from localpilot_service.model_resources import ModelResources
    from agent.omlx import OMLXBackend
    cfg=private_json(HOME/'service.json');spec=cfg['routes']['pet-local']['backend']
    env=environment(HOME)
    backend=OMLXBackend(base_url=spec['base_url'],model=spec['model'],api_key=env['LOCALPILOT_OMLX_API_KEY'])
    observed=backend.inspect_service()
    if observed.get('active_requests') != 0:raise RuntimeError('Provider has active requests; preserve it')
    row=next(m for m in observed['models'] if m['id']==spec['model'])
    owned=HOME/'acceptance-model-owned.json'
    if operation=='unload' and (not owned.exists() or private_json(owned).get('model') != spec['model']):
        print(json.dumps({'status':'not_owned_preserved'}));return
    if operation=='load' and row['loaded']:
        print(json.dumps({'status':'already_loaded_preserved'}));return
    if operation=='load' and any(m['loaded'] and m['id']!=spec['model'] for m in observed['models']):
        raise RuntimeError('Another language model is loaded; preserve it')
    ordinary=Principal('pet-client',secrets.token_urlsafe(32),routes={'pet-local':'pet-local'})
    host=Principal('fixture-host',secrets.token_urlsafe(32),operator=True,scopes=frozenset({'resource_control'}),approval_for=('pet-client',),routes={})
    resources=ModelResources(SimpleNamespace(access=SimpleNamespace(principals={'pet-client':ordinary}),model_backends={'pet-local':backend},service=SimpleNamespace(condition=threading.Condition(),tasks={})),HOME/'resources.json')
    result=resources.operate(host,{'client_subject':'pet-client','model':'pet-local','operation':operation,'confirmed':True,'max_memory_bytes':26*1024**3},'pet-final-'+operation+'-'+secrets.token_hex(8))
    (EVIDENCE/('model-'+operation+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    if operation=='load' and result.get('status')=='completed':private(owned,{'model':spec['model'],'operation':'loaded_by_this_acceptance'})
    if operation=='unload' and result.get('status')=='completed':owned.unlink(missing_ok=True)
    print(json.dumps(result))


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['setup','status','reject','restart','stop','load','unload']);a=p.parse_args()
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    if a.action=='setup':
        if ROOT.exists():raise RuntimeError('Existing fixture preserved')
        for folder in [ROOT,HOME,WORK]:folder.mkdir(mode=0o700)
        nonce='PET-NATIVE-'+secrets.token_hex(8)
        (WORK/'input.txt').write_text(nonce+'\n');(WORK/'other.txt').write_text('Second controlled file.\n')
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        provider=json.loads((Path.home()/'.omlx/settings.json').read_text())
        private(HOME/'connection.json',{'url':f'http://127.0.0.1:{port}','token_env':'LOCALPILOT_HTTP_TOKEN','omlx_settings_file':str(Path.home()/'.omlx/settings.json')})
        tokens={'LOCALPILOT_HTTP_TOKEN':secrets.token_urlsafe(32),'LOCALPILOT_OPERATOR_TOKEN':secrets.token_urlsafe(32)}
        fd=os.open(HOME/'clients.env',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:f.write(''.join(f'export {k}={v}\n' for k,v in tokens.items()))
        route={'workspace':str(WORK),'engine':'v5','backend':{'kind':'omlx','base_url':f'http://127.0.0.1:{provider["server"]["port"]}/v1','model':'mlx-community--Qwen3.6-35B-A3B-4bit','api_key_env':'LOCALPILOT_OMLX_API_KEY','context_budget':131072,'timeout':120,'chat_template_kwargs':{'enable_thinking':False},'capabilities':{'tool_calling':True,'streaming':False}},'permissions':'approve-mutations','cloud_egress':'LOCAL_ONLY','capabilities':{'read':True,'write':True,'execute':False},'budgets':{'max_steps':12,'max_tool_calls':12,'max_token_units':200000,'max_output_tokens':1024},'verification':{'id':'native-pet-exact-read','files':{'input.txt':hashlib.sha256((nonce+'\n').encode()).hexdigest()},'required_text':nonce}}
        private(HOME/'service.json',{'schema_version':1,'port':port,'data_dir':str(HOME/'data'),'clients':[{'subject':'pet-client','token_env':'LOCALPILOT_HTTP_TOKEN','routes':{'pet-local':'pet-local'}},{'subject':'host','token_env':'LOCALPILOT_OPERATOR_TOKEN','operator':True,'scopes':['read','control','cancel'],'approval_for':['pet-client'],'routes':{}}],'routes':{'pet-local':route}})
        from localpilot_service.cli import start
        result=start(HOME,manager='detached');print(json.dumps(result))
        return
    if a.action=='status':snapshot()
    elif a.action in ['load','unload']:resource(a.action)
    elif a.action=='reject':
        client,_=load()
        from localpilot_service.cli import environment
        from localpilot_service.sdk import Client
        host=Client(client.base_url,token=environment(HOME)['LOCALPILOT_OPERATOR_TOKEN'])
        tasks=client.request('/localpilot/v1/tasks');rows=tasks.get('tasks',tasks.get('items',[])) if isinstance(tasks,dict) else tasks
        rejected=[]
        for task in rows:
            if task['status']=='requires_approval':
                result=host.continue_task(task['id'],task['required_action']['id'],action='reject');rejected.append(result)
        (EVIDENCE/'host-rejections.json').write_text(json.dumps(rejected,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'rejected_tasks':len(rejected)}))
    else:
        from localpilot_service.cli import stop,start
        result=stop(HOME)
        if a.action=='restart':result={'stop':result,'start':start(HOME,manager='detached')}
        print(json.dumps(result))

if __name__=='__main__':main()
