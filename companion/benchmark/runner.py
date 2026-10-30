"""python -m companion.benchmark.runner --model-path ... --output ...
Frozen diagnostic cases; raw model failures never get replaced by rule replies.
"""
import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

from companion.benchmark.decisions import parse_decision,guard
from companion.benchmark.fixtures import make_corpus,DAY0
from companion.benchmark.scoring import score,aggregate,confusion
from companion.cli import client,start,stop
from companion.config import Config,PrivateData
from companion.memory import MemoryStore,LexicalRetriever,BM25Retriever
from companion.memory.retrieval import terms
from companion.model import ModelManager
from companion.observers.documents import extract,extractive_summary
from companion.observers import ReadScope

HERE=Path(__file__).parent


def digest(file):return hashlib.sha256(file.read_bytes()).hexdigest()


def load_suite():
    expected=(HERE/'suite.sha256').read_text().strip()
    if digest(HERE/'suite.json')!=expected:raise ValueError('Frozen benchmark hash mismatch; create a new suite version')
    return json.loads((HERE/'suite.json').read_text()),expected


def model_identity(config):
    identity={'backend':config.backend,'model_path':config.model_path,'http_model_name':config.http_model_name,
              'http_endpoint':config.http_model_endpoint,'python':sys.version,'hardware':platform.platform(),
              'packages':{}}
    for name in ('mlx-lm','mlx','transformers','pypdf','psutil','python-docx','python-pptx','openpyxl','reportlab'):
        try:identity['packages'][name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:identity['packages'][name]=None
    if config.backend=='mlx':
        root=Path(config.model_path).expanduser();identity['revision']=root.name
        identity['artifacts_sha256']={p.name:digest(p) for p in sorted(root.iterdir()) if p.is_file() and p.suffix in {'.json','.safetensors','.jinja'}}
        identity['quantization']=json.loads((root/'config.json').read_text()).get('quantization')
    return identity


def build_store(base):
    docs=base/'documents';files=make_corpus(docs)
    private=PrivateData(base/'state');store=MemoryStore(private.file('memory.sqlite3'))
    for i,file in enumerate(files):
        data=file.read_bytes();document=extract(data,file.suffix)
        store.replace_document(str(file),hashlib.sha256(data).hexdigest(),file.stat().st_mtime_ns,document,extractive_summary(document),DAY0+(i%3)*86400+i)
    current=docs/'星河'/'project.txt';current.write_text(current.read_text().replace('10万','15万').replace('状态：立项','状态：整理材料'),encoding='utf-8')
    document=extract(current.read_bytes(),'.txt')
    store.replace_document(str(current),digest(current),current.stat().st_mtime_ns,document,extractive_summary(document),DAY0+4*86400)
    store.add('reflection','星河访谈可能已经完成','companion_reflection',epistemic='reflection',confidence=.2,timestamp=DAY0+4*86400)
    store.add('summary','星河用户大概去过上海','model_summary',epistemic='inferred',confidence=.3,timestamp=DAY0+4*86400)
    store.add('user_fact','喜欢jadegreen颜色','explicit_user_statement',timestamp=DAY0)
    return store,docs,files


def canonical_context(rows):
    return [{'file':Path(r['source_reference']).name,'sha256':r.get('provenance',{}).get('file_hash'),
             'evidence_class':r.get('provenance',{}).get('evidence_class',r['epistemic']),
             'location':r.get('provenance',{}).get('source_location',[]),'text':r['summary'],
             'conflicts':[{'older_value':c['older_value'],'newer_value':c['newer_value'],'key':c['claim_key']} for c in r.get('conflicts',[])]} for r in rows]


def oracle_rows(store,case):
    retriever=BM25Retriever(store)
    records=[r for r in store.records(10000,['document']) if store.is_current(r) and Path(r['source_reference']).name in case['files']]
    return retriever.pack(records,terms(case['query']),5,8000)


def retrieval_comparison(store,suite):
    result={}
    for name,cls in [('lexical',LexicalRetriever),('bm25',BM25Retriever)]:
        retriever=cls(store);cases=[];times=[]
        import tracemalloc
        tracemalloc.start()
        for case in suite['cases']:
            if case['category']!='memory':continue
            start_at=time.perf_counter();rows=retriever.retrieve(case['query'],5,3760);times.append(time.perf_counter()-start_at)
            actual={Path(r['source_reference']).name for r in rows if r['type']=='document'};gold=set(case['files']);hits=len(actual&gold)
            cases.append({'id':case['id'],'expected':sorted(gold),'actual':sorted(actual),'recall':hits/len(gold),'precision':hits/len(actual) if actual else 0})
        _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        result[name]={'cases':cases,'recall':sum(c['recall'] for c in cases)/len(cases),
                      'precision':sum(c['precision'] for c in cases)/len(cases),'mean_latency_seconds':sum(times)/len(times),
                      'python_peak_bytes':peak,'index_bytes':None,'index_size_status':'UNKNOWN: dbstat unavailable in bundled SQLite','whole_database_bytes':store.db.execute('PRAGMA page_count').fetchone()[0]*store.db.execute('PRAGMA page_size').fetchone()[0]}
    a,b=result['lexical'],result['bm25']
    result['retain_bm25']=b['recall']>a['recall'] and b['precision']>=a['precision'] and b['mean_latency_seconds']<=max(.1,2*a['mean_latency_seconds'])
    return result


def run_case(case,suite,model,rows=(),id_prefix='',category=None):
    cat=case['category']
    if cat in {'disturbance','escalation'}:prompt=suite['templates'][cat].format(query=case['query'])
    elif rows or cat in {'memory','document'}:prompt=suite['templates']['context'].format(context=json.dumps(canonical_context(rows),ensure_ascii=False,sort_keys=True),query=case['query'])
    else:prompt=case['query']
    messages=[{'role':'system','content':suite['system']},{'role':'user','content':prompt}]
    result=model.complete(messages,max_tokens=case['max_tokens'])
    row={'id':id_prefix+case['id'],'category':category or cat,'query':case['query'],'expected':case.get('expected'),
         'prompt_sha256':hashlib.sha256(json.dumps(messages,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
         'prompt':messages,'result':result,'context':canonical_context(rows),'scores':score(case,result)}
    if cat=='disturbance':
        decision=parse_decision(result);row.update(format_valid=decision is not None,prediction=decision['action'] if decision else 'quiet',guarded_prediction=guard(case['event'],decision))
    if cat=='escalation':
        decision=result.get('text','').strip().lower();valid=result.get('status')=='ok' and decision in {'local','agent'}
        row.update(format_valid=valid,prediction=decision if valid else 'local')
    return row


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model-path',default='');p.add_argument('--config');p.add_argument('--output',required=True)
    p.add_argument('--retrieval',choices=['lexical','bm25'],default='lexical');p.add_argument('--offline',action='store_true')
    args=p.parse_args();suite,sha=load_suite()
    out=Path(args.output).resolve();out.parent.mkdir(parents=True,exist_ok=True)
    base=Path(__file__).resolve().parents[1]/'.data'/('benchmark-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    base.mkdir(parents=True)
    store,docs,files=build_store(base)
    evidence={'schema_version':1,'suite_version':suite['version'],'suite_sha256':sha,
              'generation':suite['generation'],'retrieval_records':5,'retrieval_chars':3760,'started_utc':datetime.now(timezone.utc).isoformat(),
              'kind':'offline_retrieval' if args.offline else 'real_model','retrieval_backend':args.retrieval,'base_dir':str(base),'rows':[],'oracle_rows':[],
              'source_sha256':{str(f.relative_to(HERE.parent)):digest(f) for f in HERE.parent.rglob('*.py') if not any(x in f.parts for x in ('.venv','.data','build'))}}
    evidence['fixture_sha256']={str(f.relative_to(docs)):digest(f) for f in files}
    evidence['retrieval_comparison']=retrieval_comparison(store,suite)
    raw=asdict(Config.load(args.config) if args.config else Config()) | {'data_dir':str(base/'state'),'watch_dirs':[str(docs)],'dnd':True,'retrieval_backend':args.retrieval,
        'notifications':False,'summarize_documents':False,'port':0,'model_context_tokens':suite['generation']['context_tokens'],
        'max_output_tokens':max(c['max_tokens'] for c in suite['cases']),'retrieval_records':5,'retrieval_chars':4000}
    if args.model_path:raw.update(backend='mlx',model_path=str(Path(args.model_path).expanduser()))
    filename=base/'config.json';filename.write_text(json.dumps(raw,ensure_ascii=False,indent=2));config=Config.load(filename)
    model=None
    try:
        if not args.offline:
            evidence['identity']=model_identity(config)
            evidence['identity_sha256']=hashlib.sha256(json.dumps(evidence['identity'],sort_keys=True).encode()).hexdigest()
            model=ModelManager(config)
            scope=ReadScope(config)
            retriever=(BM25Retriever if args.retrieval=='bm25' else LexicalRetriever)(store,source_allowed=lambda r:r['type'] not in {'document','computer_event','project','summary'} or scope.within(r['source_reference']))
            for case in suite['cases']:
                rows=oracle_rows(store,case) if case['category']=='document' else retriever.retrieve(case['query'],5,min(config.retrieval_chars,(config.model_context_tokens-config.max_output_tokens-512)//2)) if case['category']=='memory' else []
                row=run_case(case,suite,model,rows);evidence['rows'].append(row)
                if case['category']=='memory':
                    evidence['oracle_rows'].append(run_case(case,suite,model,oracle_rows(store,case),id_prefix='oracle-'))
                out.write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
                print(row['id'],row['result']['status'],row['scores'].get('fact_recall'),flush=True)
            # A new daemon and a new model worker repeat ALL ten key memory cases.
            model.unload();store.close();store=None
            daemon_raw=raw | {'backend':'disabled'};filename.write_text(json.dumps(daemon_raw,ensure_ascii=False,indent=2));daemon=Config.load(filename)
            start(daemon,filename)
            before={c['id']:client(daemon,{'command':'retrieve','text':c['query']})['memories'] for c in suite['cases'] if c['category']=='memory'}
            evidence['first_daemon_stop']=stop(daemon);start(daemon,filename)
            after={c['id']:client(daemon,{'command':'retrieve','text':c['query']})['memories'] for c in suite['cases'] if c['category']=='memory'}
            evidence['persistence']={key:{'before_ids':[r['id'] for r in value],'after_ids':[r['id'] for r in after[key]],
                'same_ids':[r['id'] for r in value]==[r['id'] for r in after[key]]} for key,value in before.items()}
            stop(daemon)
            for case in suite['cases']:
                if case['category']=='memory':
                    evidence['rows'].append(run_case(case,suite,model,after[case['id']],id_prefix='restart-',category='restart'))
            evidence['metrics']=aggregate(evidence['rows']);evidence['oracle_metrics']=aggregate(evidence['oracle_rows'])
            evidence['metrics'].update(idle_memory=model.stats()['worker_rss_bytes'],model_wakeups=model.stats()['model_wakes_total'],model_invocations=model.stats()['inferences'])
            evidence['restart_prompts_equal']={r['id']:r['prompt_sha256']==next(x['prompt_sha256'] for x in evidence['rows'] if x['id']=='restart-'+r['id']) for r in evidence['rows'] if r['category']=='memory'}
            # Actual product routes, with genuine model use where the host does not route early.
            from companion.runtime.service import Companion
            product=Companion(config)
            try:
                evidence['product_escalation']=[]
                for case in suite['cases']:
                    if case['category']=='escalation':
                        answer=product.ask(case['query']);evidence['product_escalation'].append({'id':case['id'],'expected':case['expected'],'prediction':'agent' if answer['status']=='escalation' else 'local','answer':answer})
            finally:
                product.model.unload();product.store.close();product.lock.close();product.channel.server.server_close()
        if evidence.get('product_escalation'):
            evidence['product_escalation_confusion']=confusion(evidence['product_escalation'],positive=lambda s:s=='agent')
        evidence['status']='completed'
    except BaseException as exc:
        evidence['status']='failed';evidence['error']=f'{type(exc).__name__}: {exc}'
        raise
    finally:
        if model:model.unload()
        if store:store.close()
        try:stop(Config.load(filename))
        except Exception:pass
        out.write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
        with out.with_suffix('.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['id','category','status','expected','prediction','format_valid','fact_recall','detected_hallucination','source_traceability','latency_seconds','text'])
            writer.writeheader()
            for r in evidence['rows']:
                writer.writerow({'id':r['id'],'category':r['category'],'status':r['result']['status'],'expected':r.get('expected'),'prediction':r.get('prediction'),'format_valid':r.get('format_valid'),
                    'fact_recall':r['scores']['fact_recall'],'detected_hallucination':r['scores']['detected_hallucination'],'source_traceability':r['scores'].get('source_traceability'),
                    'latency_seconds':r['result'].get('latency_seconds'),'text':r['result'].get('text','')})
    print(str(out),flush=True)

if __name__=='__main__':main()
