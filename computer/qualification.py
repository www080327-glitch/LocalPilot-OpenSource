"""Host evidence binding for isolated qualification drivers; no credential reads."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time
from .build import BUILD


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_binding(output, phase):
    root=Path(__file__).resolve().parents[1]
    paths=sorted([*root.joinpath('agent').glob('*.py'),*root.joinpath('computer').glob('*.py'),
        *root.joinpath('computer/native').glob('*.swift'),*root.joinpath('localpilot_service').glob('*.py'),*root.joinpath('localpilot_api').glob('*.py'),
        *root.joinpath('scripts').glob('qualify_native_computer*.py')])
    sources={str(p.relative_to(root)):file_hash(p) for p in paths}
    binaries={name:file_hash(path) for name,path in {
        'helper':BUILD/'computerusebridge','window_vision':BUILD/'windowvision',
        'fixture_bundle_executable':BUILD/'LocalPilot Computer Fixture.app/Contents/MacOS/ComputerFixture',
        'fixture_compile_only_check':BUILD/'ComputerFixture-source-check'}.items() if path.is_file()}
    value={'classification':'host_source_binary_binding','phase':phase,'at':time.time(),
        'git_base':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
        'platform':platform.platform(),'source_sha256':sources,'binary_sha256':binaries,
        'fixture_bundle_source_qualification':'separate_from_current_source_compile_only_check'}
    path=Path(output)/('binding-'+phase+'.json');path.write_text(json.dumps(value,indent=2))
    return value
