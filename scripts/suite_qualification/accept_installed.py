"""Installed CLI/service acceptance: no inference until explicit cloud-only stage."""
import json,os,subprocess,time,socket,hashlib,sys
from pathlib import Path
ROOT=Path(os.environ.get('LP_RELEASE_ROOT', Path(__file__).resolve().parents[3]))
ENV={**os.environ,'LOCALPILOT_DISABLE_LOCAL_MODELS':'1','PYTHONDONTWRITEBYTECODE':'1'}
PYTHON=str(ROOT/'fresh-env/bin/python');CLI=str(ROOT/'fresh-env/bin/localpilot')
state=ROOT/('private-acceptance-'+str(int(time.time())));state.mkdir(mode=0o700,exist_ok=True)
home=state/'home';workspace=state/'workspace';workspace.mkdir(exist_ok=True)
(workspace/'fixture.txt').write_text('SUITE-SYNTHETIC-20261021\n')
records=[]
def run(args,ok=(0,),timeout=40):
 result=subprocess.run([CLI,'--home',str(home),'--json',*args],env=ENV,capture_output=True,text=True,timeout=timeout,cwd=str(state))
 value={'args':args,'exit':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
 records.append(value)
 (ROOT/'evidence/installed-cli.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
 if result.returncode not in ok:raise AssertionError(value)
 try:return json.loads(result.stdout)
 except ValueError:return value
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
try:
 run(['init','--workspace',str(workspace),'--model','not-loaded','--port',str(port)])
 # No inferred model availability is permitted.
 run(['doctor'],ok=(0,1))
 run(['start']);run(['status']);run(['models']);run(['tasks'])
 run(['ask','你好'],ok=(2,)) # battery guard before local model request
 run(['companion','start']);a=run(['companion','ask','你好'])
 assert a['model']['status']=='not_called',a
 run(['companion','status'])
 run(['companion','stop']);run(['restart']);run(['tasks']);run(['stop'])
 # Existing init must not overwrite any existing key/data.
 before={n:hashlib.sha256((home/n).read_bytes()).hexdigest() for n in ['service.json','clients.env','connection.json']}
 run(['init','--workspace',str(workspace),'--model','different'],ok=(2,))
 assert before=={n:hashlib.sha256((home/n).read_bytes()).hexdigest() for n in before}
 # Real occupied port: safe startup failure, owner process unaffected.
 with socket.socket() as s:
  s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
  s.bind(('127.0.0.1',port));s.listen()
  run(['start'],ok=(1,2))
 print('installed non-model acceptance passed')
finally:
 for args in [['companion','stop'],['stop']]:
  try:run(args,ok=(0,1,2))
  except Exception:pass
