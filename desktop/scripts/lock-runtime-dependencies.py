"""Record exact local dependency wheels for an architecture; never downloads artifacts."""
import argparse
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import zipfile

from macos_artifacts import architecture, wheel_supports


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
        packages[name] = dict(base['packages'][name], wheel=path.name,
                              sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    if packages.keys() != base['packages'].keys():
        raise ValueError('Missing dependencies: ' + ', '.join(sorted(base['packages'].keys() - packages.keys())))
    return {'schema': 2, 'python': '3.14', 'architecture': arch,
            'provenance': 'LOCAL_ARTIFACT_HASHES_SOURCE_REVIEW_REQUIRED', 'packages': packages}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheels', type=Path, required=True)
    parser.add_argument('--base-lock', type=Path, default=Path(__file__).resolve().parents[1] / 'runtime-dependencies.json')
    parser.add_argument('--arch', required=True, choices=['arm64', 'x86_64'])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    lock = create_lock(args.wheels, json.loads(args.base_lock.read_text()), architecture(args.arch))
    with args.out.open('x') as stream:
        json.dump(lock, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'lock': str(args.out), 'architecture': args.arch,
                      'packages': len(lock['packages']), 'source_review': 'REQUIRED'}))


if __name__ == '__main__':
    main()
