"""900-second real installed-service idle soak; no real model calls, no observers."""
import json,os,sys,time,subprocess,socket,sqlite3
from pathlib import Path
import psutil
ROOT=Path(os.environ.get('LP_RELEASE_ROOT', Path(__file__).resolve().parents[3]))
CLI=str(ROOT/'fresh-env/bin/localpilot');home=ROOT/('private-soak-'+str(int(time.time())));workspace=home/'workspace'
home.mkdir(mode=0o700);workspace.mkdir();data=home/'app';data.mkdir(mode=0o700)
env={**os.environ,'LOCALPILOT_DISABLE_LOCAL_MODELS':'1'}
def cli(args):
 r=subprocess.run([CLI,'--home',str(data),'--json',*args],env=env,capture_output=True,text=True,timeout=30,cwd=str(home))
 if r.returncode:raise RuntimeError(str((args,r.returncode,r.stdout[-1000:],r.stderr[-300:])))
 return json.loads(r.stdout)
samples=[];start=time.monotonic();report={'evidence_class':'REAL_SERVICE_IDLE_NO_MODEL','target_seconds':900}
try:
 with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
 cli(['init','--workspace',str(workspace),'--model','NOT_LOADED','--port',str(port)])
 core=cli(['start']);companion=cli(['companion','start'])
 pid=core['pid'];runtime=json.loads((data/'companion-data/runtime.json').read_text());cpid=runtime['pid']
 while time.monotonic()-start<900:
  c=cli(['status']);a=cli(['companion','ask','你好'])
  assert a['model']['status']=='not_called'
  row={'elapsed_seconds':time.monotonic()-start,'core_rss':psutil.Process(pid).memory_info().rss,'companion_rss':psutil.Process(cpid).memory_info().rss,'core_cpu':sum(psutil.Process(pid).cpu_times()[:2]),'companion_cpu':sum(psutil.Process(cpid).cpu_times()[:2]),'core_log_bytes':(data/'service.log').stat().st_size,'companion_log_bytes':(data/'companion-data/service.log').stat().st_size,'active_tasks':c['service'].get('active_task_count')}
  samples.append(row)
  (ROOT/'evidence/soak-progress.json').write_text(json.dumps({'samples':samples,'elapsed_seconds':row['elapsed_seconds'],'status':'RUNNING'},indent=2))
  time.sleep(30)
 report['status']='PASS_IDLE_ONLY'
except Exception as exc:report.update(status='FAIL',error=type(exc).__name__+': '+str(exc)[:500])
finally:
 for args in [['companion','stop'],['stop']]:
  try:cli(args)
  except Exception as e:report.setdefault('cleanup_errors',[]).append(type(e).__name__)
 report.update(elapsed_seconds=time.monotonic()-start,samples=samples,real_model_calls=0)
 for name,path in [('core',data/'data/runtime.sqlite3'),('companion',data/'companion-data/memory.sqlite3')]:
  if path.exists():
   conn=sqlite3.connect(path);report[name+'_sqlite_integrity']=conn.execute('PRAGMA integrity_check').fetchone()[0];conn.close()
 (ROOT/'evidence/soak-final.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='samples'}))
