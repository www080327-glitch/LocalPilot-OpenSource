"""Optional channel process coordinator. Never loads an Agent or model."""
import argparse
import contextlib
import hashlib
import http.client
import json
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

from .channel_paths import canonical_path, private_directory, private_file, private_json

MODULES = ('adapter', 'qq', 'wechat')
KINDS = {'qq': 'qq-bridge', 'wechat': 'wechat-ilink-bridge'}
BASE_ENV = ('PATH', 'HOME', 'USERPROFILE', 'SystemRoot', 'WINDIR', 'TMPDIR', 'TMP', 'TEMP', 'LANG', 'LC_ALL')


def save(path, value):
    private_file(path)
    temporary = path.with_name(path.name + '.new')
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == 'posix':
            directory = os.open(path.parent, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def locked(root):
    if os.name != 'posix':
        raise ValueError('Suite channel lifecycle requires POSIX; native Windows remains NOT_RUN')
    import fcntl
    path = private_file(root / 'lifecycle.lock', create=True)
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def python(root):
    launcher = root / 'runtime/launch.py'
    return launcher if launcher.exists() else root / 'runtime' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def installed(root):
    if not (root / 'installation.json').exists():
        return False
    record = private_json(root / 'installation.json')
    if record.get('runtime') == 'suite_python_isolated_site':
        for name, checksum in record.get('files', {}).items():
            path = canonical_path(root / 'runtime' / name)
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
                raise ValueError('CHANNEL_INSTALLED_CODE_INTEGRITY_FAILED')
        return bool(record.get('files')) and python(root).is_file()
    return python(root).is_file()


def python_command(root):
    if python(root).name == 'launch.py':
        return [sys.executable, '-I', str(python(root))]
    return [str(python(root))]


def node(executable=None):
    executable = str(executable) if executable else shutil.which('node')
    if not executable:
        return {'status': 'unavailable', 'code': 'NODE_NOT_INSTALLED', 'required': '>=22.13.0'}
    script = 'let v=process.versions.node.split(".").map(Number);process.stdout.write(JSON.stringify({version:process.versions.node,ok:(v[0]>22||(v[0]===22&&v[1]>=13))&&typeof WebSocket==="function"&&typeof AbortSignal.any==="function"}))'
    try:
        run = subprocess.run([executable, '-e', script], capture_output=True, text=True, timeout=5)
        data = json.loads(run.stdout)
        if run.returncode or data.get('ok') is not True:
            return {'status': 'unavailable', 'code': 'NODE_TOO_OLD_OR_FEATURES_MISSING', 'required': '>=22.13.0'}
        return {'status': 'ready', 'path': str(Path(executable).resolve()), 'version': data['version']}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'status': 'unavailable', 'code': 'NODE_PROBE_FAILED'}


def assets(root, kind):
    directory = root / 'runtime' / 'share/localpilot/channels'
    paths = [directory / KINDS[kind] / 'cli.mjs', directory / KINDS[kind] / 'bridge.mjs',
             directory / 'channel-common/security.mjs', directory / 'channel-common/evidence.mjs']
    if kind == 'qq':
        paths += [directory / 'qq-bridge/gateway.mjs', directory / 'wechat-ilink-bridge/bridge.mjs']
    if not all(p.is_file() and not p.is_symlink() for p in paths):
        raise ValueError('CHANNEL_BRIDGE_MODULE_MISSING: install the candidate wheel; no npm dependencies are required')
    return paths[0]


def validate_shape(config):
    identifier = lambda value: isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.:@-]{1,128}',value)
    env_name = lambda value: isinstance(value,str) and value.isidentifier()
    if (not isinstance(config,dict) or set(config)!={'instance_id','service_url','channels'}
            or not identifier(config.get('instance_id')) or not isinstance(config.get('channels'),list)
            or not config['channels']):
        raise ValueError('INVALID_CHANNEL_CONFIGURATION')
    from urllib.parse import urlsplit
    try:
        if not isinstance(config['service_url'],str):
            raise ValueError()
        url=urlsplit(config['service_url'])
        if url.scheme!='http' or url.hostname not in {'127.0.0.1','::1'} or url.path not in {'','/'} or url.username or url.password or url.query or url.fragment:
            raise ValueError()
        port=url.port
    except (TypeError, ValueError):
        raise ValueError('CHANNEL_SERVICE_REQUIRES_LOOPBACK_ORIGIN') from None
    subjects=set()
    for channel in config['channels']:
        if (not isinstance(channel,dict) or not {'kind','channel','ingress_key_env','senders'}<=set(channel)
                or set(channel)-{'kind','channel','ingress_key_env','senders','approval'}
                or not isinstance(channel['kind'],str) or channel['kind'] not in KINDS or not identifier(channel['channel'])
                or not channel['channel'].startswith('qq.' if channel['kind']=='qq' else 'wechat.ilink.')
                or not env_name(channel['ingress_key_env']) or not isinstance(channel['senders'],list)
                or not channel['senders']):
            raise ValueError('INVALID_CHANNEL_OR_SENDERS')
        senders=set()
        for sender in channel['senders']:
            if (not isinstance(sender,dict) or set(sender)!={'sender_id','subject','token_env','model'}
                    or not identifier(sender['sender_id']) or sender['sender_id'] in senders
                    or not isinstance(sender['subject'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',sender['subject'])
                    or sender['subject'] in subjects or not identifier(sender['model']) or not env_name(sender['token_env'])):
                raise ValueError('INVALID_OR_DUPLICATE_CHANNEL_SENDER')
            senders.add(sender['sender_id']);subjects.add(sender['subject'])
        ap=channel.get('approval')
        if ap:
            if (channel['kind']!='wechat' or not isinstance(ap,dict) or set(ap)!={'key_env','token_env','subject','senders'}
                    or not env_name(ap['key_env']) or not env_name(ap['token_env'])
                    or not isinstance(ap['subject'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',ap['subject'])
                    or ap['subject'] in subjects or not isinstance(ap['senders'],list)
                    or not ap['senders'] or not all(isinstance(x,str) and x in senders for x in ap['senders'])):
                raise ValueError('INVALID_OR_NONINDEPENDENT_WECHAT_OPERATOR')
            subjects.add(ap['subject'])


def configured(root):
    return private_json(root / 'configuration.json')


def process(root, component):
    import psutil
    root = canonical_path(root)
    path = root / (component + '.process.json')
    if not path.exists() and not path.is_symlink():
        return None
    record = private_json(path)
    expected = str(root / 'adapter.json') if component == 'adapter' else str(root / 'runtime/share/localpilot/channels' / KINDS[component] / 'cli.mjs')
    if (not isinstance(record,dict) or not isinstance(record.get('argv'),list) or expected not in record['argv']
            or type(record.get('pid')) is not int or record['pid'] <= 1
            or not isinstance(record.get('created'),(int,float)) or not math.isfinite(record['created'])):
        # A copied/restored PID record must never authorize signalling the original installation.
        raise ValueError('CHANNEL_PROCESS_RECORD_NOT_OWNED_BY_THIS_ROOT')
    try:
        p = psutil.Process(record['pid'])
        if p.status() == psutil.STATUS_ZOMBIE:
            return None
        if abs(p.create_time() - record['created']) > .02 or p.cmdline() != record['argv'] or p.exe() != record['executable']:
            raise ValueError('PROCESS_IDENTITY_CHANGED: no process was signalled')
        if os.name == 'posix' and p.uids().real != os.getuid():
            raise ValueError('PROCESS_OWNER_CHANGED: no process was signalled')
        return p
    except psutil.NoSuchProcess:
        return None


def environment(config, component, credentials=None):
    source = os.environ if credentials is None else credentials
    env = {name: os.environ[name] for name in BASE_ENV if name in os.environ}
    if component == 'adapter':
        names = []
        for channel in config['adapter']['channels']:
            names.append(channel['ingress_key_env'])
            names.extend(s['token_env'] for s in channel['senders'])
            if channel.get('approval'):
                names += [channel['approval']['key_env'], channel['approval']['token_env']]
        for name in names:
            value = source.get(name)
            if not value:
                raise ValueError('CHANNEL_CREDENTIAL_MISSING: set the configured environment names privately')
            env[name] = value
    else:
        channel = next((c for c in config['adapter']['channels'] if c['kind'] == component), None)
        if channel is None:
            raise ValueError('CHANNEL_NOT_CONFIGURED')
        key = source.get(channel['ingress_key_env'])
        if not key:
            raise ValueError('CHANNEL_INGRESS_KEY_MISSING')
        env['LOCALPILOT_MESSAGE_KEY'] = key
        env['LOCALPILOT_MESSAGE_ADAPTER_URL'] = 'http://127.0.0.1:' + str(config['port'])
        env['LOCALPILOT_' + component.upper() + '_STATE_DIR'] = str(Path(config['state']) / component)
        env['LOCALPILOT_' + component.upper() + '_SENDERS'] = json.dumps([s['sender_id'] for s in channel['senders']])
        if component == 'qq':
            for name in ('QQ_BOT_APP_ID', 'QQ_BOT_APP_SECRET'):
                if not source.get(name):
                    raise ValueError('QQ_PLATFORM_CREDENTIAL_MISSING')
                env[name] = source[name]
        elif channel.get('approval'):
            ap = channel['approval']
            if not source.get(ap['key_env']):
                raise ValueError('WECHAT_APPROVAL_INGRESS_KEY_MISSING')
            env['LOCALPILOT_APPROVAL_KEY'] = source[ap['key_env']]
            env['LOCALPILOT_WECHAT_APPROVERS'] = json.dumps(ap['senders'])
    # Ordinary bridge processes never receive Core operator or model tokens.
    return env


def recent_error(root, component):
    path = root / (component + '.error.log')
    if not path.exists():
        return None
    private_file(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        with os.fdopen(fd, 'rb') as stream:
            stream.seek(max(0, path.stat().st_size - 8192))
            text = stream.read(8192).decode('utf-8', 'replace')
    except Exception:
        return 'CHANNEL_DIAGNOSTIC_UNAVAILABLE'
    allowed = ('CHANNEL_CONFIGURATION_OR_STATE_INVALID', 'ilink_login_expired', 'login_required',
               'qq_token_refused', 'qq_api_refused', 'invalid_qq_credentials',
               'invalid_message_key_or_allowlist', 'invalid_approval_key_or_allowlist',
               'node_22_13_or_runtime_features_required', 'state_locked_operator_required',
               'state_path_or_permissions_rejected', 'state_invalid_operator_required',
               'state_invalid_or_different_app', 'state_save_failed_stop_required',
               'gateway_disconnected_restart_required', 'gateway_network_unknown')
    for line in reversed(text.splitlines()):
        for code in allowed:
            if line == code or line in {'QQ 桥接停止：' + code, '桥接停止：' + code}:
                return code
    return None


def request(config, route, body=None, *, key):
    conn = http.client.HTTPConnection('127.0.0.1', config['port'], timeout=5)
    try:
        raw = None if body is None else json.dumps(body).encode()
        conn.request('GET' if raw is None else 'POST', route, body=raw,
                     headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        response = conn.getresponse()
        data = json.loads(response.read(1048577))
        if response.status != 200:
            raise ValueError('CHANNEL_HTTP_' + str(response.status))
        return data
    except (OSError, http.client.HTTPException, ValueError):
        raise ValueError('CHANNEL_CONNECTION_OR_AUTH_FAILED') from None
    finally:
        conn.close()


def main(argv, home, *, node_path=None, credentials=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['list', 'install', 'configure', 'doctor', 'start', 'stop', 'status',
                                          'pending', 'task', 'login', 'uninstall'])
    parser.add_argument('component', nargs='?', choices=MODULES)
    parser.add_argument('--wheel')
    parser.add_argument('--config')
    parser.add_argument('--core-config')
    parser.add_argument('--state-dir')
    parser.add_argument('--port', type=int, default=8003)
    parser.add_argument('--task-id')
    parser.add_argument('--sender-id')
    parser.add_argument('--channel')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    root = canonical_path(home / 'channels')
    if args.action in {'list', 'status'} and not root.exists():
        return {'status': 'not_installed', 'optional': True, 'modules': list(MODULES), 'node_required_by_gui': False}
    private_directory(root, create=args.action == 'install')
    with locked(root):
        component = args.component or 'adapter'
        if args.action == 'stop':
            p = process(root, component)
            if p:
                import psutil
                p.terminate()
                try:
                    p.wait(timeout=20)
                except psutil.TimeoutExpired:
                    return {'status': 'UNKNOWN', 'code': 'CHANNEL_STOP_TIMEOUT', 'automatic_kill': False}
            (root / (component + '.process.json')).unlink(missing_ok=True)
            return {'status': 'stopped', 'component': component}
        is_installed = installed(root)
        if args.action in {'list', 'status'}:
            return {'status': 'installed' if is_installed else 'not_installed', 'optional': True,
                    'processes': {k: 'running' if process(root, k) else 'stopped' for k in MODULES},
                    'configured': (root / 'configuration.json').is_file(),
                    'recent_errors': {k: recent_error(root,k) for k in MODULES}}
        if args.action == 'install':
            if not args.wheel:
                raise ValueError('Select the reviewed optional channels wheel with --wheel; no network install is performed')
            from .cli import wheel_info
            wheel, version = wheel_info(args.wheel, 'localpilot-channels')
            with zipfile.ZipFile(wheel) as archive:
                names = archive.namelist()
                if 'localpilot_channels/__main__.py' not in names or not any('/share/localpilot/channels/qq-bridge/cli.mjs' in n for n in names):
                    raise ValueError('WHEEL_HAS_NO_CHANNEL_COMPONENT')
            runtime = root / 'runtime'
            if runtime.exists():
                if (root / 'installation.json').exists() or any(process(root, k) for k in MODULES):
                    raise ValueError('Existing channel installation preserved; stop and uninstall code explicitly before replacing')
                runtime.rename(root / ('runtime-incomplete-' + str(time.time_ns())))
            private_directory(runtime, create=True)
            files = {}
            with zipfile.ZipFile(wheel) as archive:
                for name in archive.namelist():
                    target = None
                    if name.startswith('localpilot_channels/') and name.endswith('.py'):
                        target = runtime / 'site' / name
                    marker = '.data/data/share/localpilot/channels/'
                    if marker in name:
                        relative = name.split(marker, 1)[1]
                        target = runtime / 'share/localpilot/channels' / relative
                    if target is None:
                        continue
                    if '..' in Path(name).parts or name.startswith('/'):
                        raise ValueError('CHANNEL_WHEEL_PATH_REJECTED')
                    private_directory(target.parent, create=True)
                    data = archive.read(name)
                    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, 'wb') as output:
                        output.write(data);output.flush();os.fsync(output.fileno())
                    files[str(target.relative_to(runtime))] = hashlib.sha256(data).hexdigest()
            launcher = """import sys,runpy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'site'))
a=sys.argv[1:]
if a[:1]==['-I']:a=a[1:]
if a[:2]==['-m','localpilot_channels']:
    sys.argv=a[1:];runpy.run_module('localpilot_channels',run_name='__main__')
elif a[:1]==['-c'] and len(a)>=2:
    sys.argv=['-c',*a[2:]];exec(compile(a[1],'<controlled-suite-probe>','exec'),{'__name__':'__main__'})
else:raise SystemExit('CHANNEL_LAUNCH_ARGUMENTS_REJECTED')
"""
            fd = os.open(runtime / 'launch.py', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as output:
                output.write(launcher);output.flush();os.fsync(output.fileno())
            files['launch.py'] = hashlib.sha256(launcher.encode()).hexdigest()
            save(root / 'installation.json', {'version': version, 'wheel_sha256': hashlib.sha256(Path(wheel).read_bytes()).hexdigest(),
                'runtime': 'suite_python_isolated_site', 'transport_contract':2, 'files': files})
            return {'status': 'installed', 'node': node(node_path), 'core_service': 'external_existing_service', 'runtime': 'facade_only'}
        if args.action == 'uninstall':
            if any(process(root, k) for k in MODULES):
                raise ValueError('Stop owned channel processes before uninstall; Core is independent')
            if not args.execute:
                return {'status': 'plan_only', 'remove': 'isolated channel code only', 'preserve': 'configuration, credentials and all state'}
            runtime = canonical_path(root / 'runtime')
            if runtime.exists():
                private_directory(runtime)
                shutil.rmtree(runtime)
            (root / 'installation.json').unlink(missing_ok=True)
            return {'status': 'uninstalled', 'data_policy': 'all configurations, credentials and state preserved'}
        component = args.component or 'adapter'
        if not is_installed:
            return {'status': 'unavailable', 'code': 'CHANNEL_COMPONENT_NOT_INSTALLED'}
        if args.action == 'configure':
            if not args.config or not args.core_config or not args.state_dir or not 1 <= args.port <= 65535:
                raise ValueError('Configure with --config, --core-config, --state-dir and an available --port')
            if (root / 'configuration.json').exists() or any(process(root, k) for k in MODULES):
                raise ValueError('Existing configuration and live processes preserved; use a new explicit --home')
            config, core = private_json(args.config), private_json(args.core_config)
            validate_shape(config)
            if not isinstance(core,dict) or not isinstance(core.get('clients'),list) or not isinstance(core.get('routes'),dict) or not core['routes']:
                raise ValueError('EXPLICIT_OFFICIAL_CORE_CONFIGURATION_REQUIRED')
            workspaces=[]
            for route in core['routes'].values():
                if not isinstance(route,dict) or not isinstance(route.get('workspace'),str):
                    raise ValueError('CORE_ROUTE_WORKSPACE_REQUIRED')
                workspace=canonical_path(route['workspace'])
                if not workspace.is_dir():
                    raise ValueError('CORE_ROUTE_WORKSPACE_MISSING')
                workspaces.append(workspace)
            principals = {p['subject']: p for p in core['clients']}
            kinds = set()
            for channel in config['channels']:
                if channel['kind'] in kinds:
                    raise ValueError('Suite supports one bridge per kind in an isolated home')
                kinds.add(channel['kind'])
                for sender in channel['senders']:
                    principal = principals.get(sender['subject'], {})
                    if principal.get('operator') or sender['model'] not in principal.get('routes', {'localpilot':'localpilot'}) or principal.get('token_env') != sender['token_env'] or not {'read','submit'} <= set(principal.get('scopes', ['read','submit','cancel'])):
                        raise ValueError('CHANNEL_REQUIRES_DEDICATED_ORDINARY_CORE_PRINCIPAL')
                ap = channel.get('approval')
                if ap:
                    principal = principals.get(ap['subject'], {})
                    if channel['kind'] != 'wechat' or principal.get('operator') is not True or 'control' not in principal.get('scopes', []) or principal.get('token_env') != ap['token_env'] or not {s['subject'] for s in channel['senders'] if s['sender_id'] in ap['senders']} <= set(principal.get('approval_for', [])):
                        raise ValueError('WECHAT_REQUIRES_SEPARATE_SCOPED_OPERATOR')
            state = canonical_path(args.state_dir)
            for private in (root,state):
                if any(private == workspace or workspace in private.parents for workspace in workspaces):
                    raise ValueError('CHANNEL_PRIVATE_STATE_MUST_BE_OUTSIDE_ALL_CORE_WORKSPACES')
            if any((parent/'.git').exists() for parent in (state,*state.parents)):
                raise ValueError('CHANNEL_STATE_MUST_BE_OUTSIDE_REPOSITORIES')
            if state.exists():
                raise ValueError('Fresh explicit state directory required; existing bridge state is never imported')
            if state == root or root in state.parents:
                raise ValueError('State must be separate from the component runtime')
            private_directory(state, create=True)
            save(root / 'adapter.json', config)
            save(root / 'configuration.json', {'adapter': config, 'port': args.port, 'state': str(state)})
            return {'status': 'configured', 'requires': 'Set credential environment variables privately before start; Core configuration is unchanged'}
        config = configured(root)
        if args.action == 'doctor':
            states = {kind: node(node_path) for kind in KINDS}
            for kind in KINDS:
                try:
                    assets(root, kind)
                    states[kind]['modules'] = 'present'
                except ValueError:
                    states[kind] = {'status': 'unavailable', 'code': 'CHANNEL_BRIDGE_MODULE_MISSING'}
            channel = config['adapter']['channels'][0]
            key = (os.environ if credentials is None else credentials).get(channel['ingress_key_env'])
            upstream = 'NOT_PROBED'
            if process(root, 'adapter') and key:
                health = request(config, '/healthz', key=key)
                upstream = health['status']
            probe = """import sys,tempfile
from pathlib import Path
from localpilot_channels.security import private_json
from localpilot_channels.adapter import Adapter
try:
    c=private_json(sys.argv[1])
    # Validate configuration/credentials in an ephemeral private database only.
    # Existing channel state is not opened; upstream checks use GET exclusively.
    with tempfile.TemporaryDirectory(prefix='lp-channel-doctor-') as directory:
        adapter=Adapter(c,Path(directory)/'validation',wait_seconds=0,timeout=2)
        try:
            for binding in adapter.bindings.values():
                binding['client'].identity()
            for channel in adapter.channels.values():
                if channel.get('approval'):
                    channel['approval']['client'].identity()
        finally:
            adapter.close()
    print('IDENTITIES_READY')
except Exception:
    print('IDENTITY_OR_CONNECTION_FAILED');sys.exit(2)
"""
            try:
                result = subprocess.run([*python_command(root), '-I', '-c', probe, str(root / 'adapter.json')],
                                        env=environment(config, 'adapter', credentials), capture_output=True, text=True, timeout=30)
                identities = 'ready' if result.returncode == 0 and result.stdout.strip() == 'IDENTITIES_READY' else 'auth_or_connection_failed'
            except (ValueError, subprocess.TimeoutExpired):
                identities = 'credentials_missing_or_probe_timeout'
            return {'status': 'diagnosed', 'bridges': states, 'adapter': upstream, 'core_identities': identities,
                    'core_roles': 'checked against explicit private Core configuration at configure time',
                    'platform_connections': 'NOT_PROBED', 'recent_errors': {k: recent_error(root,k) for k in MODULES}, 'verification': 'NOT_RUN'}
        if args.action in {'pending', 'task'}:
            if not args.channel or not args.sender_id:
                raise ValueError('--channel and --sender-id are required; cross-sender queries are not combined')
            channel = next((c for c in config['adapter']['channels'] if c['channel'] == args.channel), None)
            if channel is None or args.sender_id not in {s['sender_id'] for s in channel['senders']}:
                raise ValueError('CHANNEL_SENDER_NOT_CONFIGURED')
            key = (os.environ if credentials is None else credentials).get(channel['ingress_key_env'])
            if not key:
                raise ValueError('CHANNEL_INGRESS_KEY_MISSING')
            if args.action == 'pending':
                # Read-only diagnostic of owner mapping; never refresh or execute tasks.
                dbpath = canonical_path(Path(config['state']) / 'adapter/channels.sqlite3')
                private_file(dbpath)
                import sqlite3
                db = sqlite3.connect(dbpath.as_uri() + '?mode=ro', uri=True)
                try:
                    owner = hashlib.sha256(json.dumps([args.channel,args.sender_id],sort_keys=True,ensure_ascii=True).encode()).hexdigest()
                    row = db.execute('SELECT data FROM items WHERE id=?', ('owner:' + owner,)).fetchone()
                    active = json.loads(row[0]).get('active') if row else None
                finally:
                    db.close()
                return {'status': 'observed', 'active_task': active, 'source': 'private_channel_mapping', 'verified': False}
            if not args.task_id:
                raise ValueError('--task-id required')
            return request(config, '/tasks/query', {'channel': args.channel, 'sender_id': args.sender_id, 'task_id': args.task_id}, key=key)
        component = args.component or 'adapter'
        if process(root, component):
            raise ValueError('Owned channel process is already running; no connection is restarted')
        env = environment(config, component, credentials)
        if component == 'adapter':
            if args.action == 'login':
                raise ValueError('Only WeChat has an interactive login command')
            command = [*python_command(root), '-I', '-m', 'localpilot_channels', '--config', str(root / 'adapter.json'),
                       '--state-dir', str(Path(config['state']) / 'adapter'), '--port', str(config['port'])]
        else:
            runtime = node(node_path)
            if runtime['status'] != 'ready':
                return runtime
            command = [runtime['path'], str(assets(root, component)), 'login' if args.action == 'login' else 'run']
        if args.action == 'login':
            if component != 'wechat':
                raise ValueError('Only explicit WeChat login is supported')
            result = subprocess.run(command, env=env)
            return {'status': 'login_finished' if result.returncode == 0 else 'error', 'exit_code': result.returncode}
        return launch(root, component, command, env, config)


def launch(root, component, command, env, config=None):
    if process(root, component):
        raise ValueError('CHANNEL_ALREADY_RUNNING')
    # Only CLI diagnostics reach stderr: fixed codes, never remote bodies.
    # Status/doctor expose an allowlist of codes, never raw stderr.
    error_file = private_file(root / (component + '.error.log'), create=True)
    fd = os.open(error_file, os.O_WRONLY | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        child = subprocess.Popen(command, env=env, cwd=root, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=fd, start_new_session=True)
    finally:
        os.close(fd)
    import psutil
    try:
        p = psutil.Process(child.pid)
        observed = p.cmdline()
        # macOS framework Python can canonicalize argv[0] during exec.
        # Capture the child we just spawned; subsequent controls match this
        # observed command, executable, owner and creation time exactly.
        if observed[1:] != command[1:]:
            raise ValueError('CHANNEL_CHILD_ARGUMENTS_CHANGED')
        save(root / (component + '.process.json'), {'pid': child.pid, 'created': p.create_time(),
             'argv': observed, 'executable': p.exe()})
    except Exception:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=20)
        raise ValueError('CHANNEL_PROCESS_RECORD_FAILED') from None
    def refresh_identity():
        # Framework Python execs its app binary after Popen returns. Only
        # record the final identity after authenticated startup readiness.
        current = psutil.Process(child.pid)
        if abs(current.create_time()-p.create_time()) > .02 or current.cmdline()[1:] != command[1:]:
            raise ValueError('CHANNEL_CHILD_IDENTITY_CHANGED')
        save(root / (component + '.process.json'), {'pid':child.pid,'created':current.create_time(),
             'argv':current.cmdline(),'executable':current.exe()})
    if component == 'adapter':
        key = env[config['adapter']['channels'][0]['ingress_key_env']]
        until = time.monotonic() + 5
        while time.monotonic() < until:
            if child.poll() is not None:
                raise ValueError('CHANNEL_START_FAILED: inspect private config, state permissions or port conflicts')
            try:
                health = request(config, '/healthz', key=key)
                if health.get('pid') == child.pid and health.get('instance_id') == config['adapter']['instance_id']:
                    refresh_identity()
                    return {'status': 'running', 'component': component, 'pid': child.pid}
            except ValueError:
                pass
            time.sleep(.1)
        p.terminate()
        return {'status': 'UNKNOWN', 'code': 'CHANNEL_START_NOT_CONFIRMED'}
    time.sleep(.2)
    if child.poll() is None:
        refresh_identity()
    return {'status': 'running' if child.poll() is None else 'error', 'component': component,
            'platform_connection': 'NOT_VERIFIED', 'next_step': 'doctor; status'}
