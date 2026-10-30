#!/usr/bin/env python3
"""Reproducible local file/anchor/performance acceptance; no LLM self-grading."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import statistics
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from localpilot_service.documents import DocumentEngine, Budgets
from localpilot_service.documents.vision import prepare
from tests.document_fixtures import make
from tests.test_document_engine import LocalScript
from agent.backends import BackendCapabilities
from agent.hybrid import CloudEgressPolicy


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    private=output/'.private';private.mkdir(mode=0o700)
    inputs=private/'fixtures';files=make(inputs)
    large=inputs/'large.txt'
    large.write_text(('ORBIT increment checkpoint '+'a'*998+'\n')*6000)
    files.append(large)
    engine=DocumentEngine(private/'store')
    import psutil
    before=psutil.Process().memory_info().rss;peak=[before];stop=threading.Event()
    def monitor():
        while not stop.wait(.02):peak[0]=max(peak[0],psutil.Process().memory_info().rss)
    watcher=threading.Thread(target=monitor);watcher.start()
    records=[];ids={};started=time.perf_counter()
    batch=engine.ingest('qualification','qualification',[str(f) for f in files])
    ingest_seconds=time.perf_counter()-started
    try:
        for f in batch['files']:
            aid=f['id'];ids[f['name']]=aid
            t=time.perf_counter();r=engine.process('qualification','qualification',aid);first=time.perf_counter()-t
            t=time.perf_counter();cached=engine.process('qualification','qualification',aid);warm=time.perf_counter()-t
            records.append({'name':f['name'],'size':f['size'],'sha256':f['sha256'],'status':r['status'],
                            'nodes':r['parsed_nodes'],'parse_index_wall_seconds':first,'worker_parser_seconds':r['parser_seconds'],
                            'sqlite_index_seconds':r['index_seconds'],'worker_peak_rss_bytes':r['peak_worker_rss'],
                            'cache_lookup_seconds':warm,'cache_hit':cached['cache_hit']})
        # Ground truth is specified independently in the fixture generator, not by a model.
        queries=[('approved budget','report.pdf',{'page':2},'240'),('Ship the adapter','plan.docx',{'paragraph':3},'Friday'),
                 ('240','budget.xlsx',{'sheet':'ORBIT Budget','cell':'B3'},'240'),
                 ('Milestone Alpha','status.pptx',{'slide':1},'Alpha'),('Approved amount','status.pptx',{'slide':2},'240'),
                 ('comma,name','data.csv',{'row':3,'column':1},'comma,name'),
                 ('budget','data.json',{'line':1},'240'),('跨文档','readme.md',{'line':2},'240')]
        checks=[];latencies=[]
        for query,name,anchor,quote in queries:
            t=time.perf_counter();result=engine.search('qualification','qualification',query,limit=20);latencies.append(time.perf_counter()-t)
            matching=[n for n in result['hits'] if n['attachment_id']==ids[name] and all(n['anchor'].get(k)==v for k,v in anchor.items()) and quote in n['text']]
            verified=bool(matching and engine.verify('qualification','qualification',matching[0]['citation'],quote)['verified'])
            checks.append({'query':query,'expected_file':name,'expected_anchor':anchor,'hit_at_20':bool(matching),'exact_citation_verified':verified})
        class Vision(LocalScript):capabilities=BackendCapabilities(supports_vision=True)
        t=time.perf_counter();_,packet=prepare(engine,'qualification','qualification',[ids[n] for n in ['red.png','blue.jpg','green.webp']],
                                               'Compare the three images',Vision(),CloudEgressPolicy('LOCAL_ONLY'))
        image_seconds=time.perf_counter()-t
        report={'scope':'actual parsers/processes/SQLite and synthetic independently specified file contents; no real model inference',
                'budgets':asdict(Budgets()),'files':records,'files_count':len(files),'total_source_bytes':sum(r['size'] for r in records),
                'ingest_seconds':ingest_seconds,'parent_peak_rss_bytes':peak[0],'parent_initial_rss_bytes':before,
                'retrieval_checks':checks,'retrieval_hit_at_20':sum(c['hit_at_20'] for c in checks)/len(checks),
                'citation_location_correctness':sum(c['exact_citation_verified'] for c in checks)/len(checks),
                'retrieval_median_seconds':statistics.median(latencies),'retrieval_max_seconds':max(latencies),
                'image_derivative_seconds':image_seconds,'image_request_bytes':packet['bytes'],'image_sources':packet['sources'],
                'model_token_usage':{'status':'NOT_RUN','reason':'no verified loaded vision/Agent model; byte measurements are not tokens'},
                'real_vision_answer_correctness':'NOT_RUN','semantic_retrieval_quality':'NOT_RUN; optional vectors are lexical hashing',
                'cold_os_cache':'NOT_CONTROLLED; this is first engine parse, not guaranteed cold disk',
                'index_timing_scope':'SQLite insert and commit wall time; worker/parser timers overlap IO and are not additive'}
        (output/'performance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:report[k] for k in ['files_count','total_source_bytes','retrieval_hit_at_20','citation_location_correctness','parent_peak_rss_bytes']}))
        if any(r['status']!='complete' for r in records) or not all(c['exact_citation_verified'] for c in checks):return 1
        return 0
    finally:
        stop.set();watcher.join();engine.close()


if __name__=='__main__':sys.exit(main())
