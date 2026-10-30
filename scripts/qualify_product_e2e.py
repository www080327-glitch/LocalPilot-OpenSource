"""Real-provider API acceptance on synthetic, isolated files only.

Model loading is a separate explicitly authorized operation. Never replays a
mutation or retries an UNKNOWN submission. Retains every consumed outcome.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time
import uuid
import atexit
import urllib.request
from urllib.parse import quote

from localpilot_service.deployment import build
from localpilot_service.sdk import Client

def main():
    p=argparse.ArgumentParser();p.add_argument('--provider',choices=['cloud','local'],required=True)
    p.add_argument('--key-file');p.add_argument('--evidence',required=True);p.add_argument('--model',default='mlx-community--Qwen3.5-0.8B-4bit')
    p.add_argument('--allow-fixture-egress',action='store_true')
    p.add_argument('--cloud-base-url',default='https://api.deepseek.com')
    p.add_argument('--chat-only',action='store_true')
    p.add_argument('--load-registered',action='store_true')
    p.add_argument('--cooperative',action='store_true')
    a=p.parse_args();out=Path(a.evidence).resolve();out.mkdir(parents=True,exist_ok=False)
    private=Path.home()/'.local/share/localpilot-5-validation'/uuid.uuid4().hex
    private.mkdir(parents=True,mode=0o700)
    workspace=out/'workspace';workspace.mkdir();(workspace/'input.txt').write_text('alpha=7\nbeta=5\n')
    expected='12\n';mark='PRODUCT-VERIFIED'
    tokens={'LP_PRODUCT_CLIENT':secrets.token_urlsafe(32),'LP_PRODUCT_OPERATOR':secrets.token_urlsafe(32)}
    os.environ.update(tokens)
    if a.provider=='cloud':
        backend={'kind':'deepseek-native','model':'deepseek-flash','key_file':a.key_file,'base_url':a.cloud_base_url,'context_budget':131072,'timeout':45}
    else:
        settings=json.loads((Path.home()/'.omlx/settings.json').read_text());os.environ['LP_PRODUCT_OMLX']=settings['auth']['api_key']
        backend={'kind':'omlx','base_url':'http://127.0.0.1:'+str(settings['server']['port'])+'/v1','model':a.model,
            'api_key_env':'LP_PRODUCT_OMLX','context_budget':65536,'timeout':180,'include_stream_usage':True,'chat_template_kwargs':{'enable_thinking':False}}
    owned_model=False
    def model_request(path,body=None):
        req=urllib.request.Request(backend['base_url'].removesuffix('/v1')+path,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':'Bearer '+os.environ['LP_PRODUCT_OMLX'],'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=180) as r:return json.load(r)
    def release_model():
        nonlocal owned_model
        if not owned_model:return
        model_request('/v1/models/'+quote(a.model,safe='')+'/unload',{})
        owned_model=False
        (out/'owned-model-released.json').write_text(json.dumps(model_request('/api/status'),indent=2))
    if a.load_registered:
        import psutil
        if a.provider!='local' or a.model not in {'mlx-community--Qwen3.5-0.8B-4bit','mlx-community--Qwen3.6-35B-A3B-4bit'}:raise ValueError('No resource grant for this model')
        state=model_request('/v1/models/status');entry=next(m for m in state['models'] if m['id']==a.model)
        if not entry['loaded']:
            if psutil.virtual_memory().available<entry['estimated_size']+8*1024**3:raise ValueError('Memory admission refused')
            owned_model=True;atexit.register(release_model)
            model_request('/v1/models/'+quote(a.model,safe='')+'/load',{})
        (out/'resource-lease.json').write_text(json.dumps({'model':a.model,'owned':owned_model,'source':'explicit human resume of remaining acceptance','existing_service':True,'status':model_request('/api/status')},indent=2))
    route={'workspace':str(workspace),'backend':backend,'engine':'v5','permissions':'approve-mutations',
        'capabilities':{'read':True,'write':True,'execute':False},'cache_stable_prefix':True,
        'cloud_egress':'REQUIRES_APPROVAL' if a.provider=='cloud' else 'LOCAL_ONLY',
        'budgets':{'max_steps':8,'max_tool_calls':12,'max_output_tokens':1024,'max_token_units':200000},
        'verification':{'id':'product-isolated-exact-file','files':{'answer.txt':hashlib.sha256(expected.encode()).hexdigest()},'required_text':mark}}
    chat=deepcopy(route);chat.pop('verification');chat.update(engine='legacy',reasoning_only=True,prompt_profile='minimal_0',tool_profile='compact',capabilities={'read':False,'write':False,'execute':False})
    if a.provider=='cloud':route['thinking']='none';chat['thinking']='none'
    if a.allow_fixture_egress:
        route['cloud_egress_paths']=['input.txt','answer.txt']
    config={'schema_version':1,'port':0,'data_dir':str(private/'data'),'clients':[
        {'subject':'product','token_env':'LP_PRODUCT_CLIENT','routes':{'agent':'agent','chat':'chat'}},
        {'subject':'operator','token_env':'LP_PRODUCT_OPERATOR','operator':True,'scopes':['read','control','cancel'],'approval_for':['product'],'routes':{}}],
        'routes':{'agent':route,'chat':chat}}
    if a.cooperative:
        if a.provider!='local' or not a.key_file:raise ValueError('Explicit local/cloud qualification inputs required')
        partner=deepcopy(route);partner['backend']={'kind':'deepseek-native','model':'deepseek-flash','key_file':a.key_file,'base_url':a.cloud_base_url,'context_budget':131072,'timeout':45};partner['cloud_egress']='REQUIRES_APPROVAL';partner['thinking']='none'
        config['routes']['cloud-provider']=partner
        route.update(cooperation={'cloud_route':'cloud-provider'},cloud_egress='REQUIRES_APPROVAL',cloud_egress_paths=['input.txt','answer.txt'])
    path=private/'service.json';path.write_text(json.dumps(config));path.chmod(0o600)
    server=build(path)
    thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True);thread.start()
    url='http://127.0.0.1:'+str(server.server_port)
    client=Client(url,token=tokens['LP_PRODUCT_CLIENT'],timeout=10)
    operator=Client(url,token=tokens['LP_PRODUCT_OPERATOR'],timeout=10)
    def save(name,data):(out/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    def finish(task, name):
        deadline=time.monotonic()+900;approved=set();last_state=None
        while time.monotonic()<deadline:
            task=client.status(task['id'])
            state=(task['status'],task.get('required_action',{}).get('id') if task.get('required_action') else None)
            if state!=last_state:save(name+'-latest',task);last_state=state
            if task['status']=='requires_approval':
                action=task['required_action'];aid=action['id']
                if aid in approved:raise RuntimeError('Approval repeated; no replay')
                save(name+'-approval-'+str(len(approved)),action)
                if task.get('receipt_summary',{}).get('unknown_effects'):raise RuntimeError('UNKNOWN mutation isolated')
                approved.add(aid);operator.continue_task(task['id'],aid,action='approve')
            if task.get('quiescent') and task['status'] in {'completed','incomplete','failed','cancelled','timed_out','requires_human'}:break
            time.sleep(1)
        else:client.cancel(task['id']);raise TimeoutError('Bounded product acceptance timeout')
        save(name+'-final',task)
        return task
    results=[]
    try:
        save('health',client.request('/healthz'));save('registry',client.request('/localpilot/v1/model-registry'))
        first=finish(client.submit('Remember the word ORCHID57. Reply only OK.',model='chat',max_output_tokens=64,idempotency_key='chat-first'), 'chat-first')
        second=finish(client.submit('What word did I ask you to remember? Reply only that word.',model='chat',session_id=first['session_id'],max_output_tokens=64,idempotency_key='chat-second'),'chat-second')
        results.append({'case':'multi_turn','pass':'ORCHID57' in ((second.get('result') or {}).get('text') or ''),'session':first['session_id']})
        if a.chat_only:
            save('results',{'provider_kind':'REAL_MODEL','provider':a.provider,'results':results})
            return
        task_input=('First read input.txt using the local model. Then call request_model_switch with exact arguments {"backend_id":"cloud","model":"deepseek-flash","target":"cloud","scope":"session","task_complexity":"complex","reason":"user_requested_cloud_continuation"}. Wait for host approval. Do not write files using the local model if switching fails; report incomplete. Only after switching, let the cloud model continue the same task: ' if a.cooperative else '')+'Read input.txt. Add alpha and beta. Create answer.txt containing only the sum followed by a newline. Read answer.txt back to verify. Finish with the exact marker PRODUCT-VERIFIED. Do not use shell execution or unrelated files.'
        task=client.submit(task_input,model='agent',idempotency_key='real-file-task',timeout_seconds=900)
        done=finish(task,'agent')
        actual=(workspace/'answer.txt').read_text() if (workspace/'answer.txt').exists() else None
        results.append({'case':'real_tool_file_verification','file_exact':actual==expected,'status':done['status'],'dimensions':done.get('verification_summary'),'receipts':done.get('receipt_summary')})
        events=list(client.events(done['id']));save('agent-sse',events)
        if a.cooperative:
            models=done.get('result',{}).get('reported_models',[])
            approvals=[json.loads(p.read_text()) for p in out.glob('agent-approval-*.json')]
            results.append({'case':'same_task_approved_handoff','pass':a.model in models and 'deepseek-flash' in models,
                'reported_models':models,'same_task_id':done['id']==task['id'],'same_session_id':done['session_id']==task['session_id'],
                'approval_kinds':[x.get('kind',x.get('type')) for x in approvals]})
        replay=client.submit(task_input,model='agent',idempotency_key='real-file-task',timeout_seconds=900)
        results.append({'case':'durable_idempotency','same_task':replay['id']==done['id']})
        save('results',{'provider_kind':'REAL_MODEL','provider':a.provider,'results':results})
    finally:
        for t in list(server.service.tasks.values()):
            if t.status not in {'completed','incomplete','failed','cancelled','timed_out'}:server.service.cancel(t.id)
        server.shutdown();thread.join(timeout=10)
        server.service.shutdown();server.server_close();server.access.close()
        save('settled-tasks',{t.id:{'status':t.status,'result':t.result,'tools':t.tools} for t in server.service.tasks.values()})
        save('private-state-reference',{'directory':str(private),'credentials_recorded':False,'synthetic_workspace':str(workspace)})
        release_model()

if __name__=='__main__':main()
