#!/usr/bin/env python3
"""Isolated real-GUI campaign. No installed LocalPilot service or user apps.

Explicit --foreground-authorized is the host's control grant. The script never
retries a dispatched failure. Generated fixture state is independent evidence.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from computer.build import BUILD
from computer.qualification import write_binding
from computer.native_macos import NativeMacOSBackend, NativeComputerRuntime, ComputerScope, ALL_WRITES
from agent.registry import ToolRegistry
from agent.safety import CapabilityPolicy

APP='org.localpilot.computerfixture'
TITLE='LocalPilot Computer Fixture'
SECOND='LocalPilot Computer Secondary'

def condition(id,value):return {'selector':{'identifier':id},'attribute':'value','equals':value}

def make_runtime(output, *, foreground=False, capture=True, cloud_egress=None):
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    backend=NativeMacOSBackend([APP],output/'control')
    runtime=NativeComputerRuntime(backend,scopes=[ComputerScope(APP,(TITLE,SECOND),actions=frozenset(ALL_WRITES),
        background=True,foreground=foreground,capture=capture,lifetime_seconds=3600)],
        evidence_directory=output,cloud_egress=cloud_egress,verification_timeout=1)
    workspace=output/'workspace';workspace.mkdir(mode=0o700)
    registry=ToolRegistry(workspace,permission_mode='approve-mutations',capabilities=CapabilityPolicy(read=True,write=True,execute=False))
    runtime.register_tools(registry)
    return runtime,registry

def state():return json.loads((BUILD/'acceptance'/'fixture-state.json').read_text())

def gui(output, foreground):
    runtime,registry=make_runtime(output,foreground=foreground)
    binding=write_binding(output,'before');records=[]; started=time.perf_counter()
    def observe(menus=False):
        result=registry.call('inspect_tree',{'app':APP,'window_title':TITLE,'max_nodes':512,'max_depth':20,'include_menu_bar':menus})
        if result.get('status')!='ok':raise RuntimeError('observation:'+str(result.get('error')))
        return runtime.observations[APP]
    def find(selector):
        if APP not in runtime.observations:observe()
        result=registry.call('find_element',{'app':APP,'selector':selector})
        if result.get('status')!='ok':raise RuntimeError('locate:'+json.dumps(result))
        return result
    def act(case,name,selector,post,**args):
        f=find(selector) if selector is not None else args.pop('_found')
        before=state();start=time.perf_counter()
        body={'app':APP,'element':f['element'],'observation':f['observation'],'postcondition':post,**args}
        proposal=registry.call(name,body)
        if proposal.get('status')=='approval_required':result=registry.call(name,body,approved=True)
        else:result=proposal
        record={'case':case,'classification':'scripted_host_real_GUI','tool':name,'seconds':time.perf_counter()-start,
            'result':result,'independent_before':before,'independent_after':state()}
        records.append(record);print(case,result.get('status'),result.get('error'),flush=True)
        if result.get('status')!='ok' or result.get('verified') is not True:raise RuntimeError('scenario_stopped:'+case)
        return result
    try:
        observe();s=state()
        act('foreground_focus','focus_window',{'identifier':'cu.window'},condition('cu.input',s['input']))
        act('Chinese_AX_text','input_text',{'identifier':'cu.input'},condition('cu.input','原生输入'),text='原生输入',mode='replace')
        act('foreground_shortcut','shortcut',{'identifier':'cu.input'},{'selector':{'identifier':'cu.input'},'attribute':'selection_length','equals':4},key='a',modifiers=['command'])
        act('Unicode_event_insertion','input_text',{'identifier':'cu.input'},condition('cu.input','键盘中文🙂'),text='键盘中文🙂',mode='insert')
        count=state().get('result','').split(':')[-1]
        count=int(count) if count.isdigit() else 0
        act('native_button','press',{'identifier':'cu.apply'},condition('cu.result','applied:键盘中文🙂:'+str(count+1)))
        act('rich_text_Chinese','input_text',{'identifier':'cu.richtext'},condition('cu.richtext','富文本中文🙂'),text='富文本中文🙂',mode='replace')
        f=find({'identifier':'cu.apply'});node=f['node'];bounds=node['bounds'];binding=node['window_binding'];frame=binding['bounds']
        crop=[(bounds[0]-frame[0])*2,(bounds[1]-frame[1])*2,bounds[2]*2,bounds[3]*2]
        cap=registry.call('capture_window',{'app':APP,'element':f['element'],'observation':f['observation'],'crop':crop})
        records.append({'case':'window_crop','classification':'real_GUI_local_capture','result':cap})
        if cap.get('status')!='ok':raise RuntimeError('capture:'+str(cap.get('error')))
        act('controlled_visual_click','visual_click',None,condition('cu.result','applied:键盘中文🙂:'+str(count+2)),
            _found=f,capture=cap['capture'],point=[cap['width']/2,cap['height']/2])
        act('double_click','double_click',{'identifier':'cu.richtext'},condition('cu.result','double clicked'))
        record=runtime.observations[APP];rows=[n for n in record['tree']['nodes'] if n.get('role')=='AXRow']
        f={'element':rows[1]['handle'],'observation':record['token']}
        act('list_selection','select',None,condition('cu.result','selected:1'),_found=f)
        act('list_scroll','scroll',{'identifier':'cu.list.scroll'},{'selector':{'identifier':'cu.list.scrollbar'},'attribute':'value','not_equals':0},direction='down')
        act('browser_tab','press',{'role':'AXRadioButton','title':'Browser Form'},{'selector':{'role':'AXRadioButton','title':'Browser Form'},'attribute':'value','equals':1})
        webtree=runtime.observations[APP]['tree'];(output/'browser-tree.json').write_text(json.dumps(webtree,ensure_ascii=False,indent=2))
        act('WKWebView_Chinese','input_text',{'role':'AXTextArea','description':'Browser text'},
            {'selector':{'role':'AXTextArea','description':'Browser text'},'attribute':'value','equals':'浏览器中文🙂'},text='浏览器中文🙂',mode='replace')
        buttons=[n for n in runtime.observations[APP]['tree']['nodes'] if n.get('role')=='AXButton' and any(n.get(k)=='Apply browser form' for k in ('title','description'))]
        if len(buttons)!=1:raise RuntimeError('browser_button_unresolved')
        n=buttons[0];sel={'role':'AXButton',**{k:n[k] for k in ('title','description') if n.get(k)=='Apply browser form'}}
        act('browser_form_submit','press',sel,{'selector':{'role':'AXStaticText','value':'web:浏览器中文🙂'},'exists':True})
        act('native_tab','press',{'role':'AXRadioButton','title':'Native Editor'},{'selector':{'role':'AXRadioButton','title':'Native Editor'},'attribute':'value','equals':1})
        observe(True)
        menus=[n for n in runtime.observations[APP]['tree']['nodes'] if n.get('role')=='AXMenuItem' and n.get('title')=='Fixture Menu Action']
        if not menus:
            act('open_menu','press',{'role':'AXMenuBarItem','title':'Fixture'},{'selector':{'role':'AXMenuItem','title':'Fixture Menu Action'},'exists':True})
        act('menu_selection','press',{'role':'AXMenuItem','title':'Fixture Menu Action'},condition('cu.result','menu applied'))
        observe()
        act('native_sheet_open','press',{'identifier':'cu.sheet'},{'selector':{'identifier':'cu.sheet.input'},'exists':True})
        act('native_sheet_text','input_text',{'identifier':'cu.sheet.input'},condition('cu.sheet.input','Sheet中文'),text='Sheet中文',mode='replace')
        act('native_sheet_close','press',{'identifier':'cu.sheet.close'},condition('cu.result','sheet closed'))
        status='PASS'
    except Exception as exc:
        status='FAIL';records.append({'case':'campaign_stop','classification':'driver','error_type':type(exc).__name__,'error':str(exc)})
    finally:
        end_binding=write_binding(output,'after')
        if binding['source_sha256']!=end_binding['source_sha256'] or binding['binary_sha256']!=end_binding['binary_sha256']:status='INVALID_SOURCE_CHANGED'
        report={'status':status,'classification':'scripted_host_real_GUI_not_real_model','seconds':time.perf_counter()-started,
            'records':records,'summary':runtime.summary(),'independent_final':state(),'foreground_authorized':foreground}
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        runtime.close()
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--foreground-authorized',action='store_true')
    args=p.parse_args();result=gui(args.output.resolve(),args.foreground_authorized);print('campaign',result['status'],flush=True)
    raise SystemExit(0 if result['status']=='PASS' else 1)
