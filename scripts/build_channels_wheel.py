"""Build the optional distribution from a clean staging tree, without account state."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    repo = Path(__file__).resolve().parents[1]
    out = Path(a.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='localpilot-channel-build-') as directory:
        stage = Path(directory)
        shutil.copy2(repo / 'channels/pyproject.toml', stage / 'pyproject.toml')
        package = stage / 'localpilot_channels'
        package.mkdir()
        for source in (repo / 'localpilot_channels').glob('*.py'):
            if source.is_symlink():
                raise ValueError('Linked source rejected')
            shutil.copy2(source, package / source.name)
        # Explicit transport source/license files only; never recursive state.
        for kind, files in {
            'qq-bridge': ('bridge.mjs', 'cli.mjs', 'gateway.mjs', 'package.json'),
            'wechat-ilink-bridge': ('bridge.mjs', 'cli.mjs', 'package.json', 'THIRD_PARTY_NOTICES.md'),
            'channel-common': ('security.mjs', 'evidence.mjs', 'control.mjs'),
        }.items():
            target = stage / 'integrations' / kind
            target.mkdir(parents=True)
            for name in files:
                source = repo / 'integrations' / kind / name
                if source.is_symlink():
                    raise ValueError('Linked source rejected')
                shutil.copy2(source, target / name)
        subprocess.run([sys.executable, '-m', 'build', '--wheel', '--outdir', str(out), str(stage)], check=True)


if __name__ == '__main__':
    main()
