"""Bounded same-Core cloud baseline, approved handoff and actual DSH nesting."""
import argparse,fcntl,hashlib,io,json,os,secrets,subprocess,sys,threading,time
from pathlib import Path
from types import SimpleNamespace
from agent.cloud_credentials import resolve_deepseek_key
from agent.omlx import OMLXBackend
from agent.engine_v5 import EngineV5Policy
from agent.registry import ToolRegistry
from agent.session import AgentSession,SessionBudgets
from agent.hybrid import HybridPolicy,CloudEgressPolicy
from agent.stabilization import HostVerification
from localpilot_api.service import TaskService
from localpilot_service.model_resources import ModelResources
from localpilot_service.security import Principal,AccessPolicy,private_json
from localpilot_service.server import ServiceServer
from localpilot_service.sdk import Client
from localpilot_plugins.manager import PluginManager
from localpilot_plugins.adapter import configure_session
from integration_broker import Broker

def main():
    p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,required=True);p.add_argument('--private',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--key-file',type=Path,required=True);p.add_argument('--settings',type=Path,required=True);p.add_argument('--skip-dsh',action='store_true');p.add_argument('--skip-baselines',action='store_true');p.add_argument('--tls',action='store_true');p.add_argument('--max-total-requests',type=int,default=24);p.add_argument('--prior-budget',type=Path);a=p.parse_args()
    out=a.evidence.resolve();out.mkdir(parents=True,exist_ok=False);home=a.private.resolve();home.mkdir(parents=True,mode=0o700,exist_ok=False)
    def save(n,v):(out/(n+'.json')).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
    prior=json.loads(a.prior_budget.read_text()) if a.prior_budget else {'rows':[],'reserved_usd_peak':0}
    key=resolve_deepseek_key(key_file=a.key_file);broker=Broker(key,out/'broker',limit=.20-prior['reserved_usd_peak'],max_requests=a.max_total_requests-len(prior['rows']),tls=a.skip_dsh or a.tls);key=None
    placeholder=home/'provider-placeholder.key';placeholder.write_text('native-broker-placeholder');placeholder.chmod(0o600)
    settings=private_json(a.settings);token=settings['auth']['api_key'];base=f"http://127.0.0.1:{settings['server']['port']}/v1";model='mlx-community--Qwen3.5-4B-4bit'
    backend=OMLXBackend(base_url=base,model=model,api_key=token,effective_context=131072,chat_template_kwargs={'enable_thinking':False},supports_streaming=False)
    initial=backend.inspect_service();entry=next(v for v in initial['models'] if v['id']==model)
    if initial.get('active_requests')!=0 or any(m.get('loaded') and m['id']!=model and (m.get('size_bytes') or 0)>1500000000 for m in initial['models']):raise RuntimeError('Provider busy; no resource change')
    user=Principal('qualification',secrets.token_urlsafe(32),routes={'local':'local'});operator=Principal('resource',secrets.token_urlsafe(32),operator=True,scopes=frozenset({'resource_control'}),approval_for=('qualification',),routes={})
    resources=ModelResources(SimpleNamespace(access=SimpleNamespace(principals={'qualification':user}),model_backends={'local':backend},service=SimpleNamespace(condition=threading.Condition(),tasks={})),home/'resource-journal.json')
    body={'client_subject':'qualification','model':'local','operation':'load','confirmed':True,'max_memory_bytes':8*1024**3};owned=False;service=None;server=None;http_worker=None
    lock=(Path.home()/'.cache/localpilot-model-qualification.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    results=[]
    try:
        if not entry['loaded']:
            result=resources.operate(operator,body,'cloud-qualification-local-load');save('model-load',result);owned=result.get('status')=='completed'
            if not owned:raise RuntimeError('Model loading not confirmed')
        env={**os.environ,'LP_PRODUCT_OMLX':token}
        if broker.ca_file:env['SSL_CERT_FILE']=str(broker.ca_file)
        for case,extra in ([] if a.skip_baselines else [('fully-cloud',['--provider','cloud','--allow-fixture-egress']),('approved-handoff',['--provider','local','--cooperative','--allow-fixture-egress'])]):
            broker.active=case
            args=[sys.executable,str(a.source/'scripts/qualify_product_e2e.py'),'--evidence',str(out/case),'--model',model,'--key-file',str(placeholder),'--cloud-base-url',f'{broker.scheme}://127.0.0.1:{broker.port}',*extra]
            with (out/(case+'.log')).open('w') as log:r=subprocess.run(args,env=env,cwd='/private/tmp',stdout=log,stderr=log,timeout=720)
            record=json.loads((out/case/'results.json').read_text()) if (out/case/'results.json').exists() else {'status':'NO_RESULT'}
            results.append({'case':case,'exit':r.returncode,'result':record})
        if a.skip_dsh:return
        # Actual DSH -> existing LocalPilot MCP server -> reviewed MCP client.
        caller=home/'caller';caller.mkdir();workspace=home/'workspace';workspace.mkdir();plugins=PluginManager(home/'plugins');source=a.source/'examples/plugins/public_notes/server.py'
        plugins.add({'id':'public-notes','transport':'stdio','command':sys.executable,'args':[str(source)],'source_files':[str(source)],'timeout':15});discovered=plugins.discover('public-notes',source_reviewed=True,license_id='MIT');plugins.review('public-notes',discovered['catalog_sha256'],json.loads((a.source/'examples/plugins/public_notes/review.json').read_text()));plugins.enable('public-notes')
        def factory(callback):
            local=OMLXBackend(base_url=base,model=model,api_key=token,effective_context=131072,chat_template_kwargs={'enable_thinking':False},supports_streaming=False)
            def verify(root,result):
                good='MCP connects hosts to tools, resources and prompts.' in result.text
                return HostVerification('passed' if good else 'failed','fixed_public_plugin_note',{},good,bool(result.text),True)
            runtime=AgentSession(ToolRegistry(workspace,permission_mode='approve-all'),local_backend=local,policy='local-only',streaming=False,event_callback=callback,engine_policy=EngineV5Policy(),runtime_tools=False,strict_task=True,verification_callback=verify,completion_check=lambda root,projection:HostVerification('passed' if any(r['name'].startswith('mcp_') and r['payload'].get('ok') for r in runtime.tool_history) else 'failed','reviewed_plugin_response_receipt',{},True,True,True),hybrid_policy=HybridPolicy(CloudEgressPolicy('LOCAL_ONLY')),hybrid_backends={'local':local},hybrid_primary='local',budgets=SessionBudgets(max_steps=12,max_tool_calls=10,max_subagents_per_turn=0))
            configure_session(runtime,str(home/'plugins'));return runtime
        service=TaskService({'plugin':factory},persistence=home/'tasks.sqlite3');dsh_token=secrets.token_urlsafe(32);host_token=secrets.token_urlsafe(32)
        access=AccessPolicy([Principal('dsh',dsh_token,routes={'public-plugin':'plugin'},requests_per_minute=120),Principal('host',host_token,operator=True,scopes=frozenset({'read','control','cancel'}),approval_for=('dsh',),routes={})],audit_path=home/'audit.jsonl')
        server=ServiceServer(('127.0.0.1',0),service,access=access);http_worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True);http_worker.start();url=f'http://127.0.0.1:{server.server_port}';host=Client(url,token=host_token)
        stop=threading.Event()
        def approve():
            used=set()
            while not stop.wait(.3):
                for task in list(service.tasks.values()):
                    snap=service.task_snapshot(task.id)
                    if snap['status']=='requires_approval':
                        aid=snap['required_action']['id']
                        if aid not in used:
                            used.add(aid);host.continue_task(task.id,aid,action='approve')
        watcher=threading.Thread(target=approve,daemon=True);watcher.start()
        disabled=['session-log-deepseek','plugin-package-inventory-deepseek','session-title-llm','llm-deepseek-account','tool-web','tool-subagent','tool-subagent-fork','tool-subagent-control','tool-subagent-list-agents','tool-workflow','tool-skill','skill-filesystem','agent-instructions','tool-goal','tool-todo','tool-bash','tool-pwsh','tool-read','tool-write','tool-edit','tool-glob','tool-grep']
        patch=''.join(f'- id: {name}\n  disabled: true\n' for name in disabled)+f'''- id: llm-deepseek
  config:
    baseURL: {broker.scheme}://127.0.0.1:{broker.port}
    maxTokens: 2048
    reasoningEffort: off
    retryPolicy:
      mode: normal
      maxRetries: 0
- id: agent-default-model
  config:
    provider: deepseek-official
    model: deepseek-flash
    reasoningEffort: off
- insert:
  - id: localpilot-unified-nested
    name: "@deepseek-ai/dsh-mcp-client"
    config:
      transport: stdio
      serverName: localpilot
      command: {json.dumps(sys.executable)}
      args: ["-m", "localpilot_service.adapter", "--mcp"]
      env:
        LOCALPILOT_URL: !!js process.env.LOCALPILOT_URL
        LOCALPILOT_TOKEN: !!js process.env.LOCALPILOT_TOKEN
        DEEPSEEK_API_KEY: ""
        LOCALPILOT_OPERATOR_TOKEN: ""
      failOnStartupError: true
'''
        overlay=home/'dsh.yml';overlay.write_text(patch);overlay.chmod(0o600)
        prompt='Use only LocalPilot MCP tools. Submit exactly ONE task using model public-plugin, idempotency_key unified-dsh-plugin-v1, origin_agent dsh, parent_task_id unified-integration-20261025. Input: "Use the reviewed public-notes MCP plugin to look up the MCP note. Quote its exact one-sentence note. No files, shell, network, cloud, delegation or other tools." After the one submit, call localpilot_events with limit=100 so it waits for the original SSE stream through termination; then localpilot_result. Avoid polling loops. Follow only the original task until settled. Never approve, continue, change identity or submit a replacement task. Return the real task ID, receipts, task_outcome and exact note. If host denies, report HOST_DENIED and stop.'
        broker.active='dsh-localpilot-reviewed-plugin';dsh='/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh'
        denv={k:v for k,v in env.items() if not any(x in k.upper() for x in ['OPERATOR','RESOURCE_TOKEN','PRODUCT_OMLX','UNIFIED_OMLX'])};denv.update(DEEPSEEK_API_KEY='native-broker-placeholder',LOCALPILOT_URL=url,LOCALPILOT_TOKEN=dsh_token)
        dsh_home=home/'dsh-home';dsh_home.mkdir(mode=0o700);tmp=dsh_home/'tmp';tmp.mkdir()
        denv.update(HOME=str(dsh_home),TMPDIR=str(tmp))
        if broker.ca_file:denv['NODE_EXTRA_CA_CERTS']=str(broker.ca_file)
        reads=[home.resolve(),Path(sys.base_prefix).resolve(),*([broker.ca_file.resolve()] if broker.ca_file else [])]
        ancestors={p for root in reads for p in root.parents}
        q=lambda p:json.dumps(str(p),ensure_ascii=False)
        excluded=['(require-not (subpath '+q(p)+'))' for p in reads]+['(require-not (literal '+q(p)+'))' for p in ancestors]
        rules=['(version 1)','(allow default)',
            '(deny file-read* (require-all (subpath '+q(Path.home())+') '+' '.join(excluded)+'))',
            '(deny file-write* (require-all (require-not (subpath '+q(home)+')) (require-not (literal "/dev/null")) (require-not (literal "/dev/tty"))))',
            '(deny network-outbound (require-all (require-not (remote ip "localhost:'+str(broker.port)+'")) (require-not (remote ip "localhost:'+str(server.server_port)+'"))))']
        profile=home/'dsh.sb';profile.write_text('\n'.join(rules)+'\n')
        try:r=subprocess.run(['/usr/bin/sandbox-exec','-f',str(profile),dsh,'headless','--patch',str(overlay),'--json',prompt],cwd=caller,env=denv,capture_output=True,text=True,timeout=300);raw=r.stdout+'\n'+r.stderr;exit_code=r.returncode
        except subprocess.TimeoutExpired as e:raw=(e.stdout or b'').decode() if isinstance(e.stdout,bytes) else e.stdout or '';exit_code='HOST_TIMEOUT'
        raw=raw.replace(dsh_token,'[REDACTED_LOCAL_CLIENT_TOKEN]').replace(host_token,'[REDACTED_HOST_TOKEN]').replace(token,'[REDACTED_PROVIDER_TOKEN]');(out/'dsh-raw.jsonl').write_text(raw)
        stop.set();watcher.join(5);tasks=[service.task_snapshot(t.id) for t in service.tasks.values()];save('dsh-tasks',tasks)
        good=exit_code==0 and len(tasks)==1 and tasks[0]['status']=='completed' and tasks[0].get('result',{}).get('task_outcome')=='passed' and any(t['name'].startswith('mcp_') for t in tasks[0]['tools'])
        results.append({'case':'actual_dsh_localpilot_reviewed_plugin','exit':exit_code,'status':'PASS' if good else 'FAIL','tasks':len(tasks)})
    except Exception as e:results.append({'case':'runner_exception','status':'FAIL','error_type':type(e).__name__,'message':str(e)[:300]})
    finally:
        if server:
            for t in list(service.tasks.values()):
                if t.status not in {'completed','incomplete','failed','cancelled','timed_out'}:service.cancel(t.id)
            server.shutdown();http_worker.join(5);service.shutdown();server.server_close();server.access.close()
        if owned:save('model-unload',resources.operate(operator,{**body,'operation':'unload'},'cloud-qualification-local-unload'))
        broker.close();fcntl.flock(lock,fcntl.LOCK_UN);lock.close();save('RESULTS',{'cases':results,'cloud_limit_usd_peak':.20,'prior_reserved_usd_peak':prior['reserved_usd_peak'],'actual_invoice':'UNKNOWN'});print(json.dumps(results,ensure_ascii=False))

if __name__=='__main__':main()
