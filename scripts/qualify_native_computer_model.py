#!/usr/bin/env python3
"""Real configured cloud model -> loopback API -> V5 -> GUI, generated text only.

Requires explicit --allow-configured-cloud. Reads only the existing LocalPilot
provider reference; never changes a service, copies credentials, or sends images.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent.deepseek import DeepSeekBackend
from agent.engine_v5 import EngineV5Policy
from agent.hybrid import CloudEgressPolicy
from agent.registry import ToolRegistry
from agent.retry import RetryPolicy
from agent.safety import CapabilityPolicy
from agent.session import AgentSession,SessionBudgets
from agent.stabilization import HostVerification,StabilizationControls
from computer.build import BUILD
from computer.qualification import write_binding
from computer.native_macos import ComputerScope,NativeMacOSBackend,NativeComputerRuntime
from localpilot_api.service import TaskService,SETTLED
from localpilot_api.server import APIServer
from localpilot_api.client import Client

APP='org.localpilot.computerfixture';TITLE='LocalPilot Computer Fixture'
def fixture_state():return json.loads((BUILD/'acceptance'/'fixture-state.json').read_text())
def configured_provider():
    profile=json.loads((Path.home()/'Library/Application Support/io.localpilot.desktop/profile.json').read_text())
    config=json.loads((Path(profile['home'])/'service.json').read_text())
    routes=[s['backend'] for s in config['routes'].values() if s.get('backend',{}).get('kind')=='deepseek' and s['backend'].get('key_file')]
    if not routes:raise ValueError('No configured first-party cloud credential reference')
    return routes[0]
class RecordingCloudBackend(DeepSeekBackend):
    def __init__(self,**kwargs):super().__init__(**kwargs);self.real_replies=[]
    def request(self,*args,**kwargs):
        start=time.perf_counter();result=super().request(*args,**kwargs)
        self.real_replies.append({'seconds':time.perf_counter()-start,'message':result.message.to_dict(),'finish_reason':result.finish_reason,'source':'actual_provider_response'})
        print('real_model_reply',len(self.real_replies),[c.name for c in result.message.tool_calls],flush=True)
        return result

def run(output,mode,foreground,background_authorized=False,case_marker=None):
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    workspace=output/'workspace';workspace.mkdir(mode=0o700)
    evidence=output/'computer';evidence.mkdir(mode=0o700)
    binding=write_binding(output,'before')
    expected=fixture_state();provider=configured_provider();sessions=[];backends=[]
    editing=mode in {'edit','background-edit'};target_text=('后台模型验收' if mode=='background-edit' else '模型GUI验收')+('-'+case_marker if case_marker else '')
    if editing:
        expected['input']=target_text;old=expected['result'].split(':')[-1];count=int(old) if old.isdigit() else 0
        expected['result']='applied:'+target_text+':'+str(count+1)
    conditions=[{'app':APP,'window_title':TITLE,'postcondition':{'selector':{'identifier':id},'attribute':'value','equals':expected[key]}}
                for id,key in [('cu.input','input'),('cu.result','result'),('cu.richtext','richtext')]]
    def factory(callback):
        backend=RecordingCloudBackend(key_file=provider['key_file'],model=provider['model'],base_url=provider.get('base_url','https://api.deepseek.com'),timeout=45)
        backends.append(backend)
        native=NativeMacOSBackend([APP],evidence/'control')
        computer=NativeComputerRuntime(native,scopes=[ComputerScope(APP,(TITLE,),actions=frozenset({'focus_window','input_text','set_value','press'}) if mode=='edit' else frozenset({'input_text','set_value','press'}) if mode=='background-edit' else frozenset(),
            foreground=foreground,background=mode=='background-edit' and background_authorized,capture=False,lifetime_seconds=3600)],evidence_directory=evidence,
            cloud_egress=CloudEgressPolicy('CLOUD_ALLOWED'),completion_conditions=conditions)
        registry=ToolRegistry(workspace,permission_mode='approve-mutations',capabilities=CapabilityPolicy(read=True,write=editing,execute=False))
        def verify(root,result):
            ui=computer.host_verification(root,result)
            if ui.status!='passed':return ui
            try:
                text=result.text.strip()
                if text.startswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0].strip()
                data=json.loads(text);good=data=={k:expected[k] for k in ('input','result','richtext')}
            except Exception:good=False
            return HostVerification('passed' if good else 'failed','generated_GUI_fields_and_JSON_delivery',{},good,good,ui.permitted_side_effects_only)
        session=AgentSession(registry,backend=backend,policy='cloud-only',streaming=False,thinking='none',
            engine_policy=EngineV5Policy(),computer_runtime=computer,event_callback=callback,
            completion_check=lambda root,projection:computer.host_verification(root),verification_callback=verify,
            retry_policy=RetryPolicy(max_attempts=1),budgets=SessionBudgets(max_steps=18,max_token_units=600000),
            stabilization=StabilizationControls(stagnation_limit=0))
        sessions.append(session)
        return session
    service=TaskService({'localpilot':factory},persistence=output/'tasks.sqlite3',max_timeout=300)
    key=uuid.uuid4().hex;control=uuid.uuid4().hex
    server=APIServer(('127.0.0.1',0),service,api_key=key,control_token=control)
    worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True);worker.start()
    client=Client(f'http://127.0.0.1:{server.server_port}',api_key=key,control_token=control,timeout=15)
    instruction=(f'只操作生成数据测试应用 {APP} 的精确窗口 {TITLE}。通过 inspect_tree 后 find_element 读取 cu.input、cu.result、cu.richtext 三个控件当前 value。'
        '每个字段必须来自真实工具结果。最后只输出 JSON 对象，精确包含 input、result、richtext 三个字段。不要调用截图、文件、网络、委派或其它应用工具。')
    if mode=='edit':instruction+=('任务还要求先以 cu.window 调用 focus_window 请求前台控制，postcondition 使用该窗口 identifier 的 exists=true。得到 host 批准后，把 cu.input 替换为“模型GUI验收”，然后按 cu.apply；必须以真实新值与 cu.result 的变化验证两次写入。不要在缺乏前台授权时尝试写入。')
    if mode=='background-edit':instruction+=('在后台通过 AX 语义把 cu.input 替换为“后台模型验收”，然后按 cu.apply；读取当前结果计数并推断精确新值。不得调用 focus_window、键盘/鼠标事件、截图、文件或其它应用工具。输入保护或身份不可靠时停止，不能申请前台或重放 UNKNOWN。')
    if editing and case_marker:instruction=instruction.replace('后台模型验收' if mode=='background-edit' else '模型GUI验收',target_text)
    def permitted_postcondition(post, goal, observation):
        if not isinstance(post,dict) or post.get('attribute')!='value' or post.get('selector')!=goal['selector']:return False
        if set(post)=={'selector','attribute','equals'}:return post['equals']==goal['equals']
        if set(post)=={'selector','attribute','not_equals'}:
            nodes=[n for n in observation['tree']['nodes'] if n.get('identifier')==goal['selector']['identifier']]
            return len(nodes)==1 and post['not_equals']==nodes[0].get('value') and post['not_equals']!=goal['equals']
        return False
    started=time.perf_counter();report={};approved_steps=set();approval_log=[]
    try:
        try:
            task=client.request('/localpilot/v1/tasks',{'input':instruction,'model':'localpilot','timeout_seconds':240,'max_output_tokens':1536})
        except Exception as exc:
            from urllib.error import HTTPError
            if isinstance(exc,HTTPError):
                body=json.loads(exc.read()); print('local_API_rejection',json.dumps(body,ensure_ascii=False),flush=True)
                (output/'creation-failure.json').write_text(json.dumps({'code':exc.code,'error':body},ensure_ascii=False,indent=2))
            raise
        deadline=time.monotonic()+260
        while time.monotonic()<deadline:
            with service.condition:service.condition.wait_for(lambda:service.tasks[task['id']].status in SETTLED and not service.tasks[task['id']].executing,2)
            task=client.request('/localpilot/v1/tasks/'+task['id'])
            if task['status']=='requires_approval':
                # The host approves only this generated-data test's exact
                # proposal. The model has no approval or scope-grant tool.
                pending=sessions[0].pending_approval
                if not editing or pending.get('kind')!='tool':break
                call=pending['call'];body=json.loads(call.arguments);r=sessions[0].computer
                current=r.observations.get(APP);node=next((n for n in (current or {}).get('tree',{}).get('nodes',[]) if n['handle']==body.get('element')),None)
                logical_step='input_text' if call.name=='set_value' else call.name
                allowed=(body.get('app')==APP and current and body.get('observation')==current['token'] and node and logical_step not in approved_steps)
                post=body.get('postcondition')
                if call.name=='focus_window':
                    allowed=allowed and mode=='edit' and node.get('identifier')=='cu.window' and post=={'selector':{'identifier':'cu.window'},'exists':True} and set(body)=={'app','element','observation','postcondition'}
                elif call.name=='input_text':
                    allowed=allowed and node.get('identifier')=='cu.input' and body.get('text')==target_text and body.get('mode')=='replace' and permitted_postcondition(post,conditions[0]['postcondition'],current) and set(body)=={'app','element','observation','postcondition','text','mode'}
                elif call.name=='set_value':
                    allowed=allowed and node.get('identifier')=='cu.input' and body.get('value')==target_text and permitted_postcondition(post,conditions[0]['postcondition'],current) and set(body)=={'app','element','observation','postcondition','value'}
                elif call.name=='press':
                    allowed=allowed and node.get('identifier')=='cu.apply' and permitted_postcondition(post,conditions[1]['postcondition'],current) and set(body)=={'app','element','observation','postcondition'}
                else:allowed=False
                approval_log.append({'call_id':call.id,'name':call.name,'arguments':body,'host_whitelist_allowed':bool(allowed)})
                (output/'approval-proposals.json').write_text(json.dumps(approval_log,ensure_ascii=False,indent=2))
                if not allowed:break
                approved_steps.add(logical_step)
                client.request('/localpilot/v1/tasks/'+task['id']+'/approve',{'action_id':task['required_action']['id']},control=True)
                print('exact_test_host_approval',call.name,flush=True)
                continue
            if task['status'] in SETTLED:break
        else:service.cancel(task['id']);task=service.task_snapshot(task['id'])
        independent=fixture_state()
        report={'classification':'real_cloud_model_real_GUI_loopback_API_V5_SQLite','mode':mode,'seconds':time.perf_counter()-started,
            'task':task,'real_model_replies':backends[0].real_replies if backends else [],
            'expected_fields':{k:expected[k] for k in ('input','result','richtext')},'independent_final':independent,
            'images_sent':False,'host_approval_log':approval_log,'daily_service_modified':False,'automatic_unknown_replay':False}
        report['status']='PASS' if task['status']=='completed' and task.get('result',{}).get('verification_status')=='passed' else 'FAIL'
        end_binding=write_binding(output,'after')
        if binding['source_sha256']!=end_binding['source_sha256'] or binding['binary_sha256']!=end_binding['binary_sha256']:report['status']='INVALID_SOURCE_CHANGED'
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print('model_campaign',report['status'],task['status'],task.get('result',{}).get('verification_status'),flush=True)
    finally:
        server.shutdown();server.server_close();service.shutdown()
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);p.add_argument('--allow-configured-cloud',action='store_true');p.add_argument('--mode',choices=['observe','edit','background-edit'],default='observe');p.add_argument('--foreground-authorized',action='store_true');p.add_argument('--background-authorized',action='store_true');p.add_argument('--case-marker',help='Generated independent test marker; never private data')
    args=p.parse_args()
    if not args.allow_configured_cloud:p.error('Explicit generated-text cloud authorization required')
    if args.mode=='edit' and not args.foreground_authorized:p.error('Explicit foreground grant required for edits')
    if args.mode=='background-edit' and not args.background_authorized:p.error('Explicit fixture background qualification grant required')
    if args.case_marker and (len(args.case_marker)>32 or not all(c.isalnum() or c in '-_' for c in args.case_marker)):p.error('Case marker must be at most 32 letters/digits/dashes')
    report=run(args.output.resolve(),args.mode,args.foreground_authorized,args.background_authorized,args.case_marker);raise SystemExit(0 if report.get('status')=='PASS' else 1)
