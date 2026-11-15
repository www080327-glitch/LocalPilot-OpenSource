"""Reviewed offline component upgrades with concrete artifacts and receipts."""
import argparse
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

from . import app_install, upgrade_channels
from .channel_paths import private_directory, private_json
from .channels import save

NAMES = {'core':'localpilot-agent-service', 'companion':'localpilot-companion', 'suite':'localpilot-suite', 'channels':'localpilot-channels'}
IMPORTS = {'core':'localpilot_service', 'companion':'companion', 'suite':'localpilot_suite', 'channels':'localpilot_channels'}


def plan(home, wheels=(), previous=(), *, app=None, test_app=False, python=None):
    home = private_directory(home)
    python = str(Path(python or sys.executable).absolute())
    observed = _runtime(python, home)
    targets, rollback = _wheel_set(wheels), _wheel_set(previous)
    if set(targets) != set(rollback):
        raise ValueError('Each selected component needs its exact installed-version rollback wheel')
    legacy_channels = 'core' in targets and any(row['contains_channels_code'] for row in (targets['core'], rollback['core']))
    if legacy_channels and 'channels' not in targets:
        raise ValueError('Legacy Core wheel also owns Channels code; include exact Channels target and rollback wheels in this plan')
    for module, artifact in rollback.items():
        if observed['versions'].get(NAMES[module]) != artifact['version']:
            raise ValueError('Rollback wheel does not match the installed version: ' + module)
    app_plan = app_install.make_plan(Path(app), test_app=test_app) if app else None
    if not targets and not app_plan:
        raise ValueError('Select an APP or component wheels')
    if app_plan and Path(python).is_relative_to(Path(app_plan['destination'])):
        raise ValueError('Prepare independent Suite modules before replacing an APP that contains this Python')
    _compatible(observed, targets)
    identity = 'upgrade_' + uuid.uuid4().hex
    directory = private_directory(home / 'upgrades' / identity, create=True)
    components = []
    for module in NAMES:
        if module not in targets:
            continue
        row = {'module':module, 'installed':observed['versions'][NAMES[module]]}
        for name, artifact in (('target', targets[module]), ('rollback', rollback[module])):
            folder = private_directory(directory / name, create=True)
            destination = folder / Path(artifact['path']).name
            shutil.copyfile(artifact['path'], destination)
            destination.chmod(0o600)
            row[name] = {**artifact, 'source':artifact['path'], 'path':str(destination)}
        components.append(row)
    value = {'schema_version':1, 'id':identity, 'home':str(home), 'python':python,
        'created_at':time.time(), 'components':components, 'desktop':app_plan,
        'runtime_versions':observed['versions'], 'python_version':observed['python'],
        'service_policy':'require_stopped; no task replay', 'data_policy':'preserve',
        'automatic_downloads':False, 'restart_gui':bool(app_plan), 'legacy_core_channel_overlap':legacy_channels,
        'blocking_services':_running_services(home, python), 'channels':upgrade_channels.inventory(home), 'status':'plan_only'}
    value['fingerprint'] = _fingerprint(value)
    save(directory / 'plan.json', value)
    return value


def execute(home, identity, *, fingerprint=None, rollback=False):
    home, value, directory = _load(home, identity, fingerprint)
    _artifacts(value)
    running = _running_services(home, value['python'])
    if running:
        raise ValueError('Stop these services before upgrading; no active tasks are terminated: ' + ', '.join(running))
    previous = private_json(directory / 'receipt.json') if (directory / 'receipt.json').exists() else None
    if rollback:
        if not previous or not previous.get('attempted') and not previous.get('desktop_attempted'):
            raise ValueError('This plan has not changed an installation')
        observed = _runtime(value['python'], home)
        for row in value['components']:
            if observed['versions'].get(NAMES[row['module']]) not in {row['installed'], row['target']['version']}:
                raise ValueError('Installed components changed since this upgrade; review a new plan before rollback')
        if value['desktop']:
            target = Path(value['desktop']['destination'])
            if target.exists() and app_install.digest(target) not in {value['desktop']['old_sha256'], value['desktop']['source_sha256']}:
                raise ValueError('Installed APP changed since this upgrade; review a new plan before rollback')
        receipt = {**previous, 'status':'rolling_back'}
        save(directory / 'receipt.json', receipt)
        return _rollback(value, receipt, directory)
    if previous:
        if previous['status'] == 'completed':
            return previous
        raise ValueError('This plan already has an execution receipt; inspect it and use rollback before a new plan')
    observed = _runtime(value['python'], home)
    if any(observed['versions'].get(NAMES[r['module']]) != r['installed'] for r in value['components']):
        raise ValueError('Installed components changed after review; create a new plan')
    _compatible(observed, {r['module']:r['target'] for r in value['components']})
    if value['desktop']:
        current = app_install.make_plan(Path(value['desktop']['source']), test_app=value['desktop']['test_app'])
        app_install.check_reviewed_plan(current, value['desktop'])
    receipt = {'id':identity, 'status':'installing', 'started_at':time.time(), 'attempted':[],
        'steps':[], 'data_preserved':True, 'automatic_task_replay':False, 'desktop_attempted':False}
    save(directory / 'receipt.json', receipt)
    try:
        for row in value['components']:
            receipt['attempted'].append(row['module'])
            save(directory / 'receipt.json', receipt)
            step = _install_wheel(value['python'], home, row['target']['path'], directory / (row['module'] + '-install.log'))
            receipt['steps'].append({'module':row['module'], **step})
            save(directory / 'receipt.json', receipt)
            if step['exit']:
                raise ValueError('Component installation failed: ' + row['module'])
        _verify(value, directory, rollback=False)
        upgrade_channels.install(value, receipt, directory)
        if value['desktop']:
            receipt['desktop_attempted'] = True
            receipt['desktop'] = dict(value['desktop'])
            save(directory / 'receipt.json', receipt)
            app_install.install(receipt['desktop'])
            save(directory / 'receipt.json', receipt)
        receipt.update(status='completed', finished_at=time.time(), verification='versions_imports_dependencies_passed',
                       next='Restart the GUI and explicitly recover stopped services; no task is replayed')
        save(directory / 'receipt.json', receipt)
        return receipt
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        receipt.update(status='rolling_back', failure=str(error), failed_at=time.time())
        save(directory / 'receipt.json', receipt)
        return _rollback(value, receipt, directory)


def history(home):
    home = private_directory(home)
    rows = []
    for directory in sorted((home / 'upgrades').glob('upgrade_*'), reverse=True):
        if not (directory / 'plan.json').is_file():
            continue
        value = private_json(directory / 'plan.json')
        receipt = private_json(directory / 'receipt.json') if (directory / 'receipt.json').exists() else None
        handoff = private_json(directory / 'handoff-error.json') if (directory / 'handoff-error.json').exists() else None
        rows.append({'plan':value, 'receipt':receipt, 'handoff_error':handoff})
    return {'status':'ok', 'upgrades':sorted(rows, key=lambda r:r['plan']['created_at'], reverse=True)}


def launch(home, identity, pid, *, fingerprint=None, rollback=False):
    home, value, directory = _load(home, identity, fingerprint)
    if not value['desktop']:
        raise ValueError('Detached execution is only needed for a reviewed APP replacement')
    _artifacts(value)
    running = _running_services(home, value['python'])
    if running:
        raise ValueError('Stop services before closing the GUI: ' + ', '.join(running))
    import psutil
    process = psutil.Process(pid)
    if process.uids().real != os.getuid():
        raise ValueError('The GUI process belongs to another user')
    command = [value['python'], '-m', 'localpilot_suite.upgrades', '--home',str(home),
        '--plan',identity, '--wait-pid',str(pid), '--wait-created',str(process.create_time()),
        '--fingerprint',value['fingerprint']]
    if rollback:
        command.append('--rollback')
    with (directory / 'helper.log').open('ab') as log:
        child = subprocess.Popen(command, cwd=home, env=_python_env(value['python']),
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    return {'status':'awaiting_gui_exit', 'id':identity, 'helper_pid':child.pid,
            'receipt_path':str(directory / 'receipt.json'), 'restart_gui':True}


def _rollback(value, receipt, directory):
    failures = []
    if receipt.get('desktop_attempted'):
        try:
            app_install.rollback(receipt.get('desktop', value['desktop']))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            failures.append({'module':'desktop', 'error':str(error)})
    failures.extend(upgrade_channels.rollback(value, receipt, directory))
    rows = {r['module']:r for r in value['components']}
    receipt['rollback_steps'] = []
    order = [module for module in reversed(receipt['attempted']) if module != 'channels']
    if 'channels' in receipt['attempted'] or value.get('legacy_core_channel_overlap') and 'core' in receipt['attempted']:
        # Legacy Core RECORDs own the same package. Reinstall the exact independent wheel last.
        order.append('channels')
    for module in order:
        row = rows[module]
        try:
            step = _install_wheel(value['python'], value['home'], row['rollback']['path'], directory / (module + '-rollback.log'))
        except (OSError, subprocess.SubprocessError) as error:
            failures.append({'module':module, 'error':str(error)})
            save(directory / 'receipt.json', receipt)
            continue
        receipt['rollback_steps'].append({'module':module, **step})
        if step['exit']:
            failures.append({'module':module, 'error':'rollback installation failed'})
        save(directory / 'receipt.json', receipt)
    try:
        _verify(value, directory, rollback=True)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        failures.append({'module':'components', 'error':str(error)})
    receipt.update(status='failed_rollback_failed' if failures else 'failed_rolled_back' if receipt.get('failure') else 'rolled_back',
                   rollback_failures=failures, finished_at=time.time())
    save(directory / 'receipt.json', receipt)
    return receipt


def _runtime(python, home):
    script = """import importlib.metadata as m,json,platform
items=list(m.distributions())
print(json.dumps({'python':platform.python_version(),'versions':{d.metadata['Name'].lower().replace('_','-'):d.version for d in items},'requirements':{d.metadata['Name'].lower().replace('_','-'):d.requires or [] for d in items}}))"""
    result = subprocess.run([python,'-c',script], cwd=home, env=_python_env(python), capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError('Unable to inspect the selected independent Python installation')
    return json.loads(result.stdout)


def _python_env(python):
    env = {k:v for k,v in os.environ.items() if k != 'PYTHONPATH'}
    if str(Path(python).absolute()) != str(Path(sys.executable).absolute()):
        env.pop('PYTHONHOME', None)
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
    return env


def _wheel_set(paths):
    result = {}
    for raw in paths:
        path = Path(raw).expanduser().resolve(strict=True)
        if not path.is_file() or path.suffix != '.whl':
            raise ValueError('Select a local wheel file')
        with zipfile.ZipFile(path) as archive:
            files = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
            if len(files) != 1:
                raise ValueError('Invalid wheel metadata')
            info = Parser().parsestr(archive.read(files[0]).decode())
            contains_channels_code = any(name.startswith('localpilot_channels/') for name in archive.namelist())
        name = info['Name'].lower().replace('_','-')
        module = next((k for k,v in NAMES.items() if v == name), None)
        if module is None or module in result or not info['Version']:
            raise ValueError('Select one wheel per Core, Companion, Suite or Channels component')
        result[module] = {'path':str(path), 'name':name, 'version':info['Version'],
            'contains_channels_code':contains_channels_code, 'requires_python':info.get('Requires-Python'), 'requirements':info.get_all('Requires-Dist') or [], 'sha256':_hash(path)}
    return result


def _compatible(observed, targets):
    try:
        from packaging.requirements import Requirement
        from packaging.specifiers import SpecifierSet
    except ImportError:
        from pip._vendor.packaging.requirements import Requirement
        from pip._vendor.packaging.specifiers import SpecifierSet
    versions = {**observed['versions'], **{row['name']:row['version'] for row in targets.values()}}
    requirements = {**observed['requirements'], **{row['name']:row['requirements'] for row in targets.values()}}
    for row in targets.values():
        if row['requires_python'] and not SpecifierSet(row['requires_python']).contains(observed['python'], prereleases=True):
            raise ValueError('Target wheel requires another Python version: ' + row['name'])
    changed = {row['name'] for row in targets.values()}
    for name, declarations in requirements.items():
        for text in declarations:
            dependency = Requirement(text)
            if dependency.marker and not dependency.marker.evaluate({'extra':''}):
                continue
            target = dependency.name.lower().replace('_','-')
            if name not in changed and target not in changed:
                continue
            if target not in versions or not dependency.specifier.contains(versions[target], prereleases=True):
                raise ValueError('Incompatible component set: ' + name + ' requires ' + text)


def _running_services(home, python):
    import psutil
    running = []
    record = home / 'process.json'
    if record.exists():
        saved = private_json(record)
        try:
            process = psutil.Process(saved['pid'])
            if abs(process.create_time() - saved['created']) < .02 and process.status() != psutil.STATUS_ZOMBIE:
                running.append('Core')
        except psutil.NoSuchProcess:
            pass
    config = home / 'companion.json'
    if config.exists():
        result = subprocess.run([python,'-m','companion','--config',str(config),'--json','status'],
            cwd=home, env=_python_env(python), capture_output=True, text=True, timeout=30)
        if result.returncode or not result.stdout.strip():
            raise ValueError('Companion state is UNKNOWN; inspect it before maintenance')
        if json.loads(result.stdout).get('status') in {'running','starting','stopping'}:
            running.append('Companion')
    return running + upgrade_channels.inventory(home)['running']


def _install_wheel(python, home, wheel, logfile):
    command = [python,'-m','pip','--isolated','install','--no-index','--no-deps','--force-reinstall',wheel]
    with logfile.open('ab') as log:
        result = subprocess.run(command, cwd=home, env=_python_env(python), stdout=log, stderr=log)
    return {'exit':result.returncode, 'log':str(logfile)}


def _verify(value, directory, *, rollback):
    expected = {r['module']:r['rollback' if rollback else 'target']['version'] for r in value['components']}
    script = """import importlib,importlib.metadata as m,json,sys
names=json.loads(sys.argv[1]);modules=json.loads(sys.argv[2]);expected=json.loads(sys.argv[3])
for key,version in expected.items():
 module=importlib.import_module(modules[key])
 actual=getattr(module,'VERSION',getattr(module,'__version__',None))
 if m.version(names[key])!=version or key!='channels' and actual!=version:raise ValueError('Component version/import mismatch: '+key)
if 'core' in expected:
 from localpilot_service.protocol import API_VERSION
 if API_VERSION!='1.0':raise ValueError('Agent Service API is incompatible with this Desktop')
"""
    checked = subprocess.run([value['python'],'-c',script,json.dumps(NAMES),json.dumps(IMPORTS),json.dumps(expected)],
        cwd=value['home'], env=_python_env(value['python']), capture_output=True, text=True, timeout=30)
    log = directory / ('verification-rollback.log' if rollback else 'verification-install.log')
    log.write_text(checked.stdout + checked.stderr)
    log.chmod(0o600)
    if checked.returncode:
        raise ValueError('Installed component import/version/API verification failed: ' + str(log))
    observed = _runtime(value['python'], value['home'])
    _compatible(observed, {r['module']:r['rollback' if rollback else 'target'] for r in value['components']})


def _hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _fingerprint(value):
    return hashlib.sha256(json.dumps({k:v for k,v in value.items() if k!='fingerprint'}, sort_keys=True).encode()).hexdigest()


def _load(home, identity, fingerprint):
    home = private_directory(home)
    if not isinstance(identity, str) or len(identity) != 40 or not identity.startswith('upgrade_') or any(c not in '0123456789abcdef' for c in identity[8:]):
        raise ValueError('Select a saved upgrade plan')
    directory = private_directory(home / 'upgrades' / identity)
    value = private_json(directory / 'plan.json')
    if value['schema_version'] != 1 or value['id'] != identity or value['home'] != str(home) or value['fingerprint'] != _fingerprint(value):
        raise ValueError('Upgrade plan changed; review a new plan')
    if fingerprint is not None and value['fingerprint'] != fingerprint:
        raise ValueError('Upgrade plan differs from the reviewed selection')
    return home, value, directory


def _artifacts(value):
    for row in value['components']:
        for artifact in (row['target'], row['rollback']):
            if _hash(artifact['path']) != artifact['sha256']:
                raise ValueError('A preserved wheel changed after review')


def worker():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--fingerprint', required=True)
    parser.add_argument('--wait-pid', type=int, required=True)
    parser.add_argument('--wait-created', type=float, required=True)
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    import psutil
    _, value, directory = _load(args.home, args.plan, args.fingerprint)
    try:
        try:
            process = psutil.Process(args.wait_pid)
            if abs(process.create_time() - args.wait_created) < .02:
                process.wait(timeout=60)
        except psutil.NoSuchProcess:
            pass
        result = execute(args.home, args.plan, fingerprint=args.fingerprint, rollback=args.rollback)
    except Exception as error:
        save(directory / 'handoff-error.json', {'status':'handoff_failed', 'error':str(error), 'at':time.time()})
        raise
    finally:
        destination = Path(value['desktop']['destination'])
        if sys.platform == 'darwin' and destination.is_dir():
            subprocess.run(['/usr/bin/open','-a',str(destination),'--args','--maintenance-return'], check=False)
    print(json.dumps(result))


if __name__ == '__main__':
    worker()
