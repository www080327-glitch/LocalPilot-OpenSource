"""Fail before packaging when current code/module/README versions disagree."""
from pathlib import Path
import json,tomllib
root=Path(__file__).resolve().parents[1]
core=tomllib.loads((root/'pyproject.toml').read_text())['project']['version']
suite=tomllib.loads((root/'suite/pyproject.toml').read_text())['project']['version']
companion=tomllib.loads((root/'companion/pyproject.toml').read_text())['project']['version']
desktop=json.loads((root/'desktop/package.json').read_text())['version']
assert json.loads((root/'desktop/package-lock.json').read_text())['version']==desktop
assert json.loads((root/'desktop/src-tauri/tauri.conf.json').read_text())['version']==desktop
assert tomllib.loads((root/'desktop/src-tauri/Cargo.toml').read_text())['package']['version']==desktop
for path,version in [('MODULE_RELEASE.json',core),('suite/MODULE_RELEASE.json',suite),('companion/MODULE_RELEASE.json',companion)]:assert json.loads((root/path).read_text())['version']==version,path
for name in ['README.md','desktop/README.md']:
 text=(root/name).read_text()
 for version in [core,suite,companion,desktop]:assert version in text,(name,version)
assert suite in (root/'suite/README.md').read_text()
assert companion in (root/'companion/README.md').read_text()
print(json.dumps({'consistent':True,'desktop':desktop,'core':core,'suite':suite,'companion':companion}))
