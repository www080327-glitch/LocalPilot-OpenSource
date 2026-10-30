"""Start only this checkout's private Companion + LocalPilot deployment."""
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
from urllib.request import ProxyHandler, Request, build_opener

from companion.config import Config, PrivateData
from companion import cli

ROOT=Path(__file__).resolve().parents[2]
SERVICE_SOURCE=ROOT.parent/'LocalPilot-companion-v044-service-cache'


def owned_service(private, config):
    import psutil
    record=json.loads(private.file('service-process.json').read_text())
    process=psutil.Process(record['pid'])
    expected=[str(Path(sys.executable)), '-m','localpilot_service','--config',str(config)]
    if (abs(process.create_time()-record['created'])>.01 or process.cmdline()[1:]!=expected[1:] or not Path(process.exe()).samefile(psutil.Process().exe()) or
            Path(process.cwd()).resolve()!=SERVICE_SOURCE.resolve()):
        raise RuntimeError('Existing process identity differs; preserved')
    return process


def provision(directory, port=8765):
    private=PrivateData(directory)
    credentials=private.file('client-credentials.json')
    if not credentials.exists():
        private.write(credentials.name,json.dumps({name:secrets.token_urlsafe(32) for name in
            ('LOCALPILOT_COMPANION_TOKEN','LOCALPILOT_COMPANION_RESOURCE_TOKEN')}))
    tokens=json.loads(credentials.read_text())
    if credentials.stat().st_mode&0o077 or set(tokens)!={'LOCALPILOT_COMPANION_TOKEN','LOCALPILOT_COMPANION_RESOURCE_TOKEN'}:
        raise ValueError('Private client credentials required')
    service_config=private.file('service.json')
    if not service_config.exists():
        workspace=PrivateData(private.root/'workspace').root
        snapshot=Path.home()/'.cache/huggingface/hub/models--mlx-community--Qwen3.6-35B-A3B-4bit/snapshots/38740b847e4cb78f352aba30aa41c76e08e6eb46'
        local={'workspace':str(workspace),'backend':{'kind':'local-openai','model':'Qwen3.6-35B-A3B-4bit',
            'base_url':'http://127.0.0.1:8048/v1','context_budget':65536,'timeout':90,'include_stream_usage':True},
            'managed_local_model':{'snapshot':str(snapshot),'port':8048,'memory_bytes':26*1024**3,'min_available_bytes':28*1024**3},
            'permissions':'approve-mutations','cloud_egress':'LOCAL_ONLY','cache_stable_prefix':True,'prompt_profile':'standard',
            'tool_profile':'full','capabilities':{'read':True,'write':False,'execute':False},
            'budgets':{'max_steps':4,'max_tool_calls':4,'max_output_tokens':256}}
        import copy
        reasoning=copy.deepcopy(local);reasoning.update(prompt_profile='minimal_0',tool_profile='compact',reasoning_only=True,capabilities={'read':False,'write':False,'execute':False})
        routes={'companion-execution':local,'companion-reasoning':reasoning}
        aliases={'localpilot':'companion-execution','companion-reasoning':'companion-reasoning'}
        # Reference an existing protected key in the trusted service only. No key
        # bytes enter this process, Companion, model workers or configuration.
        key=ROOT.parent/'LocalPilot/.localpilot/secrets/deepseek.key'
        if key.is_file():
            cloud=copy.deepcopy(reasoning);cloud.pop('managed_local_model')
            cloud.update(backend={'kind':'deepseek','model':'deepseek-flash','key_file':str(key)},cloud_egress='REQUIRES_APPROVAL',thinking='none')
            cloud['budgets']['max_steps']=1
            routes['companion-cloud-reasoning']=cloud;aliases['companion-cloud-reasoning']='companion-cloud-reasoning'
        value={'schema_version':1,'host':'127.0.0.1','port':port,'data_dir':str(private.root/'service-data'),
            'clients':[{'subject':'companion','token_env':'LOCALPILOT_COMPANION_TOKEN','scopes':['read','submit','cancel'],'routes':aliases},
                {'subject':'companion-resource','token_env':'LOCALPILOT_COMPANION_RESOURCE_TOKEN','operator':True,
                 'scopes':['read','resource_control'],'approval_for':['companion'],'routes':aliases}], 'routes':routes}
        private.write('service.json',json.dumps(value,indent=2)+'\n')
    return private,service_config,tokens


def start_service(private, config, tokens):
    import psutil
    try:
        process=owned_service(private,config)
        return {'status':'owned_service_running','pid':process.pid}
    except (FileNotFoundError,psutil.NoSuchProcess):pass
    value=json.loads(config.read_text());port=value['port']
    with socket.socket() as check:
        if check.connect_ex(('127.0.0.1',port))==0:
            raise RuntimeError('LocalPilot port already in use; existing service preserved')
    env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','TMPDIR'}}|tokens
    with private.file('service.log').open('a') as log:
        process=subprocess.Popen([sys.executable,'-m','localpilot_service','--config',str(config)],cwd=SERVICE_SOURCE,
            env=env,stdout=log,stderr=log,start_new_session=True)
    private.write('service-process.json',json.dumps({'pid':process.pid,'created':psutil.Process(process.pid).create_time()}))
    opener=build_opener(ProxyHandler({}))
    for _ in range(80):
        if process.poll() is not None:raise RuntimeError('Owned service failed; inspect private service.log')
        try:
            request=Request(f'http://127.0.0.1:{port}/healthz',headers={'Authorization':'Bearer '+tokens['LOCALPILOT_COMPANION_TOKEN']})
            with opener.open(request,timeout=1) as response:
                if json.load(response)['client_subject']=='companion':return {'status':'owned_service_started','pid':process.pid}
        except OSError:time.sleep(.1)
    raise RuntimeError('Owned service startup pending')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['start','stop','provision'])
    parser.add_argument('--directory',default=str(ROOT/'companion/.data/daily-trial/private-service'))
    parser.add_argument('--companion-config',default=str(ROOT/'companion/.data/daily-trial/config.json'))
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--service-only',action='store_true')
    args=parser.parse_args(argv)
    private,service_config,tokens=provision(args.directory,args.port)
    if args.action=='provision':return {'status':'provisioned','config':str(service_config)}
    if args.action=='stop':
        import psutil
        if not args.service_only:cli.stop(Config.load(args.companion_config))
        try:
            process=owned_service(private,service_config);process.terminate();process.wait(timeout=25)
        except (FileNotFoundError,ProcessLookupError,psutil.NoSuchProcess):pass
        return {'status':'owned_trial_stopped'}
    service=start_service(private,service_config,tokens)
    if args.service_only:return service
    config=Config.load(args.companion_config)
    os.environ.update(tokens)
    cli.start(config,args.companion_config)
    from companion.ui.build import launch_ui
    return {'service':service,'ui':launch_ui(config)}


if __name__=='__main__':print(json.dumps(main(),ensure_ascii=False))
