"""Installed wheel matrix with final APP wheels, pinned Node, synthetic platforms.
No source packages in the test cwd; no network dependency resolution.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv
import zipfile

MODULES=['tests.test_channel_adapter','tests.test_channel_official_integration','tests.test_channel_review_security',
    'tests.test_wechat_approval_audit','tests.test_agent_service','tests.test_runtime_api',
    'tests.test_hybrid_projection_arguments','tests.test_channel_suite_diagnostics','tests.test_channel_suite_integration']

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',required=True);p.add_argument('--out',required=True);p.add_argument('--node',required=True);p.add_argument('--baseline',required=True)
    a=p.parse_args();repo=Path(__file__).resolve().parents[1];bundle=Path(a.bundle).resolve(strict=True);out=Path(a.out).resolve();out.mkdir(mode=0o700,parents=True,exist_ok=False)
    wheels=list((bundle/'wheels').glob('*.whl'));channel=next(w for w in wheels if w.name.startswith('localpilot_channels-'))
    report={'kind':'INSTALLED_WHEELS_ACTUAL_CORE_TOOLS_SCRIPTED_MODELS_AND_PLATFORMS','real_accounts':'NOT_RUN','phases':[]}
    env={k:v for k,v in os.environ.items() if k in ['HOME','LANG','TMPDIR','USER']};env['PATH']=str(Path(a.node).resolve().parent)+':/usr/bin:/bin';env['LP_TEST_CHANNEL_WHEEL']=str(channel);env['PYTHONNOUSERSITE']='1'
    def run(name,command,cwd):
        with (out/(name+'.log')).open('w') as log:r=subprocess.run(list(map(str,command)),cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=600)
        report['phases'].append({'name':name,'exit':r.returncode});(out/'matrix.json').write_text(json.dumps(report,indent=2)+'\n')
        if r.returncode:raise RuntimeError('Installed matrix failed: '+name)
    for label in ['candidate','official-b20']:
        runtime=out/(label+'-runtime');venv.EnvBuilder(with_pip=True).create(runtime);python=runtime/'bin/python'
        selected=[w for w in wheels if label=='candidate' or not w.name.startswith('localpilot_agent_service-')]
        if label=='official-b20':selected.append(Path(a.baseline).resolve(strict=True))
        run(label+'-install',[python,'-m','pip','install','--no-index','--no-deps',*selected],out)
        harness=out/(label+'-harness');harness.mkdir();shutil.copytree(repo/'tests',harness/'tests',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        (harness/'scripts').mkdir();shutil.copy2(repo/'scripts/wechat_approval_final.py',harness/'scripts/wechat_approval_final.py')
        with zipfile.ZipFile(channel) as archive:
            for name in archive.namelist():
                marker='.data/data/share/localpilot/channels/'
                if marker not in name:continue
                target=harness/'integrations'/name.split(marker,1)[1];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(name))
        run(label+'-import-proof',[python,'-I','-c',"import sys,json,localpilot_service,localpilot_suite,localpilot_channels;from pathlib import Path;mods=[localpilot_service,localpilot_suite,localpilot_channels];assert all(Path(m.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()) for m in mods);print(json.dumps({'installed_imports':True}))"],harness)
        runner="""import json,sys,unittest
r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:]))
print(json.dumps({'run':r.testsRun,'passed':r.testsRun-len(r.failures)-len(r.errors)-len(r.skipped),'failures':len(r.failures),'errors':len(r.errors),'skipped':[{'test':str(t),'reason':why} for t,why in r.skipped]}))
sys.exit(0 if r.wasSuccessful() and not r.skipped else 1)
"""
        run(label+'-python',[python,'-B','-c',runner,*MODULES],harness)
        run(label+'-node',[a.node,'--test','tests/test_qq_bridge.mjs','tests/test_wechat_ilink_bridge.mjs','tests/test_channel_state_security.mjs','tests/test_channel_native_websocket.mjs','tests/test_channel_gui_progress.mjs'],harness)
    report['status']='PASS_REQUIRES_NATIVE_AND_REAL_PLATFORM_GATES';(out/'matrix.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
