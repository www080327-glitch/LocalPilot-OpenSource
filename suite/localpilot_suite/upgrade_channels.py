"""Channel code snapshots participate in the reviewed product upgrade transaction."""
import hashlib
from pathlib import Path
import subprocess
import time

from . import channels
from .channel_paths import private_directory, private_json


def inventory(home):
    from .channel_product import KINDS, roots, runtime_root, settings
    rows, running = [], []
    for kind in KINDS:
        hub, _ = roots(home, kind)
        if not hub.exists():
            continue
        root = runtime_root(hub, settings(hub))
        if not root.exists():
            continue
        for component in (kind, 'adapter'):
            if channels.process(root, component):
                running.append('Channels/' + kind + '/' + component)
        if channels.installed(root):
            record = root / 'installation.json'
            rows.append({'kind': kind, 'root': str(root), 'version': private_json(record)['version'],
                         'installation_sha256': hashlib.sha256(record.read_bytes()).hexdigest()})
    legacy = home / 'channels'
    if legacy.exists():
        for component in channels.MODULES:
            if channels.process(legacy, component):
                running.append('Channels/legacy/' + component)
        if channels.installed(legacy):
            record = legacy / 'installation.json'
            rows.append({'kind': 'legacy', 'root': str(legacy), 'version': private_json(record)['version'],
                         'installation_sha256': hashlib.sha256(record.read_bytes()).hexdigest()})
    reference = home / 'channels-wheel.json'
    return {'runtimes': rows, 'running': running,
            'previous_release': private_json(reference) if reference.exists() else None}


def install(value, receipt, directory):
    target = next((row['target'] for row in value['components'] if row['module'] == 'channels'), None)
    if target is None:
        return
    current = inventory(Path(value['home']))
    if current['runtimes'] != value['channels']['runtimes'] or current['running']:
        raise ValueError('Channels installation changed after review or is still running')
    receipt['channels_attempted'] = []
    for row in value['channels']['runtimes']:
        root = Path(row['root'])
        archive = private_directory(root / 'code-archives' / value['id'], create=True)
        receipt['channels_attempted'].append(dict(row, archive=str(archive)))
        channels.save(directory / 'receipt.json', receipt)
        for name in ('runtime', 'installation.json'):
            (root / name).rename(archive / name)
        installed = channels.main(['install', '--wheel', target['path']], root.parent)
        if installed.get('status') != 'installed' or not channels.installed(root):
            raise ValueError('Channel runtime installation failed: ' + row['kind'])
        for kind in ('qq', 'wechat') if row['kind'] == 'legacy' else (row['kind'],):
            channels.assets(root, kind)
        checked = subprocess.run([*channels.python_command(root), '-c', 'import localpilot_channels'],
                                 capture_output=True, text=True, timeout=30)
        logfile = directory / ('channels-' + row['kind'] + '-verify.log')
        logfile.write_text(checked.stdout + checked.stderr)
        if checked.returncode:
            raise ValueError('Channel runtime import failed; inspect ' + str(logfile))
        receipt['steps'].append({'module': 'channels/' + row['kind'], 'exit': 0, 'log': str(logfile),
                                 'code_archive': str(archive), 'state_preserved': True})
        channels.save(directory / 'receipt.json', receipt)
    channels.save(Path(value['home']) / 'channels-wheel.json',
                  {'path': target['path'], 'sha256': target['sha256'], 'upgrade': value['id']})
    receipt['channels_release_updated'] = True
    channels.save(directory / 'receipt.json', receipt)


def rollback(value, receipt, directory):
    failures = []
    for row in reversed(receipt.get('channels_attempted', [])):
        root, archive = Path(row['root']), Path(row['archive'])
        try:
            old = archive / 'installation.json'
            if not old.exists() and not (archive / 'runtime').exists():
                if (hashlib.sha256((root / 'installation.json').read_bytes()).hexdigest() == row['installation_sha256']
                        and channels.installed(root)):
                    continue
                raise ValueError('Original channel code snapshot is unavailable')
            retired = private_directory(root / 'code-archives' / (value['id'] + '-retired-' + str(time.time_ns())), create=True)
            for name in ('runtime', 'installation.json'):
                if not (archive / name).exists():
                    continue
                if (root / name).exists():
                    (root / name).rename(retired / name)
                if (archive / name).exists():
                    (archive / name).rename(root / name)
            if not channels.installed(root):
                raise ValueError('Restored channel runtime failed integrity verification')
        except (OSError, ValueError) as error:
            failures.append({'module': 'channels/' + row['kind'], 'error': str(error)})
    if receipt.get('channels_release_updated'):
        reference = Path(value['home']) / 'channels-wheel.json'
        previous = value['channels']['previous_release']
        if previous:
            channels.save(reference, previous)
        elif reference.exists():
            reference.rename(directory / ('channels-wheel-retired-' + str(time.time_ns()) + '.json'))
    return failures
