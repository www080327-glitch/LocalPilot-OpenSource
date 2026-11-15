"""Record exact runtime wheels; --download fetches fixed versions from official PyPI."""
import argparse
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import zipfile
import importlib.util
import subprocess
import sys
import urllib.request
from urllib.parse import urlsplit

from packaging.specifiers import SpecifierSet
from packaging.utils import parse_wheel_filename

from macos_artifacts import architecture, runtime_tags, wheel_supports

SOURCE_BUILDS = {
    'watchdog': ('6.0.0', '9ddf7c82fda3ae8e24decda1338ede66e1c99883db93711d8fb941eaa2d8c282'),
    'cryptography': ('50.0.2', '7b46165bb56eb4704e2eaaf86f3c940d19154535d9b0ca7d6d590b04060e00d5'),
}


def create_lock(directory, base, arch):
    packages = {}
    for path in sorted(directory.glob('*.whl')):
        with zipfile.ZipFile(path) as wheel:
            metadata = [name for name in wheel.namelist() if name.endswith('.dist-info/METADATA')]
            if len(metadata) != 1:
                raise ValueError('Exactly one distribution metadata record is required')
            info = Parser().parsestr(wheel.read(metadata[0]).decode())
        name = info['Name'].lower().replace('_', '-')
        if name not in base['packages']:
            raise ValueError('Unexpected dependency: ' + name)
        if name in packages or info['Version'] != base['packages'][name]['version']:
            raise ValueError('Duplicate dependency or version differs from reviewed baseline: ' + name)
        if not wheel_supports(path.name, arch):
            raise ValueError('Wheel does not support ' + arch + ': ' + path.name)
        if info['Requires-Python'] and '3.14.6' not in SpecifierSet(info['Requires-Python']):
            raise ValueError('Wheel does not support Python 3.14.6: ' + path.name)
        packages[name] = dict(base['packages'][name], wheel=path.name,
                              sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    if packages.keys() != base['packages'].keys():
        raise ValueError('Missing dependencies: ' + ', '.join(sorted(base['packages'].keys() - packages.keys())))
    return {'schema': 2, 'python': '3.14', 'architecture': arch,
            'minimum_macos': '15.0',
            'provenance': 'LOCAL_ARTIFACT_HASHES_SOURCE_REVIEW_REQUIRED', 'packages': packages}


def select_wheel(files, arch):
    ranks = {tag:index for index,tag in enumerate(runtime_tags(arch))}
    matches = []
    for row in files:
        if row['packagetype'] != 'bdist_wheel' or row.get('yanked'):
            continue
        filename = row['filename']
        if not wheel_supports(filename, arch):
            continue
        if row.get('requires_python') and '3.14.6' not in SpecifierSet(row['requires_python']):
            continue
        rank = min(ranks[tag] for tag in parse_wheel_filename(filename)[3] if tag in ranks)
        matches.append((rank,filename,row))
    return min(matches, key=lambda item:item[:2])[2] if matches else None


def fetch_artifact(row, directory):
    url = urlsplit(row['url'])
    filename, expected = row['filename'], row['digests']['sha256']
    if url.scheme != 'https' or url.hostname != 'files.pythonhosted.org' or Path(filename).name != filename:
        raise ValueError('Official PyPI artifact URL and filename required')
    target = directory / filename
    if not target.exists():
        with urllib.request.urlopen(row['url'], timeout=30) as source, target.open('xb') as output:
            while block := source.read(1024 * 1024):
                output.write(block)
    if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
        raise ValueError('Artifact hash mismatch; preserved for inspection: ' + filename)
    return {'filename':filename, 'url':row['url'], 'sha256':expected, 'bytes':target.stat().st_size}


def download_dependencies(directory, base, arch, openssl_dir=None, openssl_license=None):
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {'architecture':arch, 'python':'3.14.6', 'files':[], 'status':'DOWNLOADING'}
    pending = []
    for name, dependency in base['packages'].items():
        metadata_url = f"https://pypi.org/pypi/{name}/{dependency['version']}/json"
        with urllib.request.urlopen(metadata_url, timeout=30) as response:
            files = json.load(response)['urls']
        selected = select_wheel(files, arch)
        if selected is None:
            reviewed = SOURCE_BUILDS.get(name)
            if reviewed is None or dependency['version'] != reviewed[0]:
                raise ValueError('No compatible fixed-version wheel: ' + name)
            selected = next(row for row in files if row['filename'] == f'{name}-{reviewed[0]}.tar.gz')
            if selected['digests']['sha256'] != reviewed[1] or selected.get('yanked'):
                raise ValueError('Native dependency source differs from reviewed source: ' + name)
            pending.append((name, directory / selected['filename']))
        row = fetch_artifact(selected, directory)
        row['metadata_url'] = metadata_url
        row['distribution'] = name
        manifest['files'].append(row)
        (directory/'download-record.json').write_text(json.dumps(manifest,indent=2)+'\n')
    manifest['native_builds'] = {}
    manifest['pending_native_builds'] = []
    for name, source in pending:
        spec = importlib.util.spec_from_file_location(name+'_builder', Path(__file__).with_name('build-'+name+'-wheel.py'))
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        existing = directory / builder.WHEEL_NAME if name == 'watchdog' else None
        if existing and existing.is_file() and hashlib.sha256(existing.read_bytes()).hexdigest() == builder.WHEEL_SHA256:
            manifest['native_builds'][name] = {'wheel':existing.name, 'sha256':builder.WHEEL_SHA256, 'source_sha256':builder.SOURCE_SHA256}
        elif (directory/(name+'-build.json')).is_file():
            manifest['native_builds'][name] = read_build_record(directory, name, arch)
        elif sys.platform == 'darwin':
            command = [sys.executable, str(Path(__file__).with_name('build-'+name+'-wheel.py')),
                       '--source',str(source),'--out',str(directory)]
            if name == 'watchdog' and arch == 'x86_64':
                command += ['--arch','x86_64']
            if name == 'cryptography':
                if arch != 'x86_64' or not openssl_dir or not openssl_license:
                    raise ValueError('Intel cryptography build requires --openssl-dir and --openssl-license; see INTEL_MAC_20261116.md')
                command += ['--openssl-dir', str(openssl_dir), '--openssl-license', str(openssl_license)]
            subprocess.run(command, check=True)
            manifest['native_builds'][name] = read_build_record(directory, name, arch) if arch == 'x86_64' else {
                'wheel':builder.WHEEL_NAME, 'sha256':builder.WHEEL_SHA256, 'source_sha256':builder.SOURCE_SHA256}
        else:
            manifest['pending_native_builds'].append(name)
    manifest['status'] = 'NEEDS_NATIVE_SOURCE_BUILDS' if manifest['pending_native_builds'] else 'ARTIFACTS_VERIFIED_RUNTIME_NOT_RUN'
    (directory/'download-record.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def read_build_record(directory, name, arch):
    record = json.loads((directory/(name+'-build.json')).read_text())
    filename = record.get('wheel', '')
    candidate = directory/filename
    if (record.get('kind') != 'CONTROLLED_NATIVE_SOURCE_BUILD' or record.get('architecture') != arch
            or record.get('source_sha256') != SOURCE_BUILDS[name][1] or Path(filename).name != filename
            or not wheel_supports(filename, arch) or not candidate.is_file()
            or hashlib.sha256(candidate.read_bytes()).hexdigest() != record.get('sha256')):
        raise ValueError('Native build record does not match the source and target wheel: ' + name)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheels', type=Path, required=True)
    parser.add_argument('--base-lock', type=Path, default=Path(__file__).resolve().parents[1] / 'runtime-dependencies.json')
    parser.add_argument('--arch', required=True, choices=['arm64', 'x86_64'])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--download', action='store_true', help='Fetch fixed-version target wheels from official PyPI and build reviewed missing native wheels on macOS')
    parser.add_argument('--openssl-dir', type=Path, help='Intel static OpenSSL prefix for cryptography source build')
    parser.add_argument('--openssl-license', type=Path, help='License belonging to that OpenSSL build')
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit('Existing lock preserved; choose a fresh output path')
    base = json.loads(args.base_lock.read_text())
    sources = download_dependencies(args.wheels, base, args.arch, args.openssl_dir, args.openssl_license) if args.download else None
    if sources and sources['status'] == 'NEEDS_NATIVE_SOURCE_BUILDS':
        print(json.dumps({'status':sources['status'], 'record':str(args.wheels/'download-record.json'),
                          'pending':sources['pending_native_builds'], 'lock_created':False,
                          'next':'Run the same command on target macOS Python 3.14.6 with the documented build tools and OpenSSL inputs'}))
        return
    lock = create_lock(args.wheels, base, architecture(args.arch))
    if sources:
        lock['provenance'] = 'OFFICIAL_PYPI_HASHES_AND_CONTROLLED_NATIVE_SOURCE_BUILDS'
        lock['sources'] = sources
    with args.out.open('x') as stream:
        json.dump(lock, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'lock': str(args.out), 'architecture': args.arch,
                      'packages': len(lock['packages']), 'source_review': 'REQUIRED'}))


if __name__ == '__main__':
    main()
