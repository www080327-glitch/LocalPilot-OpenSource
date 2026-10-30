"""Final packaged native helper on the authorized generated background fixture only."""
import argparse,hashlib,json,subprocess,sys,time,uuid
from pathlib import Path
from agent.registry import ToolRegistry
from agent.safety import CapabilityPolicy
from computer.build import build_computer_use,build_computer_fixture,BUILD
from computer.native_macos import NativeMacOSBackend,NativeComputerRuntime,ComputerScope

def main():
    p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,required=True);p.add_argument('--private',type=Path,required=True);a=p.parse_args();out=a.evidence.resolve();out.mkdir(parents=True,exist_ok=False);private=a.private.resolve();private.mkdir(mode=0o700,parents=True,exist_ok=False)
    report={'classification':'SCRIPTED_HOST_REAL_BACKGROUND_GUI_FINAL_PACKAGED_HELPER','foreground_input_test':'DEFERRED_BY_USER','real_mouse_events_sent':0,'other_app_activated':False,'records':[],'old_unknown_journals':'preserved in original read-only source worktree; not resumed or reconciled here'}
    runtime=None;fixture=None
    def state():return json.loads((private/'fixture-state.json').read_text())
    try:
        helper=build_computer_use();bundle=build_computer_fixture();report['helper_sha256']=hashlib.sha256(helper.read_bytes()).hexdigest();report['helper_module']=sys.modules['computer.native_macos'].__file__
        backend=NativeMacOSBackend(['org.localpilot.computerfixture'],private/'control');before=backend.environment()
        fixture=subprocess.Popen([str(bundle/'Contents/MacOS/ComputerFixture'),str(private),'--background'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline=time.monotonic()+20
        while not (private/'fixture-state.json').exists() and time.monotonic()<deadline:time.sleep(.1)
        if not (private/'fixture-state.json').exists():raise RuntimeError('Background fixture failed to become ready')
        runtime=NativeComputerRuntime(backend,scopes=[ComputerScope('org.localpilot.computerfixture',('LocalPilot Computer Fixture',),actions=frozenset({'set_value','input_text','press'}),foreground=False,background=True,capture=False,lifetime_seconds=120)],evidence_directory=private/'evidence')
        (private/'workspace').mkdir()
        registry=ToolRegistry(private/'workspace',permission_mode='approve-mutations',capabilities=CapabilityPolicy(read=True,write=True,execute=False));runtime.register_tools(registry)
        def invoke(name,args,approve=False):
            value=registry.call(name,args)
            if value.get('status')=='approval_required' and approve:value=registry.call(name,args,approved=True)
            report['records'].append({'tool':name,'result':value});return value
        app='org.localpilot.computerfixture';marker='统一后台验收-'+uuid.uuid4().hex[:8]
        invoke('inspect_tree',{'app':app,'window_title':'LocalPilot Computer Fixture','max_nodes':512,'max_depth':20})
        found=invoke('find_element',{'app':app,'selector':{'identifier':'cu.input'}})
        if found.get('status')!='ok':raise RuntimeError('Input observation unavailable')
        result=invoke('set_value',{'app':app,'element':found['element'],'observation':found['observation'],'value':marker,'postcondition':{'selector':{'identifier':'cu.input'},'attribute':'value','equals':marker}},True)
        if result.get('status')!='ok' or result.get('verified')is not True:raise RuntimeError('Background semantic input did not qualify')
        found=invoke('find_element',{'app':app,'selector':{'identifier':'cu.apply'}})
        expected='applied:'+marker+':1'
        result=invoke('press',{'app':app,'element':found['element'],'observation':found['observation'],'postcondition':{'selector':{'identifier':'cu.result'},'attribute':'value','equals':expected}},True)
        time.sleep(.2);after=backend.environment();observed=state()
        report['foreground_unchanged']=before.get('frontmost_pid')==after.get('frontmost_pid');report['mouse_unchanged']=before.get('mouse')==after.get('mouse');report['fixture_active']=observed.get('active');report['exact_readback']=observed.get('input')==marker and observed.get('result')==expected
        report['status']='PASS_SCOPED' if result.get('status')=='ok' and result.get('verified')is True and report['exact_readback'] and report['foreground_unchanged'] and report['mouse_unchanged'] and not report['fixture_active'] else 'FAIL'
    except Exception as e:report.update(status='FAIL',error_type=type(e).__name__,error=str(e)[:350])
    finally:
        if runtime:runtime.close()
        if fixture and fixture.poll()is None:fixture.terminate();fixture.wait(10)
        (out/'RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='records'},ensure_ascii=False))

if __name__=='__main__':main()
