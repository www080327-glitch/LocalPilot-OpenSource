"""Thin process/installation coordinator; never imports either Agent implementation."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
from . import VERSION


def emit(value):
    print(json.dumps(value, ensure_ascii=False))


def companion_config(home):
    return home / 'companion.json'


def initialize_companion(home, model_path=None):
    from localpilot_service.cli import save
    from localpilot_service.security import private_json
    path = companion_config(home)
    if path.exists():
        return
    connection = private_json(home / 'connection.json')
    managed=connection.get('managed_qwen35') is True
    if model_path is None and managed:
        candidate=Path.home()/'.cache/huggingface/hub/models--mlx-community--Qwen3.5-0.8B-4bit/snapshots/da28692b5f139cb0ec58a356b437486b7dac7462'
        if candidate.is_dir():model_path=str(candidate)
    save(path, {'data_dir':str(home / 'companion-data'), 'backend':'mlx' if model_path else 'disabled', 'model_path':model_path or '', 'watch_dirs':[],
        'native_observation_enabled':False, 'notifications':False, 'proactive_level':'off',
        'localpilot_endpoint':connection['url'], 'localpilot_api_key_env':connection['token_env'] if managed else 'LOCALPILOT_COMPANION_TOKEN', 'localpilot_client_subject':connection.get('client_subject','companion'),'localpilot_resource_key_env':'LOCALPILOT_RESOURCE_TOKEN' if managed or connection.get('cloud_configured') else 'LOCALPILOT_COMPANION_RESOURCE_TOKEN',
        'localpilot_auto_local':managed, 'localpilot_task_timeout_seconds':600, 'allow_local_on_battery':False, 'allow_automatic_cloud':False,
        'low_power_policy':'always'})
    if connection.get('omlx_settings_file'):
        # Shared service stays independent; initialization never loads a model.
        from localpilot_service.cli import environment
        from .desktop_setup import discover_omlx
        env=environment(home)
        entries=discover_omlx(connection['omlx_base_url'],env.get('LOCALPILOT_OMLX_API_KEY'))
        small=[m for m in entries if type(m.get('size_bytes')) is int and 0<m['size_bytes']<=1500000000]
        if small:
            selected=min(small,key=lambda m:m['size_bytes'])
            meta=selected
            config=private_json(path)
            config.update(backend='omlx',model_path=meta['model_path'],http_model_endpoint=connection['omlx_base_url'],
                http_model_name=selected['id'],http_model_api_key_env='LOCALPILOT_OMLX_API_KEY',http_model_host_local_only=True,
                model_routing_enabled=False,localpilot_auto_local=True,localpilot_expected_local_model=private_json(home/'service.json')['routes']['companion-execution']['backend']['model'],
                desktop_control_enabled=True,low_power_policy='system',local_model_min_available_bytes=4*1024**3,localpilot_resource_key_env='LOCALPILOT_RESOURCE_TOKEN')
            save(path,config)


def wheel_info(path, expected):
    path = Path(path).expanduser().resolve(strict=True)
    if not path.name.endswith('.whl') or not path.is_file():
        raise ValueError('Select a local wheel file')
    with zipfile.ZipFile(path) as archive:
        metadata = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
        if len(metadata) != 1:raise ValueError('Invalid wheel metadata')
        from email.parser import Parser
        info = Parser().parsestr(archive.read(metadata[0]).decode())
        if info['Name'].lower().replace('_','-') != expected:
            raise ValueError('Wheel does not match the selected module')
        return str(path), info['Version']


def upgrade(argv, home):
    p = argparse.ArgumentParser(description='Independent offline wheel upgrade/rollback; data is preserved')
    p.add_argument('module', choices=['core','companion','suite']); p.add_argument('--wheel', required=True)
    p.add_argument('--execute', action='store_true'); p.add_argument('--previous-wheel')
    a = p.parse_args(argv)
    names = {'core':'localpilot-agent-service', 'companion':'localpilot-companion', 'suite':'localpilot-suite'}
    wheel, version = wheel_info(a.wheel, names[a.module])
    previous = wheel_info(a.previous_wheel, names[a.module])[0] if a.previous_wheel else None
    value = {'module':a.module, 'target':version, 'wheel':wheel, 'previous_wheel':previous,
             'data_policy':'preserve', 'command':[sys.executable, '-m', 'pip', 'install', '--no-deps', wheel]}
    if a.execute:
        if not previous:raise ValueError('--execute requires --previous-wheel so rollback is concrete')
        import psutil
        if home.is_symlink() or not home.is_dir() or home.stat().st_uid != os.getuid() or home.stat().st_mode & 0o077:
            raise ValueError('Initialize a private data directory before upgrade')
        if a.module == 'core':
            record_path = home / 'process.json'
            if record_path.exists():
                if record_path.is_symlink() or record_path.stat().st_mode & 0o077:raise ValueError('Unsafe process record')
                record = json.loads(record_path.read_text())
                try:
                    process = psutil.Process(record['pid'])
                    if abs(process.create_time() - record['created']) < .02 and process.status() != psutil.STATUS_ZOMBIE:
                        raise ValueError('Stop Core explicitly before upgrade; active tasks must be resolved first')
                except psutil.NoSuchProcess:pass
        elif a.module == 'companion':
            probe = subprocess.run([sys.executable, '-m', 'companion', '--config', str(companion_config(home)), '--json', 'status'], capture_output=True, text=True)
            if probe.returncode == 0 and json.loads(probe.stdout).get('status') == 'running':
                raise ValueError('Stop Companion explicitly before upgrade')
        # Record rollback before installation; never rewrite model/database/config paths.
        record_path = home / ('upgrade-' + a.module + '.json')
        temporary = record_path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as f:json.dump(value, f)
        os.replace(temporary, record_path)
        result = subprocess.run(value['command'])
        if result.returncode:return result.returncode
        value['status'] = 'installed_run_doctor_before_start'
    else:value['status'] = 'plan_only_add_execute_and_previous_wheel'
    emit(value);return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ['--version']:
        value = {'suite':VERSION}
        for name in ['localpilot-agent-service','localpilot-companion']:
            try:value[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:value[name] = 'NOT_INSTALLED'
        emit(value);return 0
    if not argv or argv in [['--help'], ['-h']]:
        print('LocalPilot Suite — independent modules through API 1.0\n\nUsage: localpilot [--home DIR] [--json] COMMAND\n\nCore: init doctor start stop restart status ask chat agent models tasks task logs config\nCompanion: companion start|stop|status|ask|... (its own CLI)\nPlugins: plugins list|add|discover|review|enable|disable|tools|doctor|update|remove\nSkills: skills list|add|show|enable|disable|doctor|update|remove\nChannels (optional): channels list|install|configure|doctor|start|stop|status|pending|task|login|uninstall\nModules: upgrade core|companion|suite --wheel FILE [--execute --previous-wheel FILE]\n\nCtrl-C detaches a task; task watch ID reconnects. No model download at initialization.\nUse localpilot COMMAND --help for details. Global options go before COMMAND.')
        return 0
    # Parse only global flags. All task options stay with their owning module.
    prefix=[]; index=0; home=Path(os.environ.get('LOCALPILOT_HOME','~/.local/share/localpilot')).expanduser().resolve(); structured=False
    while index<len(argv) and argv[index] in {'--home','--json'}:
        if argv[index]=='--home':
            if index+1>=len(argv):emit({'error':'--home needs a directory'});return 2
            home=Path(argv[index+1]).expanduser().resolve();prefix.extend(['--home',str(home)]);index+=2
        else:structured=True;prefix.append('--json');index+=1
    rest=argv[index:]
    if not rest:emit({'error':'command required'});return 2
    try:
        if rest[0] == 'channels':
            from .channels import main as channels
            value = channels(rest[1:], home)
            emit(value)
            return 0 if value.get('status') not in {'unavailable', 'error', 'UNKNOWN'} else 4
        if rest[0] in {'plugins', 'skills'}:
            from localpilot_plugins.cli import main as plugins, skills_main
            value = (plugins if rest[0] == 'plugins' else skills_main)(rest[1:], home)
            emit(value)
            return 0 if value.get('status') not in {'unavailable', 'review_required'} else 4
        if rest[0]=='maintenance':
            from .apps import main as maintenance
            emit(maintenance(rest[1:],home));return 0
        if rest[0]=='integrations':
            from .integrations import main as integrations
            emit(integrations(rest[1:],home));return 0
        if rest[0]=='product-control':
            p=argparse.ArgumentParser();group=p.add_mutually_exclusive_group(required=True);group.add_argument('--request-json');group.add_argument('--request-stdin',action='store_true')
            a=p.parse_args(rest[1:])
            if a.request_stdin:
                raw=sys.stdin.buffer.read(65537)
                if len(raw)>65536:raise ValueError('Product request exceeds limit')
                a.request_json=raw.decode('utf-8')
            from .product_control import dispatch
            emit(dispatch(home,json.loads(a.request_json)));return 0
        if rest[0]=='sync-models':
            from .desktop_setup import sync_models
            emit(sync_models(home));return 0
        if rest[0]=='model-resource':
            p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--operation',choices=['load','unload'],required=True);p.add_argument('--max-memory-bytes',type=int,required=True);p.add_argument('--key',required=True);p.add_argument('--confirmed',action='store_true')
            a=p.parse_args(rest[1:])
            if not a.confirmed:raise ValueError('Separate model resource confirmation required')
            from localpilot_service.cli import connection,environment
            from localpilot_service.sdk import Client
            ordinary=connection(home);health=ordinary.request('/healthz')
            env=environment(home)
            operator=Client(ordinary.base_url,token=env['LOCALPILOT_RESOURCE_TOKEN'],timeout=130)
            result=operator.request('/model-manager/v1/operations',{'client_subject':health['client_subject'],'model':a.model,'operation':a.operation,'confirmed':True,'max_memory_bytes':a.max_memory_bytes},key=a.key)
            emit(result);return 0 if result['status']=='completed' else 6
        if rest[0]=='desktop-init':
            p=argparse.ArgumentParser();p.add_argument('--workspace',required=True)
            a=p.parse_args(rest[1:])
            from .desktop_setup import prepare
            emit(prepare(home,a.workspace));return 0
        if rest[0]=='cloud-configure':
            p=argparse.ArgumentParser();p.add_argument('--key-file',required=True)
            a=p.parse_args(rest[1:])
            from .desktop_setup import configure_cloud
            emit(configure_cloud(home,a.key_file));return 0
        if rest[0]=='cloud-scope':
            p=argparse.ArgumentParser();p.add_argument('--paths-json',required=True)
            a=p.parse_args(rest[1:])
            from .desktop_setup import configure_cloud_scope
            emit(configure_cloud_scope(home,json.loads(a.paths_json)));return 0
        if rest[0]=='upgrade':return upgrade(rest[1:],home)
        if rest[0]=='companion':
            from localpilot_service.cli import environment
            config=companion_config(home)
            if not config.exists():raise ValueError('Run init first, or configure Companion independently with its own CLI')
            env=environment(home)
            # Separate process and no operator credentials in the ordinary Companion.
            env={k:v for k,v in env.items() if 'OPERATOR' not in k.upper() and 'DEEPSEEK' not in k.upper()}
            command=[os.environ.get('LOCALPILOT_COMPANION_PYTHON',sys.executable),'-m','companion','--config',str(config)]
            if structured:command.append('--json')
            return subprocess.run(command+rest[1:],env=env).returncode
        model_path=None
        if rest[0]=='init':
            setup=argparse.ArgumentParser(add_help=False);setup.add_argument('--companion-model-path')
            extra,rest=setup.parse_known_args(rest);model_path=extra.companion_model_path
            if model_path and not (Path(model_path).expanduser().is_dir() and (Path(model_path).expanduser()/'config.json').is_file()):raise ValueError('Companion model must reference an existing cached model directory')
        from localpilot_service.cli import main as core
        result=core(prefix+rest)
        if rest[0]=='init' and result==0:initialize_companion(home,model_path)
        return result
    except ImportError:
        if rest[0] in {'plugins', 'skills'}:
            emit({'error':'Plugin dependencies unavailable; install the reviewed Core wheel with its plugins extra.'});return 4
        emit({'error':'Core CLI unavailable; require localpilot-agent-service >=4.9.2rc1. Use upgrade core with the compatible wheel.'});return 4
    except (ValueError,OSError) as exc:
        from urllib.error import HTTPError
        if isinstance(exc, HTTPError):
            try:
                value=json.loads(exc.read(16384)); detail=value.get('error',{})
                message=detail.get('message',detail.get('code','')) if isinstance(detail,dict) else str(detail)
            except Exception:message='请查看服务状态和模型文件是否完整'
            emit({'error':f'服务拒绝操作（HTTP {exc.code}）：{message[:600]}'});return 2
        emit({'error':str(exc) if isinstance(exc,ValueError) else type(exc).__name__});return 2


if __name__=='__main__':sys.exit(main())
