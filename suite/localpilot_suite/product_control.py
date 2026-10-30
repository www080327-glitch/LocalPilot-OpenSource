"""Versioned native product operations. Never evaluates commands supplied by WebView."""
import http.cookiejar
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
from urllib.error import HTTPError
from urllib.parse import urlencode, quote
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request, HTTPRedirectHandler


def backend_settings():
    from localpilot_service.security import private_json
    p=Path.home()/'.omlx/settings.json'
    if not p.is_file():raise ValueError('本地推理服务尚未配置，请在首次使用向导中准备本机服务')
    settings=private_json(p)
    port=settings.get('server',{}).get('port')
    if type(port) is not int or not 1<=port<=65535:raise ValueError('oMLX port is invalid')
    return f'http://127.0.0.1:{port}',settings


class OmlxRejection(ValueError):
    definitive_rejection=True


class NoBackendRedirects(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None


class OmlxAdmin:
    def __init__(self):
        self.base,self.settings=backend_settings()
        self.opener=build_opener(ProxyHandler({}),HTTPCookieProcessor(http.cookiejar.CookieJar()),NoBackendRedirects())
        # Main key and admin cookie stay inside this trusted process.
        key=self.settings.get('auth',{}).get('api_key')
        if not self.settings.get('auth',{}).get('skip_api_key_verification'):
            if not key:raise ValueError('Configure the local oMLX service first')
            self.request('/admin/api/login',{'api_key':key,'remember':False})
        self.schema=self.request('/openapi.json')
        self.paths=self.schema.get('paths',{})
    def request(self,path,body=None,method=None):
        if not path.startswith('/') or path.startswith('//'):raise ValueError('Invalid service path')
        headers={'Content-Type':'application/json'}
        key=self.settings.get('auth',{}).get('api_key')
        if key:headers['Authorization']='Bearer '+key
        req=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,
            headers=headers,method=method or ('POST' if body is not None else 'GET'))
        try:
            with self.opener.open(req,timeout=45) as response:return json.load(response)
        except HTTPError as e:
            if 400<=e.code<500:raise OmlxRejection(f'oMLX 拒绝此操作（HTTP {e.code}），未自动重试') from None
            raise ValueError(f'UNKNOWN：oMLX 返回 HTTP {e.code}，请核对状态；未自动重试') from None
    def supports(self,path,method='get'):return method in self.paths.get(path,{})
    def require(self,path,method='get'):
        if not self.supports(path,method):raise ValueError('Installed oMLX does not support this operation')
    def capabilities(self):
        schema=self.schema.get('components',{}).get('schemas',{}).get('ModelSettingsRequest',{}).get('properties',{})
        fields=[x for x in ['max_context_window','ttl_seconds','is_favorite','is_pinned','temperature','top_p','top_k','max_tokens'] if x in schema]
        return {'version':1,'search':self.supports('/admin/api/hf/search'),'download':self.supports('/admin/api/hf/download','post'),
            'jobs':self.supports('/admin/api/hf/tasks'),'cancel':self.supports('/admin/api/hf/cancel/{task_id}','post'),
            'retry':self.supports('/admin/api/hf/retry/{task_id}','post'),'delete':self.supports('/admin/api/hf/models/{model_name}','delete'),'settings_fields':fields,
            'cache':{'prompt_prefix':self.settings.get('cache',{}).get('enabled') is True,
                'ssd_enabled':self.settings.get('cache',{}).get('enabled') is True and not self.settings.get('cache',{}).get('hot_cache_only',False),
                'restart_persistence':'NOT_VERIFIED','per_model_toggle':False,'retention_guaranteed':False},'pause':False,'auto_load':False,'memory_budget':False,'batching':False}


def active_power_policy(power, settings):
    """Project only the current macOS profile; unknown is not permission."""
    match=re.search(r"^Now drawing from '(AC Power|Battery Power)'\s*$",power,re.MULTILINE)
    if not match:return None,None
    source=match[1];current=None;values=[]
    for line in settings.splitlines():
        header=re.fullmatch(r'(AC Power|Battery Power|UPS Power):',line.strip())
        if line and not line[0].isspace() and line.rstrip().endswith(':'):
            current=header[1] if header else None
        elif current==source:
            value=re.fullmatch(r'\s*lowpowermode\s+([01])\s*',line)
            if value:values.append(value[1])
    return source,(values[0]=='1') if len(values)==1 else None


def hardware(home):
    import psutil
    from hardware import get_hardware
    from recommender import recommend_primary as recommend
    hw=get_hardware();vm=psutil.virtual_memory();disk=shutil.disk_usage(home if home.exists() else Path.home())
    hw.update(memory_bytes=vm.total,available_memory_bytes=vm.available,free_disk_bytes=disk.free,cpu_count=psutil.cpu_count(),gpu='Apple integrated GPU' if hw['arch']=='arm64' else 'UNKNOWN')
    try:
        display=subprocess.run(['/usr/sbin/system_profiler','-json','SPDisplaysDataType'],capture_output=True,text=True,timeout=10,check=True)
        gpu=json.loads(display.stdout).get('SPDisplaysDataType',[])
        hw['gpu_devices']=[{k:g[k] for k in ['_name','sppci_model','spdisplays_cores','spdisplays_vendor'] if k in g} for g in gpu]
        hw['gpu']=gpu[0].get('sppci_model',gpu[0].get('_name','UNKNOWN')) if gpu else 'UNKNOWN'
    except (OSError,ValueError,subprocess.SubprocessError):hw['gpu_devices']=[]
    try:
        hw['power']=subprocess.run(['/usr/bin/pmset','-g','batt'],capture_output=True,text=True,timeout=3,check=True).stdout.strip()
        hw['power_policy']=subprocess.run(['/usr/bin/pmset','-g','custom'],capture_output=True,text=True,timeout=3,check=True).stdout.strip()
        source,low=active_power_policy(hw['power'],hw['power_policy'])
        after=subprocess.run(['/usr/bin/pmset','-g','batt'],capture_output=True,text=True,timeout=3,check=True).stdout.strip()
        if active_power_policy(after,hw['power_policy'])[0]!=source:source,low=None,None
        hw.update(active_power_source=source or 'UNKNOWN',active_low_power_mode=low)
    except (OSError,subprocess.SubprocessError):hw.update(power='UNKNOWN',active_power_source='UNKNOWN',active_low_power_mode=None)
    try:
        from .desktop_setup import discover_omlx
        base,settings=backend_settings();observed=discover_omlx(base+'/v1',settings.get('auth',{}).get('api_key'));hw['models']=observed;hw['backends']=['omlx']
    except Exception:hw['models']=[];hw['backends']=[]
    from localpilot_service.protocol import local_agent_constraints
    constraints=local_agent_constraints()
    r=recommend(vm.total/1024**3,available_memory_gb=vm.available/1024**3,context_k=constraints['minimum_context']//1024,minimum_context_k=constraints['minimum_context']//1024,excluded_size_classes=constraints['excluded_size_classes'],os_name=hw['os'],arch=hw['arch'],chip=hw['chip'])
    if r:
        r['download_bytes_estimate']=round(r['model']['artifact_gb']*1024**3);r['disk_compatible']=r['download_bytes_estimate']+2*1024**3<=disk.free
        r['power_compatible']=hw.get('active_low_power_mode') is False or r['download_bytes_estimate']<=1500000000
        r['compatibility']='power_constrained' if not r['power_compatible'] else 'estimated_memory_fit' if r['disk_compatible'] else 'insufficient_disk'
        if not r['power_compatible']:
            r['reason']+=(' 暂时无法确认当前电源策略。可稍后重新检测，或跳过本地模型。' if hw.get('active_low_power_mode') is None
                else ' 当前低电量策略限制此大小模型的推理。可跳过本地模型，或在系统调整后重新检测。')
    return {'version':1,'hardware':hw,'recommendation':r,'installation': installation_state(home),
        'omlx_installed':any((p/'oMLX.app').is_dir() for p in [Path('/Applications'),Path.home()/'Applications']),
        'core_configured':(home/'connection.json').exists(),'agent_constraints':constraints,'model_download_forced':False}


def installation_state(home):
    present=[(home/f).exists() for f in ['connection.json','service.json','clients.env']]
    if any(present) and not all(present):return 'repair_required'
    if not any(present):return 'first_launch'
    try:
        from localpilot_service.cli import connection
        health=connection(home).request('/healthz')
        return 'existing' if 'desktop_session_v1' in health.get('compatibility',{}).get('capabilities',[]) else 'upgrade_available'
    except Exception:return 'installed_service_stopped'


def operator(home):
    from localpilot_service.cli import connection,environment
    from localpilot_service.sdk import Client
    client=connection(home);health=client.request('/healthz');env=environment(home)
    key=env.get('LOCALPILOT_OPERATOR_TOKEN')
    if not key:raise ValueError('Trusted operator is not configured for this installation')
    return Client(client.base_url,token=key,timeout=60),health


def dispatch(home,body):
    if not isinstance(body,dict) or body.get('version')!=1 or not isinstance(body.get('operation'),str):raise ValueError('Product contract version 1 required')
    op=body['operation'];args=body.get('args',{})
    if set(body)-{'version','operation','args'} or not isinstance(args,dict):raise ValueError('Invalid product request')
    if op=='channels':
        if set(args)!={'kind','action','args'}:raise ValueError('Exact channel operation required')
        from .channel_product import command
        return command(home,args['kind'],args['action'],args['args'])
    if op=='inspect':return hardware(home)
    if op=='installation_diagnostics':
        if args:raise ValueError('Diagnostics accepts no arguments')
        from .installation import diagnostics
        return diagnostics(home)
    if op=='prepare_uninstall':
        if args!={'confirmed':True}:raise ValueError('Explicit uninstall preparation required')
        from .installation import service
        from localpilot_service.lifecycle import unregister
        result=service(home,'core','stop')
        if result.get('status')!='stopped':raise ValueError('Core 尚未停止，请稍后重试')
        service(home,'companion','stop')
        unregister(home)
        return {'status':'stopped','data_preserved':True,'models_preserved':True,'next':'退出 LocalPilot 后将应用移到废纸篓。用户数据、密钥和 oMLX 保留。'}
    if op=='service_control':
        if set(args)!={'module','action','confirmed'} or args['confirmed'] is not True:raise ValueError('Exact service action required')
        from .installation import service
        return service(home,args['module'],args['action'])
    if op=='restore_installation':
        if set(args)!={'source','destination'}:raise ValueError('Exact backup and new destination required')
        from .product_backup import restore
        return restore(args['source'],args['destination'])
    if op=='configure_pet_model':
        if args!={'confirmed':True}:raise ValueError('Explicit local pet model selection required')
        from .desktop_setup import configure_pet_model
        return configure_pet_model(home)
    if op=='backup_installation':
        if set(args)!={'destination'}:raise ValueError('Exact backup destination required')
        from .product_backup import backup
        return backup(home,Path(args['destination']))
    if op=='preferences':
        from localpilot_service.cli import save,private_dir
        from localpilot_service.security import private_json
        path=private_dir(home)/'model-preferences.json'
        values=private_json(path) if path.exists() else {}
        if args:
            if set(args)!={'model','value'} or not isinstance(args['model'],str) or len(args['model'])>240 or not isinstance(args['value'],dict) or set(args['value'])!={'favorite','cache_prefix'} or any(type(v) is not bool for v in args['value'].values()):raise ValueError('Invalid model preferences')
            values[args['model']]=args['value'];save(path,values)
        return {'models':values,'cache_effect':'preference_only; backend shared cache has no per-model control'}

    if op=='workspace_grants':
        client,health=operator(home)
        return client.request('/localpilot/v1/workspace-grants',{'client_subject':health['client_subject'],**args})
    if op=='desktop_session':
        if set(args)-{'model','permission_mode','agent_profile','source','key','workspace_grant'} or not {'model','permission_mode','agent_profile','source','key'}<=set(args):raise ValueError('Exact session settings required')
        client,health=operator(home)
        return client.request('/localpilot/v1/desktop-sessions',{'client_subject':health['client_subject'],'model':args['model'],'options':{k:args[k] for k in ['permission_mode','agent_profile','workspace_grant'] if k in args},'source':args['source']},key=__import__('hashlib').sha256(str(args['key']).encode()).hexdigest())
    if op=='desktop_profile':
        if set(args)!={'session_id','agent_profile','expected_profile'} or not isinstance(args['session_id'],str) or not re.fullmatch(r'sess_[A-Za-z0-9_-]{1,128}',args['session_id']):raise ValueError('Exact Desktop session required')
        client,health=operator(home)
        return client.request('/localpilot/v1/desktop-sessions/'+args['session_id']+'/profile',{'client_subject':health['client_subject'],'agent_profile':args['agent_profile'],'expected_profile':args['expected_profile']})
    if op=='attachments':
        if set(args)!={'model','paths'}:raise ValueError('Exact selected file references required')
        client,health=operator(home)
        return client.request('/localpilot/v1/attachments/import',{'client_subject':health['client_subject'],**args})
    if op=='documents':
        if not isinstance(args,dict) or args.get('operation') not in {'import','list','status','read','process','reindex','search','verify','cancel','revoke','gc','vision_plan','vision_approve','vision_infer'} or 'session_id' not in args:raise ValueError('Versioned document operation required')
        client,health=operator(home)
        return client.request('/localpilot/v2/attachments',{'client_subject':health['client_subject'],**args})
    if op=='initialize_backend':
        if args!={'confirmed':True}:raise ValueError('Service setup confirmation required')
        from .product_installer import initialize_service
        return initialize_service()
    if op=='install_backend':
        if args!={'confirmed':True}:raise ValueError('Installation must be explicitly confirmed')
        from .product_installer import install
        return install()
    admin=OmlxAdmin();cap=admin.capabilities()
    if op=='verify_model':
        if set(args)!={'repo_id'}:raise ValueError('Exact model repository required')
        validate_repo(args['repo_id'])
        from .model_integrity import verify
        return verify(admin,home,args['repo_id'])
    if op=='capabilities':return cap
    if op=='catalog':
        result=admin.request('/admin/api/models')
        return {'version':1,'capabilities':{**cap,'integrity':True},'catalog':result,'jobs':admin.request('/admin/api/hf/tasks') if cap['jobs'] else {'tasks':[]}}
    if op=='search':
        if set(args)!={'query'} or not isinstance(args['query'],str) or len(args['query'])>200:raise ValueError('Invalid search')
        admin.require('/admin/api/hf/search');return admin.request('/admin/api/hf/search?'+urlencode({'q':args['query'],'limit':30}))
    if op=='info':
        repo=args.get('repo_id');validate_repo(repo);admin.require('/admin/api/hf/model-info')
        return admin.request('/admin/api/hf/model-info?'+urlencode({'repo_id':repo}))
    if op=='download':
        if set(args)!={'repo_id','confirmed'} or args['confirmed'] is not True:raise ValueError('Download confirmation required')
        repo=args['repo_id'];validate_repo(repo);admin.require('/admin/api/hf/download','post')
        info=admin.request('/admin/api/hf/model-info?'+urlencode({'repo_id':repo}))
        size=info.get('size') or info.get('total_size') or info.get('total_size_bytes')
        if type(size) is not int or size<=0:raise ValueError('Download size is unknown; use official model details before downloading')
        if shutil.disk_usage(Path.home()).free<size+2*1024**3:raise ValueError('Insufficient disk space for download and verification')
        from .download_journal import download
        return download(admin,home,repo)
    if op in {'cancel','retry'}:
        if set(args)!={'id','confirmed'} or args['confirmed'] is not True or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',str(args['id'])):raise ValueError('Exact download task required')
        path='/admin/api/hf/'+op+'/{task_id}';admin.require(path,'post')
        return admin.request(path.replace('{task_id}',args['id']),{} if op=='retry' else None,method='POST')
    if op=='delete':
        if set(args)!={'model','confirmed','typed_name'} or args['confirmed'] is not True or args['typed_name']!=args['model']:raise ValueError('Confirm the exact model name')
        model=args['model']
        if not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,240}',model):raise ValueError('Invalid model identity')
        observed=admin.request('/admin/api/models').get('models',[])
        entry=next((m for m in observed if m.get('id')==model),None)
        if entry is None or entry.get('loaded') is not False:raise ValueError('Only an observed unloaded model can be deleted')
        if admin.request('/api/status').get('active_requests')!=0:raise ValueError('Model service is busy; no deletion performed')
        admin.require('/admin/api/hf/models/{model_name}','delete')
        if any(t.get('status') in {'pending','downloading'} for t in admin.request('/admin/api/hf/tasks').get('tasks',[])):raise ValueError('请先完成或停止下载任务，再删除模型')
        result=admin.request('/admin/api/hf/models/'+quote(model,safe=''),method='DELETE')
        from .download_journal import model_deleted
        model_deleted(admin,home,model)
        return result
    if op=='settings':
        if set(args)!={'model','settings','confirmed'} or args['confirmed'] is not True:raise ValueError('Explicit settings confirmation required')
        model=args['model'];values=args['settings']
        if not isinstance(model,str) or not model or '/' in model or '..' in model:raise ValueError('Invalid model identity')
        if not isinstance(values,dict) or set(values)-set(cap['settings_fields']):raise ValueError('Unsupported backend parameter')
        limits={'max_context_window':(1024,262144),'ttl_seconds':(30,86400),'temperature':(0,2),'top_p':(0,1),'top_k':(0,1000),'max_tokens':(1,32768)}
        for k,v in values.items():
            if v is None:continue
            if k in limits and (type(v) not in {int,float} or not limits[k][0]<=v<=limits[k][1]):raise ValueError('Invalid model parameter: '+k)
            if k in {'is_favorite','is_pinned'} and type(v) is not bool:raise ValueError('Boolean expected')
        if values.get('max_context_window') is not None:
            entry=next((m for m in admin.request('/admin/api/models').get('models',[]) if m.get('id')==model),None)
            limit=(entry or {}).get('model_context_length')
            if not entry or type(limit) is not int:raise ValueError('The model native context limit is unknown; settings were not changed')
            if values['max_context_window']>limit:raise ValueError('Requested context exceeds the model native limit')
        if (values.get('max_context_window') or 0)>32768:
            import psutil
            if psutil.virtual_memory().available<8*1024**3:raise ValueError('Insufficient available memory for a large context; lower the context length')
        from localpilot_service.cli import connection
        if connection(home).request('/healthz').get('active_task_count',1):raise ValueError('请先结束活动任务，再修改模型设置。新上下文用于新会话。')
        admin.require('/admin/api/models/{model_id}/settings','put')
        return admin.request('/admin/api/models/'+quote(model,safe='')+'/settings',values,method='PUT')
    raise ValueError('Unsupported product operation')


def validate_repo(repo):
    if not isinstance(repo,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,150}',repo):raise ValueError('Expected a repository model identity')
