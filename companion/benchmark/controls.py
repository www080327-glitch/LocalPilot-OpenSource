"""Real daemon/HTTP/file-event reliability checks. No model stub passes as ability."""
from dataclasses import asdict
from datetime import datetime,timezone
import json
from pathlib import Path
import time

from companion.cli import client,start,stop
from companion.config import Config
from companion.memory import MemoryStore
from companion.triggers import NoticePolicy


def run(output):
    base=Path(__file__).resolve().parents[1]/'.data'/('controls-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));docs=base/'documents';docs.mkdir(parents=True)
    budget=docs/'budget.txt';budget.write_text('项目：星河\n预算：10万\n')
    filename=base/'config.json';filename.write_text(json.dumps(asdict(Config()) | {'data_dir':str(base/'state'),'watch_dirs':[str(docs)],'backend':'disabled','quiet_start_hour':0,'quiet_end_hour':0}))
    config=Config.load(filename);result={'base_dir':str(base),'model_capability':'NOT_TESTED: backend disabled in these host controls','actions':{}}
    try:
        result['start']=start(config,filename)
        initial=client(config,{'command':'ask','text':'星河现在预算多少？'});result['initial_budget']=initial
        event_count=client(config,{'command':'status'})['observed_events'];budget.write_text('项目：星河\n预算：15万\n')
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            status=client(config,{'command':'status'})
            if status['observed_events']>event_count:break
            time.sleep(.5)
        result['real_file_event']=status['observed_events']>event_count
        result['updated_budget']=client(config,{'command':'ask','text':'星河现在预算多少？'})
        before=client(config,{'command':'retrieve','text':'星河预算'})['memories']
        result['first_stop']=stop(config);start(config,filename)
        after=client(config,{'command':'retrieve','text':'星河预算'})['memories']
        result['restart_same_ids']=[r['id'] for r in before]==[r['id'] for r in after]
        result['restart_budget']=client(config,{'command':'ask','text':'星河现在预算多少？'})
        # Four explicitly labelled scaffold notices test transport/actions, not unsolicited relevance.
        for action in ('ignore','useful','mute','help'):
            store=MemoryStore(base/'state'/'memory.sqlite3')
            nid=NoticePolicy(config,store).record('fixture_'+action,'fixture_'+action,'Synthetic feedback control')
            store.close()
            reply=client(config,{'command':'notice_action','id':nid,'action':action,'text':'请帮我修改预算文件'})
            result['actions'][action]=reply
        result['endpoint_absent']=result['actions']['help']['escalation']['status']=='unavailable'
        client(config,{'command':'escalate','text':'请修改预算文件'})
        budget.write_text('项目：星河\n预算：20万\n')
        result['stale_escalation_rejected']=client(config,{'command':'submit_escalation','approved':True})
        store=MemoryStore(base/'state'/'memory.sqlite3')
        result['persisted_feedback']=store.get('notice_feedback');result['historical_versions']=store.db.execute('SELECT count(*) FROM source_versions').fetchone()[0];store.close()
        result['acceptance']={'budget10_before': '10万' in initial['text'],
            'real_file_event':result['real_file_event'], 'budget15_after': '15万' in result['updated_budget']['text'] and '10万' not in result['updated_budget']['text'],
            'budget15_restart':'15万' in result['restart_budget']['text'],'same_ids_after_restart':result['restart_same_ids'],
            'all_actions':all(v['status'] in {'ok','escalation'} for v in result['actions'].values()),
            'mute_persisted':result['persisted_feedback']['fixture_mute']['muted'],
            'help_unavailable':result['endpoint_absent'],
            'changed_escalation_refused':result['stale_escalation_rejected']['status']=='unavailable' and 'changed' in result['stale_escalation_rejected'].get('reason','')}
    finally:
        result['stop']=stop(config);result['runtime_record_removed']=not (base/'state'/'runtime.json').exists()
        Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    if not all(result['acceptance'].values()) or not result['runtime_record_removed']:raise AssertionError(result['acceptance'])
    print(json.dumps(result['acceptance'],ensure_ascii=False))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);run(p.parse_args().output)
