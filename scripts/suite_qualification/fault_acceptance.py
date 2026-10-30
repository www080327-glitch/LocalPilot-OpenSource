"""Real HTTP/SQLite and installed CLI; scripted model ONLY for deterministic faults."""
import json,os,secrets,subprocess,threading,time,hashlib
from pathlib import Path
import sys
sys.path.insert(0,str(Path(os.environ.get('LP_RELEASE_ROOT', Path(__file__).resolve().parents[3]))/"core"))
from dataclasses import replace
from unittest.mock import patch
from agent.registry import create_default_registry
from agent.session import AgentSession
from agent.retry import RetryPolicy
from localpilot_api.service import TaskService
from localpilot_service.server import ServiceServer
from localpilot_service.security import AccessPolicy,Principal
from localpilot_service.sdk import Client
from localpilot_service.verification import configured_verifier
from tests.test_runtime_api import Backend,answer,call
ROOT=Path(os.environ.get('LP_RELEASE_ROOT', Path(__file__).resolve().parents[3]));state=ROOT/('private-faults-'+str(int(time.time())));state.mkdir(mode=0o700);workspace=state/'workspace';workspace.mkdir();home=state/'home';home.mkdir(mode=0o700)
CLI=str(ROOT/'fresh-env/bin/localpilot');token=secrets.token_urlsafe(32);operator=secrets.token_urlsafe(32)
env={**os.environ,'LP_FAULT_TOKEN':token,'LP_FAULT_OPERATOR':operator,'LOCALPILOT_DISABLE_LOCAL_MODELS':'1'}
backend=Backend(answer(None,call('apply_patch',{'changes':[{'path':'approved.txt','operation':'create','content':'TRUSTED-APPROVAL-FIXTURE'}]},'write')),answer('TRUSTED-APPROVAL-FIXTURE'))
verifier=configured_verifier(workspace,{'id':'fault-fixture','files':{'approved.txt':hashlib.sha256(b'TRUSTED-APPROVAL-FIXTURE').hexdigest()},'required_text':'TRUSTED-APPROVAL-FIXTURE'})
def factory(cb):return AgentSession(create_default_registry(workspace,permission_mode='approve-mutations'),backend=backend,policy='cloud-only',event_callback=cb,retry_policy=RetryPolicy(max_attempts=1),verification_callback=verifier)
principals=[Principal('http',token),Principal('operator',operator,scopes=frozenset({'read','control','cancel'}),operator=True,approval_for=('http',))]
services=[];report={'evidence_class':'REAL_HTTP_SQLITE_INSTALLED_CLI_SCRIPTED_MODEL','steps':[]};server=None

def start(port=0):
 global server,service,thread,origin
 service=TaskService({'localpilot':factory},persistence=state/'runtime.db');services.append(service);access=AccessPolicy(principals)
 server=ServiceServer(('127.0.0.1',port),service,access=access,catalog={'localpilot':{'adapter':'deepseek','cloud_egress':'CLOUD_ALLOWED','deployment_status':'ready','model':'SCRIPTED_ONLY','prompt_profile':'standard','reasoning_only':False}})
 thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start();origin='http://127.0.0.1:'+str(server.server_port)
 (home/'connection.json').write_text(json.dumps({'url':origin,'token_env':'LP_FAULT_TOKEN'}));(home/'connection.json').chmod(0o600)

def stop():
 server.shutdown();thread.join();server.server_close();server.access.close();service.suspend()

def run(args,ok=(0,),extra=None):
 r=subprocess.run([CLI,'--home',str(home),'--json',*args],env=env|dict(extra or {}),capture_output=True,text=True,timeout=30,cwd=str(state));report['steps'].append({'command':args,'exit':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
 assert r.returncode in ok,report['steps'][-1]
 return json.loads(r.stdout)
try:
 start();client=Client(origin,token=token)
 t=run(['agent','Create approved.txt only after trusted approval.','--key','same-key','--detach'],ok=(0,5));service.wait(t['id']);t=client.status(t['id'])
 assert t['status']=='requires_approval' and not (workspace/'approved.txt').exists()
 old=t['required_action']['id'];report['approval_wait']='PASS'
 run(['task','approve',t['id'],'--action-id',old,'--operator-token-env','LP_FAULT_TOKEN'],ok=(3,));assert not (workspace/'approved.txt').exists();report['ordinary_cannot_approve']='PASS'
 first=next(client.events(t['id']));after=first['data']['sequence'];reconnected=list(client.events(t['id'],after=after));assert all(e['data']['sequence']>after for e in reconnected)
 retry=run(['agent','Create approved.txt only after trusted approval.','--key','same-key','--detach'],ok=(0,5));assert retry['id']==t['id'] and len(backend.requests)==1;report['sse_disconnect_no_mutation_replay']='PASS'
 port=server.server_port;stop();start(port);client=Client(origin,token=token);restored=client.status(t['id']);assert restored['required_action']['id']!=old
 run(['task','approve',t['id'],'--action-id',old,'--operator-token-env','LP_FAULT_OPERATOR'],ok=(4,))
 run(['task','approve',t['id'],'--action-id',restored['required_action']['id'],'--operator-token-env','LP_FAULT_OPERATOR'])
 service.wait(t['id']);done=client.status(t['id']);assert done['status']=='completed' and done['verification_summary']['verification_status']=='passed';assert len(done['tools'])==1;report['restart_fresh_ticket_approval_and_verification']='PASS'
 run(['tasks'],ok=(3,),extra={'LP_FAULT_TOKEN':'wrong-token'});report['bad_token']='PASS'
 from localpilot_service.protocol import manifest
 with patch('localpilot_service.protocol.manifest',return_value={**manifest(),'agent_service_api':'2.0'}):run(['agent','private text must not be submitted','--key','incompatible'],ok=(2,))
 assert len(service.tasks)==1;report['incompatible_api_before_submit']='PASS'
 p=server.access.principals['http'];server.access.principals['http']=replace(p,requests_per_minute=1);server.access.times['http'].clear()
 run(['models'],ok=(7,));report['429']='PASS';server.access.principals['http']=p;server.access.times['http'].clear()
 stop();start(port);client=Client(origin,token=token);assert client.status(t['id'])['status']=='completed';assert len(service.tasks)==1;report['sqlite_history_recovery']='PASS'
 report['status']='PASS';report['model_requests']=len(backend.requests);report['tools_executed']=1
except Exception as e:report.update(status='FAIL',error=type(e).__name__+': '+str(e)[:1000])
finally:
 if server:
  try:stop()
  except Exception:pass
 for s in services:
  if s.store.connection:s.shutdown()
 (ROOT/'evidence/fault-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='steps'},ensure_ascii=False))
