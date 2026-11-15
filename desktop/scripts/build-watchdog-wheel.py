"""Build the reviewed watchdog wheel from the official 6.0.0 source archive."""
import argparse
import hashlib
from importlib.metadata import version
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import json
import platform
import zipfile

from macos_artifacts import verify_macho

SOURCE_SHA256 = '9ddf7c82fda3ae8e24decda1338ede66e1c99883db93711d8fb941eaa2d8c282'
WHEEL_NAME = 'watchdog-6.0.0-cp314-cp314-macosx_10_15_universal2.whl'
WHEEL_SHA256 = 'c1d1d020f564cdec2ea437ff1304e47c182fe19d4310d3eb0923c33158025ab5'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--arch', choices=['x86_64'])
    args = parser.parse_args()
    if sys.platform != 'darwin' or sys.version_info[:3] != (3, 14, 6):
        raise SystemExit('Requires reviewed macOS Python 3.14.6')
    if args.arch and platform.machine() != args.arch:
        raise SystemExit('Use a Python process running as the selected architecture')
    for name, expected in {'setuptools': '84.2.0', 'wheel': '0.48.0', 'packaging': '26.3'}.items():
        if version(name) != expected:
            raise SystemExit(f'Requires {name}=={expected}')
    if hashlib.sha256(args.source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise SystemExit('Watchdog source archive hash mismatch')
    name = 'watchdog-6.0.0-cp314-cp314-macosx_10_15_x86_64.whl' if args.arch else WHEEL_NAME
    destination = args.out / name
    if destination.exists():
        raise SystemExit('Existing wheel preserved; choose a fresh output directory')
    with tempfile.TemporaryDirectory(prefix='localpilot-watchdog-build-') as temp:
        root = Path(temp)
        with tarfile.open(args.source, 'r:gz') as source:
            source.extractall(root, filter='data')
        env = dict(os.environ, SOURCE_DATE_EPOCH='1730419200', PYTHONHASHSEED='0', CFLAGS='-g0')
        if args.arch:
            env.update(ARCHFLAGS='-arch x86_64', MACOSX_DEPLOYMENT_TARGET='10.15')
        command = [sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation',
                   '--no-cache-dir', '--wheel-dir', str(root / 'wheel'),
                   str(root / 'watchdog-6.0.0')]
        if args.arch:
            # The framework's configured universal2 tag can survive ARCHFLAGS.
            command.append('--config-settings=--build-option=--plat-name=macosx_10_15_x86_64')
        subprocess.run(command, env=env, check=True)
        wheel = root / 'wheel' / name
        if args.arch:
            with zipfile.ZipFile(wheel) as archive:
                binaries = [member for member in archive.namelist() if member.endswith('.so')]
                if not binaries:
                    raise SystemExit('Native watchdog extension missing')
                for index, member in enumerate(binaries):
                    binary = root / ('native-' + str(index))
                    binary.write_bytes(archive.read(member))
                    verify_macho(binary, args.arch)
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        if not args.arch and digest != WHEEL_SHA256:
            raise SystemExit('Built wheel differs from reviewed hash; preserve the lock and investigate the toolchain')
        args.out.mkdir(parents=True, exist_ok=True)
        with wheel.open('rb') as src, destination.open('xb') as dst:
            shutil.copyfileobj(src, dst)
    if args.arch:
        record = {
            'kind': 'CONTROLLED_NATIVE_SOURCE_BUILD', 'source_sha256': SOURCE_SHA256,
            'wheel': name, 'sha256': digest, 'architecture': args.arch,
            'python': platform.python_version(),
            'build_tools': {tool:version(tool) for tool in ['setuptools','wheel','packaging']},
            'compiler': subprocess.check_output(['xcrun','clang','--version'], text=True).strip(),
            'sdk': subprocess.check_output(['xcrun','--show-sdk-version'], text=True).strip(),
            'runtime_qualification': 'NOT_RUN',
        }
        with (args.out/'watchdog-build.json').open('x') as stream:
            json.dump(record, stream, indent=2)
            stream.write('\n')
    print(f'{digest}  {destination}')


if __name__ == '__main__':
    main()
