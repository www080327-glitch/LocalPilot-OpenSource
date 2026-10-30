"""One real consultation verifying the final exact-original-question transport."""
from pathlib import Path
import json,os,sys,threading,time
ROOT=Path(os.environ.get('LP_RELEASE_ROOT',Path(__file__).resolve().parents[3]))
# Reuse only the already-reviewed cloud test's configuration construction.
source=(ROOT/'cloud_acceptance.py').read_text().split('report={',1)[0]
exec(compile(source,str(ROOT/'cloud_acceptance.py'),'exec'),globals())
report={'evidence_class':'REAL_DEEPSEEK_EXACT_QUESTION_WIRE','local_models':'DISABLED','tasks':[]};server=None
try:
 server=build(state/'service.json');thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start();origin='http://127.0.0.1:'+str(server.server_port)
 cfg=Config(data_dir=str(state/'companion'),backend='disabled',localpilot_endpoint=origin,localpilot_api_key_env='LP_ACCEPT_COMPANION',localpilot_host_local_only=False,localpilot_allow_cloud=True)
 provider=LocalPilotProvider(cfg)
 q=EscalationRequest('What is 17 plus 25? Answer with the number only.','LOCAL-INTENT-CANARY','LOCAL-REASON-CANARY',[{'text':'LOCAL-MEMORY-CANARY'}],[{'text':'LOCAL-OBSERVATION-CANARY'}],[{'text':'LOCAL-FILE-CANARY'}],{'classification':'PUBLIC','local_only':False},'LOCAL-SUMMARY-CANARY')
 denied=provider.submit(q,approved=True,cloud_approved=False,mode='reasoning',submission_id='exact-denied');assert denied.get('submission_attempted') is False and not server.service.tasks
 start=time.monotonic();v=provider.submit(q,approved=True,cloud_approved=True,mode='reasoning',submission_id='exact-consult');assert v.get('task_id'),v
 server.service.wait(v['task_id']);t=server.service.task_snapshot(v['task_id']);report['tasks'].append(t)
 messages=server.service._session(t['session_id']).runtime.messages
 user_messages=[m.content for m in messages if m.role=='user']
 assert user_messages==[q.user_request],user_messages
 assert all('CANARY' not in (m.content or '') for m in messages)
 assert t['status']=='completed' and not t['tools'],t
 report.update(status='PASS',user_messages=user_messages,local_metadata_sent=False,answer=t['result']['text'],elapsed_seconds=time.monotonic()-start,cloud_decline_no_task=True)
except Exception as e:report.update(status='FAIL',error=type(e).__name__+': '+str(e)[:500])
finally:
 if server:server.shutdown();thread.join();server.service.shutdown();server.server_close();server.access.close()
 (ROOT/'evidence/exact-cloud-wire.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='tasks'}))
