"""Create a normal macOS APP ZIP and verify ordinary extraction independently.

FileProvider-managed Desktop folders can acquire FinderInfo after extraction.
Verification uses a fresh system temporary directory, never removes attributes,
never changes quarantine, and never changes Gatekeeper policy.
"""
from pathlib import Path
import argparse
import subprocess
import tempfile


def archive(app, output):
    if not app.is_dir() or app.is_symlink() or output.exists():
        raise ValueError('Use an existing generated APP and a new archive path')
    for path in app.rglob('*'):
        if path.is_symlink() and not path.resolve().is_relative_to(app):
            raise ValueError('External bundle link rejected')
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True)
    subprocess.run(['/usr/bin/ditto','-c','-k','--keepParent','--norsrc','--noextattr',str(app),str(output)],check=True)
    with tempfile.TemporaryDirectory(prefix='localpilot-archive-verify-',dir='/private/tmp') as folder:
        subprocess.run(['/usr/bin/ditto','-xk',str(output),folder],check=True)
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(Path(folder)/app.name)],check=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('app');p.add_argument('output');a=p.parse_args()
    archive(Path(a.app).resolve(strict=True),Path(a.output).resolve())
