"""Current Codex host -> supplied HTTP Skill adapter; actual DSH host -> MCP.
All LocalPilot permissions remain read-only and use synthetic public data.
"""
import json,os,secrets,sys,time,threading,subprocess,shutil,hashlib
from pathlib import Path
ROOT=Path(os.environ.get('LP_RELEASE_ROOT', Path(__file__).resolve().parents[3]))
from localpilot_service.deployment import build
from localpilot_service.cli import save
state=ROOT/('private-adapters-'+str(int(time.time())));state.mkdir(mode=0o700)
workspace=state/'workspace';workspace.mkdir();(workspace/'fixture.txt').write_text('SUITE-EXTERNAL-FIXTURE')
caller=state/'caller';caller.mkdir();skill=caller/'.agents/skills/localpilot-agent';skill.parent.mkdir(parents=True);shutil.copytree(ROOT/'core/localpilot-agent',skill)
for k in ['LP_CODEX_EXTERNAL','LP_DSH_EXTERNAL']:os.environ[k]=secrets.token_urlsafe(32)
route={'workspace':str(workspace),'backend':{'kind':'deepseek','model':'deepseek-flash','key_file':os.environ.get('DEEPSEEK_API_KEY_FILE'),'timeout':40},'thinking':'none','prompt_profile':'standard','tool_profile':'full','cache_stable_prefix':True,'cloud_egress':'CLOUD_ALLOWED','cloud_egress_paths':['fixture.txt'],'permissions':'approve-mutations','capabilities':{'read':True,'write':False,'execute':False,'read_only':True},'budgets':{'max_steps':4},'verification':{'id':'external-synthetic','files':{'fixture.txt':hashlib.sha256(b'SUITE-EXTERNAL-FIXTURE').hexdigest()},'required_text':'SUITE-EXTERNAL-FIXTURE'}}
config={'schema_version':1,'host':'127.0.0.1','port':0,'data_dir':str(state/'data'),'clients':[{'subject':'codex','token_env':'LP_CODEX_EXTERNAL'},{'subject':'dsh','token_env':'LP_DSH_EXTERNAL'}],'routes':{'localpilot':route}}
save(state/'service.json',config)
report={'model_evidence':'REAL_DEEPSEEK_IF_TASK_SUBMITTED','local_models':'DISABLED','operator_credentials':'ABSENT','tasks':[]}
server=None
try:
 server=build(state/'service.json');thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True);thread.start()
 origin='http://127.0.0.1:'+str(server.server_port);adapter=str(skill/'scripts/localpilot_adapter.py');python=str(ROOT/'fresh-env/bin/python')
 env={**os.environ,'LOCALPILOT_URL':origin,'LOCALPILOT_TOKEN':os.environ['LP_CODEX_EXTERNAL'],'LOCALPILOT_DISABLE_LOCAL_MODELS':'1'}
 text='Read fixture.txt through read_file and return its exact marker. No other tools.'
 r=subprocess.run([python,adapter,'localpilot_submit','--arguments',json.dumps({'input':text,'idempotency_key':'codex-suite-external'})],env=env,capture_output=True,text=True,timeout=60,cwd=str(caller))
 assert r.returncode==0,r.stderr;task=json.loads(r.stdout);server.service.wait(task['id'])
 r=subprocess.run([python,adapter,'localpilot_status','--arguments',json.dumps({'task_id':task['id']})],env=env,capture_output=True,text=True,timeout=20,cwd=str(caller));done=json.loads(r.stdout)
 report['tasks'].append(done);report['codex_http_current_host']={'status':'PASS' if done['status']=='completed' and done['verification_summary']['verification_status']=='passed' else 'FAIL','outer_caller':'this authorized Codex session via tool-executed portable Skill HTTP adapter; no nested Codex model'}
 patch=state/'mcp.patch.yml'
 patch.write_text('- insert:\n  - id: suite-localpilot-mcp\n    name: "@deepseek-ai/dsh-mcp-client"\n    config:\n      transport: stdio\n      serverName: localpilot\n      command: '+json.dumps(python)+'\n      args: ['+json.dumps(adapter)+', "--mcp"]\n      env:\n        LOCALPILOT_URL: !!js process.env.LOCALPILOT_URL\n        LOCALPILOT_TOKEN: !!js process.env.LOCALPILOT_TOKEN\n      failOnStartupError: true\n      reconnect:\n        maxAttempts: 1\n')
 patch.chmod(0o600)
 dsh='/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh'
 env['LOCALPILOT_TOKEN']=os.environ['LP_DSH_EXTERNAL']
 prompt='Use the localpilot-agent Skill in .agents/skills/localpilot-agent/SKILL.md. Only use the LocalPilot MCP tools. Submit exactly one task using localpilot_submit with input '+json.dumps(text)+' and idempotency_key dsh-suite-external. Poll localpilot_status on the same task. Do not approve, continue, execute shell commands, read credentials, or use other tools. Report task ID, marker, receipts and verification. If host permissions or cloud credentials are missing, report the refusal; do not bypass it.'
 try:
  result=subprocess.run([dsh,'headless','--patch',str(patch),'--json',prompt],env=env,capture_output=True,text=True,timeout=120,cwd=str(caller))
  raw=result.stdout+'\n'+result.stderr
  # Raw host transcripts remain private; only a redacted transcript is exported.
  for key in [os.environ['LP_DSH_EXTERNAL'],os.environ['LP_CODEX_EXTERNAL']]:raw=raw.replace(key,'[REDACTED_SERVICE_TOKEN]')
  (ROOT/'evidence/dsh-host-redacted.log').write_text(raw)
  tasks=[server.service.task_snapshot(t.id) for t in server.service.tasks.values() if server.service._session(t.session_id).owner_subject=='dsh']
  for t in tasks:server.service.wait(t['id'])
  tasks=[server.service.task_snapshot(t['id']) for t in tasks];report['tasks'].extend(tasks)
  report['dsh_host_mcp']={'exit':result.returncode,'tasks_submitted':len(tasks),'status':'PASS' if tasks and all(t['status']=='completed' and t['result']['verification_status']=='passed' for t in tasks) else 'FAIL_OR_NOT_RUN_HOST_REFUSAL','raw_transcript':'dsh-host-redacted.log'}
 except subprocess.TimeoutExpired:
  report['dsh_host_mcp']={'status':'NOT_RUN_TIMEOUT','timeout_seconds':120}
except Exception as exc:report['driver_failure']=type(exc).__name__+': '+str(exc)[:800]
finally:
 if server:
  server.shutdown();thread.join(2);server.service.shutdown();server.server_close();server.access.close()
 (ROOT/'evidence/external-adapters.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps({k:v for k,v in report.items() if k!='tasks'},ensure_ascii=False))
