"""Offline component resources using a distribution-provided Linux Python.

The application carries reviewed wheels and an isolated relocatable environment,
not a copy of /usr or the builder's Python environment.
"""
import argparse
import base64
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tomllib
import zipfile
from concurrent.futures import ThreadPoolExecutor
from email.parser import Parser
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = {
    'localpilot-agent-service': ('pyproject.toml', ''),
    'localpilot-companion': ('companion/pyproject.toml', ''),
    'localpilot-suite': ('suite/pyproject.toml', 'suite'),
    'localpilot-channels': ('channels/pyproject.toml', ''),
}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def interpreter(python):
    script = 'import json,sys,platform;print(json.dumps({"version":platform.python_version(),"minor":"%d.%d"%sys.version_info[:2],"executable":sys.executable,"base_prefix":sys.base_prefix,"implementation":platform.python_implementation(),"system":platform.system(),"architecture":platform.machine()}))'
    info = json.loads(subprocess.check_output([str(python), '-I', '-c', script], text=True))
    if info['system'] != 'Linux' or info['implementation'] != 'CPython':
        raise ValueError('A native Linux CPython interpreter is required')
    if info['architecture'] != platform.machine():
        raise ValueError('Build on the target architecture')
    if not Path(info['executable']).resolve().is_relative_to('/usr'):
        raise ValueError('Select the distribution interpreter in /usr, not a private Python installation')
    return info


def wheel_info(path):
    with zipfile.ZipFile(path) as archive:
        entries = [name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
        if len(entries) != 1:
            raise ValueError(f'Invalid wheel metadata: {path.name}')
        info = Parser().parsestr(archive.read(entries[0]).decode())
    return info['Name'].lower().replace('_', '-'), info['Version']


def lock_dependencies(args):
    info = interpreter(args.python)
    pinned = json.loads((ROOT / 'runtime-dependencies.json').read_text())['packages']
    pinned['pip'] = {'version': args.pip_version, 'license': 'MIT'}
    inputs = {}
    for wheel in sorted(args.dependencies.glob('*.whl')):
        name, version = wheel_info(wheel)
        if name not in pinned or name in inputs or version != pinned[name]['version']:
            raise ValueError('Dependency set differs from pinned versions: ' + name)
        inputs[name] = wheel
    if set(inputs) != set(pinned):
        raise ValueError('All existing pinned dependencies plus the declared pip version are required')
    def official(item):
        name, wheel = item
        version = pinned[name]['version']
        metadata_url = f'https://pypi.org/pypi/{name}/{version}/json'
        with urlopen(metadata_url, timeout=30) as response:
            metadata = json.load(response)
        records = [file for file in metadata['urls'] if file['filename'] == wheel.name]
        sha = digest(wheel)
        if len(records) != 1 or records[0]['digests']['sha256'] != sha:
            raise ValueError('Official PyPI artifact hash mismatch: ' + wheel.name)
        return name, {'version': version, 'wheel': wheel.name, 'sha256': sha,
                      'license': pinned[name]['license'], 'source': metadata_url,
                      'url': records[0]['url'], 'requires_python': records[0]['requires_python']}
    with ThreadPoolExecutor(max_workers=4) as pool:
        packages = dict(pool.map(official, inputs.items()))
    result = {'schema': 1, 'system': 'Linux', 'architecture': info['architecture'],
              'python': info['minor'], 'packages': packages}
    if args.dependency_lock.exists():
        raise ValueError('Existing dependency lock preserved; select a fresh path')
    args.dependency_lock.write_text(json.dumps(result, indent=2) + '\n')
    return result


def prepare(args):
    info = interpreter(args.python)
    destination = args.output.resolve()
    if destination.exists():
        raise ValueError('Existing resources preserved; use a fresh build slot')
    lock = json.loads(args.dependency_lock.read_text())
    if lock['system'] != 'Linux' or lock['python'] != info['minor'] or lock['architecture'] != info['architecture']:
        raise ValueError('Dependency lock does not match the native interpreter')
    packages = lock['packages']
    expected = set(COMPONENTS) | set(packages)
    inputs = {}
    for directory in (args.wheels, args.dependencies):
        for wheel in sorted(directory.glob('*.whl')):
            name, version = wheel_info(wheel)
            if name not in expected or name in inputs:
                raise ValueError(f'Unexpected or duplicate wheel: {name}')
            if name in packages and (version != packages[name]['version'] or wheel.name != packages[name]['wheel'] or digest(wheel) != packages[name]['sha256']):
                raise ValueError(f'Dependency differs from reviewed lock: {name}')
            inputs[name] = wheel
    if set(inputs) != expected or 'pip' not in packages:
        raise ValueError('All four components, locked dependencies and pip are required')
    runtime = destination / 'runtime'
    subprocess.run([str(args.python), '-I', '-m', 'venv', '--without-pip', str(runtime)], check=True)
    executable = Path(info['executable']).resolve()
    (runtime / 'pyvenv.cfg').write_text(f'home = {executable.parent}\ninclude-system-site-packages = false\nversion = {info["version"]}\n')
    for name in ('python', 'python3', 'python' + info['minor']):
        (runtime / 'bin' / name).unlink(missing_ok=True)
        (runtime / 'bin' / name).symlink_to(executable)
    for name in ('activate', 'activate.csh', 'activate.fish', 'Activate.ps1'):
        (runtime / 'bin' / name).unlink(missing_ok=True)
    site = runtime / f'lib/python{info["minor"]}/site-packages'
    with zipfile.ZipFile(inputs['pip']) as archive:
        archive.extractall(site)
    wheels = destination / 'wheels'
    wheels.mkdir()
    for source in inputs.values():
        shutil.copyfile(source, wheels / source.name)
    env = {key: value for key, value in os.environ.items() if key not in ('PYTHONHOME', 'PYTHONPATH')}
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
    python = runtime / 'bin/python'
    subprocess.run([str(python), '-m', 'pip', '--isolated', 'install', '--no-index', '--no-deps', '--no-compile', '--force-reinstall', *map(str, sorted(wheels.glob('*.whl')))], env=env, check=True)
    subprocess.run([str(python), '-m', 'pip', 'check'], env=env, check=True)
    # venv writes absolute shebangs. Generate launchers from their installed bodies.
    entries = runtime / 'bin/portable-entrypoints'
    entries.mkdir()
    rewritten = {}
    for entry in list((runtime / 'bin').iterdir()):
        if entry.is_symlink() or not entry.is_file():
            continue
        payload = entry.read_bytes()
        if not payload.startswith(b'#!') or b'python' not in payload.split(b'\n', 1)[0]:
            continue
        body = entries / (entry.name + '.py')
        body.write_bytes(payload.split(b'\n', 1)[1])
        entry.write_text('#!/bin/sh\nset -eu\nLP_ENTRY_BIN=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexport PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1\nunset PYTHONHOME PYTHONPATH\nexec "$LP_ENTRY_BIN/python" "$LP_ENTRY_BIN/portable-entrypoints/' + body.name + '" "$@"\n')
        entry.chmod(0o755)
        rewritten[entry.name] = body
    for record in site.glob('*.dist-info/RECORD'):
        rows = []
        with record.open(newline='') as stream:
            installed_records = list(csv.reader(stream))
        for filename, sha, length in installed_records:
            path = site / filename
            if filename.endswith('/direct_url.json'):
                path.unlink(missing_ok=True)
                continue
            if path.is_file() and path != record:
                sha = 'sha256=' + base64.urlsafe_b64encode(bytes.fromhex(digest(path))).decode().rstrip('=')
                length = str(path.stat().st_size)
            rows.append([filename, sha, length])
            if filename.startswith('../../../bin/') and Path(filename).name in rewritten:
                body = rewritten[Path(filename).name]
                rows.append([os.path.relpath(body, site), 'sha256=' + base64.urlsafe_b64encode(bytes.fromhex(digest(body))).decode().rstrip('='), str(body.stat().st_size)])
        with record.open('w', newline='') as stream:
            csv.writer(stream).writerows(rows)
    (destination / 'run_suite.py').write_text('from localpilot_suite.cli import main\nraise SystemExit(main())\n')
    (destination / 'localpilot').write_text('#!/bin/sh\nset -eu\nLP_BUNDLE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexport PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1\nunset PYTHONHOME PYTHONPATH\nexec "$LP_BUNDLE_ROOT/runtime/bin/python" "$LP_BUNDLE_ROOT/run_suite.py" "$@"\n')
    (destination / 'localpilot').chmod(0o755)
    shutil.copyfile(args.dependency_lock, destination / 'runtime-dependencies.json')
    node_archive = None
    if args.channel_runtime:
        sys.path.insert(0, str(ROOT.parent / 'suite'))
        from localpilot_suite.channel_runtime import runtime_archive
        filename, expected_hash = runtime_archive('Linux', info['architecture'])
        if args.channel_runtime.name != filename or digest(args.channel_runtime) != expected_hash:
            raise ValueError('Pinned Linux Node runtime mismatch')
        channel = destination / 'channel-runtime'
        channel.mkdir()
        shutil.copyfile(args.channel_runtime, channel / filename)
        node_archive = {'filename': filename, 'sha256': expected_hash}
    manifest = {'kind': 'OFFLINE_INDEPENDENT_MODULES', 'system': 'Linux',
                'architecture': info['architecture'], 'python': info['minor'],
                'python_runtime': 'distribution', 'python_executable': str(executable),
                'python_debian_dependency': 'python' + info['minor'],
                'python_version_at_build': info['version'], 'weights_bundled': False,
                'credentials_bundled': False, 'wheels': sorted(path.name for path in inputs.values()),
                'channel_runtime': node_archive,
                'dependency_lock_sha256': digest(destination / 'runtime-dependencies.json')}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    subprocess.run([str(python), '-m', 'compileall', '-q', '-f', '--invalidation-mode', 'checked-hash', '-s', str(runtime), '-p', '/LocalPilot/Python', str(site)], env=env, check=True)
    return check(destination)


def check(root):
    manifest = json.loads((root / 'manifest.json').read_text())
    info = interpreter(Path(manifest['python_executable']))
    if manifest['system'] != 'Linux' or manifest['python'] != info['minor'] or manifest['architecture'] != info['architecture']:
        raise ValueError('Installed distribution Python does not match the resource')
    lock_path = root / 'runtime-dependencies.json'
    if digest(lock_path) != manifest['dependency_lock_sha256']:
        raise ValueError('Bundled dependency lock changed')
    lock = json.loads(lock_path.read_text())
    site = root / f'runtime/lib/python{info["minor"]}/site-packages'
    expected, hashes, verified, owners = {}, {}, {}, {}
    wheels = sorted((root / 'wheels').glob('*.whl'))
    if [wheel.name for wheel in wheels] != manifest['wheels']:
        raise ValueError('Resource wheel inventory changed')
    for wheel in wheels:
        name, version = wheel_info(wheel)
        hashes[wheel.name] = digest(wheel)
        if name in expected or name not in COMPONENTS and name not in lock['packages']:
            raise ValueError('Unexpected or duplicate distribution')
        expected[name] = version
        if name in lock['packages']:
            item = lock['packages'][name]
            if item['version'] != version or item['wheel'] != wheel.name or item['sha256'] != hashes[wheel.name]:
                raise ValueError('Runtime dependency differs from lock: ' + name)
        else:
            config, prefix = COMPONENTS[name]
            if tomllib.loads((ROOT.parent / config).read_text())['project']['version'] != version:
                raise ValueError('Component differs from current version: ' + name)
            count, code_hash = 0, hashlib.sha256()
            with zipfile.ZipFile(wheel) as archive:
                for filename in sorted(archive.namelist()):
                    if not filename.endswith(('.py', '.swift')) or '.data/' in filename or '.dist-info/' in filename:
                        continue
                    if filename in owners:
                        raise ValueError('Independent component code overlaps: ' + filename)
                    owners[filename] = name
                    payload = archive.read(filename)
                    if (ROOT.parent / prefix / filename).read_bytes() != payload or (site / filename).read_bytes() != payload:
                        raise ValueError('Installed component differs from current source: ' + filename)
                    code_hash.update(filename.encode() + b'\0' + payload)
                    count += 1
            verified[name] = {'source_files': count, 'sha256': code_hash.hexdigest()}
    if set(expected) != set(COMPONENTS) | set(lock['packages']):
        raise ValueError('Missing component or dependency')
    if manifest.get('channel_runtime'):
        node = manifest['channel_runtime']
        sys.path.insert(0, str(ROOT.parent / 'suite'))
        from localpilot_suite.channel_runtime import runtime_archive
        filename, expected_hash = runtime_archive('Linux', info['architecture'])
        if node != {'filename': filename, 'sha256': expected_hash} or digest(root / 'channel-runtime' / filename) != expected_hash:
            raise ValueError('Bundled Node runtime differs from the reviewed official archive')
    actual = json.loads(subprocess.check_output([str(root / 'localpilot'), '--version'], text=True))
    for name in COMPONENTS:
        key = 'suite' if name == 'localpilot-suite' else name
        if actual.get(key) != expected[name]:
            raise ValueError('Installed component version mismatch: ' + name)
    result = {'passed': True, 'system': 'Linux', 'architecture': info['architecture'],
              'python': info['minor'], 'python_runtime': 'distribution',
              'actual_module_versions': actual, 'expected_wheel_versions': expected,
              'channel_runtime': manifest.get('channel_runtime'),
              'verified_code': verified, 'wheel_hashes': hashes}
    (root / 'verified-modules.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['lock', 'prepare', 'check'])
    parser.add_argument('--output', type=Path, default=ROOT / 'src-tauri/bundled-backends')
    parser.add_argument('--python', type=Path, default=Path('/usr/bin/python3'))
    parser.add_argument('--wheels', type=Path)
    parser.add_argument('--dependencies', type=Path)
    parser.add_argument('--dependency-lock', type=Path)
    parser.add_argument('--channel-runtime', type=Path)
    parser.add_argument('--pip-version', default='25.0.1')
    args = parser.parse_args()
    if args.operation == 'prepare' and any(getattr(args, name) is None for name in ('wheels', 'dependencies', 'dependency_lock')):
        parser.error('prepare requires --wheels, --dependencies and --dependency-lock')
    if args.operation == 'lock' and (args.dependencies is None or args.dependency_lock is None):
        parser.error('lock requires --dependencies and --dependency-lock')
    result = lock_dependencies(args) if args.operation == 'lock' else prepare(args) if args.operation == 'prepare' else check(args.output.resolve())
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
