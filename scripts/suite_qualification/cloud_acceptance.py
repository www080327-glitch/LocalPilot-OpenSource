import os
"""Bounded REAL DeepSeek + installed Core/Companion API, synthetic public fixture only.
No Qwen inference; no claim of full Qwen -> DeepSeek acceptance.
"""
import contextlib,io,json,os,secrets,sys,time,threading,hashlib
from pathlib import Path
ROOT=Path(os.environ.get('LP_RELEASE_ROOT', Path(__file__).resolve().parents[3]))
os.environ['LOCALPILOT_DISABLE_LOCAL_MODELS']='1'
from localpilot_service.deployment import build
from localpilot_service.sdk import Client
from localpilot_service.cli import save,main as cli
from companion.config import Config
from companion.escalation.service_v491 import LocalPilotProvider
from companion.escalation.provider import EscalationRequest
state=ROOT/('private-cloud-'+str(int(time.time())));state.mkdir(mode=0o700)
workspace=state/'workspace';workspace.mkdir();(workspace/'fixture.txt').write_text('SUITE-CLOUD-FIXTURE-20261021\n')
key_path=Path(os.environ.get('DEEPSEEK_API_KEY_FILE',''))
if not key_path.is_file():
 (ROOT/'evidence/cloud-acceptance.json').write_text(json.dumps({'status':'NOT_RUN','reason':'existing protected provider credential unavailable'}));sys.exit(0)
for k in ['LP_ACCEPT_HTTP','LP_ACCEPT_COMPANION']:os.environ[k]=secrets.token_urlsafe(32)
base={'workspace':str(workspace),'backend':{'kind':'deepseek','model':'deepseek-flash','key_file':str(key_path),'timeout':40},
 'thinking':'none','cache_stable_prefix':True,'cloud_egress':'CLOUD_ALLOWED','cloud_egress_paths':['fixture.txt'],
 'permissions':'approve-mutations','capabilities':{'read':True,'write':False,'execute':False,'read_only':True},'budgets':{'max_steps':4}}
reasoning={**base,'prompt_profile':'minimal_0','tool_profile':'compact','reasoning_only':True,'capabilities':{'read':False,'write':False,'execute':False}}
agent={**base,'verification':{'id':'suite-current-file','files':{'fixture.txt':hashlib.sha256((workspace/'fixture.txt').read_bytes()).hexdigest()},'required_text':'SUITE-CLOUD-FIXTURE-20261021'}}
config={'schema_version':1,'host':'127.0.0.1','port':0,'data_dir':str(state/'data'),'clients':[
 {'subject':'http','token_env':'LP_ACCEPT_HTTP','routes':{'localpilot':'agent','companion-reasoning':'reasoning'}},
 {'subject':'companion','token_env':'LP_ACCEPT_COMPANION','routes':{'localpilot':'reasoning','companion-reasoning':'reasoning'}}],
 'routes':{'agent':agent,'reasoning':reasoning}}
save(state/'service.json',config)
report={'evidence_class':'REAL_CLOUD_HTTP_SQLITE_INSTALLED_PACKAGES','local_models':'NOT_RUN_OPERATOR_DISABLED','provider':'deepseek-flash','tasks':[], 'permission_scope':'read synthetic fixture only; no operator token present','ui_consent':'driver trusted consent injection; popup MANUAL_REQUIRED','billing_cost':'UNKNOWN_NO_BILLING_API','ttft':'UNKNOWN_NOT_IN_PROVIDER_USAGE'}
server=None
try:
 server=build(state/'service.json');thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.1},daemon=True);thread.start()
 origin='http://127.0.0.1:'+str(server.server_port)
 home=state/'cli';home.mkdir(mode=0o700);save(home/'connection.json',{'url':origin,'token_env':'LP_ACCEPT_HTTP'})
 # A real CLI submit streams native SSE and returns trusted verification.
 stdout=io.StringIO();start=time.monotonic()
 with contextlib.redirect_stdout(stdout):rc=cli(['--home',str(home),'--json','agent','Read fixture.txt with read_file and return its exact marker. Do not write or execute.','--key','real-cloud-read'])
 values=[json.loads(x) for x in stdout.getvalue().splitlines()];task=values[-1]
 report['cli']={'exit':rc,'elapsed_seconds':time.monotonic()-start,'event_count':len(values)-1,'task_id':task.get('id')}
 report['tasks'].append(task)
 assert task['status']=='completed',task
 assert task['verification_summary']['verification_status']=='passed',task
 assert any(t['name']=='read_file' for t in task['tools']),task['tools']
 # Same submission key never repeats a paid provider request or tool.
 client=Client(origin,token=os.environ['LP_ACCEPT_HTTP']);before=len(task['result']['model_calls'])
 retry=client.submit('Read fixture.txt with read_file and return its exact marker. Do not write or execute.',model='localpilot',idempotency_key='real-cloud-read')
 assert retry['id']==task['id'];report['durable_idempotency']='PASS'
 cfg=Config(data_dir=str(state/'companion'),backend='disabled',localpilot_endpoint=origin,localpilot_api_key_env='LP_ACCEPT_COMPANION',localpilot_host_local_only=False,localpilot_allow_cloud=True,low_power_policy='always')
 provider=LocalPilotProvider(cfg)
 q=EscalationRequest('What is 17 plus 25? Answer with the number only.','suite_public_fixture','question_only', [{'text':'PRIVATE-MEMORY-CANARY'}],[{'text':'PRIVATE-OBSERVATION-CANARY'}],[{'text':'PRIVATE-FILE-CANARY'}],{'classification':'PUBLIC','local_only':False},'PRIVATE-SUMMARY-CANARY')
 denied=provider.submit(q,approved=True,cloud_approved=False,mode='reasoning',submission_id='refused-cloud')
 assert denied.get('submission_attempted') is False and len(server.service.tasks)==1,denied
 report['cloud_refusal_no_task']='PASS'
 for i in range(2):
  start=time.monotonic();view=provider.submit(q,approved=True,cloud_approved=True,mode='reasoning',submission_id='consult-'+str(i))
  assert view.get('task_id'),view
  server.service.wait(view['task_id']);result=provider.status(view['task_id'],cloud_approved=True);raw=client if False else server.service.task_snapshot(view['task_id'])
  report['tasks'].append(raw)
  # Inspect retained messages at the actual provider boundary, not estimated text similarity.
  session=server.service._session(raw['session_id']).runtime
  all_text='\n'.join(m.content or '' for m in session.messages)
  assert 'PRIVATE-' not in all_text,all_text
  assert not raw['tools'] and raw['status']=='completed',raw
  report.setdefault('consultations',[]).append({'status':raw['status'],'answer':result.get('agent_response'),'elapsed_seconds':time.monotonic()-start,'local_canaries_egressed':False,'tools':0})
 report['status']='PASS_SCOPED_CLOUD_ONLY'
except Exception as exc:
 report['status']='FAIL';report['failure']=type(exc).__name__+': '+str(exc)[:1000]
finally:
 if server:
  server.shutdown();thread.join(3);server.service.shutdown();server.server_close();server.access.close()
 (ROOT/'evidence/cloud-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps({'status':report.get('status'),'tasks':len(report['tasks']),'failure':report.get('failure')}))
