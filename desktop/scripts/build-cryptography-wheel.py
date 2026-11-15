"""Build the fixed cryptography source for native Intel macOS with static OpenSSL."""
import argparse
from email.parser import Parser
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

from macos_artifacts import verify_macho, wheel_supports

SOURCE_NAME = 'cryptography-50.0.2.tar.gz'
SOURCE_SHA256 = '7b46165bb56eb4704e2eaaf86f3c940d19154535d9b0ca7d6d590b04060e00d5'
BUILD_TOOLS = {'maturin': '1.14.1', 'setuptools': '84.2.0', 'cffi': '2.1.1',
               'pycparser': '3.12', 'wheel': '0.48.0', 'packaging': '26.3'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--openssl-dir', type=Path, required=True)
    parser.add_argument('--openssl-license', type=Path, required=True)
    args = parser.parse_args()
    openssl = validate_build_inputs(args)
    with tempfile.TemporaryDirectory(prefix='localpilot-cryptography-build-') as temp:
        root = Path(temp)
        with tarfile.open(args.source, 'r:gz') as source:
            source.extractall(root, filter='data')
        source_root = root / 'cryptography-50.0.2'
        env = dict(os.environ, SOURCE_DATE_EPOCH='1730419200', PYTHONHASHSEED='0',
                   CARGO_BUILD_TARGET='x86_64-apple-darwin', CARGO_BUILD_JOBS='1',
                   ARCHFLAGS='-arch x86_64', MACOSX_DEPLOYMENT_TARGET='15.0',
                   OPENSSL_DIR=str(args.openssl_dir.resolve()), OPENSSL_STATIC='1',
                   OPENSSL_NO_VENDOR='1')
        # The reviewed source sets maturin locked=true and carries Cargo.lock.
        subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps',
                        '--no-build-isolation', '--no-cache-dir', '--wheel-dir', str(root/'wheels'),
                        str(source_root)], env=env, check=True)
        built = list((root/'wheels').glob('cryptography-50.0.2-*.whl'))
        if len(built) != 1 or not wheel_supports(built[0].name, 'x86_64'):
            raise ValueError('Expected exactly one compatible CPython 3.14 Intel macOS wheel')
        validate_binaries(built[0], root/'binaries')
        final = root/'with-license'/built[0].name
        bundle_openssl_license(built[0], final, args.openssl_license.read_bytes())
        record = {
            'kind': 'CONTROLLED_NATIVE_SOURCE_BUILD', 'architecture': 'x86_64',
            'source': SOURCE_NAME, 'source_sha256': SOURCE_SHA256,
            'wheel': final.name, 'sha256': hashlib.sha256(final.read_bytes()).hexdigest(),
            'python': platform.python_version(), 'build_tools': BUILD_TOOLS,
            'pip': version('pip'), 'openssl': openssl,
            'cargo_lock_sha256': hashlib.sha256((source_root/'Cargo.lock').read_bytes()).hexdigest(),
            'rust': subprocess.check_output(['rustc', '--version'], text=True).strip(),
            'cargo': subprocess.check_output(['cargo', '--version'], text=True).strip(),
            'compiler': subprocess.check_output(['xcrun', 'clang', '--version'], text=True).strip(),
            'sdk': subprocess.check_output(['xcrun', '--show-sdk-version'], text=True).strip(),
            'runtime_qualification': 'NOT_RUN',
        }
        args.out.mkdir(parents=True, exist_ok=True)
        with final.open('rb') as source, (args.out/final.name).open('xb') as target:
            shutil.copyfileobj(source, target)
        with (args.out/'cryptography-build.json').open('x') as stream:
            json.dump(record, stream, indent=2)
            stream.write('\n')
    print(json.dumps(record, indent=2))


def validate_build_inputs(args):
    if sys.platform != 'darwin' or platform.machine() != 'x86_64' or sys.version_info[:3] != (3, 14, 6):
        raise ValueError('Requires native Intel macOS CPython 3.14.6')
    if (args.out/'cryptography-build.json').exists() or list(args.out.glob('cryptography-*.whl')):
        raise ValueError('Existing cryptography output preserved; choose a fresh output directory')
    if args.source.name != SOURCE_NAME or hashlib.sha256(args.source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError('Cryptography source archive differs from the reviewed PyPI source')
    for name, expected in BUILD_TOOLS.items():
        if version(name) != expected:
            raise ValueError(f'Requires {name}=={expected}')
    libraries = {}
    for name in ('libssl.a', 'libcrypto.a'):
        path = args.openssl_dir/'lib'/name
        verify_macho(path, 'x86_64')
        libraries[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    license_text = args.openssl_license.read_bytes()
    if not license_text.strip():
        raise ValueError('The license belonging to the linked OpenSSL build is required')
    return {'version': subprocess.check_output([str(args.openssl_dir/'bin/openssl'), 'version'], text=True).strip(),
            'static_libraries_sha256': libraries,
            'license_sha256': hashlib.sha256(license_text).hexdigest()}


def validate_binaries(wheel, directory):
    directory.mkdir()
    with zipfile.ZipFile(wheel) as archive:
        binaries = [name for name in archive.namelist() if name.endswith(('.so', '.dylib'))]
        if not binaries:
            raise ValueError('Compiled cryptography binding missing')
        for index, name in enumerate(binaries):
            path = directory/str(index)
            path.write_bytes(archive.read(name))
            verify_macho(path, 'x86_64')
            listing = subprocess.check_output(['otool', '-L', str(path)], text=True)
            for line in listing.splitlines()[1:]:
                dependency = line.strip().split(' (')[0]
                if not dependency.startswith(('/usr/lib/', '/System/Library/')):
                    raise ValueError('Non-system dynamic library prevents offline relocation: ' + dependency)


def bundle_openssl_license(source, target, license_text):
    from wheel.wheelfile import WheelFile
    target.parent.mkdir(parents=True)
    with zipfile.ZipFile(source) as archive:
        metadata = next(name for name in archive.namelist() if name.endswith('.dist-info/METADATA'))
        dist_info = metadata.rsplit('/', 1)[0]
        info = Parser().parsestr(archive.read(metadata).decode())
        info['License-File'] = 'OPENSSL.txt'
        with WheelFile(target, 'w') as output:
            for name in archive.namelist():
                if name.endswith('.dist-info/RECORD'):
                    continue
                entry = archive.getinfo(name)
                entry.date_time = (2024, 11, 1, 0, 0, 0)
                output.writestr(entry, info.as_bytes() if name == metadata else archive.read(name))
            license_entry = zipfile.ZipInfo(dist_info+'/licenses/OPENSSL.txt', (2024, 11, 1, 0, 0, 0))
            output.writestr(license_entry, license_text)


if __name__ == '__main__':
    main()
