"""Build/install/E2E acceptance. Never connects to real QQ/WeChat or a model.

Run from an isolated candidate checkout with Python 3.14 and Node >=22.13.
Results record the executing architecture, translation status and every failure.
This script does NOT grant any GO flag on behalf of unrun manual/Intel tests.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile

BASELINE = 'df04ca709b699b170a29c2aaa337aeebe8a38ef4'
MODULES = ['tests.test_channel_adapter', 'tests.test_channel_official_integration',
           'tests.test_channel_review_security', 'tests.test_wechat_approval_audit',
           'tests.test_agent_service', 'tests.test_runtime_api', 'tests.test_hybrid_projection_arguments', 'tests.test_channel_suite_diagnostics', 'tests.test_channel_suite_integration']
NODE_TESTS = ['tests/test_qq_bridge.mjs', 'tests/test_wechat_ilink_bridge.mjs', 'tests/test_channel_state_security.mjs', 'tests/test_channel_native_websocket.mjs']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, help='New private evidence directory outside the checkout')
    parser.add_argument('--expected-machine', required=True, choices=['arm64','x86_64','AMD64','aarch64'])
    parser.add_argument('--require-darwin', action='store_true')
    parser.add_argument('--baseline-wheel', help='Optional independently built official Core 5.0.0b20 wheel')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    out = Path(args.out).expanduser().resolve()
    if out == repo or repo in out.parents or out.exists():
        raise SystemExit('Choose a new private output directory outside the checkout')
    out.mkdir(mode=0o700,parents=True)
    result = {'status':'RUNNING','host':{'system':platform.system(),'machine':platform.machine(),
              'python':platform.python_version()},'baseline':BASELINE,'phases':[], 'manual_platform_accounts':'NOT_RUN',
              'daily_app_touched':False,'model_or_paid_api_used':False}
    def record():
        path = out/'acceptance.json'
        path.write_text(json.dumps(result,ensure_ascii=True,indent=2)+'\n')
        path.chmod(0o600)
    record()
    # Intentionally discard service/operator/model variables inherited by the shell.
    env = {k:os.environ[k] for k in ('PATH','HOME','USERPROFILE','SystemRoot','WINDIR','TMPDIR','TMP','TEMP','LANG','LC_ALL') if k in os.environ}
    env['PYTHONNOUSERSITE']='1'
    def run(name, command, *, cwd=out, extra=None):
        logfile = out/(name+'.log')
        with logfile.open('w',encoding='utf-8') as log:
            completed = subprocess.run(list(map(str,command)),cwd=cwd,env={**env,**(extra or {})},stdout=log,stderr=subprocess.STDOUT,timeout=600)
        logfile.chmod(0o600)
        phase = {'name':name,'status':'PASS' if completed.returncode==0 else 'FAIL','exit_code':completed.returncode}
        for line in reversed(logfile.read_text(encoding='utf-8',errors='replace').splitlines()):
            if line.startswith('{"test_summary":'):
                phase.update(json.loads(line))
                break
        result['phases'].append(phase)
        record()
        if completed.returncode:
            raise RuntimeError(name+' failed; inspect private evidence log')
    test_modules = MODULES if os.name == 'posix' else [m for m in MODULES if m not in {
        'tests.test_channel_official_integration','tests.test_agent_service','tests.test_runtime_api','tests.test_hybrid_projection_arguments','tests.test_channel_suite_integration'}]
    result['not_run_on_this_host'] = sorted(set(MODULES)-set(test_modules))
    try:
        if platform.machine()!=args.expected_machine or (args.require_darwin and platform.system()!='Darwin'):
            raise RuntimeError('Native platform/architecture differs from requested acceptance')
        if platform.system()=='Darwin':
            translated=subprocess.run(['/usr/sbin/sysctl','-in','sysctl.proc_translated'],capture_output=True,text=True)
            if (args.expected_machine=='x86_64' and translated.returncode
                    and 'unknown oid' not in translated.stderr.lower()):
                raise RuntimeError('Cannot verify native Intel execution; translated sysctl probe unavailable')
            result['host']['rosetta_translated']=translated.stdout.strip()=='1'
            if result['host']['rosetta_translated']:
                raise RuntimeError('Rosetta execution cannot certify native Intel or native arm64')
        if sys.version_info[:2]!=(3,14):
            raise RuntimeError('Python 3.14 required for this acceptance matrix')
        node=shutil.which('node')
        if not node:
            raise RuntimeError('Node is missing; ordinary Suite/GUI use does not require it')
        run('node-runtime',[node,'-e','let v=process.versions.node.split(".").map(Number);console.log(JSON.stringify({node:process.versions.node,arch:process.arch,platform:process.platform}));if(v[0]<22||(v[0]===22&&v[1]<13)||typeof WebSocket!=="function"||(process.platform==="darwin"&&process.arch!==process.argv[1]))process.exit(2)',args.expected_machine])
        buildenv=out/'build-runtime'
        venv.EnvBuilder(with_pip=True).create(buildenv)
        buildpython=buildenv/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        run('build-tools',[buildpython,'-m','pip','--isolated','install','build>=1.2,<2','setuptools>=77'])
        wheels=out/'wheels';wheels.mkdir()
        run('build-core',[buildpython,'-m','build','--wheel','--outdir',wheels,repo])
        run('build-suite',[buildpython,'-m','build','--wheel','--outdir',wheels,repo/'suite'])
        run('build-channels',[buildpython,repo/'scripts/build_channels_wheel.py','--out',wheels])
        core=next(wheels.glob('localpilot_agent_service-*.whl'))
        suite=next(wheels.glob('localpilot_suite-*.whl'))
        channels=next(wheels.glob('localpilot_channels-*.whl'))
        with zipfile.ZipFile(core) as archive:
            assert 'localpilot_channels/__main__.py' in archive.namelist(), 'Core wheel omitted the facade'
            assert any('/share/localpilot/channels/channel-common/security.mjs' in n for n in archive.namelist())
        with zipfile.ZipFile(channels) as archive:
            names=archive.namelist()
            assert 'localpilot_channels/__main__.py' in names
            assert not any(n.startswith(('agent/','localpilot_api/','localpilot_service/')) for n in names), 'Optional component contains a second Agent runtime'
        result['wheels']=[{'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (core,suite,channels)]
        # Build the official b20 baseline from immutable Git source if no wheel was supplied.
        if args.baseline_wheel:
            baseline=Path(args.baseline_wheel).resolve(strict=True)
        else:
            source=out/'official-b20';source.mkdir()
            archive=out/'official-b20.tar'
            with archive.open('wb') as stream:
                subprocess.run(['git','-C',str(repo),'archive',BASELINE],stdout=stream,check=True)
            with tarfile.open(archive) as bundle:
                members = bundle.getmembers()
                result['baseline_archive_skipped_links'] = [m.name for m in members if m.issym() or m.islnk()]
                bundle.extractall(source,members=[m for m in members if m.isdir() or m.isfile()],filter='data')
            baselineout=out/'baseline-wheels';baselineout.mkdir()
            run('build-baseline-b20',[buildpython,'-m','build','--wheel','--outdir',baselineout,source])
            baseline=next(baselineout.glob('localpilot_agent_service-5.0.0b20-*.whl'))
        with zipfile.ZipFile(baseline) as archive:
            metadata=next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))
            assert '\nVersion: 5.0.0b20\n' in archive.read(metadata).decode(), 'Baseline is not exact official b20'
        for label, hostwheel in [('candidate',core),('official-b20',baseline)]:
            runtime=out/(label+'-runtime')
            venv.EnvBuilder(with_pip=True).create(runtime)
            py=runtime/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            run(label+'-install-core',[py,'-m','pip','--isolated','install',hostwheel])
            run(label+'-install-suite',[py,'-m','pip','--isolated','install','--no-deps',suite])
            if label=='official-b20':
                run(label+'-install-channel-facade',[py,'-m','pip','--isolated','install','--no-deps',channels])
            # The test directory has NO Agent, Service or facade source. Imports
            # must resolve to the fresh installed wheels from a different cwd.
            sandbox=out/(label+'-test-harness');sandbox.mkdir()
            shutil.copytree(repo/'tests',sandbox/'tests',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            (sandbox/'scripts').mkdir()
            shutil.copy2(repo/'scripts/wechat_approval_final.py',sandbox/'scripts/wechat_approval_final.py')
            shutil.copytree(runtime/'share/localpilot/channels',sandbox/'integrations')
            run(label+'-wheel-import',[py,'-I','-c','import localpilot_channels,localpilot_service,localpilot_suite,sys;from pathlib import Path;assert all(Path(m.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()) for m in (localpilot_channels,localpilot_service,localpilot_suite));print("INSTALLED_WHEEL_IMPORTS_PASS")'])
            run(label+'-entry-point',[py,'-I','-m','localpilot_channels','--help'])
            run(label+'-suite-list-no-node',[py,'-m','localpilot_suite.cli','--home',out/(label+'-no-node'),'channels','list'],extra={'PATH':''})
            test_script = """import contextlib,json,os,sys,unittest
from pathlib import Path
from unittest.mock import patch
suite=unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:])
with contextlib.ExitStack() as stack:
    if os.name=='posix':
        stack.enter_context(patch('agent.file_locks.LOCK_DIRECTORY',Path.cwd()/'isolated-core-file-locks'))
    r=unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps({'test_summary':{'run':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'skipped':[{'test':str(t),'reason':why} for t,why in r.skipped]}}))
sys.exit(0 if r.wasSuccessful() and (os.name=='nt' or not r.skipped) else 1)
"""
            run(label+'-python-tests',[py,'-B','-c',test_script,*test_modules],cwd=sandbox,extra={'LP_TEST_CHANNEL_WHEEL':str(channels)})
            run(label+'-node-tests',[node,'--test',*NODE_TESTS],cwd=sandbox)
        result['status']='AUTOMATED_MATRIX_PASSED_REQUIRES_REVIEW'
        result['limitations']=['Suite Companion/GUI full regression NOT_RUN','Real QQ/WeChat accounts NOT_RUN',
                              'Only the recorded native architecture ran','Power-loss durability and long duration NOT_RUN']
    except Exception as exc:
        result['status']='FAIL'
        result['error_type']=type(exc).__name__
        # Exceptions here are local fixed test/build errors, never remote bodies.
        result['error_code']='ACCEPTANCE_INCOMPLETE_INSPECT_PHASE_LOGS'
        raise
    finally:
        record()


if __name__=='__main__':
    main()
