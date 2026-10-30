"""Trusted-terminal evidence capture over the released HTTP/CLI contract.
Never imported or invoked by the desktop WebView. No Runtime or SQLite access.
"""
from pathlib import Path
(Path(__file__).resolve().parents[1]/'docs/evidence/runs/v0.2.0').mkdir(parents=True,exist_ok=True)
import json,sys,os,re,subprocess
from urllib.request import Request,build_opener,ProxyHandler
ROOT=Path(__file__).resolve().parents[1];HOME=Path.home()/'.local/share/localpilot-desktop-e2e';CLI=Path.home()/'.local/share/localpilot-desktop-runtime/bin/localpilot'
def credentials():
 result={}
 for line in (HOME/'clients.env').read_text().splitlines():
  m=re.fullmatch(r'export ([A-Z][A-Z0-9_]*)=([A-Za-z0-9_-]+)',line)
  if not m:raise ValueError('Invalid private credential grammar')
  result[m[1]]=m[2]
 return result
creds=credentials();connection=json.loads((HOME/'connection.json').read_text());origin=connection['url'];token=creds[connection['token_env']]
def get(path):
 with build_opener(ProxyHandler({})).open(Request(origin+path,headers={'Authorization':'Bearer '+token}),timeout=10) as f:return json.load(f)
command=sys.argv[1] if len(sys.argv)>1 else 'tasks'
if command=='tasks':
 value=get('/localpilot/v1/tasks');(ROOT/'docs/evidence/runs/real-service-tasks.json').write_text(json.dumps(value,ensure_ascii=False,indent=2));print(json.dumps([{'id':t['id'],'model':t['model'],'status':t['status'],'required_action':t.get('required_action'),'verification':t.get('verification_summary')} for t in value['tasks']],ensure_ascii=False,indent=2))
elif command in {'approve','reject','resume'}:
 task=get('/localpilot/v1/tasks/'+sys.argv[2]);action=task.get('required_action') or {}
 if task.get('recovery',{}).get('class')=='UNKNOWN_BLOCKED':raise ValueError('UNKNOWN cannot be replayed')
 aid=action['id'];env={**os.environ,'LOCALPILOT_OPERATOR_TOKEN':creds['LOCALPILOT_OPERATOR_TOKEN']}
 p=subprocess.run([str(CLI),'--home',str(HOME),'--json','task',command,task['id'],'--action-id',aid,'--operator-token-env','LOCALPILOT_OPERATOR_TOKEN'],env=env,capture_output=True,text=True,timeout=30)
 value={'action':command,'action_id':aid,'task_id':task['id'],'exit':p.returncode,'result':json.loads(p.stdout)}
 (ROOT/('docs/evidence/runs/trusted-'+command+'-'+task['id']+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2));print(json.dumps({'task_id':task['id'],'exit':p.returncode,'status':value['result'].get('status')}))
elif command=='events':
 taskid=sys.argv[2]
 with build_opener(ProxyHandler({})).open(Request(origin+'/localpilot/v1/tasks/'+taskid+'/events?after=0',headers={'Authorization':'Bearer '+token}),timeout=30) as f:text=f.read().decode()
 (ROOT/('docs/evidence/runs/real-events-'+taskid+'.sse')).write_text(text);print(json.dumps({'task_id':taskid,'frames':text.count('data:')}))
