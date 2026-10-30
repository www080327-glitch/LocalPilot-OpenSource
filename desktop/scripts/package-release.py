"""Package newly built GUI only; release folder is never a backend/user-data copy."""
from pathlib import Path
import hashlib, json, os, plistlib, subprocess, tempfile
root=Path(__file__).resolve().parents[1]
out=Path(os.environ['LP_GUI_PACKAGE_OUTPUT']);app=Path(os.environ['LP_GUI_PACKAGE_APP']);version=os.environ['LP_GUI_PACKAGE_VERSION']
with tempfile.TemporaryDirectory(prefix='localpilot-new-dmg-') as stage:
    subprocess.run(['/usr/bin/ditto','--norsrc','--noextattr',str(app),str(Path(stage)/'LocalPilot.app')],check=True)
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(Path(stage)/'LocalPilot.app')],check=True)
    (Path(stage)/'Applications').symlink_to('/Applications')
    dmg=out/f'LocalPilot-{version}-arm64.dmg'
    subprocess.run(['/usr/bin/hdiutil','create','-volname','LocalPilot','-srcfolder',stage,'-format','UDZO',str(dmg)],check=True)
    subprocess.run(['/usr/bin/hdiutil','verify',str(dmg)],check=True)
files={p.name:{'sha256':hashlib.file_digest(p.open('rb'),'sha256').hexdigest(),'bytes':p.stat().st_size} for p in sorted(out.iterdir()) if p.is_file() and not p.is_symlink()}
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
dirty=bool(subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=root,text=True).strip())
bundle=plistlib.loads((app/'Contents/Info.plist').read_bytes())
bundled=json.loads((app/'Contents/Resources/bundled-backends/verified-modules.json').read_text())['actual_module_versions']
manifest={'version':version,'kind':'ISOLATED_TEST_NOT_PUBLISHED' if bundle['CFBundleIdentifier'].endswith('.test') else 'LOCAL_CANDIDATE_NOT_PUBLISHED','source_commit':head,'source_dirty':dirty,'platform':'macOS arm64','bundle_id':bundle['CFBundleIdentifier'],'signing':'ad-hoc; not notarized','app_path':str(app),'files':files,'backend_bundled':True,'bundled_modules':{'core':bundled['localpilot-agent-service'],'companion':bundled['localpilot-companion'],'suite':bundled['suite']},'user_data_bundled':False,'weights_bundled':False,'omlx_bundled':False,'admission':'INTEGRATED_RELEASE_CANDIDATE_GO=NO_PENDING_REAL_LOCAL_ACCEPTANCE'}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(out/'SHA256SUMS').write_text(''.join(f'{v["sha256"]}  {name}\n' for name,v in files.items()))
