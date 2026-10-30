"""Read-only online dev.17 snapshot; private restore, no tasks or model requests."""
import argparse,hashlib,json,os,sqlite3,subprocess,sys
from pathlib import Path
from localpilot_suite.product_backup import backup,restore
from localpilot_service.security import private_json
from localpilot_service.cli import environment
from localpilot_service.sdk import Client
from agent.persistence import unpack

def main():
    p=argparse.ArgumentParser();p.add_argument('--private',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--bundle',type=Path,required=True);a=p.parse_args();private=a.private.resolve();private.mkdir(mode=0o700,parents=True,exist_ok=False);a.evidence.mkdir(parents=True,exist_ok=False)
    profile=private_json(Path.home()/'Library/Application Support/io.localpilot.desktop/profile.json');source=Path(profile['home']);before=hashlib.sha256((source/'service.json').read_bytes()).hexdigest();target=private/'restored';report={'classification':'ACTUAL_DEV17_USER_DATA_PRIVATE_COPY_NO_EGRESS','model_requests':0,'user_messages_exported':False,'daily_service_stopped':False,'cases':[]}
    def record(name,good,detail):report['cases'].append({'case':name,'status':'PASS' if good else 'FAIL','detail':detail})
    def run(args):
        env={k:v for k,v in os.environ.items() if k not in {'PYTHONHOME','PYTHONPATH'}};env['PYTHONDONTWRITEBYTECODE']='1'
        r=subprocess.run([str(a.bundle/'localpilot'),'--home',str(target),'--json',*args],env=env,cwd=private,capture_output=True,text=True,timeout=80)
        try:value=json.loads(r.stdout)
        except ValueError:value={'exit':r.returncode,'error_type':'non_json_response'}
        return r.returncode,value
    try:
        backup(source,private/'snapshot');restore(private/'snapshot',target)
        old_tasks={};old_owners={}
        with sqlite3.connect((private/'snapshot/core.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
            for (raw,) in db.execute('SELECT payload FROM checkpoints'):
                data=json.loads(raw)
                for row in data.get('tasks',[]):
                    t=unpack(row);old_owners[t['id']]=data['session'].get('owner_subject');old_tasks[t['id']]=hashlib.sha256(str((t.get('result')or{}).get('text','')).encode()).hexdigest()
        record('online_snapshot_and_restore',True,{'historical_tasks':len(old_tasks),'original_config_unchanged':hashlib.sha256((source/'service.json').read_bytes()).hexdigest()==before})
        memory_counts={}
        with sqlite3.connect((private/'snapshot/companion.sqlite3').as_uri()+'?mode=ro',uri=True) as old,sqlite3.connect((target/'companion-data/memory.sqlite3').as_uri()+'?mode=ro',uri=True) as new:
            for (table,) in old.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                if not table.replace('_','').isalnum():continue
                count=old.execute('SELECT count(*) FROM "'+table+'"').fetchone()[0];count2=new.execute('SELECT count(*) FROM "'+table+'"').fetchone()[0];memory_counts[table]=[count,count2]
        record('companion_memory_tables_preserved',all(a==b for a,b in memory_counts.values()),{'tables_compared':len(memory_counts),'all_counts_equal':all(a==b for a,b in memory_counts.values())})
        config=private_json(target/'companion.json');config.update(backend='disabled',watch_dirs=[],native_observation_enabled=False,notifications=False,proactive_level='off',proactive_delivery='silent');(target/'companion.json').write_text(json.dumps(config));(target/'companion.json').chmod(0o600)
        # Only the private restored observer is disabled for this no-inference audit.
        code,value=run(['desktop-init','--workspace',str(private/'workspace')]);record('both_restored_services_ready',code==0 and value.get('status')=='ready' and value.get('companion_ready')is True,{'exit':code,'status':value.get('status'),'companion_ready':value.get('companion_ready'),'error':value.get('error')})
        if code==0 and value.get('status')=='ready':
            connection=private_json(target/'connection.json');token=environment(target)[connection['token_env']];client=Client(connection['url'],token=token)
            values=client.request('/localpilot/v1/tasks')['tasks'];new={t['id']:hashlib.sha256(str((t.get('result')or{}).get('text','')).encode()).hexdigest() for t in values}
            subject=client.request('/healthz')['client_subject'];expected={k:v for k,v in old_tasks.items() if old_owners[k]==subject}
            record('historical_results_visible',all(new.get(k)==v for k,v in expected.items()),{'expected_for_authenticated_subject':len(expected),'visible':len(new),'unchanged_result_text_hashes':sum(new.get(k)==v for k,v in expected.items()),'other_subject_history_remains_private':True})
            run(['companion','stop']);run(['stop']);code,value=run(['desktop-init','--workspace',str(private/'workspace')]);record('restored_restart',code==0 and value.get('status')=='ready' and value.get('companion_ready')is True,{'status':value.get('status')})
    except Exception as e:record('exception',False,{'error_type':type(e).__name__,'message':str(e)[:200]})
    finally:
        for args in [['companion','stop'],['service-unregister']]:
            try:run(args)
            except Exception:pass
        report['original_config_unchanged']=hashlib.sha256((source/'service.json').read_bytes()).hexdigest()==before
        (a.evidence/'RESULTS.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
