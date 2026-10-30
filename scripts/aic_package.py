"""Build review-only archives from exact Git blobs and generated public fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/aic-20261029';E=ROOT/'docs/evidence/aic-final-20261029'


def sha(data):return hashlib.sha256(data).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--revision',default='final');a=p.parse_args()
    source=OUT/('localpilot-受限源码-'+a.revision+'.zip');evidence=OUT/('localpilot-实验记录-'+a.revision+'.zip');materials=OUT/('localpilot-提交材料-'+a.revision+'.zip')
    for path in [source,evidence,materials]:
        if path.exists():raise FileExistsError(path)
    required=['localpilot-技术报告.pdf','localpilot-答辩-final.pptx','localpilot-真实演示.mp4','作品介绍.txt','声明与开源计划.txt']
    if any(not (OUT/'materials'/name).is_file() for name in required):raise ValueError('Submission artifacts are incomplete')
    from agent.cloud_credentials import resolve_deepseek_key
    cloud_key=resolve_deepseek_key(key_file=ROOT.parent/'LocalPilot/.localpilot/secrets/deepseek.key').encode()
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    paths=subprocess.check_output(['git','ls-tree','-r','--name-only',revision],cwd=ROOT,text=True).splitlines()
    prefixes=('agent/','computer/','localpilot_api/','localpilot_service/','localpilot_plugins/','localpilot_channels/',
        'companion/','suite/','channels/','integrations/','third_party/','tests/','benchmarks/','configs/','scripts/','examples/','localpilot-agent/','kv-cache-repro/',
        'desktop/src/','desktop/src-tauri/','desktop/scripts/','desktop/icons/','desktop/public/','desktop/tests/',
        'docs/development/aic-final-20261029/')
    roots={'LICENSE','README.md','pyproject.toml','requirements.txt','catalog.py','hardware.py','main.py','recommender.py','selector_mlp.py','text.py',
        'AGENT_SERVICE_API.md','MODEL_BACKEND_API.md','MODEL_MANAGER_CONTRACT.md','SERVICE_DEPLOYMENT.md','COMPANION_CLIENT_CONTRACT.md','docs/PLUGIN_ECOSYSTEM.md','MODULE_RELEASE.json'}
    extensions={'.py','.toml','.json','.md','.txt','.rs','.ts','.tsx','.js','.mjs','.cjs','.svg','.swift','.sh','.yml','.yaml','.lock','.xml','.html','.css','.cpp','.h','.c','.plist','.entitlements','.command','.png','.ico','.icns','.sha256'}
    selected=[path for path in paths if (path in roots or ('/' not in path and Path(path).suffix=='.md') or path.startswith(prefixes) or (path.startswith('desktop/') and '/' not in path[8:]))
        and (Path(path).suffix in extensions or Path(path).name=='LICENSE')
        and not any(part in {'node_modules','target','build','dist','.private'} for part in Path(path).parts)]
    import tomllib
    for project in ['pyproject.toml','suite/pyproject.toml','companion/pyproject.toml','channels/pyproject.toml']:
        config=tomllib.loads(subprocess.check_output(['git','show',revision+':'+project],cwd=ROOT,text=True))
        for group in config.get('tool',{}).get('setuptools',{}).get('data-files',{}).values():
            for relative in group:
                # The optional channels builder stages this pyproject at the repo root.
                base=Path('.') if project=='channels/pyproject.toml' else Path(project).parent
                full=str(base/relative)
                if full not in selected:raise ValueError('Missing declared build input: '+full)
    manifest=[]
    with zipfile.ZipFile(source,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in selected:
            data=subprocess.check_output(['git','show',revision+':'+path],cwd=ROOT)
            if cloud_key in data:raise ValueError('Credential content detected in source: '+path)
            archive.writestr('localpilot/'+path,data);manifest.append({'path':path,'sha256':sha(data),'bytes':len(data)})
        notice=('localpilot / 大肥鱼队\nGit commit: '+revision+'\nMIT for original code; retain third-party notices.\n'
            'Competition-period restricted access; no public publication performed.\n'
            'This is source for review, not a consumer APP. Selector MLP JSON parameters are included; foundation-model checkpoints, credentials, private databases and user configuration are excluded.\n'
            'Use the current AIC report for qualification boundaries; retained baseline documentation is historical.\n')
        archive.writestr('localpilot/AIC_REVIEW_NOTICE.txt',notice)
        archive.writestr('localpilot/AIC_SOURCE_MANIFEST.json',json.dumps({'commit':revision,'entries':manifest},indent=2))
    secrets=[cloud_key]
    for endpoint in (ROOT/'.aic-runtime/owned-services').glob('*/endpoint.json'):
        token=json.loads(endpoint.read_text()).get('api_key')
        if token:secrets.append(token.encode())
    def public_bytes(raw):
        for token in secrets:raw=raw.replace(token,b'[REDACTED_CREDENTIAL]')
        return raw.replace(str(Path.home()).encode(),b'USER_HOME')
    mappings=[]
    with zipfile.ZipFile(evidence,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(E.rglob('*')):
            if not path.is_file() or path.name=='host-python-package-inventory.json':continue
            frozen_source='measured-source-snapshot' in path.parts and path.suffix in {'.py','.mjs'}
            if path.suffix not in {'.json','.jsonl','.log','.stdout','.stderr','.sse','.yml','.txt'} and not frozen_source:continue
            raw=path.read_bytes();public=raw if frozen_source else public_bytes(raw)
            if any(token in public for token in secrets):raise ValueError('Credential content in frozen evidence source: '+str(path))
            rel=str(path.relative_to(E));archive.writestr('evidence/'+rel,public)
            mappings.append({'path':rel,'original_sha256':sha(raw),'public_sha256':sha(public),'redacted':raw!=public})
        for name in ['raw-cost-ledger.json','strict-score-audit.json']:
            path=OUT/name
            if not path.is_file():raise ValueError('Missing auditable ledger: '+name)
            raw=path.read_bytes();public=public_bytes(raw)
            archive.writestr('evidence/'+name,public)
            mappings.append({'path':name,'original_sha256':sha(raw),'public_sha256':sha(public),'redacted':raw!=public})
        archive.writestr('evidence/REDACTION_MANIFEST.json',json.dumps(mappings,indent=2))
        archive.writestr('evidence/README.txt','Original files remain in the private worktree. Review copy redacts credential values and home paths only; usage, outcomes and amounts are preserved. This archive contains public synthetic fixtures and benchmark observations, not personal user data.\n')
    with zipfile.ZipFile(materials,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((OUT/'materials').rglob('*')):
            if path.is_file():archive.write(path,'materials/'+str(path.relative_to(OUT/'materials')))
        for name in ['summary.json','video-validation.json','report-validation.json']:
            if (OUT/name).exists():archive.writestr(name,public_bytes((OUT/name).read_bytes()))
        for path in sorted((OUT/'charts').glob('*.svg')):archive.write(path,'charts/'+path.name)
    summary=json.loads((OUT/'summary.json').read_text())
    final={'commit':revision,'source_files':len(manifest),'artifacts':[{'name':p.name,'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())} for p in [source,evidence,materials]],
        'benchmark_all_arms_measured':all(row['n'] for row in summary['benchmark']),
        'benchmark_cohort_role':summary['cohort_role'],'benchmark_run':summary['benchmark_run'],
        'mlp_formal_quality_replacement':'NO_GO','statistical_noninferiority':'NOT_ESTABLISHED',
        'confirmed_architecture_api_savings':'NOT_ESTABLISHED','limits':summary['limits'],
        'official_leaderboard_score':False,'public_release_performed':False,'main_merged':False,'daily_app_replaced':False,
        'materials_present':True,'team_review_required':True,'registration_signature_upload':'NOT_PERFORMED'}
    (OUT/('DELIVERY-'+a.revision+'.json')).write_text(json.dumps(final,indent=2)+'\n')
    print(json.dumps(final))


if __name__=='__main__':main()
