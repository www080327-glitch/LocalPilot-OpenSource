"""Bounded desktop channel controls over Suite and the official Core.

No Agent loop, shell evaluation, automatic task replay, or arbitrary URL/path API.
Secrets enter only through the native controller's stdin, never argv or WebView.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import sys
import time
import uuid
from . import channels
from .channel_paths import private_directory, private_file, private_json
from . import channel_runtime

KINDS = ('qq', 'wechat')
FIELDS = {
    'status': set(), 'diagnose': set(), 'install': {'confirmed'}, 'update': {'confirmed'}, 'uninstall': {'confirmed'}, 'workspace': {'path','confirmed'},
    'cancel_download': set(), 'qq_credentials': {'app_id', 'app_secret', 'confirmed'},
    'login': {'confirmed'}, 'login_status': set(), 'cancel_login': set(),
    'discover': {'confirmed'}, 'configure': {'senders', 'model', 'allow_write', 'confirmed'},
    'start': {'confirmed'}, 'stop': {'confirmed'}, 'disconnect': {'confirmed'},
    'operator': {'senders', 'enabled', 'confirmed'}, 'receipts': set(),
    'rollback': {'confirmed'}, 'background': {'enabled', 'confirmed'},
    'decision': {'task_id','approval_id','preview_fingerprint','decision_id','decision','confirmed'},
    'history': {'generation'}, 'fresh': {'confirmed'}, 'cancel_task': {'task_id','confirmed'}, 'restore_review': {'confirmed'},
    'skip': set(), 'exit': set(),
}

def roots(home, kind, create=False):
    home = private_directory(home, create=create)
    if kind not in KINDS:
        raise ValueError('CHANNEL_KIND_REJECTED')
    hub = home / 'message-platforms' / kind
    if create:
        private_directory(hub, create=True)
    elif hub.exists() or hub.is_symlink():
        private_directory(hub)
    return hub, home / 'message-state' / kind / settings(hub).get('generation', 'preparation') / 'bridge'

def settings(hub):
    state = private_json(hub / 'settings.json') if (hub / 'settings.json').exists() or (hub / 'settings.json').is_symlink() else {}
    if not isinstance(state,dict) or ('generation' in state and not isinstance(state['generation'],str)) or (state.get('generation','preparation')!='preparation' and not re.fullmatch('[a-f0-9]{32}',state['generation'])):
        raise ValueError('CHANNEL_SETTINGS_GENERATION_INVALID')
    return state

def store_settings(hub, value):
    channels.save(hub / 'settings.json', value)

def credentials(hub):
    return private_json(hub / 'credentials.json') if (hub / 'credentials.json').exists() or (hub / 'credentials.json').is_symlink() else {}

def component_home(hub, state):
    generation=state.get('generation','preparation')
    if not isinstance(generation,str) or (generation!='preparation' and not re.fullmatch('[a-f0-9]{32}',generation)):
        raise ValueError('CHANNEL_SETTINGS_GENERATION_INVALID')
    return hub/'generations'/generation

def runtime_root(hub, state):
    return component_home(hub, state) / 'channels'

def state_info(state_dir):
    path = state_dir / 'state.json'
    if not path.exists() and not path.is_symlink():
        return {}
    private_file(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if os.fstat(fd).st_size > 128 * 1024 ** 2:
            raise ValueError('CHANNEL_STATE_BUDGET_EXCEEDED')
        with os.fdopen(fd, 'r', closefd=False) as stream:
            data = json.load(stream)
        if not isinstance(data,dict) or not isinstance(data.get('messages',{}),dict) or not isinstance(data.get('peers',[]),list):
            raise ValueError('CHANNEL_STATE_CORRUPT')
        return data
    finally:
        os.close(fd)

def unresolved(root, state_dir):
    data = state_info(state_dir)
    if data.get('blocked') or any(item.get('status') in {'unknown', 'submitting'}
        or item.get('delivery') in {'unknown', 'sending'} for item in data.get('messages', {}).values()):
        return True
    db = Path(channels.configured(root)['state']) / 'adapter/channels.sqlite3' if (root / 'configuration.json').exists() else state_dir.parent / 'services' / 'adapter/channels.sqlite3'
    if db.exists():
        private_file(db)
        connection = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
        try:
            for (raw,) in connection.execute("SELECT data FROM items WHERE id LIKE 'message:%'"):
                item = json.loads(raw)
                if item.get('status') == 'unknown' or item.get('decision_hold'):
                    return True
        finally:
            connection.close()
    return False

def wheel_source():
    # This exact directory is supplied by the signed APP resource layout.
    resources = Path(sys.prefix).parent
    manifest = json.loads((resources / 'verified-modules.json').read_text())
    candidates = list((resources / 'wheels').glob('localpilot_channels-*.whl'))
    if len(candidates) != 1 or candidates[0].is_symlink():
        raise ValueError('CHANNEL_REVIEWED_BUNDLED_WHEEL_MISSING')
    path = candidates[0]
    if channel_runtime.digest(path) != manifest.get('wheel_hashes', {}).get(path.name):
        raise ValueError('CHANNEL_BUNDLED_WHEEL_INTEGRITY_FAILED')
    return path

def component_compatible(root):
    if not channels.installed(root):return False
    record=private_json(root/'installation.json')
    return record.get('transport_contract')==2 and record.get('wheel_sha256')==channel_runtime.digest(wheel_source())


def update_component(home,hub,state,kind):
    root=runtime_root(hub,state)
    if root.exists():
        for component in (kind,'adapter'):
            result=channels.main(['stop',component],component_home(hub,state))
            if result.get('status')!='stopped':return result
        archive=private_directory(root/'code-archives'/uuid.uuid4().hex,create=True)
        if (root/'runtime').exists():
            private_directory(root/'runtime');(root/'runtime').rename(archive/'runtime')
        if (root/'installation.json').exists():
            private_file(root/'installation.json');(root/'installation.json').rename(archive/'installation.json')
    install_component(home,hub,state)
    return {'status':'updated','state_preserved':True,'processes_started':False}


def install_component(home, hub, state):
    node = channel_runtime.installed(home)
    if node is None:
        raise ValueError('CHANNEL_OPTIONAL_RUNTIME_REQUIRED')
    target = component_home(hub, state)
    private_directory(target, create=True)
    root = target / 'channels'
    if channels.installed(root) and not component_compatible(root):raise ValueError('CHANNEL_COMPONENT_UPDATE_REQUIRED')
    if not channels.installed(root):
        channels.main(['install', '--wheel', str(wheel_source())], target, node_path=node)
    return node

def bridge_env(hub, kind, state_dir, config=None):
    values = credentials(hub)
    if config is not None:
        env = channels.environment(config, kind, values)
    else:
        env = {key: os.environ[key] for key in channels.BASE_ENV if key in os.environ}
        env.update(LOCALPILOT_MESSAGE_KEY=values['LP_CHANNEL_INGRESS'],
            LOCALPILOT_MESSAGE_ADAPTER_URL='http://127.0.0.1:1')
        env['LOCALPILOT_' + kind.upper() + '_STATE_DIR'] = str(state_dir)
        env['LOCALPILOT_' + kind.upper() + '_SENDERS'] = '[]'
        if kind == 'qq':
            if not values.get('QQ_BOT_APP_ID') or not values.get('QQ_BOT_APP_SECRET'):
                raise ValueError('QQ_NATIVE_CREDENTIALS_REQUIRED')
            env.update({key: values[key] for key in ('QQ_BOT_APP_ID', 'QQ_BOT_APP_SECRET')})
    env['LOCALPILOT_' + kind.upper() + '_STATE_DIR'] = str(state_dir)
    env['LOCALPILOT_CHANNEL_GUI'] = '1'
    return env

def core_models(home):
    if not (home / 'service.json').exists():
        return []
    config = private_json(home / 'service.json')
    return [{'id': name, 'name': route['backend'].get('model', name),
        'cloud':route['backend'].get('kind') in {'deepseek','deepseek-native','remote-openai','remote-vllm'},
        'ready': route['backend'].get('kind') != 'unavailable' and route['backend'].get('model') != 'not-selected'}
        for name, route in config['routes'].items()
        if route['backend'].get('kind') in {'unavailable', 'omlx', 'local-openai', 'vllm','deepseek','deepseek-native','remote-openai','remote-vllm'}
        and not route.get('reasoning_only') and not route.get('managed_local_model') and not name.startswith('channel-')]

def status(home, kind, include_login=False):
    hub, state_dir = roots(home, kind)
    if not hub.exists():
        return {'kind': kind, 'status': 'not_installed', 'configured': False,
            'connected': False, 'models': core_models(home), 'background': False}
    state = settings(hub)
    root = runtime_root(hub, state)
    installed = channels.installed(root)
    compatible = component_compatible(root) if installed else False
    running = {component: bool(channels.process(root, component)) if root.exists() else False
        for component in (kind, 'adapter')}
    data = state_info(state_dir)
    peers = data.get('peers', [])
    account_name = data.get('appId') or (data.get('account') or {}).get('botId')
    result = {'kind': kind, 'status': 'not_configured' if installed else 'not_installed',
        'installed': installed, 'update_required':installed and not compatible, 'configured': bool(state.get('binding')), 'connected': False,
        'processes': running, 'background': state.get('background', False),
        'models': core_models(home), 'senders': [{'id': value, 'label': value[:7] + '…' + value[-4:],
            'allowed': value in state.get('senders', [])} for value in peers],
        'operator_enabled': bool(state.get('operator_senders')), 'skipped': state.get('skipped', False),
        'permissions': {'operator': False, 'shell': False, 'cloud': state.get('allow_cloud',False), 'computer_use': False,
            'write': state.get('allow_write', False), 'approval': 'approve-mutations',
            'workspace': state.get('workspace_label','独立渠道工作区')},
        'account': '…' + str(account_name)[-4:] if account_name else None,
        'source': 'official_core_agent_service', 'verification': 'NOT_RUN', 'history':state.get('history',[])}
    if installed and not compatible:
        result['status']='update_required'
    if (root/'installation.json').exists():
        record=private_json(root/'installation.json')
        result['advanced']={'component_version':record.get('version'),'transport_contract':record.get('transport_contract'),'managed_node_version':channel_runtime.VERSION,'api_contract':'1.0; live identities checked separately'}
    if (root/'configuration.json').exists():
        config=channels.configured(root);channels.validate_shape(config['adapter'])
        result.setdefault('advanced',{})['adapter_port']=config['port']
    if state.get('binding') and installed and compatible:
        result['status'] = 'stopped'
    if running[kind]:
        result['status'] = 'connecting'
    progress_path = state_dir / 'connection.json'
    if progress_path.exists():
        progress = private_json(progress_path)
        child = channels.process(root, kind)
        same = child is not None and progress.get('pid') == child.pid
        phase = progress.get('status')
        if same and phase in {'waiting_scan', 'waiting_confirmation', 'connecting'}:
            result['status'] = phase
            if include_login and phase in {'waiting_scan', 'waiting_confirmation'}:
                result['login_url'] = progress.get('login_url')
        elif same and phase == 'authenticated':
            result['status'] = 'awaiting_senders'
            if state.get('binding') and running['adapter']:
                try:
                    configuration = channels.configured(root)
                    key = credentials(hub)['LP_CHANNEL_INGRESS']
                    health = channels.request(configuration, '/healthz', key=key)
                    adapter = channels.process(root, 'adapter')
                    if health.get('pid') == adapter.pid and health.get('instance_id') == configuration['adapter']['instance_id']:
                        from localpilot_channels.client import ServiceClient
                        for sender in configuration['adapter']['channels'][0]['senders']:
                            ServiceClient(configuration['adapter']['service_url'], credentials(hub)[sender['token_env']], sender['subject'], timeout=2).identity()
                        result.update(status='connected', connected=True)
                except Exception:
                    result['status'] = 'UNKNOWN'
        elif (not child or same) and phase in {'expired', 'cancelled', 'auth_expired', 'fault', 'logged_in', 'UNKNOWN'}:
            result['status'] = phase
    if installed and not compatible:result.update(status='update_required',connected=False)
    from .channel_tasks import journal,decision_unknown
    decision_hold=any(decision_unknown(item) and item.get('generation')==state.get('generation','preparation') for item in journal(hub).values())
    if unresolved(root, state_dir) or decision_hold:
        result.update(status='UNKNOWN', connected=False, requires_manual_reconciliation=True)
    return result

def require_quiet(home):
    from .product_control import operator
    client, health = operator(home)
    tasks = client.request('/localpilot/v1/tasks').get('tasks', [])
    if health.get('active_task_count', 1) or any(not task.get('quiescent') or task['status'] in {'requires_approval', 'requires_human', 'unknown'}
        or task.get('receipt_summary', {}).get('unknown_effects') for task in tasks):
        raise ValueError('CORE_ACTIVE_APPROVAL_OR_UNKNOWN_REQUIRES_MANUAL_REVIEW')
    return tasks

def read_env(home):
    path = private_file(home / 'clients.env')
    raw = path.read_text()
    if any(not re.fullmatch(r'export [A-Z][A-Z0-9_]*=[a-zA-Z0-9_-]+', line) for line in raw.splitlines()):
        raise ValueError('CORE_CREDENTIAL_FORMAT_REJECTED')
    return raw

def replace_env(path, value):
    private_file(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(value); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)

def change_core(home, hub, config, env, expected_before=None):
    """A stopped Core observes the pair together; crash journal blocks further writes."""
    from localpilot_service.cli import stop
    from .installation import start_core
    require_quiet(home)
    if (hub / 'transaction.json').exists() and private_json(hub / 'transaction.json')['status'] == 'pending':
        raise ValueError('CHANNEL_CONFIGURATION_TRANSACTION_REQUIRES_ROLLBACK')
    backup = private_directory(hub / 'core-config-backups' / str(time.time_ns()), create=True)
    before=private_json(home/'service.json');before_env=read_env(home)
    if expected_before is not None and before!=expected_before:raise ValueError('CHANNEL_CORE_CHANGED_SINCE_PREVIEW')
    channels.save(backup/'service.json',before)
    replace_env(backup/'clients.env',before_env)
    channels.save(backup/'channel-settings.json',settings(hub))
    fingerprint=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=True).encode()).hexdigest()
    transaction={'status':'pending','backup':str(backup),'before_config':fingerprint(before),'after_config':fingerprint(config),
        'before_credentials':hashlib.sha256(before_env.encode()).hexdigest(),'after_credentials':hashlib.sha256(env.encode()).hexdigest(),
        'new_subjects':[p['subject'] for p in config['clients'] if p['subject'] not in {old['subject'] for old in before['clients']}]}
    channels.save(hub/'transaction.json',transaction)
    if stop(home).get('status') != 'stopped':
        raise ValueError('CORE_STOP_NOT_CONFIRMED_CONFIGURATION_PRESERVED')
    try:
        replace_env(home / 'clients.env', env)
        channels.save(home / 'service.json', config)
        start_core(home)
        channels.save(hub/'transaction.json',{**transaction,'status':'committed'})
    except Exception:
        # Never restart or overwrite an uncertain live Core. Explicit rollback follows.
        raise ValueError('CHANNEL_CORE_RESTART_UNKNOWN_USE_ROLLBACK') from None

def bind(home, kind, hub, state_dir, state, args):
    if state.get('binding'):
        raise ValueError('CHANNEL_EXISTING_BINDING_PRESERVED_DISCONNECT_BEFORE_RECONFIGURE')
    senders = args['senders']
    prefix = 'q_' if kind == 'qq' else 's_'
    if not isinstance(senders, list) or not 1 <= len(senders) <= 16 or len(set(senders)) != len(senders) or any(not isinstance(s, str) or not re.fullmatch(prefix + '[a-f0-9]{64}', s) for s in senders):
        raise ValueError('CHANNEL_SELECT_EXPLICIT_DISCOVERED_SENDERS')
    data = state_info(state_dir)
    if not set(senders) <= set(data.get('peers', [])) or type(args['allow_write']) is not bool:
        raise ValueError('CHANNEL_SENDER_NOT_DISCOVERED_OR_PERMISSION_INVALID')
    root = runtime_root(hub, state)
    if unresolved(root, state_dir):
        raise ValueError('CHANNEL_UNKNOWN_NEVER_AUTOMATICALLY_CLEARED')
    channels.main(['stop', kind], component_home(hub, state))
    if kind == 'qq':
        account = 'qq.' + hashlib.sha256(json.dumps(credentials(hub)['QQ_BOT_APP_ID'], separators=(',', ':')).encode()).hexdigest()[:24]
    else:
        if not data.get('account'):
            raise ValueError('WECHAT_LOGIN_IDENTITY_REQUIRED')
        account = 'wechat.ilink.' + hashlib.sha256(json.dumps(data['account']['botId'], ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:24]
    original_config=private_json(home/'service.json')
    config=deepcopy(original_config)
    model = args['model']
    if model not in {item['id'] for item in core_models(home)}:
        raise ValueError('CHANNEL_LOCAL_MODEL_ROUTE_REQUIRED')
    route_name = 'channel-' + kind + '-' + uuid.uuid4().hex[:12]
    template = config['routes'][model]
    cloud=template['backend']['kind'] in {'deepseek','deepseek-native','remote-openai','remote-vllm'}
    if type(args.get('allow_cloud',False)) is not bool or (cloud and args.get('allow_cloud') is not True):
        raise ValueError('CHANNEL_CLOUD_REQUIRES_EXPLICIT_HOST_CONFIRMATION')
    workspace = validate_workspace(home,state['workspace']) if state.get('workspace') else default_workspace(home,kind)
    route = {key: deepcopy(template[key]) for key in ('backend', 'engine', 'thinking', 'budgets', 'deployment_status') if key in template}
    route.update(workspace=str(workspace), permissions='approve-mutations', capabilities={'read': True, 'write': args['allow_write'], 'execute': False},
        cloud_egress='REQUIRES_APPROVAL' if cloud else 'LOCAL_ONLY', cloud_egress_paths=[], prompt_profile='standard', tool_profile='full')
    config['routes'][route_name] = route
    values = credentials(hub)
    bindings = []
    env = read_env(home)
    for index, sender in enumerate(senders):
        subject = route_name + '-s' + str(index)
        token_env = 'LP_' + subject.upper().replace('-', '_')
        values[token_env] = secrets.token_urlsafe(32)
        env += 'export ' + token_env + '=' + values[token_env] + '\n'
        config['clients'].append({'subject': subject, 'token_env': token_env, 'operator': False,
            'scopes': ['read', 'submit', 'cancel'], 'routes': {'localpilot': route_name}, 'max_active_tasks': 1})
        bindings.append({'sender_id': sender, 'subject': subject, 'token_env': token_env, 'model': 'localpilot'})
        # Existing desktop operator may review these exact subjects. Channel users cannot.
        desktop_operator = next((p for p in config['clients'] if p.get('token_env') == 'LOCALPILOT_OPERATOR_TOKEN' and p.get('operator') is True), None)
        if desktop_operator:
            desktop_operator.setdefault('approval_for', []).append(subject)
    approval = None
    if state.get('operator_senders'):
        if kind != 'wechat' or not set(state['operator_senders']) <= set(senders):
            raise ValueError('WECHAT_OPERATOR_MUST_BE_EXPLICIT_ALLOWED_SENDER')
        subject = route_name + '-operator'
        token_env = 'LP_' + subject.upper().replace('-', '_')
        values[token_env] = secrets.token_urlsafe(32)
        values['LP_CHANNEL_APPROVAL_INGRESS'] = secrets.token_urlsafe(32)
        env += 'export ' + token_env + '=' + values[token_env] + '\n'
        config['clients'].append({'subject': subject, 'token_env': token_env, 'operator': True,
            'scopes': ['read', 'control'], 'routes': {}, 'approval_for': [b['subject'] for b in bindings if b['sender_id'] in state['operator_senders']]})
        approval = {'key_env': 'LP_CHANNEL_APPROVAL_INGRESS', 'token_env': token_env,
            'subject': subject, 'senders': state['operator_senders']}
        state['operator_subject'] = subject
    channels.save(hub / 'credentials.json', values)
    change_core(home, hub, config, env,expected_before=original_config)
    origin = private_json(home / 'connection.json')['url']
    adapter = {'instance_id': 'gui-' + uuid.uuid4().hex, 'service_url': origin,
        'channels': [{'kind': kind, 'channel': account, 'ingress_key_env': 'LP_CHANNEL_INGRESS', 'senders': bindings}]}
    if approval:
        adapter['channels'][0]['approval'] = approval
    channels.validate_shape(adapter)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    channels.save(root / 'adapter.json', adapter)
    # Suite expects <state>/<kind>, keeping bridge and adapter state independent.
    channels.save(root / 'configuration.json', {'adapter': adapter, 'port': port, 'state': str(state_dir.parent / 'services')})
    service_state = private_directory(state_dir.parent / 'services', create=True)
    # Existing bridge state retains its original location; controller adjusts env only.
    state.update(binding=True, senders=senders, subjects=[b['subject'] for b in bindings],
        route=route_name, channel=account, allow_write=args['allow_write'], allow_cloud=cloud, skipped=False)
    store_settings(hub, state)
    return {'status': 'configured', 'connected': False, 'permissions': 'ordinary_only; no shell/computer_use; cloud requires separate host approval'}

def stop_owned(home,kind,action):
    if kind not in KINDS:raise ValueError('CHANNEL_KIND_REJECTED')
    hub=home/'message-platforms'/kind
    if not hub.exists():return {'status':'stopped','optional_not_selected':True}
    private_directory(hub)
    if action=='exit':
        try:
            if settings(hub).get('background'):return {'status':'kept_running_by_preference'}
        except ValueError:pass
    with channels.locked(hub):
        generations=hub/'generations'
        if not generations.exists():return {'status':'stopped','state_preserved':True}
        private_directory(generations)
        paths=list(generations.iterdir())
        if len(paths)>256:raise ValueError('CHANNEL_GENERATION_SCAN_BUDGET_EXCEEDED')
        for directory in paths:
            if directory.name!='preparation' and not re.fullmatch('[a-f0-9]{32}',directory.name):continue
            private_directory(directory)
            if not (directory/'channels').exists():continue
            for component in (kind,'adapter'):
                result=channels.main(['stop',component],directory)
                if result.get('status')!='stopped':return result
    return {'status':'stopped','state_preserved':True,'ownership':'PID,creation,UID,executable,argv and exact root'}


def default_workspace(home,kind):
    root=home.parent/('localpilot-channel-workspaces-'+hashlib.sha256(str(home).encode()).hexdigest()[:12])
    root=private_directory(root,create=True)
    marker=root/'localpilot-owner.json'
    value={'purpose':'LocalPilot channel workspaces','core_home':str(home)}
    if marker.exists() and private_json(marker)!=value:
        raise ValueError('CHANNEL_WORKSPACE_OWNER_MISMATCH')
    if not marker.exists():channels.save(marker,value)
    return private_directory(root/kind,create=True)


def carry_transport(data,kind):
    prefix='q_m_' if kind=='qq' else 'm_'
    retired={**data.get('retired',{}),**{key:True for key in data.get('messages',{})}}
    if len(retired)>65536 or any(not isinstance(key,str) or not re.fullmatch(prefix+'[a-f0-9]{64}',key) or value is not True for key,value in retired.items()):
        raise ValueError('CHANNEL_DEDUP_HISTORY_INVALID_OR_CAPACITY_EXCEEDED')
    blocked=deepcopy(data.get('blocked',{}))
    for record in data.get('messages',{}).values():
        if record.get('status') in {'unknown','submitting'} or record.get('delivery') in {'unknown','sending'}:
            blocked[record['sender']]=True
    value={'version':1,'messages':{},'blocked':blocked,'peers':[],'retired':retired}
    if kind=='qq':value['appId']=data.get('appId')
    else:value.update(account=data.get('account'),cursor=data.get('cursor',''))
    return value


def native_binding(state,kind,config):
    route=state.get('route')
    if not isinstance(route,str) or not re.fullmatch('channel-'+kind+'-[a-f0-9]{12}',route):
        raise ValueError('CHANNEL_BINDING_ISSUER_MISMATCH')
    entries=config.get('adapter',{}).get('channels',[])
    if len(entries)!=1 or entries[0].get('kind')!=kind or entries[0].get('channel')!=state.get('channel'):
        raise ValueError('CHANNEL_BINDING_ISSUER_MISMATCH')
    senders=entries[0].get('senders',[])
    if not senders or any(not re.fullmatch(re.escape(route)+'-s[0-9]{1,2}',s.get('subject','')) or s.get('token_env')!='LP_'+s['subject'].upper().replace('-','_') for s in senders):
        raise ValueError('CHANNEL_BINDING_ISSUER_MISMATCH')
    return entries[0]


def disconnect(home,hub,state_dir,state,kind):
    if not state.get('binding'):return
    from localpilot_service.cli import lock
    try:data=state_info(state_dir)
    except (ValueError,OSError):data={}
    from .channel_tasks import mappings
    _,records=mappings(runtime_root(hub,state),state)
    if not data:
        data={'version':1,'messages':{},'blocked':{sender['sender_id']:True for _,sender in records},'peers':[]}
        if kind=='qq':data['appId']=credentials(hub).get('QQ_BOT_APP_ID')
        else:data.update(account=None,cursor='')
    retired=dict(data.get('retired',{}))
    for record,_ in records:retired[record['external_id']]=True
    data['retired']=retired
    carried=carry_transport(data,kind)
    entry=native_binding(state,kind,channels.configured(runtime_root(hub,state)))
    with lock(home,'channel-identity.lock'):
        config=private_json(home/'service.json');original_config=deepcopy(config);env=read_env(home)
        subjects={sender['subject'] for sender in entry['senders']}
        if entry.get('approval'):
            if kind!='wechat' or entry['approval']['subject']!=state['route']+'-operator':raise ValueError('CHANNEL_BINDING_ISSUER_MISMATCH')
            subjects.add(entry['approval']['subject'])
        for principal in config['clients']:
            if principal['subject'] not in subjects:continue
            # Rotate the old token and retain only read access for historical facts.
            token_env='LP_RETIRED_'+uuid.uuid4().hex.upper()
            env+='export '+token_env+'='+secrets.token_urlsafe(32)+'\n'
            principal.update(token_env=token_env,operator=False,scopes=['read'],routes={},approval_for=[])
        change_core(home,hub,config,env,expected_before=original_config)
    history_id=uuid.uuid4().hex
    directory=private_directory(hub/'history',create=True)
    channels.save(directory/(history_id+'.json'),deepcopy(state))
    history=[*state.get('history',[]),{'generation':history_id,'label':'历史连接 '+str(len(state.get('history',[]))+1)+'（只读）'}]
    state.update(binding=False,senders=[],subjects=[],operator_senders=[],disconnected=True,
        generation=uuid.uuid4().hex,history=history)
    state.pop('operator_subject',None)
    store_settings(hub,state)
    _,next_state=roots(home,kind)
    if carried:
        private_directory(next_state,create=True);channels.save(next_state/'state.json',carried)
    values=credentials(hub);values['LP_CHANNEL_INGRESS']=secrets.token_urlsafe(32)
    channels.save(hub/'credentials.json',values)


def validate_workspace(home,value):
    if not isinstance(value,str) or len(value)>4096 or not Path(value).is_absolute():
        raise ValueError('CHANNEL_NATIVE_WORKSPACE_REQUIRED')
    workspace=channels.canonical_path(value)
    if not workspace.is_dir():
        raise ValueError('CHANNEL_WORKSPACE_DIRECTORY_REQUIRED')
    protected=[home]
    if (home/'service.json').exists():
        config=private_json(home/'service.json')
        protected.extend(Path(config[key]).expanduser().resolve() for key in ('data_dir','log_dir') if key in config)
        for route in config.get('routes',{}).values():
            key=route.get('backend',{}).get('key_file')
            if key and Path(key).expanduser().is_file():protected.append(Path(key).expanduser().resolve().parent)
    if (home/'connection.json').exists():
        settings_file=private_json(home/'connection.json').get('omlx_settings_file')
        if settings_file and Path(settings_file).expanduser().is_file():protected.append(Path(settings_file).expanduser().resolve().parent)
    if any(workspace==private or workspace in private.parents or private in workspace.parents for private in protected):
        raise ValueError('CHANNEL_WORKSPACE_OVERLAPS_PRIVATE_STATE')
    return workspace


def command(home, kind, action, args):
    if action not in FIELDS or not isinstance(args, dict) or (set(args) != FIELDS[action] and not (action=='configure' and set(args)==FIELDS[action]|{'allow_cloud'})):
        raise ValueError('CHANNEL_EXACT_BOUNDED_REQUEST_REQUIRED')
    if 'confirmed' in args and args['confirmed'] is not True:
        raise ValueError('CHANNEL_EXPLICIT_CONFIRMATION_REQUIRED')
    home = channels.canonical_path(home)
    restoration=private_json(home/'restoration.json') if (home/'restoration.json').exists() else {}
    quarantine=restoration.get('channels_quarantined',False)
    quarantine=quarantine.get(kind,False) if isinstance(quarantine,dict) else bool(quarantine)
    if quarantine:
        if action in {'status','login_status','diagnose'}:
            return {'kind':kind,'status':'restore_review_required','installed':False,'configured':False,'connected':False,
                'restored_data':True,'models':core_models(home),'processes':{},'history':[]}
        if action in {'stop','cancel_login','exit'}:return {'status':'stopped','restored_quarantine':True,'signals_sent':False}
        if action not in {'receipts','history','cancel_task','restore_review'}:
            raise ValueError('CHANNEL_RESTORED_DATA_REVIEW_REQUIRED')
    if action in {'stop','cancel_login','exit'}:
        return stop_owned(home,kind,action)
    if action in {'status', 'login_status'}:
        return status(home, kind, action == 'login_status')
    if action == 'exit' and not roots(home, kind)[0].exists():
        return {'status':'stopped','optional_not_selected':True}
    hub, state_dir = roots(home, kind, create=True)
    if action == 'cancel_download':
        root = private_directory(home / 'channel-node', create=True)
        private_file(root / 'cancel', create=True)
        return {'status': 'cancellation_requested'}
    with channels.locked(hub):
        state = settings(hub)
        if action == 'restore_review':
            if not quarantine:raise ValueError('CHANNEL_RESTORATION_REVIEW_NOT_REQUIRED')
            require_quiet(home)
            if state.get('binding'):disconnect(home,hub,state_dir,state,kind)
            else:
                if state_info(state_dir):
                    value=carry_transport(state_info(state_dir),kind)
                    state['generation']=uuid.uuid4().hex;store_settings(hub,state)
                    _,target=roots(home,kind);private_directory(target,create=True);channels.save(target/'state.json',value)
            flags=restoration.get('channels_quarantined',{})
            flags=dict(flags) if isinstance(flags,dict) else {item:True for item in KINDS}
            flags[kind]=False
            channels.save(home/'restoration.json',{**restoration,'channels_quarantined':flags})
            return {'status':'restoration_reviewed','connected':False,'history_preserved':True,'replayed':False}
        if action == 'workspace':
            if state.get('binding'):
                raise ValueError('CHANNEL_DISCONNECT_BEFORE_WORKSPACE_CHANGE')
            workspace=validate_workspace(home,args['path'])
            state.update(workspace=str(workspace),workspace_label=workspace.name)
            store_settings(hub,state)
            return {'status':'workspace_staged','label':workspace.name,'active':False,'write_requires_separate_confirmation':True}
        if action == 'skip':
            state['skipped'] = True; store_settings(hub, state)
            return {'status': 'skipped', 'other_initialization_preserved': True}
        if action == 'background':
            if type(args['enabled']) is not bool:
                raise ValueError('CHANNEL_BACKGROUND_BOOLEAN_REQUIRED')
            state['background'] = args['enabled']; store_settings(hub, state)
            return {'status': 'saved', 'background': args['enabled'], 'auto_start': False}
        root = runtime_root(hub, state)
        if action in {'stop', 'cancel_login', 'disconnect', 'exit'}:
            if action == 'exit' and state.get('background'):
                return {'status': 'kept_running_by_preference'}
            if root.exists():
                for component in (kind, 'adapter'):
                    result = channels.main(['stop', component], component_home(hub, state))
                    if result.get('status') != 'stopped':
                        return result
            if action == 'disconnect':
                disconnect(home,hub,state_dir,state,kind)
            return {'status': 'stopped', 'state_preserved': True, 'platform_token_revoked': False}
        if action == 'fresh':
            if state.get('binding'):raise ValueError('CHANNEL_DISCONNECT_BEFORE_FRESH_CONNECTION')
            require_quiet(home)
            data=state_info(state_dir)
            if data:
                # Historical files remain immutable; only the new connection is isolated.
                value=carry_transport(data,kind);value['blocked']={};value['peers']=[]
                if kind=='wechat':value.update(account=None,cursor='')
                old_generation=state.get('generation','preparation')
                # Keep the old state at its original generation, including all
                # uncertain messages and receipts, before publishing a new one.
                state['generation']=uuid.uuid4().hex
                next_state=home/'message-state'/kind/state['generation']/'bridge'
                private_directory(next_state,create=True);channels.save(next_state/'state.json',value)
                channels.save(hub/('fresh-review-'+str(time.time_ns())+'.json'),{'generation':old_generation,'new_generation':state['generation'],'old_history_preserved':True,'retired_messages':len(value['retired']),'replayed':False})
                store_settings(hub,state)
            return {'status':'fresh_connection_staged','historical_unknown_preserved':True,'replayed':False}
        if action == 'qq_credentials':
            if kind != 'qq' or state.get('binding') or not re.fullmatch(r'[0-9]{3,32}', args['app_id']) or not re.fullmatch(r'[!-~]{8,512}', args['app_secret']):
                raise ValueError('QQ_CREDENTIAL_OR_EXISTING_BINDING_REJECTED')
            prior=state_info(state_dir)
            from .channel_tasks import journal,decision_unknown
            if unresolved(root,state_dir) or any(decision_unknown(item) and item.get('generation')==state.get('generation','preparation') for item in journal(hub).values()):
                raise ValueError('CHANNEL_UNKNOWN_NEVER_AUTOMATICALLY_CLEARED')
            if channels.process(root,kind):raise ValueError('CHANNEL_STOP_BEFORE_CREDENTIAL_CHANGE')
            if prior.get('appId') and prior['appId']!=args['app_id']:
                private_directory(hub/'history',create=True)
                channels.save(hub/'history'/('account-'+uuid.uuid4().hex+'.json'),prior)
                value=carry_transport(prior,kind);value.update(appId=args['app_id'],peers=[])
                channels.save(state_dir/'state.json',value)
            values = credentials(hub)
            values.update(QQ_BOT_APP_ID=args['app_id'], QQ_BOT_APP_SECRET=args['app_secret'])
            channels.save(hub / 'credentials.json', values)
            return {'status': 'credentials_saved', 'connected': False}
        if action == 'update':
            channel_runtime.install(home)
            return update_component(home,hub,state,kind)
        if action == 'install':
            result = channel_runtime.install(home)
            if result['status'] == 'cancelled':
                return result
            values = credentials(hub)
            values.setdefault('LP_CHANNEL_INGRESS', secrets.token_urlsafe(32))
            channels.save(hub / 'credentials.json', values)
            install_component(home, hub, state)
            return {'status': 'installed', 'connected': False, 'node': result}
        if action == 'uninstall':
            if root.exists():
                return channels.main(['uninstall', '--execute'], component_home(hub, state))
            return {'status': 'not_installed', 'state_preserved': True}
        if action == 'rollback':
            from localpilot_service.cli import stop,lock
            from .installation import start_core
            with lock(home,'channel-identity.lock'):
                transaction=private_json(hub/'transaction.json')
                backup=channels.canonical_path(transaction['backup'])
                if not backup.is_relative_to(hub/'core-config-backups'):
                    raise ValueError('CHANNEL_ROLLBACK_SOURCE_REJECTED')
                fingerprint=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=True).encode()).hexdigest()
                config_hash=fingerprint(private_json(home/'service.json'));env_hash=hashlib.sha256(read_env(home).encode()).hexdigest()
                if config_hash not in {transaction.get('before_config'),transaction.get('after_config')} or env_hash not in {transaction.get('before_credentials'),transaction.get('after_credentials')}:
                    raise ValueError('CHANNEL_CORE_CHANGED_SINCE_TRANSACTION_REVIEW_REQUIRED')
                facts=require_quiet(home)
                if any(t.get('service',{}).get('client_subject') in transaction.get('new_subjects',[]) for t in facts):
                    raise ValueError('CHANNEL_HISTORY_PRESENT_USE_DISCONNECT_INSTEAD_OF_ROLLBACK')
                if stop(home)['status']!='stopped':raise ValueError('CORE_STOP_NOT_CONFIRMED')
                replace_env(home/'clients.env',private_file(backup/'clients.env').read_text())
                channels.save(home/'service.json',private_json(backup/'service.json'))
                start_core(home)
                restored=private_json(backup/'channel-settings.json')
                old_data=state_info(state_dir)
                restored['generation']=uuid.uuid4().hex
                store_settings(hub,restored)
                if old_data:
                    _,target=roots(home,kind);private_directory(target,create=True)
                    channels.save(target/'state.json',carry_transport(old_data,kind))
                channels.save(hub/'transaction.json',{**transaction,'status':'rolled_back'})
                return {'status':'rolled_back','tasks_replayed':False,'other_configuration_preserved':True}
        if action == 'configure':
            from localpilot_service.cli import lock
            with lock(home, 'channel-identity.lock'):
                return bind(home, kind, hub, state_dir, state, args)
        if action == 'operator':
            if kind != 'wechat' or state.get('binding') or type(args['enabled']) is not bool or not isinstance(args['senders'], list):
                raise ValueError('WECHAT_OPERATOR_REQUIRES_EXPLICIT_NEW_BINDING')
            senders = args['senders'] if args['enabled'] else []
            if args['enabled'] and not senders:raise ValueError('WECHAT_OPERATOR_EXPLICIT_SENDER_REQUIRED')
            if not set(senders) <= set(state_info(state_dir).get('peers', [])):
                raise ValueError('WECHAT_OPERATOR_SENDER_NOT_DISCOVERED')
            state['operator_senders'] = senders
            store_settings(hub, state)
            return {'status': 'staged', 'operator_active': False, 'scope': 'only this channel ordinary subjects'}
        if action in {'login', 'discover', 'start', 'configure'} and (hub / 'transaction.json').exists() and private_json(hub / 'transaction.json')['status'] == 'pending':
            raise ValueError('CHANNEL_CONFIGURATION_TRANSACTION_REQUIRES_ROLLBACK')
        if action in {'login', 'discover', 'start'}:
            from .channel_tasks import journal,decision_unknown
            if any(decision_unknown(item) and item.get('generation')==state.get('generation','preparation') for item in journal(hub).values()):raise ValueError('CHANNEL_DECISION_UNKNOWN_QUERY_ORIGINAL_NO_RETRY')
            node = install_component(home, hub, state)
            if unresolved(root, state_dir):
                raise ValueError('CHANNEL_UNKNOWN_REQUIRES_MANUAL_RECONCILIATION_NO_RESTART')
            if channels.process(root, kind):
                raise ValueError('CHANNEL_ALREADY_RUNNING_NO_RECONNECT')
            private_directory(state_dir, create=True)
            if action == 'login' and kind != 'wechat':
                raise ValueError('ONLY_WECHAT_QR_LOGIN_SUPPORTED')
            configuration = channels.configured(root) if state.get('binding') else None
            if action == 'start':
                if configuration is None:
                    raise ValueError('CHANNEL_ALLOWLIST_AND_CORE_BINDING_REQUIRED')
                if not channels.process(root, 'adapter'):
                    channels.main(['start', 'adapter'], component_home(hub, state), node_path=node, credentials=credentials(hub))
            env = bridge_env(hub, kind, state_dir, configuration if action == 'start' else None)
            command_line = [str(node), str(channels.assets(root, kind)), 'login' if action == 'login' else 'run']
            return channels.launch(root, kind, command_line, env)
        if action == 'diagnose':
            result = status(home, kind)
            result['runtime'] = {'version': channel_runtime.VERSION, 'ready': bool(channel_runtime.installed(home))}
            result['errors'] = {key: channels.recent_error(root, key) for key in (kind, 'adapter')} if root.exists() else {}
            result['platform_test'] = 'authenticated_read_only_probe; no test message sent'
            return result
        if action in {'receipts','decision','history','cancel_task'}:
            from . import channel_tasks
            if state.get('binding'):native_binding(state,kind,channels.configured(root))
            if action == 'cancel_task':
                if not state.get('binding'):raise ValueError('CHANNEL_ACTIVE_BINDING_REQUIRED')
                return channel_tasks.cancel(home,hub,state,root,args)
            if action == 'decision':
                if not state.get('binding'):raise ValueError('CHANNEL_ACTIVE_BINDING_REQUIRED')
                return channel_tasks.decide(home,hub,state,root,args)
            if action == 'history':
                generation=args['generation']
                if not isinstance(generation,str) or not re.fullmatch('[a-f0-9]{32}',generation):raise ValueError('CHANNEL_HISTORY_NOT_IN_THIS_HOME')
                if generation not in {item['generation'] for item in state.get('history',[])}:
                    raise ValueError('CHANNEL_HISTORY_NOT_IN_THIS_HOME')
                archived=private_json(hub/'history'/(generation+'.json'))
                archived_root=runtime_root(hub,archived)
                native_binding(archived,kind,channels.configured(archived_root))
                return channel_tasks.receipts(home,hub,archived,archived_root,True)
            return channel_tasks.receipts(home,hub,state,root,historical=quarantine)
    raise ValueError('CHANNEL_OPERATION_NOT_AVAILABLE')
