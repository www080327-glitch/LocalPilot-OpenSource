"""Architecture checks shared by the native build and offline runtime packagers."""
import json
from pathlib import Path
import subprocess
from functools import lru_cache

from packaging.tags import compatible_tags, cpython_tags, mac_platforms
from packaging.utils import InvalidWheelFilename, parse_wheel_filename


def architecture(value):
    aliases = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'x86_64', 'amd64': 'x86_64'}
    try:
        return aliases[value.lower()]
    except KeyError:
        raise ValueError('Only macOS arm64 and x86_64 artifacts are supported') from None


@lru_cache(maxsize=2)
def runtime_tags(arch):
    platforms = tuple(mac_platforms(version=(15, 0), arch=arch))
    return tuple(dict.fromkeys([
        *cpython_tags(python_version=(3, 14), abis=['cp314'], platforms=platforms),
        *compatible_tags(python_version=(3, 14), interpreter='cp314', platforms=platforms),
    ]))


def wheel_supports(filename, arch):
    try:
        tags = parse_wheel_filename(filename)[3]
    except InvalidWheelFilename:
        return False
    return not tags.isdisjoint(runtime_tags(arch))


def runtime_lock(path, arch):
    lock = json.loads(Path(path).read_text())
    if lock.get('python') != '3.14' or not isinstance(lock.get('packages'), dict):
        raise ValueError('Python 3.14 runtime dependency lock required')
    if lock.get('architecture', arch) != arch:
        raise ValueError('Runtime lock belongs to a different architecture')
    for name, row in lock['packages'].items():
        if not wheel_supports(row['wheel'], arch):
            raise ValueError(f'{name} has no {arch} wheel in this lock; generate and review a target architecture lock')
    return lock


def bundled_runtime_lock(root, arch, override=None):
    bundled = root / 'runtime-dependencies.json'
    path = root.parents[1] / 'runtime-dependencies.json'
    if override is not None:
        path = Path(override)
    elif bundled.exists():
        path = bundled
    return runtime_lock(path, arch)


def verify_macho(path, arch):
    supported = subprocess.check_output(['/usr/bin/lipo', '-archs', str(path)], text=True).split()
    if arch not in supported:
        raise ValueError(f'{Path(path).name} does not contain the required {arch} executable')
    return supported
