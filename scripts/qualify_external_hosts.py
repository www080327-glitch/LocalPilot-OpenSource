"""Actual Codex HTTP Skill invocation and installed DSH host through MCP."""
import argparse,hashlib,json,os,re,secrets,shutil,subprocess,sys,threading,time,uuid
from pathlib import Path
from localpilot_service.deployment import build
from localpilot_service.cli import save
from localpilot_service.sdk import Client

def main():
    p=argparse.ArgumentParser();p.add_argument('--evidence',required=True);p.add_argument('--skill',required=True);p.add_argument('--dsh-key-file');a=p.parse_args()
    out=Path(a.evidence).resolve();out.mkdir(parents=True,exist_ok=False)
    private=Path.home()/'.local/share/localpilot-5-validation'/('adapters-'+uuid.uuid4().hex);private.mkdir(parents=True,mode=0o700)
    workspace=private/'workspace';workspace.mkdir();marker='ADAPTER-'+secrets.token_hex(6);(workspace/'fixture.txt').write_text(marker)
    caller=private/'caller';caller.mkdir();skill=caller/'.agents/skills/localpilot-agent';skill.parent.mkdir(parents=True);shutil.copytree(a.skill,skill)
    keys={n:secrets.token_urlsafe(32) for n in ['LP_EXTERNAL_CODEX','LP_EXTERNAL_DSH','LP_EXTERNAL_OPERATOR']};os.environ.update(keys)
    route={'workspace':str(workspace),'engine':'v5','backend':{'kind':'deepseek-native','model':'deepseek-flash','key_file':str(Path.home()/'Desktop/aic竞赛/LocalPilot/.localpilot/secrets/deepseek.key'),'timeout':45},'thinking':'none','permissions':'approve-mutations','capabilities':{'read':True,'write':False,'execute':False,'read_only':True},'cloud_egress':'REQUIRES_APPROVAL','cloud_egress_paths':['fixture.txt'],'cache_stable_prefix':True,'budgets':{'max_steps':6,'max_output_tokens':512},'verification':{'id':'external-host-random-marker','files':{'fixture.txt':hashlib.sha256(marker.encode()).hexdigest()},'required_text':marker}}
    config={'schema_version':1,'port':0,'data_dir':str(private/'data'),'clients':[{'subject':'codex','token_env':'LP_EXTERNAL_CODEX'},{'subject':'dsh','token_env':'LP_EXTERNAL_DSH'},{'subject':'operator','token_env':'LP_EXTERNAL_OPERATOR','operator':True,'scopes':['read','control','cancel'],'approval_for':['codex','dsh'],'routes':{}}],'routes':{'localpilot':route}}
    save(private/'service.json',config);server=build(private/'service.json');thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True);thread.start()
    origin='http://127.0.0.1:'+str(server.server_port);operator=Client(origin,token=keys['LP_EXTERNAL_OPERATOR']);stop=threading.Event();grants=[]
    def approve():
        while not stop.wait(1):
            try:
                for t in operator.request('/localpilot/v1/tasks')['tasks']:
                    if t['status']=='requires_approval':
                        requests=t['required_action'].get('requests',[])
                        if requests and requests[0].get('kind')=='cloud_egress':
                            grants.append({'task':t['id'],'action':t['required_action']['id'],'scope':'this exact public-fixture request only'})
                            operator.continue_task(t['id'],t['required_action']['id'],action='approve')
            except Exception:pass
    watcher=threading.Thread(target=approve,daemon=True);watcher.start()
    safe={k:v for k,v in os.environ.items() if not k.startswith('LP_EXTERNAL') and not any(s in k.upper() for s in ['OPERATOR','RESOURCE']) and k not in {'DEEPSEEK_API_KEY','OMLX_API_KEY','LOCALPILOT_OMLX_API_KEY'}}
    safe.update(LOCALPILOT_URL=origin,LOCALPILOT_DISABLE_LOCAL_MODELS='1')
    adapter=str(skill/'scripts/localpilot_adapter.py');question='Use read_file to read fixture.txt and return its exact marker. Do not use shell or modify files.'
    report={'evidence_kind':'REAL_CLOUD_MODEL_AND_ACTUAL_ADAPTER_HOSTS','local_inference':False,'operator_credential_given_to_callers':False}
    try:
        env={**safe,'LOCALPILOT_TOKEN':keys['LP_EXTERNAL_CODEX']}
        submit=subprocess.run([sys.executable,adapter,'localpilot_submit','--arguments',json.dumps({'input':question,'idempotency_key':'codex-actual-host'})],env=env,capture_output=True,text=True,timeout=30,cwd=caller)
        assert submit.returncode==0;task=json.loads(submit.stdout)
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            result=subprocess.run([sys.executable,adapter,'localpilot_status','--arguments',json.dumps({'task_id':task['id']})],env=env,capture_output=True,text=True,timeout=15,cwd=caller)
            done=json.loads(result.stdout)
            if done['quiescent'] and done['status'] in {'completed','incomplete','failed','cancelled','timed_out'}:break
            time.sleep(1)
        report['codex_http_skill']={'pass':done['status']=='completed' and done['verification_summary']['verification_status']=='passed' and any(t['name']=='read_file' for t in done['tools']),'task':done,'caller':'current authorized Codex session invokes packaged Skill HTTP adapter'}
        patch=private/'mcp.yml';patch.write_text('- insert:\n  - id: localpilot-v5-mcp-acceptance\n    name: "@deepseek-ai/dsh-mcp-client"\n    config:\n      transport: stdio\n      serverName: localpilot\n      command: '+json.dumps(sys.executable)+'\n      args: ['+json.dumps(adapter)+', "--mcp"]\n      env:\n        LOCALPILOT_URL: !!js process.env.LOCALPILOT_URL\n        LOCALPILOT_TOKEN: !!js process.env.LOCALPILOT_TOKEN\n      failOnStartupError: true\n      reconnect:\n        maxAttempts: 1\n');patch.chmod(0o600)
        patch.write_text(patch.read_text().replace('      failOnStartupError:', '        DEEPSEEK_API_KEY: ""\n        DEEPSEEK_API_KEY_FILE: ""\n        LOCALPILOT_OPERATOR_TOKEN: ""\n        LOCALPILOT_RESOURCE_TOKEN: ""\n      failOnStartupError:'))
        prompt='Use the provided localpilot-agent Skill. Only access the workspace through its LocalPilot MCP tools. Submit exactly one task with localpilot_submit: input '+json.dumps(question)+' and idempotency_key dsh-actual-host. Poll the same task no faster than once per second. An independent host will approve exact public-fixture cloud requests. Never approve tools, read credentials, execute shell, or create another task. Return the task ID, marker, receipts and verification. If permission or credentials are unavailable, report that refusal.'
        dsh='/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh'
        dsh_env={**safe,'LOCALPILOT_TOKEN':keys['LP_EXTERNAL_DSH']};dsh_key=None
        if a.dsh_key_file:
            from agent.cloud_credentials import resolve_deepseek_key
            dsh_key=resolve_deepseek_key(key_file=a.dsh_key_file);dsh_env['DEEPSEEK_API_KEY']=dsh_key
            report['dsh_provider_credential_scope']='existing private file, process-only, not persisted, removed from MCP child environment'
        try:
            result=subprocess.run([dsh,'headless','--patch',str(patch),'--json',prompt],env=dsh_env,capture_output=True,text=True,timeout=180,cwd=caller)
            raw=result.stdout+'\n'+result.stderr
            for key in keys.values():raw=raw.replace(key,'[REDACTED_SERVICE_CREDENTIAL]')
            if dsh_key:raw=raw.replace(dsh_key,'[REDACTED_PROVIDER_CREDENTIAL]')
            raw=re.sub(r'sk-[A-Za-z0-9_-]{16,}','[REDACTED_PROVIDER_CREDENTIAL]',raw)
            (out/'dsh-host-redacted.log').write_text(raw)
            tasks=[operator.status(t['id']) for t in operator.request('/localpilot/v1/tasks')['tasks'] if t.get('service',{}).get('client_subject')=='dsh']
            report['dsh_actual_mcp']={'exit':result.returncode,'pass':len(tasks)==1 and tasks[0]['status']=='completed' and tasks[0]['verification_summary']['verification_status']=='passed' and any(r['name']=='read_file' for r in tasks[0]['tools']),'tasks':tasks}
        except subprocess.TimeoutExpired:report['dsh_actual_mcp']={'pass':False,'status':'HOST_TIMEOUT_NOT_PASSED'}
        report['independent_cloud_approvals']=grants
    finally:
        stop.set();watcher.join(timeout=3)
        for task in list(server.service.tasks.values()):
            if task.status not in {'completed','incomplete','failed','cancelled','timed_out'}:server.service.cancel(task.id)
        server.shutdown();thread.join(timeout=5);server.service.shutdown();server.server_close();server.access.close()
        (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:({'pass':v.get('pass')} if isinstance(v,dict) else v) for k,v in report.items() if k!='independent_cloud_approvals'},ensure_ascii=False))

if __name__=='__main__':main()
