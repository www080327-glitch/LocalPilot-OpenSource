"""Real provider proposals against generated public fixtures; approvals stay native."""
from pathlib import Path
import argparse,json,time,uuid
from localpilot_service.cli import environment
from localpilot_service.security import private_json
from localpilot_service.sdk import Client
p=argparse.ArgumentParser();p.add_argument('--home',type=Path,required=True);p.add_argument('--stage',choices=['propose','collect'],required=True);p.add_argument('--case');p.add_argument('--run-id',default='post-hybrid');a=p.parse_args()
home=a.home;env=environment(home);url=private_json(home/'connection.json')['url'];c=Client(url,token=env['LOCALPILOT_HTTP_TOKEN']);o=Client(url,token=env['LOCALPILOT_OPERATOR_TOKEN'])
out=Path('docs/evidence/stability-20261025');record=out/'real-task-proposals.json'
if a.stage=='propose':
 outside=(out/'fixtures/outside').resolve();outside.mkdir(exist_ok=True)
 specs=[('organize','workspace','Use only file tools to organize the generated public fixture. Inspect source.txt, create sorted, move source.txt to sorted/source.txt with its real SHA-256, copy it to copied.txt with the same hash, then inspect both targets. Never overwrite, delete, delegate, or use Shell. Report actual receipts and verification.'),
 ('outside','request','Use apply_patch to create exactly '+str(outside/'approved.txt')+' with exactly OUTSIDE-STABILITY. This is the generated public test file outside the workspace. Propose that one operation and wait for host approval; never use another path or tool.'),
 ('shell','request','Use the shell tool exactly once with command "printf SHELL-STABILITY > shell.txt; sleep 12" and access workspace. Wait for host approval. Then read shell.txt to check the bytes. Do not use execute, other commands, networking or other paths.'),
 ('network','full','Use http_get exactly once on https://api.github.com/zen. Wait for its separate exact URL approval. No other URLs, request data, uploads, Shell or file access. Report the actual tool status; do not invent a response body.'),
 ('reject','request','Use apply_patch to create exactly '+str(outside/'rejected.txt')+' with exactly REJECT-MUST-NOT-EXIST. Propose the action and wait for host approval. If denied, stop without another model/tool attempt or alternative path.')]
 rows=json.loads(record.read_text()) if record.exists() else []
 for name,mode,prompt in specs:
  if a.case and name!=a.case:continue
  if any(row['name']==name for row in rows):continue
  s=o.request('/localpilot/v1/desktop-sessions',{'client_subject':'http','model':'stability','source':'balanced','options':{'permission_mode':mode,'agent_profile':'standard'}},key='native-acceptance-final-'+name+'-'+a.run_id)
  t=c.submit(prompt,session_id=s['id'],model='stability',idempotency_key='real-native-final-'+name+'-'+a.run_id,timeout_seconds=900)
  rows.append({'name':name,'task_id':t['id'],'session_id':s['id']})
  record.write_text(json.dumps(rows,indent=2)+'\n')
 record.write_text(json.dumps(rows,indent=2)+'\n')
else:rows=json.loads(record.read_text())
for row in rows:
 if a.case and row['name']!=a.case:continue
 deadline=time.monotonic()+100
 while True:
  t=c.status(row['task_id'])
  if (t.get('quiescent') and t['status'] not in {'queued','running','cancelling'}) or time.monotonic()>deadline:break
  time.sleep(.25)
 (out/('real-'+row['name']+'-'+a.stage+'.json')).write_text(json.dumps(t,ensure_ascii=False,indent=2)+'\n')
 print(row['name'],t['id'],t['status'],len(t.get('tools',[])),flush=True)
