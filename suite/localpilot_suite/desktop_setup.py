"""First-run coordination using each independently installed module's CLI."""
import json
import os
from pathlib import Path
import subprocess
import sys

def discover_omlx(base, key):
    from localpilot_service.sdk import Client
    # Versioned provider API only; Suite does not import either Agent engine.
    client=Client(base.removesuffix('/v1'),token=key or 'no-credential',timeout=5)
    state=client.request('/v1/models/status')
    return [dict(m,size_bytes=m.get('estimated_size')) for m in state.get('models',[])
        if m.get('engine_type') not in {'markitdown'} and not m.get('is_helper')]

def prepare(home, workspace):
    from localpilot_service.cli import private_dir, environment, main as core
    from localpilot_service.security import private_json
    from .cli import initialize_companion
    home=private_dir(home)
    present=[(home/name).exists() for name in ('connection.json','service.json','clients.env')]
    if any(present) and not all(present):
        raise ValueError('配置不完整，原文件已保留。请从备份恢复到独立目录；不会覆盖初始化')
    workspace=Path(workspace).expanduser().resolve()
    workspace.mkdir(parents=True,exist_ok=True)
    settings_path=Path.home()/'.omlx/settings.json'
    backend_ready=False;observed=[];base='http://127.0.0.1:1234/v1'
    if settings_path.exists():
        try:
            settings=private_json(settings_path)
            port=settings.get('server',{}).get('port')
            if type(port) is not int or not 1<=port<=65535:raise ValueError('Invalid oMLX port')
            base=f'http://127.0.0.1:{port}/v1'
            observed=discover_omlx(base,settings.get('auth',{}).get('api_key'));backend_ready=True
        except (OSError,ValueError):pass
    small=[m for m in observed if type(m.get('size_bytes')) is int and 0<m['size_bytes']<=1500000000]
    candidates=small or observed
    selected=min(candidates,key=lambda m:m.get('size_bytes') or 2**63) if candidates else {'id':'not-selected','loaded':False}
    # Bind a free port for this new installation without touching existing Core.
    import socket
    if not (home/'connection.json').exists():
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));core_port=listener.getsockname()[1]
        import contextlib,io
        with contextlib.redirect_stdout(io.StringIO()):
            arguments=['--home',str(home),'--json','init','--workspace',str(workspace),'--model',selected['id'],'--base-url',base,'--port',str(core_port)]
            if backend_ready:arguments+=['--omlx','--omlx-settings-file',str(settings_path)]
            code=core(arguments)
        if code:raise ValueError('Core initialization failed; inspect original configuration before retrying')
        from localpilot_service.cli import save
        connection=private_json(home/'connection.json');connection.update(token_env='LOCALPILOT_COMPANION_TOKEN',client_subject='companion')
        save(home/'connection.json',connection)
        if not backend_ready:
            config=private_json(home/'service.json')
            for route in config['routes'].values():
                route.update(backend={'kind':'unavailable','model':'not-selected'},deployment_status='not_deployed')
            save(home/'service.json',config)
    initialize_companion(home)
    if backend_ready and (home/'connection.json').exists():attach_omlx(home,base,settings_path)
    migrate_desktop_acceptance_route(home)
    import contextlib,io
    with contextlib.redirect_stdout(io.StringIO()):
        from .installation import start_core
        start_core(home)
    env={k:v for k,v in environment(home).items() if 'OPERATOR' not in k.upper() and 'DEEPSEEK' not in k.upper()}
    result=subprocess.run([sys.executable,'-m','companion','--config',str(home/'companion.json'),'--json','start'],env=env,capture_output=True,text=True,timeout=30)
    try:companion_ready=result.returncode==0 and json.loads(result.stdout).get('status')=='running'
    except ValueError:companion_ready=False
    connection=private_json(home/'connection.json')
    return {'status':'ready' if companion_ready else 'partial','home':str(home),'origin':connection['url'],'workspace':str(workspace),
        'lightweight_model':selected['id'],'loaded':selected['loaded'],
        'model_loading':'requires separate authorization in oMLX',
        'cloud_configured':False,'model_downloaded':False,'omlx_service_reused':backend_ready,'companion_ready':companion_ready}


def sync_models(home):
    from copy import deepcopy
    import hashlib
    from localpilot_service.cli import connection,environment,stop,start,save
    from localpilot_service.security import private_json
    config=private_json(home/'service.json');conn=private_json(home/'connection.json')
    if not conn.get('omlx_settings_file'):raise ValueError('This installation does not reference a shared oMLX service')
    observed=discover_omlx(conn['omlx_base_url'],environment(home).get('LOCALPILOT_OMLX_API_KEY'))
    models={r['backend'].get('model') for r in config['routes'].values()}
    added=[]
    local_template=next((r for r in config['routes'].values() if r['backend'].get('kind')=='omlx'),None)
    if local_template is None:raise ValueError('No local backend is attached; run GUI component setup first')
    template=deepcopy(local_template);template.pop('verification',None);template.pop('cooperation',None)
    template.update(cloud_egress='LOCAL_ONLY',prompt_profile='standard',tool_profile='full',reasoning_only=False,capabilities={'read':True,'write':True,'execute':False})
    for model in observed:
        if model['id'] in models:continue
        route=deepcopy(template);route['backend'].update(model=model['id'],context_budget=min(model.get('max_context_window') or 65536,131072))
        if (model.get('size_bytes') or 0)<=1500000000:route.update(reasoning_only=True,prompt_profile='minimal_0',capabilities={'read':False,'write':False,'execute':False})
        name='omlx-import-'+hashlib.sha256(model['id'].encode()).hexdigest()[:12]
        config['routes'][name]=route;added.append(name)
        for client in config['clients']:
            if not client.get('operator'):client['routes'][name]=name
    if added:
        before=private_json(home/'service.json')
        if stop(home)['status']!='stopped':raise ValueError('Core is still stopping; routes unchanged')
        save(home/'service.json',config)
        try:start(home)
        except Exception:save(home/'service.json',before);start(home);raise
    return {'status':'synchronized','added_routes':added,'downloaded':False,'loaded':False,'existing_routes_preserved':True}


def configure_cloud(home, key_file):
    from copy import deepcopy
    import secrets
    import time
    from agent.cloud_credentials import resolve_deepseek_key
    from localpilot_service.cli import connection, compatible, stop, start, save, environment
    from localpilot_service.security import private_json
    # Verify the selected protected file, retaining only its path reference.
    resolve_deepseek_key(key_file=key_file)
    client=connection(home);compatible(client)
    if any(not t.get('quiescent') or t['status'] in {'requires_approval','requires_human'} for t in client.request('/localpilot/v1/tasks')['tasks']):
        raise ValueError('Resolve active tasks and approvals before adding a provider')
    config=private_json(home/'service.json')
    if 'deepseek-agent' in config['routes']:
        return {'status':'already_configured','cloud_egress':'REQUIRES_APPROVAL','model':'deepseek-flash','credential_copied':False,'api_connection':'NOT_PROBED'}
    agent=deepcopy(config['routes']['default'])
    agent.update(engine='v5',backend={'kind':'deepseek-native','model':'deepseek-flash','key_file':str(Path(key_file).expanduser().resolve()),'context_budget':1000000,'timeout':45},
        cloud_egress='REQUIRES_APPROVAL',deployment_status='ready',thinking='none',routing_rank={'speed':60,'quality':95,'efficiency':60,'balanced':60})
    reasoning=deepcopy(agent)
    reasoning.update(reasoning_only=True,prompt_profile='minimal_0',tool_profile='compact',capabilities={'read':False,'write':False,'execute':False})
    config['routes'].update({'deepseek-agent':agent,'companion-cloud-reasoning':reasoning})
    local=deepcopy(config['routes'].get('local-v5',config['routes']['default']))
    local.update(cooperation={'cloud_route':'deepseek-agent'},cloud_egress='REQUIRES_APPROVAL')
    config['routes']['local-cloud-agent']=local
    for principal in config['clients']:
        if not principal.get('operator'):
            principal['routes'].update({'deepseek-agent':'deepseek-agent','companion-cloud-reasoning':'companion-cloud-reasoning','local-cloud-agent':'local-cloud-agent'})
    if not any(p['subject']=='resource' for p in config['clients']):
        config['clients'].append({'subject':'resource','token_env':'LOCALPILOT_RESOURCE_TOKEN','operator':True,'scopes':['read','resource_control'],'approval_for':['companion'],'routes':{}})
        fd=os.open(home/'clients.env',os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW)
        with os.fdopen(fd,'a') as f:f.write('export LOCALPILOT_RESOURCE_TOKEN='+secrets.token_urlsafe(32)+'\n')
    backup=home/('service.before-cloud-'+str(time.time_ns())+'.json')
    save(backup,private_json(home/'service.json'))
    stopped=stop(home)
    if stopped['status']!='stopped':raise ValueError('Core has not stopped; provider configuration unchanged')
    save(home/'service.json',config)
    try:start(home)
    except Exception:
        save(home/'service.json',private_json(backup));start(home);raise
    companion=private_json(home/'companion.json')
    companion.update(localpilot_allow_cloud=True,localpilot_resource_key_env='LOCALPILOT_RESOURCE_TOKEN')
    save(home/'companion.json',companion)
    env={k:v for k,v in environment(home).items() if 'OPERATOR' not in k.upper() and 'DEEPSEEK' not in k.upper()}
    for command in ['stop','start']:
        result=subprocess.run([sys.executable,'-m','companion','--config',str(home/'companion.json'),'--json',command],env=env,capture_output=True,timeout=30)
        if result.returncode:raise ValueError('Companion restart incomplete; inspect service status')
    return {'status':'configured','cloud_egress':'REQUIRES_APPROVAL','model':'deepseek-flash','credential_copied':False,'api_connection':'NOT_PROBED','backup':str(backup)}


def configure_cloud_scope(home, paths):
    from copy import deepcopy
    from pathlib import PurePosixPath
    import time
    from localpilot_service.cli import stop,start,save
    from localpilot_service.security import private_json
    if not isinstance(paths,list) or not 1<=len(paths)<=32 or any(not isinstance(p,str) or not p or len(p)>1024 or PurePosixPath(p).is_absolute() or '..' in PurePosixPath(p).parts or str(PurePosixPath(p))!=p for p in paths):
        raise ValueError('Choose 1-32 exact normalized workspace-relative file paths')
    config=private_json(home/'service.json')
    if 'deepseek-agent' not in config['routes']:raise ValueError('Configure DeepSeek first')
    name='deepseek-files-'+str(time.time_ns())
    route=deepcopy(config['routes']['deepseek-agent']);route['cloud_egress_paths']=list(dict.fromkeys(paths))
    config['routes'][name]=route
    cooperative=None
    if 'local-cloud-agent' in config['routes']:
        cooperative=name+'-cooperative';cop=deepcopy(config['routes']['local-cloud-agent']);cop['cloud_egress_paths']=list(dict.fromkeys(paths));config['routes'][cooperative]=cop
    for p in config['clients']:
        if not p.get('operator'):
            p['routes'][name]=name
            if cooperative:p['routes'][cooperative]=cooperative
    backup=private_json(home/'service.json')
    if stop(home)['status']!='stopped':raise ValueError('Core is still stopping; scope unchanged')
    save(home/'service.json',config)
    try:start(home)
    except Exception:
        save(home/'service.json',backup);start(home);raise
    return {'status':'configured','route':name,'cooperative_route':cooperative,'cloud_egress_paths':route['cloud_egress_paths'],'existing_sessions':'unchanged; choose the new route for a new Session'}


def attach_omlx(home, base, settings_path):
    """Add a local backend to an existing cloud-only installation; keep old routes."""
    from copy import deepcopy
    import secrets,time
    from localpilot_service.cli import stop,start,save
    from localpilot_service.security import private_json
    home=Path(home);before=private_json(home/'service.json');old_connection=private_json(home/'connection.json')
    if any(r.get('backend',{}).get('kind')=='omlx' for r in before['routes'].values()):return
    config=deepcopy(before);conn=deepcopy(old_connection)
    template=deepcopy(config['routes'].get('default') or next(iter(config['routes'].values())))
    template.update(engine='v5',reasoning_only=False,prompt_profile='standard',tool_profile='full',cloud_egress='LOCAL_ONLY',deployment_status='ready')
    template.pop('verification',None);template.pop('cooperation',None)
    template['backend']={'kind':'omlx','model':'not-selected','base_url':base,'api_key_env':'LOCALPILOT_OMLX_API_KEY','context_budget':65536,'include_stream_usage':True,'chat_template_kwargs':{'enable_thinking':False}}
    name='omlx-bootstrap';config['routes'][name]=template
    for client in config['clients']:
        if not client.get('operator'):client['routes'][name]=name
    resource=not any(p.get('subject')=='resource' for p in config['clients'])
    if resource:config['clients'].append({'subject':'resource','token_env':'LOCALPILOT_RESOURCE_TOKEN','operator':True,'scopes':['read','resource_control'],'approval_for':[p['subject'] for p in config['clients'] if not p.get('operator')],'routes':{}})
    conn.update(omlx_settings_file=str(settings_path),omlx_base_url=base)
    if stop(home)['status']!='stopped':raise ValueError('Core is still stopping; local backend was not attached')
    save(home/f'service.before-local-{time.time_ns()}.json',before)
    if resource:
        fd=os.open(home/'clients.env',os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW)
        with os.fdopen(fd,'a') as f:f.write('export LOCALPILOT_RESOURCE_TOKEN='+secrets.token_urlsafe(32)+'\n')
    save(home/'service.json',config);save(home/'connection.json',conn)
    try:start(home)
    except Exception:
        save(home/'service.json',before);save(home/'connection.json',old_connection);start(home);raise


def configure_pet_model(home):
    """Explicitly select an already downloaded tiny model; no observers or downloads."""
    from localpilot_service.cli import environment,save,connection
    from localpilot_service.security import private_json
    from .product_control import backend_settings
    base,settings=backend_settings();models=discover_omlx(base+'/v1',settings.get('auth',{}).get('api_key'))
    small=[m for m in models if type(m.get('size_bytes')) is int and 0<m['size_bytes']<=1500000000]
    if not small:raise ValueError('尚未下载轻量模型。请在模型库搜索并下载 Qwen3.5-0.8B-4bit，然后回来连接。')
    selected=min(small,key=lambda m:(0 if 'Qwen3.5-0.8B-4bit' in m['id'] else 1,m['size_bytes']))
    model_path=Path(selected['model_path']).resolve(strict=True)
    meta=json.loads((model_path/'config.json').read_text())
    if meta.get('auto_map') or meta.get('model_file'):raise ValueError('模型包含未授权的自定义代码，未连接')
    client=connection(home)
    if client.request('/healthz').get('active_task_count',1):raise ValueError('请先等待活动 Agent 任务结束，再更换宠物模型')
    path=home/'companion.json';config=private_json(path);before=dict(config)
    config.update(backend='omlx',model_path=str(model_path),http_model_endpoint=base+'/v1',http_model_name=selected['id'],http_model_api_key_env='LOCALPILOT_OMLX_API_KEY',http_model_host_local_only=True,model_routing_enabled=False,desktop_control_enabled=True,low_power_policy='system',local_model_min_available_bytes=4*1024**3)
    env={k:v for k,v in environment(home).items() if 'OPERATOR' not in k.upper() and 'DEEPSEEK' not in k.upper()}
    def run(command):
        r=subprocess.run([sys.executable,'-m','companion','--config',str(path),'--json',command],env=env,capture_output=True,text=True,timeout=30)
        if r.returncode:raise ValueError('Companion service change failed; original configuration retained')
    run('stop');save(path,config)
    try:run('start')
    except Exception:save(path,before);run('start');raise
    return {'status':'configured','model':selected['id'],'loaded':selected['loaded'],'downloaded':False,'privacy_scope_changed':False,'next':'模型未加载时，请在模型库单独确认加载。'}

def migrate_desktop_acceptance_route(home):
    """Preserve exact legacy QA routes/history; add an everyday route with empty disclosure.

    No directory, execute grant, provider credential or model is added. Only the
    known fixture configuration is recognized; custom routes are untouched.
    """
    from copy import deepcopy
    from localpilot_service.cli import save,stop
    from localpilot_service.security import private_json
    import time
    home=Path(home);config=private_json(home/'service.json')
    legacy=config['routes'].get('gui-cloud-approval',{})
    if ('desktop-file-agent-v1' in config['routes'] or legacy.get('verification',{}).get('id')!='desktop-approved-file'
        or legacy.get('cloud_egress_paths')!=['fixture.txt','approved.txt'] or legacy.get('capabilities')!={'read':True,'write':True,'execute':False}):
        return {'status':'not_applicable'}
    route={k:deepcopy(legacy[k]) for k in ['workspace','backend','permissions','capabilities','cloud_egress','prompt_profile','tool_profile','thinking'] if k in legacy}
    route.update(engine='v5',cloud_egress_paths=[],budgets={'max_steps':24,'max_tool_calls':64,'max_output_tokens':4096,'max_token_units':1048576})
    if route['backend'].get('kind')=='deepseek' and 'base_url' not in route['backend']:
        route['backend']['kind']='deepseek-native'
    config['routes']['desktop-file-agent-v1']=route
    for client in config['clients']:
        if client.get('subject') in {'http','codex','dsh'} and not client.get('operator'):client.setdefault('routes',{})['desktop-file-agent-v1']='desktop-file-agent-v1'
    # Caller is the explicit component setup/upgrade workflow, never task input.
    if stop(home)['status']!='stopped':raise ValueError('Stop the active service before migrating the exact legacy acceptance route')
    save(home/('service.before-permission-agent-'+str(time.time_ns())+'.json'),private_json(home/'service.json'))
    save(home/'service.json',config)
    return {'status':'migrated','route':'desktop-file-agent-v1','workspace_changed':False,'execute_granted':False,'cloud_paths':[],'legacy_sessions_preserved':True}
