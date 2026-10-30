"""Independent trusted-terminal checks; never imported into the Desktop application.
Only reads existing ordinary/operator credential references. No credential values are exported.
"""
import json,re,sys,subprocess,os,time
from pathlib import Path
(Path(__file__).resolve().parents[1]/'docs/evidence/runs/v0.2.0').mkdir(parents=True,exist_ok=True)
from urllib.request import Request,build_opener,ProxyHandler
root=Path(__file__).resolve().parents[1];home=Path.home()/'.local/share/localpilot-desktop-e2e';out=root/'docs/evidence/runs/v0.2.0'
config=json.loads((home/'connection.json').read_text());creds={m[1]:m[2] for m in re.finditer(r'^export ([A-Z_][A-Z0-9_]*)=([A-Za-z0-9_-]+)$',(home/'clients.env').read_text(),re.M)}
origin=config['url'];opener=build_opener(ProxyHandler({}));token=creds[config['token_env']]
def get(path):
 with opener.open(Request(origin+path,headers={'Authorization':'Bearer '+token}),timeout=10) as f:return json.load(f)
args=sys.argv[1:];cmd=args[0] if args else 'snapshot';tasks=get('/localpilot/v1/tasks')['tasks'];latest=max(tasks,key=lambda t:t['created_at'])
if cmd=='snapshot':
 name=args[1] if len(args)>1 else 'current'
 value={'task_count':len(tasks),'task_ids':[t['id'] for t in tasks],'latest':latest}
 (out/(name+'.json')).write_text(json.dumps(value,indent=2,ensure_ascii=False));print(json.dumps({'task_count':len(tasks),'latest':{k:latest.get(k) for k in ['id','status','session_id']},'model_calls':len((latest.get('result') or {}).get('model_calls',[]))}))
elif cmd=='approve-latest':
 if latest['status']!='requires_approval' or any(r.get('kind')!='cloud_egress' for r in latest['required_action']['requests']):raise ValueError('Only approve current public question cloud egress fixture')
 if latest['model']!='deepseek-question':raise ValueError('Expected pure question route')
 aid=latest['required_action']['id'];env={**os.environ,'LOCALPILOT_OPERATOR_TOKEN':creds['LOCALPILOT_OPERATOR_TOKEN']}
 cli=Path.home()/'.local/share/localpilot-desktop-runtime/bin/localpilot'
 result=subprocess.run([str(cli),'--home',str(home),'--json','task','approve',latest['id'],'--action-id',aid,'--operator-token-env','LOCALPILOT_OPERATOR_TOKEN'],env=env,capture_output=True,text=True,timeout=30)
 (out/'trusted-cloud-approval.json').write_text(json.dumps({'exit':result.returncode,'task_id':latest['id'],'action_id':aid,'result':json.loads(result.stdout)},indent=2,ensure_ascii=False));print(json.dumps({'exit':result.returncode,'task_id':latest['id']}))
