"""Exercise bundled Suite with no global Node/Python; no real platform login.

The test sends requests over the same private stdin contract as the native GUI.
Use a fresh private output directory. Models, daily installations, cloud and
platform accounts are never touched by this fixture.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',required=True);p.add_argument('--out',required=True);p.add_argument('--verified-node-cache',required=True)
    a=p.parse_args();bundle=Path(a.bundle).resolve(strict=True);out=Path(a.out).resolve()
    out.mkdir(mode=0o700,parents=True,exist_ok=False)
    home=out/'product';home.mkdir(mode=0o700)
    user=out/'empty-user';user.mkdir(mode=0o700)
    workspace=out/'workspace';workspace.mkdir(mode=0o700)
    env={'HOME':str(user),'PATH':'/usr/bin:/bin','LANG':'en_US.UTF-8','TMPDIR':'/private/tmp','PYTHONDONTWRITEBYTECODE':'1'}
    cli=bundle/'localpilot';report={'source':'final_bundled_suite_private_stdin','real_platforms':'NOT_RUN','model_inference':'NOT_RUN','phases':[]}
    def run(arguments,body=None):
        result=subprocess.run([str(cli),'--home',str(home),'--json',*arguments],input=None if body is None else json.dumps(body),text=True,env=env,capture_output=True,timeout=240)
        value=json.loads(result.stdout)
        if result.returncode:raise RuntimeError('fixture failed: '+str(value.get('error','unknown')))
        return value
    def request(kind,action,args=None):
        return run(['product-control','--request-stdin'],{'version':1,'operation':'channels','args':{'kind':kind,'action':action,'args':args or {}}})
    try:
        run(['desktop-init','--workspace',str(workspace)])
        report['phases'].append({'name':'empty_home_bundled_initialization','status':'PASS','system_node_python_used':False})
        for kind in ('qq','wechat'):
            before=request(kind,'status');assert before['status']=='not_installed' and before['connected'] is False
            request(kind,'skip');assert request(kind,'status')['skipped'] is True
        report['phases'].append({'name':'skip_both_platforms_preserves_agent','status':'PASS'})
        cache=Path(a.verified_node_cache).resolve(strict=True)
        manifest=json.loads((cache/'installation.json').read_text())
        assert hashlib.file_digest((cache/'node').open('rb'),'sha256').hexdigest()==manifest['binary_sha256']
        shutil.copytree(cache,home/'channel-node')
        for kind in ('qq','wechat'):
            installed=request(kind,'install',{'confirmed':True})
            assert installed['status']=='installed'
            observed=request(kind,'status')
            assert observed['installed'] is True and observed['connected'] is False
        report['phases'].append({'name':'optional_wheel_install_with_verified_cached_node','status':'PASS','global_node_used':False,'network_download_repeated':False})
        value=request('qq','qq_credentials',{'app_id':'123456','app_secret':'FIXTURE-NOT-A-REAL-SECRET','confirmed':True})
        assert 'FIXTURE-NOT' not in json.dumps(value)
        report['phases'].append({'name':'native_stdin_credentials_private_not_connected','status':'PASS'})
        for kind in ('qq','wechat'):
            result=request(kind,'diagnose');assert not result['connected']
        report['status']='PASS_WITH_PLATFORM_AND_MODEL_LIMITATIONS'
    finally:
        for kind in ('qq','wechat'):
            try:request(kind,'stop',{'confirmed':True})
            except Exception:pass
        for module in ('companion','core'):
            try:run(['product-control','--request-stdin'],{'version':1,'operation':'service_control','args':{'module':module,'action':'stop','confirmed':True}})
            except Exception:pass
        (out/'qualification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))

if __name__=='__main__':main()
