#!/usr/bin/env python3
"""Live generated-fixture capture/OCR/diff, read only and without activation.

No input tools are authorized. Requires the disposable fixture already running.
"""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from computer.qualification import write_binding
from computer.native_macos import NativeMacOSBackend,NativeComputerRuntime,ComputerScope
from agent.registry import ToolRegistry
from agent.safety import CapabilityPolicy

APP='org.localpilot.computerfixture';TITLE='LocalPilot Computer Fixture'
def run(root):
    root.mkdir(mode=0o700,parents=True,exist_ok=False)
    workspace=root/'workspace';workspace.mkdir(mode=0o700);evidence=root/'computer';evidence.mkdir(mode=0o700)
    binding=write_binding(root,'before')
    r=NativeComputerRuntime(NativeMacOSBackend([APP],evidence/'control'),scopes=[ComputerScope(APP,(TITLE,),actions=frozenset(),capture=True,lifetime_seconds=120)],evidence_directory=evidence)
    registry=ToolRegistry(workspace,permission_mode='approve-mutations',capabilities=CapabilityPolicy(read=True,write=False,execute=False));r.register_tools(registry)
    records=[]
    try:
        env=r.backend.environment()
        tree=registry.call('inspect_tree',{'app':APP,'window_title':TITLE,'max_nodes':512,'max_depth':20})
        found=registry.call('find_element',{'app':APP,'selector':{'identifier':'cu.window'}})
        if found.get('status')!='ok':raise RuntimeError('Window observation failed: '+str(found.get('error')))
        body={'app':APP,'element':found['element'],'observation':found['observation']}
        cap=registry.call('capture_window',body);records.append({'step':'capture','result':cap})
        if cap.get('status')!='ok':raise RuntimeError(str(cap.get('error')))
        start=time.perf_counter();located=registry.call('locate_visual',{'app':APP,'observation':found['observation'],'capture':cap['capture'],'query':'Apply'})
        records.append({'step':'locate','seconds':time.perf_counter()-start,'result':located})
        second=registry.call('capture_window',body);records.append({'step':'second_capture','result':second})
        if second.get('status')=='ok':records.append({'step':'compare','result':registry.call('compare_captures',{'app':APP,'before':cap['capture'],'after':second['capture']})})
        after=r.backend.environment()
        report={'classification':'real_GUI_capture_local_Vision_AX_agreement_and_diff_READ_ONLY','records':records,
            'foreground_pid_unchanged':env.get('frontmost_pid')==after.get('frontmost_pid'),'mouse_unchanged':env.get('mouse')==after.get('mouse'),
            'GUI_inputs_dispatched':0,'images_uploaded':False,'summary':r.summary()}
        report['status']='PASS_SCOPED_READ_ONLY' if located.get('status')=='ok' and records[-1].get('result',{}).get('status')=='ok' else 'FAIL'
    except Exception as exc:
        report={'classification':'real_GUI_visual_READ_ONLY','status':'FAIL','records':records,'error_type':type(exc).__name__,'error':str(exc),'GUI_inputs_dispatched':0}
    finally:
        r.close();end=write_binding(root,'after')
        if binding['source_sha256']!=end['source_sha256'] or binding['binary_sha256']!=end['binary_sha256']:report['status']='INVALID_SOURCE_CHANGED'
        (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);args=p.parse_args()
    report=run(args.output.resolve());print(report['status'],[(x['step'],x.get('result',{}).get('status'),x.get('result',{}).get('error')) for x in report.get('records',[])],flush=True)
    raise SystemExit(0 if report['status']=='PASS_SCOPED_READ_ONLY' else 1)
