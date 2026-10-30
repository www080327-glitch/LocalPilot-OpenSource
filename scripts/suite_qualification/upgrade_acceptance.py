"""Real independent package replacement, migration order, rollback and data preservation."""
import json,os,subprocess,hashlib,time,socket
from pathlib import Path
ROOT=Path(os.environ.get('LP_RELEASE_ROOT', Path(__file__).resolve().parents[3]));PYTHON=str(ROOT/'upgrade-env/bin/python');CLI=str(ROOT/'upgrade-env/bin/localpilot')
state=ROOT/('private-upgrade-'+str(int(time.time())));state.mkdir(mode=0o700);workspace=state/'workspace';workspace.mkdir();home=state/'home'
env={**os.environ,'LOCALPILOT_DISABLE_LOCAL_MODELS':'1'};records=[]
def run(args,ok=(0,)):
 r=subprocess.run(args,env=env,capture_output=True,text=True,timeout=60,cwd=str(state));records.append({'command':args[1:],'exit':r.returncode,'stdout':r.stdout[-5000:],'stderr':r.stderr[-1000:]})
 (ROOT/'evidence/upgrades.json').write_text(json.dumps(records,indent=2))
 assert r.returncode in ok,records[-1]
 return r
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
run([CLI,'--home',str(home),'--json','init','--workspace',str(workspace),'--model','NOT_LOADED','--port',str(port)])
(home/'user-sentinel.txt').write_text('user data must survive upgrade and reinstall')
protected=['clients.env','service.json','connection.json','companion.json','user-sentinel.txt']
before={f:hashlib.sha256((home/f).read_bytes()).hexdigest() for f in protected}
def pip(*args):return run([PYTHON,'-m','pip',*args])
old_companion=str(ROOT/'previous/dist/localpilot_companion-0.5.4-py3-none-any.whl');old_core=str(ROOT/'previous/dist/localpilot_agent_service-4.9.1rc2-py3-none-any.whl')
new_companion=str(ROOT/'dist/localpilot_companion-0.5.5rc1-py3-none-any.whl');new_core=str(ROOT/'dist/localpilot_agent_service-4.9.2rc1-py3-none-any.whl')
# Old Companion is genuinely installed; no rebuilt historical version labels.
pip('install','--no-index','--no-deps',old_companion)
run([CLI,'--home',str(home),'--json','companion','start']);run([CLI,'--home',str(home),'--json','companion','ask','你好']);run([CLI,'--home',str(home),'--json','companion','stop'])
run([CLI,'--home',str(home),'upgrade','companion','--wheel',new_companion,'--previous-wheel',old_companion,'--execute'])
# Rollback to the old consumer, then restore; compatibility rejection against new Core is a known migration gate.
run([CLI,'--home',str(home),'upgrade','companion','--wheel',old_companion,'--previous-wheel',new_companion,'--execute'])
run([CLI,'--home',str(home),'upgrade','companion','--wheel',new_companion,'--previous-wheel',old_companion,'--execute'])
pip('install','--no-index','--no-deps',old_core)
run([CLI,'--version'])
# Thin Suite upgrade still works when the old Core has no unified CLI module.
run([CLI,'--home',str(home),'upgrade','core','--wheel',new_core,'--previous-wheel',old_core,'--execute'])
run([CLI,'--home',str(home),'--json','start']);run([CLI,'--home',str(home),'--json','stop'])
run([CLI,'--home',str(home),'upgrade','core','--wheel',old_core,'--previous-wheel',new_core,'--execute'])
run([CLI,'--home',str(home),'--json','doctor'],ok=(4,))
run([CLI,'--home',str(home),'upgrade','core','--wheel',new_core,'--previous-wheel',old_core,'--execute'])
pip('uninstall','-y','localpilot-companion')
pip('install','--no-index','--no-deps',new_companion)
run([PYTHON,'-m','pip','check'])
after={f:hashlib.sha256((home/f).read_bytes()).hexdigest() for f in protected};assert before==after
(ROOT/'evidence/upgrades-summary.json').write_text(json.dumps({'status':'PASS_INSTALLATION_AND_DATA_PRESERVATION','protected_file_count':len(protected),'hashes_unchanged':before==after,'independent_companion_replacements':4,'core_rollback':'old Core lacks new CLI; suite reports incompatibility, upgrade path works','runtime_database_migration':'NOT_RUN_REAL_MODEL_STATE'},indent=2))
print('independent replacements, rollback/recovery, uninstall/reinstall and data hashes passed')
