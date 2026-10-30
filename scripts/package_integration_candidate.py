"""Local-only, explicit wheel allowlist; no user data, history or model export."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/delivery/v5.0.0-beta.2-core-b4'
WHEELS = ROOT / 'docs/delivery/v5-completion-20261023/beta4/wheels'
FILES = {
    'core': 'localpilot_agent_service-5.0.0b4-py3-none-any.whl',
    'companion': 'localpilot_companion-0.5.6b2-py3-none-any.whl',
    'suite': 'localpilot_suite-0.2.0b1-py3-none-any.whl',
    'psutil': 'psutil-7.2.2-cp36-abi3-macosx_11_0_arm64.whl',
    'pypdf': 'pypdf-6.21.1-py3-none-any.whl',
    'watchdog': 'watchdog-6.0.0-cp314-cp314-macosx_10_15_universal2.whl',
}
GROUPS = {
    'LocalPilot-Core-5.0.0b4-offline.zip': ['core', 'psutil'],
    'LocalPilot-Companion-0.5.6b2-offline.zip': ['companion', 'psutil', 'pypdf', 'watchdog'],
    'LocalPilot-Suite-0.2.0b1-offline.zip': list(FILES),
}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--desktop-build',type=Path,required=True)
    args=parser.parse_args()
    OUT.mkdir(exist_ok=False)
    shutil.copy2(ROOT/'docs/delivery/v5-completion-20261023/INSTALL.md', OUT/'INSTALL.md')
    for name in FILES.values():
        if not (WHEELS / name).is_file():
            raise ValueError('Missing exact allowlisted wheel: ' + name)
    patterns = [re.compile(rb'(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{24,}'), re.compile(rb'(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{30,}')]
    for name in FILES.values():
        with zipfile.ZipFile(WHEELS / name) as archive:
            for item in archive.infolist():
                parts = Path(item.filename).parts
                if '..' in parts or Path(item.filename).is_absolute():
                    raise ValueError('Unsafe wheel path')
                if any(Path(item.filename).suffix == x for x in ['.key', '.sqlite3', '.safetensors', '.gguf']):
                    raise ValueError('Forbidden wheel member')
                data = archive.read(item)
                if any(p.search(data) for p in patterns):
                    raise ValueError('Credential-shaped content in ' + item.filename)
    for filename, members in GROUPS.items():
        target = OUT / filename
        if target.exists():
            raise FileExistsError('Retained artifact must not be replaced: ' + str(target))
        own = [FILES[k] for k in members if k in {'core', 'companion', 'suite'}]
        command = 'python -m pip install --no-index --find-links wheels ' + ' '.join('wheels/' + f for f in own)
        readme = ('LocalPilot 5 Beta 2: independent module installation\n\n'
                  'Use a fresh macOS arm64 Python 3.14 virtual environment.\n' + command + '\n\n'
                  'The GUI DMG includes its own portable Python; these archives do not.\n'
                  'No credentials, models, user configuration, database or Git history included.\n'
                  'See INSTALL.md and the complete acceptance matrix before use.\n')
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for key in members:
                archive.write(WHEELS / FILES[key], 'wheels/' + FILES[key])
            archive.writestr('INSTALL.txt', readme)
            archive.write(OUT / 'INSTALL.md', 'INSTALL.md')
    desktop = args.desktop_build.resolve()
    dest = OUT / 'Desktop'
    dest.mkdir(exist_ok=True)
    for filename in ['LocalPilot-5.0.0-beta.2-arm64.dmg', 'LocalPilot-5.0.0-beta.2-arm64.app.zip', 'manifest.json']:
        target = dest / filename
        if target.exists(): raise FileExistsError(target)
        shutil.copy2(desktop / filename, target)
    manifest = {
        'kind': 'LOCAL_CANDIDATE_NOT_PUBLISHED',
        'INTEGRATED_RELEASE_CANDIDATE_GO': False,
        'CORE_PRODUCT_CHAIN_SCOPED_GO': True,
        'acceptance': '../../acceptance/v5-completion-20261023/ACCEPTANCE.md',
        'build_manifest_note': 'Build-time pending gate is historical; final decision is recorded here and in ACCEPTANCE.md.',
        'modules': {k: FILES[k] for k in ['core', 'companion', 'suite']},
        'implementation_commits': {name: subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
            for name, path in {'core': ROOT, 'companion': ROOT.parent/'LocalPilot-Companion-5-release',
                'suite': ROOT.parent/'LocalPilot-Suite-5-release', 'desktop': ROOT.parent/'LocalPilot-Desktop-5-release'}.items()},
        'scan': 'PASS_EXPLICIT_MEMBERS_AND_CREDENTIAL_PATTERNS',
        'files': {},
    }
    installed_wheels=OUT/'wheels';installed_wheels.mkdir()
    for name in FILES.values():shutil.copy2(WHEELS/name,installed_wheels/name)
    for p in sorted([*OUT.glob('*.zip'), *dest.glob('*'), *installed_wheels.glob('*.whl')]):
        if p.is_file():
            manifest['files'][str(p.relative_to(OUT))] = {'bytes': p.stat().st_size,
                'sha256': hashlib.file_digest(p.open('rb'), 'sha256').hexdigest()}
    (OUT/'ARTIFACTS.json').write_text(json.dumps(manifest, indent=2)+'\n')
    (OUT/'SHA256SUMS').write_text(''.join(v['sha256']+'  '+k+'\n' for k,v in manifest['files'].items()))
    print(json.dumps({'artifacts': len(manifest['files']), 'scan': manifest['scan']}))

if __name__ == '__main__': main()
