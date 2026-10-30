"""Explicit macOS application inventory, verified archives and reversible cleanup.

No cache, source, model or user-data deletion. Cleanup consumes a reviewed plan.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import time
import uuid

LS = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'


def run(argv, timeout=60):
    p = subprocess.run(list(map(str, argv)), capture_output=True, text=True, timeout=timeout)
    return {'code': p.returncode, 'output': (p.stdout + p.stderr).strip()[-12000:]}


def digest(path):
    """Canonical tree checksum: relative names, file bytes and symlink destinations."""
    h = hashlib.sha256()
    for p in sorted(path.rglob('*')):
        name = p.relative_to(path).as_posix().encode()
        if p.is_symlink():
            h.update(b'L\0' + name + b'\0' + os.readlink(p).encode() + b'\0')
        elif p.is_file():
            h.update(b'F\0' + name + b'\0')
            with p.open('rb') as f:
                h.update(hashlib.file_digest(f, 'sha256').digest())
    return h.hexdigest()


def processes():
    import psutil
    rows = []
    for p in psutil.process_iter(['pid', 'ppid', 'cmdline', 'exe']):
        try:
            cmd = ' '.join(p.info['cmdline'] or [])
            if 'localpilot' in cmd.lower():
                # Keep only process ownership, never credentials or arbitrary command text.
                rows.append({'pid': p.pid, 'ppid': p.ppid(), 'exe': p.info['exe'],
                             'bundle_paths': [s[:s.index('.app/')+4] for s in (p.info['cmdline'] or []) if '.app/' in s]})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return rows


def roots():
    home = Path.home()
    result = [home/'Applications', Path('/Applications'), home/'Desktop/aic竞赛',
              home/'.local/share/localpilot-desktop-builds',home/'.cache/localpilot-desktop/target/release/bundle/macos', home/'Downloads']
    base = home/'Desktop/aic竞赛/LocalPilot'
    if base.exists():
        for line in run(['git', '-C', base, 'worktree', 'list', '--porcelain'])['output'].splitlines():
            if line.startswith('worktree '): result.append(Path(line[9:]))
    return list(dict.fromkeys(result))


def current_references():
    import re
    result={}
    files=list((Path.home()/'Library/Application Support').glob('io.localpilot*/profile.json'))
    files+=list((Path.home()/'.local/share').glob('localpilot*-caller*/.localpilot/dsh.patch.json'))
    for p in files:
        try:
            for path in re.findall(r'"([^"\n]*[.]app)/[^"\n]*"',p.read_text()):result.setdefault(path,[]).append(str(p))
        except (OSError,ValueError):pass
    return result


def scan(extra=()):
    running = processes(); paths = set(); links = []; errors = []; bindings={};references=current_references()
    search = roots() + list(map(Path, extra))
    for root in search:
        if not root.exists(): continue
        def error(e): errors.append(str(e))
        for parent, dirs, files in os.walk(root, followlinks=False, onerror=error):
            for name in set(files)&{'manifest.json','ARTIFACTS.json','SOURCE_BINDING.json'}:
                manifest=Path(parent)/name
                try:
                    if manifest.stat().st_size>1048576:continue
                    value=json.loads(manifest.read_text())
                    if isinstance(value,dict) and value.get('app_path') and value.get('source_commit'):
                        bindings.setdefault(value['app_path'],[]).append({'manifest':str(manifest),'source_commit':value['source_commit']})
                except (OSError,ValueError):pass
            for name in list(dirs):
                p = Path(parent)/name
                if name.endswith('.app'):
                    dirs.remove(name)
                    if 'localpilot' in name.lower():
                        if p.is_symlink(): links.append({'path': str(p), 'target': str(p.resolve())})
                        else: paths.add(p)
                elif name in {'.git', 'node_modules', '.venv', 'site-packages'}: dirs.remove(name)
    spotlight = run(['mdfind', 'kMDItemContentType == "com.apple.application-bundle" && kMDItemFSName == "*LocalPilot*"cd'])
    for line in spotlight['output'].splitlines():
        p = Path(line)
        if p.is_dir() and not p.is_symlink() and '.Trash' not in p.parts: paths.add(p)
    daily = Path.home()/'Applications/LocalPilot.app'
    rows = []
    for p in sorted(paths):
        try:
            with (p/'Contents/Info.plist').open('rb') as f: info = plistlib.load(f)
            active = [r['pid'] for r in running if any(Path(v).resolve() == p.resolve() for v in r['bundle_paths'])]
            category = 'A' if p == daily else 'B' if active else 'F' if p.name != 'LocalPilot.app' or str(p) in references else 'D' if '/target/' in str(p) else 'C' if 'LocalPilot Backups' in p.parts else 'E'
            known=(str(p).startswith(str(Path.home()/'.local/share/localpilot-desktop-builds')+'/') or category in {'A','B','C','D'} or '/docs/delivery/' in str(p))
            if not known or not str(info.get('CFBundleIdentifier','')).startswith('io.localpilot.desktop'):category='F'
            files = [f for f in p.rglob('*') if f.is_file() and not f.is_symlink()]
            st = p.stat(); binding = list(bindings.get(str(p),[]))
            for manifest in [p.parent/'manifest.json', p.parent/'SOURCE_BINDING.json', p.parent/'ARTIFACTS.json']:
                if manifest.is_file():
                    value = json.loads(manifest.read_text())
                    binding.append({'manifest':str(manifest), 'source_commit':value.get('source_commit', value.get('commit', 'UNKNOWN'))})
            rows.append({'path':str(p), 'version':info.get('CFBundleShortVersionString'),
                         'bundle_id':info.get('CFBundleIdentifier'), 'sha256':digest(p),
                         'checksum_definition':'canonical relative path + file sha256 + symlink target',
                         'bytes':sum(f.stat().st_size for f in files), 'created':getattr(st,'st_birthtime',None),
                         'modified':st.st_mtime, 'signature':run(['/usr/bin/codesign','--verify','--deep','--strict',p]),
                         'signing_identity':run(['/usr/bin/codesign','-dv','--verbose=2',p]),
                         'source_binding':binding or 'UNKNOWN', 'running_pids':active,
                         'active_references':references.get(str(p),[]),
                         'daily':p == daily, 'category':category,
                         'recoverable_archive':'NOT_VERIFIED', 'eligible':category in {'C','D','E'} and not active})
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            errors.append({'path':str(p),'error':str(exc)})
    # Keep only LocalPilot records; do not publish another application's registry data.
    full=subprocess.run([LS,'-dump'],capture_output=True,text=True,timeout=60)
    registration={'code':full.returncode,'records':[block for block in full.stdout.split('--------------------------------------------------------------------------------') if 'localpilot' in block.lower()]}
    return {'schema':1, 'created':time.time(), 'roots':list(map(str,search)), 'apps':rows,
            'links':links, 'processes':running, 'scan_errors':errors,
            'launch_services':registration}


def archive(app, destination, expected):
    destination.mkdir(parents=True, exist_ok=True)
    target = destination/(app.parent.name+'-'+expected[:12]+'.app.zip')
    if not target.exists():
        run_result = run(['/usr/bin/ditto','-c','-k','--keepParent','--norsrc','--noextattr',app,target], timeout=600)
        if run_result['code']: raise ValueError(run_result)
    # Actual extraction and signature verification, not just zip CRC.
    with tempfile.TemporaryDirectory(prefix='localpilot-restore-') as tmp:
        result = run(['/usr/bin/ditto','-x','-k',target,tmp], timeout=600)
        restored = Path(tmp)/app.name
        if result['code'] or not restored.is_dir() or digest(restored) != expected:
            raise ValueError('Restored archive does not match application; preserved, cleanup refused')
        verification = run(['/usr/bin/codesign','--verify','--deep','--strict',restored])
    with target.open('rb') as f: sha = hashlib.file_digest(f,'sha256').hexdigest()
    return {'path':str(target),'sha256':sha,'restored_tree_sha256':expected,'signature':verification}


def cleanup(plan, destination):
    data = json.loads(Path(plan).read_text()); results = []
    for row in data['apps']:
        if not row.get('eligible'): continue
        app = Path(row['path'])
        if app.name != 'LocalPilot.app' or app.is_symlink() or app == Path.home()/'Applications/LocalPilot.app':
            raise ValueError('Plan targets a protected application')
        if not app.exists():
            results.append({'path':str(app),'status':'already_absent'}); continue
        if any(str(app) == path for p in processes() for path in p['bundle_paths']):
            results.append({'path':str(app),'status':'retained_running'}); continue
        if str(app) in current_references():
            results.append({'path':str(app),'status':'retained_referenced'});continue
        if digest(app) != row['sha256']: raise ValueError('Application changed since scan; rescan required')
        with (app/'Contents/Info.plist').open('rb') as f:identity=plistlib.load(f).get('CFBundleIdentifier','')
        if not str(identity).startswith('io.localpilot.desktop'):raise ValueError('Application ownership unknown; cleanup refused')
        backup = archive(app,destination,row['sha256'])
        # Recheck immediately after the potentially long archive operation.
        if digest(app) != row['sha256'] or str(app) in current_references() or any(str(app) == path for p in processes() for path in p['bundle_paths']):
            raise ValueError('Application changed or started during backup; cleanup refused')
        trash = Path.home()/'.Trash'; trash.mkdir(exist_ok=True)
        target = trash/('LocalPilot-'+str(row['version'])+'-'+uuid.uuid4().hex[:8]+'.app')
        run([LS,'-u',app])
        app.rename(target)
        results.append({'path':str(app),'status':'trashed','trash_path':str(target),'archive':backup})
        # Durable receipt after every application, including partial runs.
        receipt = destination/'cleanup-results.json'
        receipt.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    return results


def main(argv, home=None):
    p = argparse.ArgumentParser(description='Inventory or archive/restore/Trash reviewed redundant apps; never empties Trash')
    p.add_argument('subject',choices=['apps'])
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--scan',action='store_true'); mode.add_argument('--dry-run',action='store_true'); mode.add_argument('--cleanup',action='store_true')
    p.add_argument('--plan',type=Path); p.add_argument('--output',type=Path)
    p.add_argument('--root',action='append',default=[])
    p.add_argument('--archives',type=Path,default=Path.home()/'.local/share/localpilot-app-archives')
    a = p.parse_args(argv)
    if a.cleanup:
        if not a.plan: p.error('--cleanup requires the reviewed --plan from --dry-run')
        value = cleanup(a.plan,a.archives)
    else:
        value = scan(a.root)
        if a.dry_run: value['mode']='DRY_RUN_NO_MUTATION'
        if home is not None:
            try:
                from localpilot_service.cli import connection,compatible,owned
                from localpilot_service.lifecycle import diagnostic
                process=owned(home)
                value['core']={'managed_pid':process.pid if process else None,'lifecycle':diagnostic(home)}
                try:value['core']['health']=compatible(connection(home))
                except (OSError,ValueError):value['core']['health']='UNREACHABLE'
            except (OSError,ValueError):value['core']={'status':'NOT_CONFIGURED_OR_UNREACHABLE','model_health':'NOT_PROBED'}
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        return {'output':str(a.output),'apps':len(value.get('apps',[])) if isinstance(value,dict) else len(value)}
    return value
