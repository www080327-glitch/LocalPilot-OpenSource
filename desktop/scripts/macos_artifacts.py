"""Architecture checks shared by the native build and offline runtime packagers."""
import json
from pathlib import Path
import subprocess


def architecture(value):
    aliases = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'x86_64', 'amd64': 'x86_64'}
    try:
        return aliases[value.lower()]
    except KeyError:
        raise ValueError('Only macOS arm64 and x86_64 artifacts are supported') from None


def wheel_supports(filename, arch):
    platforms = filename.removesuffix('.whl').rsplit('-', 1)[-1].split('.')
    return any(value == 'any' or value.startswith('macosx_') and
               (value.endswith('_' + arch) or value.endswith('_universal2')) for value in platforms)


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


def verify_macho(path, arch):
    supported = subprocess.check_output(['/usr/bin/lipo', '-archs', str(path)], text=True).split()
    if arch not in supported:
        raise ValueError(f'{Path(path).name} does not contain the required {arch} executable')
    return supported
