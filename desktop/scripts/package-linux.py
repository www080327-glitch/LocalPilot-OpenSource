"""Archive and inspect the just-built DEB without installing it."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile


def restore_distribution_python(candidate, destination, staging, product, manifest):
    package_root = staging / 'package'
    subprocess.run(['dpkg-deb', '--raw-extract', str(candidate), str(package_root)], check=True)
    runtime = package_root / 'usr/lib' / product / 'bundled-backends/runtime'
    system_python = Path(manifest['python_executable'])
    expected = hashlib.sha256(system_python.read_bytes()).hexdigest()
    # Tauri dereferences resource symlinks; retain the distribution interpreter
    # dependency instead of shipping three unmaintained copies of /usr/bin/python.
    for name in ('python', 'python3', 'python' + manifest['python']):
        entry = runtime / 'bin' / name
        if hashlib.sha256(entry.read_bytes()).hexdigest() != expected:
            raise SystemExit('Tauri resource Python differs from the selected distribution interpreter')
        entry.unlink()
        entry.symlink_to(system_python)
    sums = []
    for path in sorted(package_root.rglob('*')):
        relative = path.relative_to(package_root)
        if relative.parts[0] != 'DEBIAN' and path.is_file() and not path.is_symlink():
            sums.append(f'{hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()}  {relative}\n')
    (package_root / 'DEBIAN/md5sums').write_text(''.join(sums))
    installed_kib = int(subprocess.check_output(['du', '-sk', '--exclude=DEBIAN', str(package_root)], text=True).split()[0])
    control = package_root / 'DEBIAN/control'
    control.write_text(''.join(f'Installed-Size: {installed_kib}\n' if line.startswith('Installed-Size:') else line for line in control.read_text().splitlines(keepends=True)))
    subprocess.run(['dpkg-deb', '-Zgzip', '--root-owner-group', '--build', str(package_root), str(destination)], check=True)
    return {'distribution_python': str(system_python), 'interpreter_symlinks': 3, 'installed_size_kib': installed_kib}


root = Path(__file__).resolve().parents[1]
out = Path(os.environ['LP_GUI_OUTPUT'])
config = json.loads((out / 'build-config.json').read_text())
base = json.loads((root / 'src-tauri/tauri.conf.json').read_text())
version = base['version']
test = config.get('identifier') == 'io.localpilot.desktop.test'
product = config.get('productName', base['productName'])
arch = platform.machine()
debian_arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}[arch]
package_name = 'local-pilot-test' if test else 'local-pilot'
target = Path(os.environ['CARGO_TARGET_DIR'])
matches = []
for candidate in (target / 'release/bundle/deb').glob('*.deb'):
    metadata = subprocess.check_output(['dpkg-deb', '-f', str(candidate), 'Package', 'Version', 'Architecture', 'Depends'], text=True)
    fields = dict(line.split(': ', 1) for line in metadata.strip().splitlines())
    if (fields.get('Package') == package_name and fields.get('Architecture') == debian_arch
            and fields.get('Version') == version):
        matches.append((candidate, fields))
if len(matches) != 1:
    raise SystemExit('Expected exactly one DEB for this application identity, version and architecture')
candidate, fields = matches[0]
tauri_input = {'artifact': candidate.name, 'sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(), 'bytes': candidate.stat().st_size}
manifest = json.loads((root / 'src-tauri/bundled-backends/manifest.json').read_text())
if manifest['python_debian_dependency'] not in fields.get('Depends', '').split(', '):
    raise SystemExit('DEB does not require the distribution Python minor used by its wheels')
asset_arch = 'arm64' if arch == 'aarch64' else arch
name = f'LocalPilot{"-Test" if test else ""}-{version}-linux-{asset_arch}.deb'
delivery = out / name
if delivery.exists():
    raise SystemExit('Existing delivery preserved')
with tempfile.TemporaryDirectory(prefix='localpilot-deb-inspect-', dir=target) as staging:
    normalization = restore_distribution_python(candidate, delivery, Path(staging), product, manifest)
    extracted = Path(staging) / 'extracted with spaces'
    subprocess.run(['dpkg-deb', '-x', str(delivery), str(extracted)], check=True)
    executable = extracted / 'usr/bin' / ('localpilot-desktop-test' if test else 'localpilot-desktop')
    with executable.open('rb') as stream:
        header = stream.read(20)
    machine = int.from_bytes(header[18:20], 'little')
    if header[:4] != b'\x7fELF' or machine != {'x86_64': 62, 'aarch64': 183}[arch]:
        raise SystemExit('Packaged executable is not the target ELF architecture')
    proof = json.loads(subprocess.check_output([str(executable), '--bundle-self-check'], text=True))
    if proof['bundle_id'] != config.get('identifier', base['identifier']):
        raise SystemExit('Packaged identity differs from the reviewed build configuration')
    if proof['version'] != version:
        raise SystemExit('Packaged executable differs from the reviewed version')
    files = subprocess.check_output(['dpkg-deb', '-c', str(delivery)], text=True)
    if f'usr/lib/{product}/bundled-backends/localpilot' not in files:
        raise SystemExit('Relocatable runtime resource is absent from DEB')
    resources = extracted / 'usr/lib' / product / 'bundled-backends'
    for executable_name in ('python', 'python3', 'python' + manifest['python']):
        entry = resources / 'runtime/bin' / executable_name
        if not entry.is_symlink() or entry.readlink() != Path(manifest['python_executable']):
            raise SystemExit('Extracted Python must refer to the distribution interpreter')
    python = resources / 'runtime/bin/python'
    imports = json.loads(subprocess.check_output([
        str(python), '-I', '-c',
        'import importlib,json; print(json.dumps({name:importlib.import_module(name).__file__ for name in ("agent","companion","localpilot_suite","localpilot_channels","pydantic_core","PIL._imaging","cryptography.hazmat.bindings._rust")}))',
    ], text=True, cwd=extracted))
    if any(not Path(path).resolve().is_relative_to(resources / 'runtime') for path in imports.values()):
        raise SystemExit('An extracted module was imported from outside its isolated runtime')
    dependency_check = subprocess.check_output([str(python), '-I', '-m', 'pip', 'check'], text=True, cwd=extracted).strip()
    module_versions = json.loads(subprocess.check_output([str(resources / 'localpilot'), '--version'], text=True, cwd=extracted))
    if module_versions != proof['modules']:
        raise SystemExit('Extracted CLI module versions differ from the native bundle check')
    node_check = {'status': 'NOT_BUNDLED'}
    if manifest.get('channel_runtime'):
        node = manifest['channel_runtime']
        archive = resources / 'channel-runtime' / node['filename']
        if hashlib.sha256(archive.read_bytes()).hexdigest() != node['sha256']:
            raise SystemExit('Extracted Node archive differs from its reviewed hash')
        node_root = extracted / 'node-check'
        with tarfile.open(archive) as package:
            package.extractall(node_root, filter='data')
        executable = node_root / node['filename'].removesuffix('.tar.gz') / 'bin/node'
        actual_version = subprocess.check_output([str(executable), '--version'], text=True).strip()
        if actual_version != node['filename'].split('-')[1]:
            raise SystemExit('Extracted Node executable version differs from its archive name')
        node_check = {'status': 'PASS', 'version': actual_version, 'sha256': node['sha256']}
    relocation = {'status': 'PASS', 'modules': list(imports), 'module_versions': module_versions,
                  'pip_check': dependency_check, 'node': node_check}
sha = hashlib.sha256(delivery.read_bytes()).hexdigest()
report = {'artifact': name, 'sha256': sha, 'bytes': delivery.stat().st_size,
          'package': fields, 'bundle_self_check': proof, 'installed': False,
          'tauri_input': tauri_input, 'normalization': normalization,
          'extracted_runtime': relocation,
          'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
          'source_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True).strip()),
          'host': platform.platform(), 'python_runtime': manifest}
(out / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
(out / 'SHA256SUMS').write_text(f'{sha}  {name}\n')
print(json.dumps(report, indent=2))
