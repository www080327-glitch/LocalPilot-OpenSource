"""Linux launchers for the existing Shell and host assertion contracts."""
from pathlib import Path
import shutil
import sys
import tempfile


def shell_launcher(command, workspace, mode):
    launcher = _base() + ['--ro-bind', '/', '/', '--proc', '/proc',
                          '--remount-ro', '/proc', '--dev', '/dev']
    if mode == 'workspace':
        roots = {Path(workspace).resolve(), Path(tempfile.gettempdir()).resolve(), Path('/tmp').resolve()}
        for root in sorted(roots):
            launcher += ['--bind', str(root), str(root)]
    return launcher + ['--', *command]


def acceptance_launcher(command, workspace, assertions):
    unshare = shutil.which('unshare')
    if not unshare:
        raise ValueError('Linux host assertions require util-linux unshare for a network-free namespace')
    # No loopback is configured: assertions cannot contact even a local service.
    launcher = [unshare, '--user', '--map-root-user', '--net', '--', *_base(),
                '--proc', '/proc', '--remount-ro', '/proc', '--dev', '/dev']
    roots = {Path(p).resolve() for p in ('/usr', '/bin', '/lib', '/lib64', sys.base_prefix)
             if Path(p).exists()}
    for root in sorted(roots):
        launcher += ['--ro-bind', str(root), str(root)]
    # Preserve the host's loader aliases without exposing /etc or the user's home.
    for alias in ('/bin', '/lib', '/lib64'):
        path = Path(alias)
        if path.is_symlink():
            launcher += ['--symlink', str(path.readlink()), alias]
    for path in (Path('/etc/ld.so.cache'), Path(command[0]), Path(workspace), Path(assertions)):
        if path.exists():
            launcher += ['--ro-bind', str(path), str(path)]
    return launcher + ['--', *command]


def _base():
    binary = shutil.which('bwrap')
    if not binary:
        raise ValueError('Linux scoped Shell and host assertions require bubblewrap; install bwrap or explicitly select Full permission')
    # A private PID namespace lets killing the existing process group also reap
    # command descendants. Network stays available unless the caller disables it.
    return [binary, '--die-with-parent', '--unshare-user', '--unshare-pid',
            '--disable-userns', '--cap-drop', 'ALL']
