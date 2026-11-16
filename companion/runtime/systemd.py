"""Explicit installation of one user-scoped Companion service."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


UNIT = 'localpilot-companion.service'


def unit_text(config_filename, environment_file=None):
    arguments = [sys.executable, '-m', 'companion', '--config', str(Path(config_filename).absolute()), 'run']
    text = ('# LocalPilot Companion user service\n[Unit]\nDescription=LocalPilot Companion\n'
            'After=graphical-session.target\n\n[Service]\nType=exec\n'
            'ExecStart=' + ' '.join(_quote(value, command=True) for value in arguments) + '\n'
            'WorkingDirectory=' + str(Path(__file__).resolve().parents[2]).replace('%', '%%') + '\n'
            'Environment=PYTHONUNBUFFERED=1\nRestart=no\nTimeoutStopSec=30\n')
    if environment_file:
        text += 'EnvironmentFile=' + _quote(str(Path(environment_file).absolute())) + '\n'
    return text + '\n[Install]\nWantedBy=default.target\n'


def manage(action, config_filename, private, confirmed=False, environment_file=None):
    if action not in {'render', 'status', 'install', 'uninstall'}:
        raise ValueError('Unknown systemd action')
    text = unit_text(config_filename, environment_file)
    if action == 'render':
        target = private.write(UNIT, text)
        return {'status':'preview', 'path':str(target), 'installed':False, 'manager':'systemd_user'}
    if not sys.platform.startswith('linux'):
        return {'status':'unavailable', 'reason':'linux_required', 'installed':False}
    destination = _destination()
    executable = shutil.which('systemctl')
    if not executable:
        return {'status':'unavailable', 'reason':'systemctl_not_found', 'installed':destination.exists()}
    if action == 'status':
        result = _run(executable, 'show', UNIT, '--property=ActiveState,SubState,LoadState,UnitFileState,MainPID')
        values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        return {'status':'unavailable' if result.returncode else values.get('ActiveState', 'UNKNOWN'),
                'installed':destination.exists(), 'path':str(destination), 'manager':'systemd_user',
                'unit':values, 'detail':result.stderr.strip()[:500] if result.returncode else ''}
    if not confirmed:
        return {'status':'confirmation_required', 'reason':'Re-run with --confirm to change this user startup service.'}
    if action == 'uninstall':
        return _uninstall(executable, destination, private)
    _validate_install(destination, config_filename, environment_file, private)
    ready = _run(executable, 'show', '--property=Version')
    if ready.returncode:
        return {'status':'unavailable', 'reason':'systemd_user_manager_unavailable',
                'detail':ready.stderr.strip()[:500], 'installed':False}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x') as stream:
        stream.write(text)
    destination.chmod(0o600)
    private.write('systemd-installation.json', json.dumps({'path':str(destination),
        'sha256':hashlib.sha256(text.encode()).hexdigest()}) + '\n')
    for args in [('daemon-reload',), ('enable', '--now', UNIT)]:
        result = _run(executable, *args)
        if result.returncode:
            return {'status':'unavailable', 'installed':True, 'path':str(destination),
                    'reason':'systemd_start_failed', 'detail':result.stderr.strip()[:500],
                    'recovery':'Inspect the user journal; use systemd uninstall --confirm to remove the owned unit.'}
    return {'status':'installed', 'installed':True, 'path':str(destination), 'manager':'systemd_user',
            'startup_readiness':'check_companion_status', 'linger_enabled':False}


def _quote(value, command=False):
    if any(ord(char) < 32 for char in value):
        raise ValueError('Service paths must not contain control characters')
    value = value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    if command:
        value = value.replace('$', '$$')
    return '"' + value + '"'


def _destination():
    configured = os.environ.get('XDG_CONFIG_HOME', '')
    base = Path(configured) if configured and Path(configured).is_absolute() else Path.home() / '.config'
    return base / 'systemd' / 'user' / UNIT


def _run(executable, *arguments):
    return subprocess.run([executable, '--user', *arguments], capture_output=True, text=True, timeout=35)


def _validate_install(destination, config_filename, environment_file, private):
    if destination.exists() or destination.is_symlink():
        raise ValueError('Existing startup item preserved; uninstall it explicitly first')
    if any(path.is_symlink() for path in destination.parents):
        raise ValueError('Symlink startup path refused')
    if not Path(config_filename).is_file():
        raise ValueError('Companion configuration must exist before startup registration')
    if environment_file:
        file = Path(environment_file)
        if not file.is_absolute() or not file.is_file() or file.is_symlink():
            raise ValueError('Environment file must be an absolute regular file')
        info = file.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Environment file must be private to the current user')
    from .process import service_record
    try:
        service_record(private)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return
    raise ValueError('Stop the current Companion before installing its user service')


def _uninstall(executable, destination, private):
    receipt_path = private.file('systemd-installation.json')
    if not destination.exists() and not destination.is_symlink():
        return {'status':'not_installed', 'installed':False, 'memory_preserved':True}
    if destination.is_symlink() or not receipt_path.is_file():
        raise ValueError('Unrecognized startup item preserved')
    receipt = json.loads(receipt_path.read_text())
    if receipt != {'path':str(destination), 'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}:
        raise ValueError('Modified or unrelated startup item preserved')
    result = _run(executable, 'disable', '--now', UNIT)
    if result.returncode:
        return {'status':'unavailable', 'installed':True, 'path':str(destination),
                'reason':'systemd_stop_failed', 'detail':result.stderr.strip()[:500]}
    destination.unlink()
    receipt_path.unlink()
    reload = _run(executable, 'daemon-reload')
    return {'status':'uninstalled', 'installed':False, 'memory_preserved':True,
            'daemon_reload_returncode':reload.returncode, 'manager':'systemd_user'}
