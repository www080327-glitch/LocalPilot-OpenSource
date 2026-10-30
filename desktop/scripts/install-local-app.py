"""Install a verified local build at the existing app entry, retaining rollback."""
import argparse
import datetime
import json
import os
from pathlib import Path
import plistlib
import subprocess
import uuid
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'suite'))
from localpilot_suite.apps import archive, digest, processes

p = argparse.ArgumentParser()
p.add_argument('--source', type=Path, required=True)
p.add_argument('--execute', action='store_true')
p.add_argument('--receipt', type=Path)
p.add_argument('--desktop-link', action='store_true')
a = p.parse_args()
source = a.source.expanduser().resolve(strict=True)
target = Path.home() / 'Applications/LocalPilot.app'
expected = 'io.localpilot.desktop'

def info(path):
    return plistlib.loads((path / 'Contents/Info.plist').read_bytes())

def verify(path):
    value = info(path)
    if value.get('CFBundleIdentifier') != expected:
        raise ValueError('App identity differs from the installed entry')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(path)], check=True)
    return value

new = verify(source)
old = info(target) if target.exists() else None
if old and old.get('CFBundleIdentifier') != expected:
    raise ValueError('The existing entry belongs to a different App')
if target.is_symlink() or source == target:
    raise ValueError('Expected a separate real installed App directory')
if target.exists() and not target.is_dir():
    raise ValueError('Existing entry is not an App directory')
run = datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
backup = target.parent / ('.LocalPilot-upgrade-' + run + '.app')
archive_dir = Path.home()/'.local/share/localpilot-app-archives'/run
plan = {'source': str(source), 'destination': str(target), 'backup': str(backup),
        'archive_directory':str(archive_dir),
        'old_version': (old or {}).get('CFBundleShortVersionString'),
        'new_version': new.get('CFBundleShortVersionString'),
        'bundle_id': expected, 'user_data_modified': False, 'executed': False}
if a.receipt and a.receipt.exists():
    raise ValueError('Existing receipt is preserved')
if a.execute:
    commands = subprocess.check_output(['ps', '-axo', 'command='], text=True).splitlines()
    executable = str(target / 'Contents/MacOS') + '/'
    if any(str(target)+'/' in command for command in commands):
        raise ValueError('Quit the existing App and explicitly stop its Core before replacing its entry')
    if target.exists():
        plan['rollback_archive']=archive(target,archive_dir,digest(target))
    stage = target.parent / ('.LocalPilot-install-' + uuid.uuid4().hex + '.app')
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ditto', '--norsrc', '--noextattr', str(source), str(stage)], check=True)
    verify(stage)
    if target.exists():
        os.rename(target, backup)
    try:
        if target.exists():
            raise ValueError('App entry changed during installation')
        os.rename(stage, target)
        verify(target)
    except Exception:
        if backup.exists() and not target.exists():
            os.rename(backup, target)
        raise
    ls = Path('/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister')
    subprocess.run([str(ls), '-f', str(target)], check=True)
    if backup.exists():
        # The checked ZIP is the durable rollback. Old installed bundle goes to Trash.
        trash=Path.home()/'.Trash'/('LocalPilot-'+str(plan['old_version'])+'-'+run+'.app')
        subprocess.run([str(ls),'-u',str(backup)],check=False)
        backup.rename(trash)
        plan['old_app_trash']=str(trash)
    plan['executed'] = True
if a.receipt:
    a.receipt.parent.mkdir(parents=True, exist_ok=True)
    if a.receipt.exists():
        raise ValueError('Existing receipt is preserved')
    a.receipt.write_text(json.dumps(plan, indent=2) + '\n')
print(json.dumps(plan, indent=2))
