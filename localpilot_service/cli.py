"""Core management and public API CLI. No additional agent runtime."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
import uuid

from . import VERSION
from .protocol import check
from .sdk import Client
from .security import private_json

TERMINAL = {'completed', 'incomplete', 'failed', 'cancelled', 'timed_out'}
_controller_children = {}
_streamed_text = {}


def private_dir(path):
    path = Path(path).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError('Data directory must be owned by you with permissions 700')
    return path


def save(path, value):
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, ensure_ascii=False); f.write('\n')
    os.replace(tmp, path)


@contextmanager
def lock(home, name='manager.lock'):
    fd = os.open(home / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError:
        raise ValueError('Another lifecycle operation is in progress') from None
    finally:
        os.close(fd)


def environment(home):
    env = dict(os.environ)
    path = home / 'clients.env'
    if path.exists():
        # Never execute a shell file. Accept only configure.py's exact grammar.
        st = path.lstat()
        if path.is_symlink() or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise ValueError('Client credentials must be owner-only regular files')
        for line in path.read_text().splitlines():
            m = re.fullmatch(r'export ([A-Z][A-Z0-9_]*)=([a-zA-Z0-9_-]+)', line)
            if not m:
                raise ValueError('Unsupported credentials file format; shell execution is forbidden')
            env.setdefault(m[1], m[2])
    connection_path=home/'connection.json'
    if connection_path.exists():
        connection=private_json(connection_path)
        if connection.get('omlx_settings_file'):
            settings=private_json(Path(connection['omlx_settings_file']).expanduser())
            key=settings.get('auth',{}).get('api_key')
            if key:env.setdefault('LOCALPILOT_OMLX_API_KEY',key)
    return env


@contextmanager
def temporary_environment(values):
    previous={key:os.environ.get(key) for key in values}
    os.environ.update(values)
    try:yield
    finally:
        for key,value in previous.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


def owned(home):
    import psutil
    try:
        record = private_json(home / 'process.json')
        p = psutil.Process(record['pid'])
        cmd = p.cmdline()
        if abs(p.create_time() - record['created']) > .02 or p.uids().real != os.getuid() or 'localpilot_service.cli' not in cmd or str(home) not in cmd:
            raise ValueError('Process identity mismatch; refusing to signal')
        if p.status() == psutil.STATUS_ZOMBIE:
            return None
        return p
    except (FileNotFoundError, psutil.NoSuchProcess):
        return None


def connection(home, token_env=None):
    config = private_json(home / 'connection.json')
    env = environment(home)
    token = env.get(token_env or config.get('token_env', 'LOCALPILOT_HTTP_TOKEN'))
    if not token:
        raise ValueError('API token not configured; run init or set the selected token environment variable')
    return Client(config['url'], token=token, timeout=30)


def compatible(client):
    health = client.request('/healthz')
    if health.get('status') != 'ready' or health.get('persistence') is not True:
        raise ValueError('Persistent service is not ready')
    check(health)
    return health


def configuration_checks(home):
    """Inspect references only. No model endpoint calls or credential reads."""
    path=home/'service.json'
    if not path.exists():return {'scope':'connected_service_only','issues':[],'model_readiness':'UNKNOWN'}
    config=private_json(path);env=environment(home);issues=[];managed=set()
    for name,spec in config.get('routes',{}).items():
        if spec.get('deployment_status')=='not_deployed':continue
        backend=spec.get('backend',{})
        if backend.get('key_file') and not os.access(Path(backend['key_file']).expanduser(),os.R_OK):issues.append({'route':name,'code':'provider_key_reference_unreadable'})
        if backend.get('api_key_env') and not env.get(backend['api_key_env']):issues.append({'route':name,'code':'model_credential_environment_unset'})
        profile=spec.get('managed_local_model')
        if profile:
            managed.add(profile['snapshot'])
            root=Path(profile['snapshot']).expanduser()
            if not (root/'config.json').is_file() or not any(root.glob('*.safetensors')):issues.append({'route':name,'code':'cached_model_files_missing'})
    if managed:
        from .cached_omlx import BINARY
        if not os.access(BINARY,os.X_OK):issues.append({'code':'managed_model_launcher_missing','required':'installed oMLX.app or use an external local-openai backend'})
    return {'scope':'static_configuration_references','issues':issues,'managed_model_profiles':len(managed),'model_readiness':'NOT_PROBED'}


def initialize(args, home):
    with lock(home):
        if (home / 'connection.json').exists() or (home / 'service.json').exists():
            raise ValueError('Already initialized; existing configuration preserved')
        if args.connect:
            save(home / 'connection.json', {'url':args.connect, 'token_env':args.token_env})
        else:
            workspace = args.workspace
            model = args.model
            if not model and args.managed_qwen35:
                from .cached_omlx import MODEL
                model=MODEL
            if sys.stdin.isatty():
                workspace = workspace or input('Task workspace directory: ').strip()
                model = model or input('Existing local model ID (no download): ').strip()
            if not workspace or not model:
                raise ValueError('init requires --workspace and --model, or --connect URL --token-env NAME')
            from .configure import main as configure
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                setup_env={}
                if args.omlx_settings_file:
                    if not args.omlx:raise ValueError('--omlx-settings-file requires --omlx')
                    settings=private_json(Path(args.omlx_settings_file).expanduser())
                    setup_env['LOCALPILOT_OMLX_API_KEY']=settings.get('auth',{}).get('api_key','')
                with temporary_environment(setup_env):
                    configure(['--workspace', workspace, '--model', model, '--directory', str(home), '--base-url', args.base_url] + (['--api-key-env','LOCALPILOT_OMLX_API_KEY'] if args.omlx_settings_file else ['--api-key-env',args.api_key_env] if args.api_key_env else []) + (['--omlx'] if args.omlx else []) + (['--managed-qwen35'] if args.managed_qwen35 else []) + (['--cloud-key-file',args.cloud_key_file] if args.cloud_key_file else []))
            config = private_json(home / 'service.json'); config['port'] = args.port
            save(home / 'service.json', config)
            save(home / 'connection.json', {'url':f'http://127.0.0.1:{args.port}', 'token_env':'LOCALPILOT_LOCAL_TOKEN' if args.managed_qwen35 else 'LOCALPILOT_HTTP_TOKEN', 'managed_qwen35':args.managed_qwen35, 'client_subject':'local' if args.managed_qwen35 else 'companion', 'cloud_configured':bool(args.cloud_key_file),
                **({'omlx_settings_file':str(Path(args.omlx_settings_file).expanduser().resolve()),'omlx_model':model,'omlx_base_url':args.base_url} if args.omlx_settings_file else {})})
        return {'status':'initialized', 'home':str(home), 'model_health':'NOT_PROBED', 'next':'doctor; start; ask "你好"'}


def start(home, manager=None):
    with lock(home):
        p = owned(home)
        if p:
            return {'status':'already_running', 'pid':p.pid}
        # Check port without touching a model endpoint.
        config = private_json(home / 'service.json')
        manager = manager or config.get('process_manager', 'launchd' if sys.platform=='darwin' else 'detached')
        if manager not in {'launchd','detached'}:raise ValueError('Unknown service process manager')
        import socket
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((config.get('host', '127.0.0.1'), config.get('port', 8765)))
        logpath = home / 'service.log'
        fd = os.open(logpath, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as log:
            if manager == 'launchd':
                from .lifecycle import launch
                launch(home)
                p = None
            else:
                p = subprocess.Popen([sys.executable, '-m', 'localpilot_service.cli', '--home', str(home), '_serve'],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=environment(home), start_new_session=True, cwd=str(home))
        # First launch of a relocated bundled Python can spend over 30 seconds
        # in macOS validation. Observe this one launch; never submit work again.
        startup_wait_seconds = 120
        deadline = time.monotonic() + startup_wait_seconds
        health_client = connection(home)
        health_client.timeout = 1
        while time.monotonic() < deadline:
            if p is not None and p.poll() is not None:
                raise ValueError('Service exited during startup; use logs and doctor')
            try:
                health = compatible(health_client)
                process = owned(home)
                return {'status':'running', 'pid':process.pid if process else None, 'version':health['version'], 'model_health':'NOT_PROBED', 'manager':manager}
            except (OSError, ValueError, URLError):
                time.sleep(.1)
        raise ValueError(f'Service is still starting after {startup_wait_seconds} seconds; inspect status and logs before retrying')


def stop(home):
    with lock(home):
        p = owned(home)
        if not p:
            return {'status':'stopped'}
        # Do not destroy authorized work as a side effect of lifecycle management.
        client = connection(home)
        if client.request('/healthz').get('active_task_count', 1):
            raise ValueError('Service has active tasks (possibly owned by another client); resolve them before stop')
        tasks = client.request('/localpilot/v1/tasks')['tasks']
        active = [t['id'] for t in tasks if t['status'] not in TERMINAL]
        if active:
            raise ValueError('Active tasks remain; query/cancel them explicitly before stopping: ' + ', '.join(active))
        p.send_signal(signal.SIGTERM)
        import psutil
        try:
            p.wait(timeout=15)
        except psutil.TimeoutExpired:
            if not p.is_running() or p.status()==psutil.STATUS_ZOMBIE:return {'status':'stopped'}
            return {'status':'stopping', 'pid':p.pid}
        return {'status':'stopped'}


def checkpoint_stop(home):
    """Operator-authorized restart at a yielded boundary, preserving tasks."""
    with lock(home):
        process=owned(home)
        if not process:return {'status':'stopped'}
        client=connection(home,'LOCALPILOT_OPERATOR_TOKEN')
        client.request('/localpilot/v1/lifecycle/suspend',{})
        import psutil
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            try:
                if not process.is_running() or process.status()==psutil.STATUS_ZOMBIE:return {'status':'stopped','tasks_preserved':True}
            except psutil.NoSuchProcess:return {'status':'stopped','tasks_preserved':True}
            time.sleep(.1)
        return {'status':'stopping','pid':process.pid,'tasks_preserved':True}


def exit_status(task):
    if task.get('status') == 'completed':
        return 0
    if task.get('status') in {'requires_approval', 'requires_human'}:
        return 5
    if task.get('status') in TERMINAL:
        return 6
    return 0


def follow(client, task_id, home, *, json_output=False):
    cursor_path = home / ('cursor-' + uuid.uuid5(uuid.NAMESPACE_URL, client.base_url + ':' + task_id).hex + '.json')
    after = private_json(cursor_path).get('after', 0) if cursor_path.exists() else 0
    reconnects = 0
    visible_status = None
    while True:
        try:
            for event in client.events(task_id, after=after):
                data = event['data']; sequence = data.get('sequence', 0)
                if sequence <= after:
                    continue
                if json_output:
                    print(json.dumps({'type':'event', **event}, ensure_ascii=False), flush=True)
                else:
                    payload = data.get('data', {})
                    runtime_type = payload.get('type') if isinstance(payload, dict) else None
                    if isinstance(payload, dict) and isinstance(payload.get('data'), dict):
                        payload = payload['data']
                    delta = payload.get('text') if runtime_type == 'TextDelta' else None
                    if isinstance(delta, str):
                        print(delta, end='', flush=True)
                        _streamed_text[task_id]=_streamed_text.get(task_id,'')+delta
                    elif runtime_type in {'ModelRequestStarted','ToolCallStarted','ToolCallCompleted','VerificationCompleted','ModelSwitched'}:
                        label={'ModelRequestStarted':'Thinking','ToolCallStarted':'Tool','ToolCallCompleted':'Tool finished','VerificationCompleted':'Verification','ModelSwitched':'Model switched'}[runtime_type]
                        detail=payload.get('name') or payload.get('model') or payload.get('status') or ''
                        print('['+label+(' · '+str(detail) if detail else '')+']',file=sys.stderr,flush=True)
                    elif data.get('type') in {'task.created','task.status'}:
                        status=payload.get('status')
                        if status and status!=visible_status:
                            visible_status=status;print('['+status+']',file=sys.stderr,flush=True)
                after = sequence
                save(cursor_path, {'after':after})
            task = client.status(task_id)
            if task.get('quiescent') or task['status'] in TERMINAL:
                return task
            reconnects = 0
        except HTTPError as exc:
            if exc.code == 409:
                exc.close(); task = client.status(task_id)
                after = task.get('last_event_id', 0); save(cursor_path, {'after':after})
                if json_output:
                    print(json.dumps({'type':'resync', 'task':task}, ensure_ascii=False), flush=True)
                if task.get('quiescent'):
                    return task
            elif exc.code in {429, 502, 503, 504}:
                exc.close(); reconnects += 1
            else:
                raise
        except (URLError, OSError, TimeoutError):
            reconnects += 1
        if reconnects > 3:
            raise ValueError('Connection interrupted; task continues. Reconnect with task watch ' + task_id)
        time.sleep(min(2 ** reconnects, 8))


def ensure_controller(home, client, task, ticket, timeout_seconds):
    """Keep only the resource heartbeat alive after CLI detach; never approvals."""
    if task.get('quiescent') and task.get('status') in TERMINAL:return
    import psutil
    for name,child in list(_controller_children.items()):
        if child.poll() is not None:_controller_children.pop(name,None)
    path=home/('control-'+uuid.uuid5(uuid.NAMESPACE_URL,client.base_url+':'+task['id']).hex+'.json')
    if path.exists():
        old=private_json(path)
        try:
            process=psutil.Process(old['pid'])
            if abs(process.create_time()-old['created'])<.02 and process.uids().real==os.getuid() and 'localpilot_service.task_control' in process.cmdline():return
        except (KeyError,psutil.NoSuchProcess):pass
    ticket=(task.get('service') or {}).get('control_ticket') or ticket
    save(path,{'url':client.base_url,'task_id':task['id'],'ticket':ticket,'expires_at':time.time()+timeout_seconds+30})
    env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','TMPDIR'}}
    roots=[str(Path(__file__).resolve().parent.parent)]+[str(Path(p).resolve()) for p in os.environ.get('PYTHONPATH','').split(os.pathsep) if p]
    env.update(PYTHONPATH=os.pathsep.join(dict.fromkeys(roots)),LOCALPILOT_HEARTBEAT_TOKEN=client.token)
    _controller_children[str(path)] = subprocess.Popen([sys.executable,'-m','localpilot_service.task_control','--home',str(home),'--record',str(path)],env=env,cwd=str(home),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,close_fds=True)


def submit(args, home, client, text, *, chat_session=None):
    health=compatible(client)
    client.client_generation=health.get("client_generation")
    registry = client.request('/localpilot/v1/model-registry')['models']
    model = args.model or ('companion-reasoning' if args.action in {'ask', 'chat'} else 'localpilot')
    entry = next((m for m in registry if m['id'] == model), None)
    if not entry:
        raise ValueError('Model route not found; run models and select --model')
    if args.action == 'agent' and (entry.get('reasoning_only') is True or entry.get('prompt_profile') != 'standard'):
        raise ValueError('agent requires a standard execution route; use ask for reasoning only')
    if args.action in {'ask', 'chat'} and entry.get('reasoning_only') is not True:
        raise ValueError('ask/chat requires an isolated reasoning_only route; use agent for tool tasks')
    if entry.get('adapter') == 'local-openai':
        # CLI defaults to no inference on battery/unknown power, with no automatic override.
        import psutil
        power = psutil.sensors_battery()
        if os.environ.get('LOCALPILOT_DISABLE_LOCAL_MODELS') == '1' or power is None or power.power_plugged is not True:
            raise ValueError('Local model inference blocked: external power required or operator disabled models')
    key = getattr(args, 'key', None) or uuid.uuid4().hex
    if getattr(args,'timeout',None) is not None and (not math.isfinite(args.timeout) or not 0 < args.timeout <= 3600):
        raise ValueError('Task timeout must be finite and within (0, 3600]')
    body = {'input':text, 'model':model}
    if getattr(args,'timeout',None) is not None:body['timeout_seconds']=args.timeout
    if chat_session or getattr(args, 'session', None):
        body['session_id'] = chat_session or args.session
    # Write BEFORE transmission; on ambiguous transport failure use request retry with the original key.
    request_file = home / ('request-' + uuid.uuid5(uuid.NAMESPACE_URL, client.base_url + ':' + key).hex + '.json')
    record = {'key':key, 'body':body, 'url':client.base_url}
    old=private_json(request_file) if request_file.exists() else None
    lifecycle=entry.get('local_model_lifecycle') or {}
    managed=lifecycle.get('control_surface_required') is True
    if managed and getattr(args,'timeout',None) is None:
        if old and 'timeout_seconds' in old.get('body',{}):body['timeout_seconds']=old['body']['timeout_seconds']
        elif not old:body['timeout_seconds']=600
    if old and any(old.get(k)!=v for k,v in record.items()):
        raise ValueError('Idempotency key already belongs to a different request')
    if managed:
        import psutil
        if psutil.virtual_memory().available < lifecycle.get('minimum_available_bytes',0):
            raise ValueError('Available memory is below the managed model budget; release idle models or use the explicit Companion resource controls')
        ticket=(old or {}).get('control_ticket') or uuid.uuid4().hex
        record['control_ticket']=ticket;client.control_ticket=ticket
    save(request_file, record)
    if not args.json:
        print('Request key: ' + key, file=sys.stderr)
    task = client.submit(idempotency_key=key, **body)
    save(home / 'last-task.json', {'id':task['id'], 'session_id':task['session_id'], 'key':key})
    if managed:ensure_controller(home,client,task,ticket,body.get('timeout_seconds',120))
    if getattr(args, 'detach', False):
        return task
    if not args.json:
        print('Task: ' + task['id'] + ' (Ctrl-C detaches; task continues)', file=sys.stderr)
    return follow(client, task['id'], home, json_output=args.json)


def output(value, structured):
    if structured:
        print(json.dumps(value, ensure_ascii=False))
    elif isinstance(value, dict) and value.get('object') == 'localpilot.task':
        result = value.get('result') or {}
        text=str(result.get('text',''))
        if _streamed_text.pop(value['id'],None)!=text:print('\n'+text)
        else:print()
        print('Task ' + value['id'] + ': ' + value['status'])
        print('Verification: ' + str(value.get('verification_summary', {})))
        if value.get('required_action'):
            print('Approval/human action required; use a separate trusted operator token and current action ID.')
            print(json.dumps(value['required_action'], ensure_ascii=False))
    else:
        print(json.dumps(value, indent=2, ensure_ascii=False))


def parser():
    p = argparse.ArgumentParser(description='LocalPilot Core — persistent tasks, explicit permissions, independent service')
    p.add_argument('--version', action='version', version=VERSION)
    p.add_argument('--home', default=os.environ.get('LOCALPILOT_HOME', '~/.local/share/localpilot'))
    p.add_argument('--json', action='store_true', help='JSON; streaming commands emit newline-delimited event objects followed by final task')
    sub = p.add_subparsers(dest='action', required=True)
    init = sub.add_parser('init', help='Configure existing model without loading/downloading it')
    init.add_argument('--omlx', action='store_true');init.add_argument('--omlx-settings-file', help='Reference existing private oMLX settings; credentials are never copied')
    init.add_argument('--workspace'); init.add_argument('--model'); init.add_argument('--managed-qwen35',action='store_true',help='Use approved existing cached Qwen35 with managed lifecycle'); init.add_argument('--cloud-key-file',help='Existing protected DeepSeek credential file reference; no copy'); init.add_argument('--base-url', default='http://127.0.0.1:1234/v1')
    init.add_argument('--api-key-env',default='',help='Existing local backend credential environment name; no value is copied'); init.add_argument('--port', type=int, default=8765); init.add_argument('--connect'); init.add_argument('--token-env', default='LOCALPILOT_TOKEN')
    for name in ['start','stop','restart','status','doctor','models','tasks','logs','config','_serve','service-unregister']:
        sub.add_parser(name)
    for name in ['ask','agent','chat']:
        cmd = sub.add_parser(name, help='Reasoning only' if name != 'agent' else 'Submit standard Agent task through Permission Gateway')
        if name != 'chat':cmd.add_argument('text')
        cmd.add_argument('--model'); cmd.add_argument('--session'); cmd.add_argument('--key'); cmd.add_argument('--detach', action='store_true'); cmd.add_argument('--timeout', type=float, help='Total task deadline in seconds, including approvals; maximum 3600')
    task = sub.add_parser('task').add_subparsers(dest='operation', required=True)
    for name in ['show','watch','cancel','approve','reject','resume']:
        cmd = task.add_parser(name); cmd.add_argument('id')
        if name in {'approve','reject','resume'}:
            cmd.add_argument('--action-id', required=True); cmd.add_argument('--operator-token-env', required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        home = private_dir(args.home)
        if args.action == '_serve':
            with lock(home, 'service.owner.lock'):
                import psutil
                from .lifecycle import event
                save(home / 'process.json', {'pid':os.getpid(), 'created':psutil.Process().create_time()})
                event(home,'process_started',version=VERSION,ppid=os.getppid(),executable=sys.executable)
                from .__main__ import main as serve
                try:
                    with temporary_environment(environment(home)):
                        serve(['--config', str(home / 'service.json')])
                except BaseException as exc:
                    event(home,'process_exception',exception=type(exc).__name__)
                    raise
                else:event(home,'process_exited',reason='graceful')
            return 0
        if args.action == 'init':value = initialize(args, home)
        elif args.action == 'start':value = start(home)
        elif args.action == 'stop':value = stop(home)
        elif args.action == 'service-unregister':
            value=stop(home)
            if value['status']!='stopped':raise ValueError('Wait for Core to stop before unregistering')
            from .lifecycle import unregister
            value=unregister(home)
        elif args.action == 'restart':
            health=connection(home).request('/healthz')
            stopped = checkpoint_stop(home) if 'lifecycle_suspend_v1' in health.get('compatibility',{}).get('capabilities',[]) else stop(home)
            if stopped['status'] != 'stopped':raise ValueError('Service has not stopped')
            value = start(home)
        elif args.action == 'logs':
            path = home / 'service.log'
            value = {'lines':path.read_text()[-32000:].splitlines()[-100:] if path.exists() else []}
        elif args.action == 'config':
            c = private_json(home / 'connection.json')
            value = {'url':c['url'], 'token_env':c['token_env'], 'home':str(home), 'credentials':'REDACTED'}
        elif args.action == 'doctor':
            checks = {'version':VERSION, 'platform':sys.platform, 'model_health':'NOT_PROBED', 'local_inference_disabled':os.environ.get('LOCALPILOT_DISABLE_LOCAL_MODELS') == '1', 'configuration':configuration_checks(home)}
            c = connection(home)
            try:checks.update(service=compatible(c), compatibility='PASS')
            except (URLError, OSError):checks.update(service='UNREACHABLE', compatibility='NOT_RUN')
            value = checks
        elif args.action == 'status':
            p = owned(home)
            from .lifecycle import diagnostic
            value = {'managed_pid':p.pid if p else None, 'lifecycle':diagnostic(home)}
            try:value['service']=compatible(connection(home))
            except (URLError,OSError):value.update(service='UNREACHABLE',health='failed' if p else 'stopped')
        else:
            c = connection(home, getattr(args, 'operator_token_env', None))
            compatible(c)
            if args.action == 'models':value = c.request('/localpilot/v1/model-registry')
            elif args.action == 'tasks':value = c.request('/localpilot/v1/tasks')
            elif args.action == 'task':
                if args.operation == 'show':value = c.status(args.id)
                elif args.operation == 'watch':value = follow(c, args.id, home, json_output=args.json)
                elif args.operation == 'cancel':value = c.cancel(args.id)
                else:value = c.continue_task(args.id, args.action_id, action={'resume':'continue'}.get(args.operation, args.operation))
            elif args.action == 'chat':
                session = args.session
                while True:
                    try:text = input('You> ')
                    except EOFError:break
                    if text.strip() in {'/quit','/exit'}:break
                    if not text.strip():continue
                    value = submit(args, home, c, text, chat_session=session); session = value['session_id']; output(value, args.json)
                return 0
            else:value = submit(args, home, c, args.text)
        output(value, args.json)
        if args.action == 'doctor':
            if value.get('configuration',{}).get('issues'):return 2
            if value.get('compatibility') != 'PASS':return 1
        return exit_status(value) if isinstance(value, dict) and value.get('object') == 'localpilot.task' else 0
    except KeyboardInterrupt:
        print(json.dumps({'status':'detached', 'message':'Task continues; use tasks or task watch to reconnect'}) if args.json else '\nDetached. Authorized task continues; use tasks or task watch to reconnect.', file=sys.stderr)
        return 130
    except HTTPError as exc:
        code = exc.code
        try:detail = json.load(exc).get('error', {}).get('code', 'http_error')
        except Exception:detail = 'http_error'
        exc.close(); output({'error':detail, 'http_status':code, 'retry':'Reuse original idempotency key; never automatically resubmit mutations'}, args.json)
        return 3 if code in {401,403} else 4 if code == 409 else 7 if code == 429 else 1
    except (ValueError, OSError, KeyError, URLError) as exc:
        # Do not print arbitrary provider bodies, credential values or config contents.
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__ + ': check config, service status and logs'
        output({'error':message}, args.json)
        return 2 if isinstance(exc, (ValueError, KeyError)) else 1


if __name__ == '__main__':
    sys.exit(main())
