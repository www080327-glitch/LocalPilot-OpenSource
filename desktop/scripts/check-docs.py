"""Check live Markdown links, required root policy and archive rename integrity."""
from pathlib import Path
import re, subprocess, json, hashlib
from urllib.parse import unquote
ROOT = Path(__file__).resolve().parents[1]
errors = []
for p in [ROOT/'README.md', ROOT/'AGENTS.md', *ROOT.joinpath('docs').rglob('*.md')]:
    if '/evidence/' in str(p) or '/archive/' in str(p):
        continue  # frozen historical material is not rewritten
    for link in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', p.read_text()):
        link = unquote(link.split('#')[0].split(' "')[0])
        if not link or re.match(r'^[a-zA-Z]+:', link):
            continue
        target = p.parent/link
        if not target.exists(): errors.append(f'{p.relative_to(ROOT)}: missing {link}')
for p in ROOT.glob('*.md'):
    if p.name not in {'README.md','AGENTS.md','LICENSE.md'}: errors.append('Root report: '+p.name)
moves = ROOT/'docs/evidence/maintenance-20261023/moves.json'
if moves.exists():
    for m in json.loads(moves.read_text()):
        if not m['from'].startswith('evidence/'): continue
        original_ref = subprocess.run(['git','cat-file','-e','03119d5^{commit}'],cwd=ROOT,capture_output=True)
        if original_ref.returncode == 0:
            original = subprocess.run(['git','show','03119d5:'+m['from']],cwd=ROOT,capture_output=True,check=True).stdout
            expected = hashlib.sha256(original).hexdigest()
        else:
            # The public monorepo does not contain the independent GUI Git DAG.
            # Carry verified original byte identities; never skip the check.
            proof = json.loads((ROOT/'docs/evidence/agent-profile-20261024/original-archive-byte-proof.json').read_text())
            if proof['source_commit'].startswith('03119d5') is not True: raise ValueError('Invalid original source identity')
            expected = proof['sha256'][m['from']]
        if expected != hashlib.sha256((ROOT/m['to']).read_bytes()).hexdigest(): errors.append('Evidence bytes changed: '+m['to'])
if errors: raise SystemExit('\n'.join(errors))
print('PASS: live Markdown links, root policy, and original evidence bytes')
