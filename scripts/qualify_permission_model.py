"""Real provider proposals; never auto approves. GUI handles pending test actions."""
from pathlib import Path
import json,time
from localpilot_service.cli import environment
from localpilot_service.sdk import Client
home=Path.home()/'.local/share/localpilot-permission-parity-20261024';env=environment(home)
client=Client('http://127.0.0.1:48763',token=env['LOCALPILOT_HTTP_TOKEN']);operator=Client('http://127.0.0.1:48763',token=env['LOCALPILOT_OPERATOR_TOKEN'])
out=Path('docs/evidence/desktop-permission-parity-20261024');outside=(out/'gui/outside').resolve()
report=[]
for name,mode in [('approve-v2','request'),('reject-v2','request')]:
 target=outside/(name+'.txt')
 session=operator.request('/localpilot/v1/desktop-sessions',{'client_subject':'http','model':'desktop-parity','source':'balanced','options':{'permission_mode':mode,'agent_profile':'standard'}},key='model-scope-session-'+name)
 prompt='This is a generated public acceptance fixture. Use apply_patch to create the exact file '+str(target)+' with exactly "PARITY-'+name+'\\n". This path is outside the workspace: propose the file operation so the host can request one-operation approval. Do not change any other files or request a persistent grant. No shell, delegation or alternative paths. Stop and wait for approval. Once permitted, execute the approved action and report its actual result.'
 start=time.monotonic();task=client.submit(prompt,session_id=session['id'],model='desktop-parity',idempotency_key='model-scope-'+name)
 deadline=time.monotonic()+100
 while time.monotonic()<deadline:
  task=client.status(task['id'])
  if task['quiescent'] and task['status'] not in {'queued','running','cancelling'}:break
  time.sleep(.25)
 (out/f'model-{name}-before.json').write_text(json.dumps(task,indent=2,ensure_ascii=False)+'\n')
 report.append({'name':name,'task':task['id'],'session':task['session_id'],'status':task['status'],'target':str(target),'target_exists_before_approval':target.exists(),'seconds_to_yield':time.monotonic()-start,'provider':'actual configured deepseek-flash','approval':'NOT_AUTO_APPROVED'})
(out/'model-proposals-v2.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n');print(json.dumps(report,ensure_ascii=False))
