"""Install a verified daily or explicitly isolated test APP, retaining rollback."""
import argparse
import datetime
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'suite'))
from localpilot_suite.apps import archive, digest

LS = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--test-app', action='store_true',
                        help='Use only io.localpilot.desktop.test at ~/Applications/LocalPilot Test.app')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--plan', type=Path, help='Bind execution to a saved, reviewed dry-run receipt')
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--desktop-link', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.receipt and args.receipt.exists():
        raise ValueError('Existing receipt is preserved')
    plan = make_plan(args.source, test_app=args.test_app)
    if args.plan:
        check_reviewed_plan(plan, json.loads(args.plan.read_text()))
    try:
        if args.execute:
            install(plan)
    except Exception:
        plan['status'] = 'failed'
        save_receipt(args.receipt, plan)
        print(json.dumps(plan, indent=2))
        raise
    save_receipt(args.receipt, plan)
    print(json.dumps(plan, indent=2))


def info(path):
    return plistlib.loads((path / 'Contents/Info.plist').read_bytes())


def verify(path, expected):
    value = info(path)
    if value.get('CFBundleIdentifier') != expected:
        raise ValueError('App identity differs from the selected installed entry')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(path)], check=True)
    return value


def make_plan(source, *, test_app=False, home=None):
    home = Path.home() if home is None else Path(home)
    source = source.expanduser().resolve(strict=True)
    name = 'LocalPilot Test' if test_app else 'LocalPilot'
    expected = 'io.localpilot.desktop.test' if test_app else 'io.localpilot.desktop'
    target = home / 'Applications' / (name + '.app')
    if target.is_symlink() or source == target:
        raise ValueError('Expected a separate real installed App directory')
    if target.exists() and not target.is_dir():
        raise ValueError('Existing entry is not an App directory')
    new = verify(source, expected)
    old = info(target) if target.exists() else None
    if old and old.get('CFBundleIdentifier') != expected:
        raise ValueError('The existing entry belongs to a different App')
    run = datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    prefix = name.replace(' ', '-')
    archive_root = 'localpilot-test-app-archives' if test_app else 'localpilot-app-archives'
    return {'source': str(source), 'source_sha256': digest(source), 'destination': str(target),
            'old_sha256': digest(target) if old else None,
            'backup': str(target.parent / ('.' + prefix + '-upgrade-' + run + '.app')),
            'stage': str(target.parent / ('.' + prefix + '-install-' + run + '.app')),
            'archive_directory': str(home / '.local/share' / archive_root / run),
            'trash_directory': str(home / '.Trash'), 'run': run, 'app_name': name,
            'old_version': (old or {}).get('CFBundleShortVersionString'),
            'new_version': new.get('CFBundleShortVersionString'),
            'bundle_id': expected, 'test_app': test_app, 'user_data_modified': False,
            'executed': False, 'status': 'plan_only'}


def check_reviewed_plan(current, reviewed):
    for key in ('source', 'source_sha256', 'destination', 'old_sha256', 'bundle_id', 'test_app'):
        if reviewed.get(key) != current[key]:
            raise ValueError('Application changed since reviewed plan: ' + key)
    if reviewed.get('executed') is not False:
        raise ValueError('A dry-run plan is required')


def install(plan):
    source, target, stage = (Path(plan[key]) for key in ('source', 'destination', 'stage'))
    commands = subprocess.check_output(['ps', '-axo', 'command='], text=True).splitlines()
    if any(str(target) + '/' in command for command in commands):
        raise ValueError('Quit the selected App and explicitly stop its Core before replacing its entry')
    if target.exists():
        plan['rollback_archive'] = archive(target, Path(plan['archive_directory']), plan['old_sha256'])
        if plan['rollback_archive']['signature']['code']:
            raise ValueError('Extracted rollback APP failed signature verification')
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ditto', '--norsrc', '--noextattr', str(source), str(stage)], check=True)
    verify(stage, plan['bundle_id'])
    if digest(stage) != plan['source_sha256']:
        raise ValueError('Staged APP differs from the reviewed source')
    activate(plan)
    plan.update(executed=True, status='installed')


def activate(plan):
    target, stage, backup = (Path(plan[key]) for key in ('destination', 'stage', 'backup'))
    if target.exists():
        os.rename(target, backup)
    try:
        os.rename(stage, target)
        verify(target, plan['bundle_id'])
        subprocess.run([LS, '-f', str(target)], check=True)
    except Exception:
        # Verification can fail after rename: preserve that candidate before restoring.
        if target.exists():
            plan['failed_app_trash'] = trash_app(target, plan, 'failed')
        if backup.exists():
            os.rename(backup, target)
            plan['rollback'] = 'restored_previous_app'
            subprocess.run([LS, '-f', str(target)], check=False)
        else:
            plan['rollback'] = 'restored_absent_entry'
        raise
    if backup.exists():
        subprocess.run([LS, '-u', str(backup)], check=False)
        plan['old_app_trash'] = trash_app(backup, plan, str(plan['old_version']))


def trash_app(app, plan, suffix):
    directory = Path(plan['trash_directory'])
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (plan['app_name'] + '-' + suffix + '-' + plan['run'] + '.app')
    app.rename(target)
    return str(target)


def save_receipt(path, plan):
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x') as stream:
            stream.write(json.dumps(plan, indent=2) + '\n')


if __name__ == '__main__':
    main()
