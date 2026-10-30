"""Real installed Core: pause, process restart, resume, SSE and cancellation."""
import argparse,hashlib,json,os,secrets,socket,subprocess,sys,threading,time,uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from urllib.parse import quote
import localpilot_service
from localpilot_service.sdk import Client

def main():
    p=argparse.ArgumentParser();p.add_argument('--evidence',required=True);a=p.parse_args()
    out=Path(a.evidence).resolve();out.mkdir(parents=True,exist_ok=False)
    private=Path.home()/'.local/share/localpilot-5-validation'/('lifecycle-'+uuid.uuid4().hex);private.mkdir(parents=True,mode=0o700)
    workspace=out/'workspace';workspace.mkdir();(workspace/'input.txt').write_text('alpha=13\nbeta=8\n')
    expected='21\n';model='mlx-community--Qwen3.6-35B-A3B-4bit'
    settings=json.loads((Path.home()/'.omlx/settings.json').read_text());omlx='http://127.0.0.1:'+str(settings['server']['port'])
    def provider(path,body=None):
        req=Request(omlx+path,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':'Bearer '+settings['auth']['api_key'],'Content-Type':'application/json'})
        with urlopen(req,timeout=180) as response:return json.load(response)
    baseline=provider('/v1/models/status');entry=next(m for m in baseline['models'] if m['id']==model);owned=not entry['loaded']
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    client_token=secrets.token_urlsafe(32);operator_token=secrets.token_urlsafe(32)
    env={**os.environ,'LP_LIFE_CLIENT':client_token,'LP_LIFE_OPERATOR':operator_token,'LP_LIFE_OMLX':settings['auth']['api_key']}
    backend={'kind':'omlx','model':model,'base_url':omlx+'/v1','api_key_env':'LP_LIFE_OMLX','context_budget':65536,'timeout':180,'include_stream_usage':True,'chat_template_kwargs':{'enable_thinking':False}}
    route={'workspace':str(workspace),'engine':'v5','backend':backend,'permissions':'approve-mutations','capabilities':{'read':True,'write':True,'execute':False},'cache_stable_prefix':True,'budgets':{'max_steps':10,'max_tool_calls':12,'max_output_tokens':1024,'max_token_units':300000},'verification':{'id':'resume-exact-file','files':{'answer.txt':hashlib.sha256(expected.encode()).hexdigest()},'required_text':'RESUME-VERIFIED'}}
    from copy import deepcopy
    chat=deepcopy(route);chat.pop('verification');chat.update(reasoning_only=True,prompt_profile='minimal_0',capabilities={'read':False,'write':False,'execute':False})
    config={'schema_version':1,'port':port,'data_dir':str(private/'data'),'clients':[{'subject':'lifecycle','token_env':'LP_LIFE_CLIENT','routes':{'agent':'agent','chat':'chat'}},{'subject':'operator','token_env':'LP_LIFE_OPERATOR','operator':True,'scopes':['read','control','cancel'],'approval_for':['lifecycle'],'routes':{}}],'routes':{'agent':route,'chat':chat}}
    path=private/'service.json';path.write_text(json.dumps(config));path.chmod(0o600)
    client=Client('http://127.0.0.1:'+str(port),token=client_token,timeout=15);operator=Client(client.base_url,token=operator_token,timeout=15)
    child=None;log=(out/'core-process.log').open('a');results={}
    def save(name,value):(out/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    def launch():
        process=subprocess.Popen([sys.executable,'-m','localpilot_service','--config',str(path)],cwd=private,env=env,stdout=log,stderr=log)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if process.poll() is not None:raise RuntimeError('Installed Core startup failed')
            try:client.request('/healthz');return process
            except OSError:time.sleep(.2)
        raise TimeoutError('Core startup timeout')
    def finish(task,name):
        deadline=time.monotonic()+900
        while time.monotonic()<deadline:
            task=client.status(task['id'])
            if task['status']=='requires_approval':
                save(name+'-approval-'+task['required_action']['id'],task['required_action'])
                operator.continue_task(task['id'],task['required_action']['id'],action='approve')
            if task['quiescent'] and task['status'] in {'completed','incomplete','failed','cancelled','timed_out','requires_human'}:break
            time.sleep(1)
        else:raise TimeoutError('Task timeout')
        save(name,task);return task
    try:
        if owned:provider('/v1/models/'+quote(model,safe='')+'/load',{})
        child=launch();save('installed-identity',{'module':localpilot_service.__file__,'version':localpilot_service.VERSION,'interpreter':sys.executable,'pid':child.pid})
        task=client.submit('Read input.txt. Add alpha and beta, write only the result and a newline to answer.txt, read it back, then finish with RESUME-VERIFIED.',model='agent',idempotency_key='pause-original',timeout_seconds=1200)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            status=client.status(task['id'])
            if status['status']=='running':break
            time.sleep(.1)
        client.request('/localpilot/v1/tasks/'+task['id']+'/pause',{})
        paused=finish(task,'paused-before-restart');assert paused['status']=='requires_human' and paused['recovery']['class']=='SAFE_TO_RESUME'
        old_action=paused['required_action']['id'];old_pid=child.pid
        operator.request('/localpilot/v1/lifecycle/suspend',{});child.wait(timeout=15)
        child=launch();restored=client.status(task['id']);save('restored',restored)
        stale_rejected=False
        try:operator.continue_task(task['id'],old_action)
        except HTTPError as exc:stale_rejected=exc.code==409;exc.close()
        assert stale_rejected
        operator.continue_task(task['id'],restored['required_action']['id'])
        done=finish(task,'resumed-complete')
        results['restart_resume']={'pass':done['status']=='completed' and (workspace/'answer.txt').read_text()==expected,'pid_changed':child.pid!=old_pid,'same_task':done['id']==task['id'],'same_session':done['session_id']==task['session_id'],'stale_action_rejected':stale_rejected,'dimensions':done.get('verification_summary'),'receipts':done.get('receipt_summary')}
        stream_task=client.submit('Write 60 short numbered lines describing a quiet garden. Do not use any tool.',model='chat',max_output_tokens=512,idempotency_key='live-stream',timeout_seconds=300)
        frames=[];observed_running=False
        for event in client.events(stream_task['id']):
            frames.append(event)
            if not observed_running and event['data'].get('type')=='runtime.event' and event['data'].get('data',{}).get('type')=='TextDelta':
                observed_running=client.status(stream_task['id'])['status']=='running'
        save('live-sse',frames);stream_done=client.status(stream_task['id']);save('live-stream-task',stream_done)
        results['live_sse']={'delta_while_task_running':observed_running,'events':len(frames),'task_status':stream_done['status']}
        cancel_task=client.submit('Write 200 numbered short sentences about trees. Do not use tools.',model='chat',max_output_tokens=1024,idempotency_key='cancel-real',timeout_seconds=300)
        cancelled_at=None
        for event in client.events(cancel_task['id']):
            if event['data'].get('type')=='runtime.event' and event['data'].get('data',{}).get('type')=='TextDelta':
                cancelled_at=time.monotonic();client.cancel(cancel_task['id']);break
        cancelled=finish(cancel_task,'cancelled-task')
        for _ in range(20):
            health=provider('/api/status')
            if health['active_requests']==0:break
            time.sleep(.25)
        save('provider-after-cancel',health)
        results['real_cancel']={'status':cancelled['status'],'active_provider_requests':health['active_requests'],'seconds_to_quiescent':time.monotonic()-cancelled_at if cancelled_at else None,'unknown_effects':cancelled['receipt_summary']['unknown_effects']}
        save('results',results)
    finally:
        if child and child.poll() is None:
            try:
                for task in client.request('/localpilot/v1/tasks')['tasks']:
                    if task['status'] not in {'completed','incomplete','failed','cancelled','timed_out'}:client.cancel(task['id'])
            except Exception:pass
            child.terminate()
            try:child.wait(timeout=30)
            except subprocess.TimeoutExpired:child.kill();child.wait()
        if owned:provider('/v1/models/'+quote(model,safe='')+'/unload',{})
        save('cleanup',{'core_exited':child is None or child.poll() is not None,'owned_model_released':owned,'provider':provider('/api/status'),'private_state':str(private)})
        log.close()

if __name__=='__main__':main()
