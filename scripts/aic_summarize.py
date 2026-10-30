"""Derive all tables/charts from preserved results, never from target claims."""
import argparse
from datetime import datetime,timezone
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from statistics import median
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks.hybrid_accounting import CostLedger

ROOT=Path(__file__).resolve().parents[1];E=ROOT/'docs/evidence/aic-final-20261029'
NAMES={'A':'DSH 云端','B':'LP 完全云端','C':'LP 云端优先','D':'LP 平衡','E':'LP 本地优先','F':'LP 完全本地','G':'DSH 本地'}
ALIASES={'dsh':'A','cloud-only':'B','cloud-first':'C','balanced':'D','local-first':'E','local-only':'F','dsh-local':'G'}

def read(path,default=None):return json.loads(path.read_text()) if path.exists() else default
def wilson(s,n):
    if not n:return None
    z=1.959963984540054;p=s/n;den=1+z*z/n
    centre=(p+z*z/(2*n))/den;radius=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [max(0,centre-radius),min(1,centre+radius)]
def percentile(v,p):
    if not v:return None
    v=sorted(v);x=(len(v)-1)*p;i=int(x);return v[i]+(v[min(i+1,len(v)-1)]-v[i])*(x-i)


def metric_value(raw,name):
    values=[float(line.rsplit(' ',1)[1]) for line in (raw or '').splitlines()
            if line.startswith(name+'{') or line.startswith(name+' ')]
    return sum(values) if values else None


def cache_observation(row):
    usage=(row.get('response') or {}).get('usage') or {}
    hit=usage.get('prompt_cache_hit_tokens',(usage.get('prompt_tokens_details') or {}).get('cached_tokens'))
    queried=usage.get('prompt_tokens')
    source='provider Usage' if hit is not None else None
    def delta(name):
        before=metric_value(row.get('metrics_before'),name);after=metric_value(row.get('metrics_after'),name)
        return after-before if before is not None and after is not None and after>=before else None
    if hit is None:
        hit=delta('vllm:prefix_cache_hits_total');queried=delta('vllm:prefix_cache_queries_total')
        if hit is not None:source='owned serial Prometheus counter delta; HELP defines tokens'
    prefill=usage.get('prompt_eval_duration');prefill_source='provider prompt_eval_duration' if prefill is not None else None
    if prefill is None and delta('vllm:request_prefill_time_seconds_count')==1:
        prefill=delta('vllm:request_prefill_time_seconds_sum');prefill_source='owned serial PREFILL histogram sum delta'
    return {'engine':row['engine'],'cache':row['cache'],'tag':row['tag'],'status':row['status'],
            'correct':row.get('correct',False),'ttft_seconds':row.get('ttft_seconds'),
            'elapsed_seconds':row.get('elapsed_seconds'),'cache_hit_tokens':hit,'cache_queried_tokens':queried,
            'cache_metric_source':source,'provider_prefill_seconds':prefill,'prefill_metric_source':prefill_source,
            'peak_process_tree_rss_bytes':row.get('peak_process_tree_rss_bytes'),
            'process_cpu_seconds':row.get('process_cpu_seconds'),'device_only_prefill_seconds':None}


def summarize_local_cache(rows):
    observations=[cache_observation(r) for r in rows]
    groups={'warm_standard':['warm_standard_1','warm_standard_2'],
            'long_repeat':['long_repeat_1','long_repeat_2'],
            'tool_followup':['tool_followup','tool_followup_repeat'],
            'after_owned_service_restart':['after_owned_service_restart']}
    summary=[]
    for engine in ['omlx','vllm']:
        for tag,tags in groups.items():
            off=[r for r in rows if r['engine']==engine and not r['cache'] and r['tag'] in tags]
            on=[r for r in rows if r['engine']==engine and r['cache'] and r['tag'] in tags]
            def med(items,key):
                values=[r[key] for r in items if r.get(key) is not None];return median(values) if values else None
            off_ttft=med(off,'ttft_seconds');on_ttft=med(on,'ttft_seconds')
            measured=[r for r in observations if r['engine']==engine and r['cache'] and r['tag'] in tags]
            hits=[r['cache_hit_tokens'] for r in measured];queries=[r['cache_queried_tokens'] for r in measured]
            known=bool(hits) and all(v is not None for v in hits+queries)
            pairs={r['tag']:r for r in on}
            complete=bool(off) and len(off)==len(on) and all(r['status']=='RESPONSE' for r in off+on)
            equal=all(r['tag'] in pairs and r.get('canonical')==pairs[r['tag']].get('canonical') for r in off) if complete else None
            summary.append({'engine':engine,'tag':tag,'aggregation':'median of all predefined repetitions; no outcome filtering',
                'off_n':len(off),'on_n':len(on),'off_ttft_seconds':off_ttft,'on_ttft_seconds':on_ttft,
                'off_ttft_range':[min(r['ttft_seconds'] for r in off if r.get('ttft_seconds') is not None),max(r['ttft_seconds'] for r in off if r.get('ttft_seconds') is not None)] if off_ttft else None,
                'on_ttft_range':[min(r['ttft_seconds'] for r in on if r.get('ttft_seconds') is not None),max(r['ttft_seconds'] for r in on if r.get('ttft_seconds') is not None)] if on_ttft else None,
                'off_failures':sum(r['status']!='RESPONSE' for r in off),'on_failures':sum(r['status']!='RESPONSE' for r in on),
                'observed_ttft_speedup':off_ttft/on_ttft if off_ttft and on_ttft else None,
                'off_e2e_seconds':med(off,'elapsed_seconds'),'on_e2e_seconds':med(on,'elapsed_seconds'),
                'on_cache_hit_tokens':sum(hits) if known else None,'on_cache_queried_tokens':sum(queries) if known else None,
                'on_cache_hit_ratio':sum(hits)/sum(queries) if known and sum(queries)>0 else None,
                'output_equal':equal,'status':'MEASURED' if off_ttft and on_ttft else 'FAILED_OR_NOT_RUN'})
    return summary,observations


def assess_strict(row):
    row=deepcopy(row);states=row.get('turn_statuses') or []
    native=row.get('arm') in {'A','G'}
    complete=bool(states) and all(type(s) is int and s==0 if native else isinstance(s,str) and s=='completed' for s in states)
    row['raw_driver_strict_success']=row.get('strict_success',False)
    row['all_turns_completed']=complete
    row['driver_completion_misclassification']=row.get('status')=='generated' and not complete
    row['state_only_checker_pass']=bool((row.get('checker') or {}).get('valid'))
    row['strict_success']=bool(row.get('status')=='generated' and complete and row['state_only_checker_pass'])
    row['false_completed']=bool(complete and row.get('status')=='generated' and not row['state_only_checker_pass'])
    return row


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--run',default='bfcl-evaluation-final1');p.add_argument('--protocol',default='bfcl-protocol-final.json');a=p.parse_args()
    phase_ledgers=[{'path':p.name,**CostLedger(p).snapshot()} for p in sorted((ROOT/'.aic-runtime').glob('cloud-ledger*.sqlite3'))]
    calls=sorted([call for phase in phase_ledgers for call in phase['calls']],key=lambda c:c['started_unix'])
    for call in calls:
        stamp=datetime.fromtimestamp(call['started_unix'],timezone.utc)
        ordinary=stamp.date().isoformat() in {'2026-10-29','2026-10-30'}
        factor=(1.0 if stamp.weekday()<5 and (1<=stamp.hour<4 or 6<=stamp.hour<10) else .5) if ordinary or stamp.weekday()>=5 else None
        call['documented_time_rate_factor']=factor
        call['time_adjusted_standard_usd']=call.get('cost_usd_standard')*factor if factor is not None and call.get('cost_usd_standard') is not None else None
        call['time_adjusted_upper_usd']=call['budget_charge_cny']/10*factor if factor is not None else None
        call['time_rate_scope']='Published standard time tariff; not a confirmed invoice, discount credit or FX conversion'
    ledger={'limit_cny':sum(phase['limit_cny'] for phase in phase_ledgers),
        'budget_charged_cny':sum(phase['budget_charged_cny'] for phase in phase_ledgers),
        'actual_invoice':'UNKNOWN','phase_ledgers':phase_ledgers,'calls':calls}
    rows=[];score_audit=[]
    for file in sorted((E/a.run).glob('*/result.json')):
        row=assess_strict(read(file));row['evidence']=str(file.relative_to(ROOT))
        provider_trace=read(file.parent/'provider-trace.json',[])
        row['local_provider_attempts']=sum(t.get('local') is True or (row['arm']=='G' and type(t.get('request')) is int) for t in provider_trace)
        physical=[t['local'] for t in sorted(provider_trace,key=lambda t:t.get('request') or 0) if type(t.get('local')) is bool]
        row['local_to_cloud_provider_transitions']=sum(before and not after for before,after in zip(physical,physical[1:]))
        if row['raw_driver_strict_success']!=row['strict_success']:
            score_audit.append({'instance':row['instance'],'arm':row['arm'],'original_flag':row['raw_driver_strict_success'],'strict_corrected':row['strict_success'],
                'turn_statuses':row.get('turn_statuses'),'reason':'Strict success requires completed agent turns AND unchanged upstream checker pass; immutable original result retained'})
        rows.append(row)
    tables=[]
    for arm,name in NAMES.items():
        trials=[r for r in rows if r['arm']==arm]
        usage=[c for c in calls if c.get('run')==a.run and ALIASES.get(c.get('arm'),c.get('arm'))==arm]
        s=sum(r['strict_success'] for r in trials);n=len(trials);times=[r['elapsed_seconds'] for r in trials]
        known=sum(c.get('cost_usd_standard') or 0 for c in usage)
        unknown=sum(c.get('cost_usd_standard') is None for c in usage)
        upper=sum(c['budget_charge_cny']/10 for c in usage)
        escalation=sum(sum(e.get('type')=='ModelHandoffCommitted' and
            e.get('data',{}).get('from_backend_id')=='l' and e.get('data',{}).get('to_backend_id')=='c'
            for e in r.get('events',[])) for r in trials)
        hit=sum((c.get('usage') or {}).get('prompt_cache_hit_tokens') or 0 for c in usage)
        prompt=sum((c.get('usage') or {}).get('prompt_tokens') or 0 for c in usage)
        resources=[r.get('local_resources',{}) for r in trials]
        agent_resources=[r.get('agent_resources',{}) for r in trials]
        tables.append({'arm':arm,'name':name,'status':'MEASURED' if n else 'NOT_RUN','n':n,'successes':s,
            'strict_success_rate':s/n if n else None,'wilson_95':wilson(s,n),
            'api_requests':len(usage) if n else None,'api_known_usd_peak_standard':known if n else None,
            'api_upper_usd_peak_standard':upper if n else None,'usage_unknown_calls':unknown if n else None,
            'api_total_usd_peak_standard':known if n and not unknown else None,
            'api_cost_per_verified_success_usd':known/s if s and not unknown else None,
            'api_cost_per_verified_success_lower_usd':known/s if s else None,
            'api_cost_per_verified_success_upper_usd':upper/s if s else None,
            'elapsed_total_seconds':sum(times) if n else None,'p50_seconds':median(times) if n else None,'p95_seconds':percentile(times,.95),
            'local_compute_wall_seconds':sum(r.get('local_compute_wall_seconds',0) for r in trials) if n else None,
            'local_provider_attempts':sum(r['local_provider_attempts'] for r in trials) if n else None,
            'local_work_evidence':'MEASURED_LOCAL_ATTEMPTS' if any(r['local_provider_attempts'] for r in trials) else ('NO_LOCAL_INFERENCE_IN_THIS_COHORT' if n else 'NOT_RUN'),
            'local_process_cpu_seconds':sum(r['process_cpu_seconds'] for r in resources if r.get('process_cpu_seconds') is not None) if any(r.get('process_cpu_seconds') is not None for r in resources) else None,
            'local_peak_tree_rss_bytes':max((r['peak_process_tree_rss_bytes'] for r in resources if r.get('peak_process_tree_rss_bytes') is not None),default=None),
            'agent_sampled_cpu_seconds':sum(r['process_cpu_seconds'] for r in agent_resources if r.get('process_cpu_seconds') is not None) if any(r.get('process_cpu_seconds') is not None for r in agent_resources) else None,
            'agent_peak_tree_rss_bytes':max((r['peak_process_tree_rss_bytes'] for r in agent_resources if r.get('peak_process_tree_rss_bytes') is not None),default=None),
            'cache_hit_ratio_known_usage':hit/prompt if prompt else None,'cache_hit_tokens':hit if n else None,
            'cache_prompt_tokens':prompt if n else None,'local_to_cloud_escalations':escalation if n else None,
            'local_to_cloud_provider_transitions':sum(r['local_to_cloud_provider_transitions'] for r in trials) if n else None,
            'escalation_metric_status':'l-to-c logical primary handoff events, possibly before first local inference; physical provider transitions are separately reported and may include reviews',
            'false_completed':sum(r.get('false_completed',False) for r in trials) if n else None,
            'driver_completion_misclassifications':sum(r.get('driver_completion_misclassification',False) for r in trials) if n else None,
            'side_effect_replay':'UNKNOWN_NOT_INSTRUMENTED','failures':[{k:r.get(k) for k in ['instance','status','strict_success','error_type']} for r in trials if not r['strict_success']]})
    baseline=tables[0]
    for row in tables:
        b=baseline['api_total_usd_peak_standard'];cost=row['api_total_usd_peak_standard']
        row['api_saving_fraction']=1-cost/b if b and cost is not None else None
        if row['arm']=='A' and row['n']:
            row['api_saving_fraction']=0;row['api_saving_bounds']=[0,0]
        elif row['n'] and baseline['n'] and baseline['api_known_usd_peak_standard']>0:
            row['api_saving_bounds']=[1-row['api_upper_usd_peak_standard']/baseline['api_known_usd_peak_standard'],
                1-row['api_known_usd_peak_standard']/baseline['api_upper_usd_peak_standard']]
        else:row['api_saving_bounds']=None
        pairs={r['instance']:r for r in rows if r['arm']==row['arm']};base={r['instance']:r for r in rows if r['arm']=='A'}
        common=set(pairs)&set(base);diff=[int(pairs[i]['strict_success'])-int(base[i]['strict_success']) for i in common]
        radius=math.sqrt(2*math.log(40)/len(diff)) if diff else None
        row['paired_delta_vs_A']=sum(diff)/len(diff) if diff else None
        row['paired_hoeffding_95']=[max(-1,row['paired_delta_vs_A']-radius),min(1,row['paired_delta_vs_A']+radius)] if diff else None
        row['noninferiority']='NOT_ESTABLISHED'
    cache_cloud=[]
    for directory in ['cloud-cache','cloud-cache-wire2','cloud-cache-v5']:
        requests=read(E/directory/'requests.json',[])
        for kind in ['standard_system','long_context','tool_roundtrip']:
            repeated=[r for r in requests if r['tag'].startswith(kind+':repeat') and r.get('usage')]
            cold=next((r for r in repeated if r['tag'].endswith('repeat0')),None)
            warm=[r for r in repeated if not r['tag'].endswith('repeat0') and r.get('ttft_seconds') is not None]
            cold_ttft=cold.get('ttft_seconds') if cold else None;warm_ttft=median(r['ttft_seconds'] for r in warm) if warm else None
            hit=sum(r['usage'].get('prompt_cache_hit_tokens') or 0 for r in repeated);tokens=sum(r['usage'].get('prompt_tokens') or 0 for r in repeated)
            cache_cloud.append({'run':directory,'kind':kind,'n_responses':len(repeated),
                'cold_ttft_seconds':cold_ttft,'warm_p50_ttft_seconds':warm_ttft,
                'cold_over_warm_observed_ratio':cold_ttft/warm_ttft if cold_ttft and warm_ttft else None,
                'known_token_hit_ratio':hit/tokens if tokens else None,
                'all_requests':len([r for r in requests if r['tag'].startswith(kind)]),
                'failures':sum(r['status']=='FAIL' for r in requests if r['tag'].startswith(kind)),
                'cache_off':'NO_DOCUMENTED_REQUEST_LEVEL_OFF','permanent_cache':'NOT_CLAIMED'})
    local_run='local-cache2' if (E/'local-cache2/summary.json').exists() else 'local-cache1'
    local=read(E/local_run/'requests.json',[]);cache_local,cache_local_observations=summarize_local_cache(local)
    known_total=sum(c.get('cost_usd_standard') or 0 for c in calls)
    selector_run='selector-quality2' if (E/'selector-quality2/summary.json').exists() else 'selector-quality1'
    selector_protocol=read(E/selector_run/'protocol.json',{})
    selector_trials=read(E/selector_run/'results.json',[])
    expected_selector_trials=len(selector_protocol.get('models',[]))*(len(selector_protocol.get('development_ids',[]))+len(selector_protocol.get('evaluation_ids',[])))
    selector_execution={'run':selector_run,'expected_model_trials':expected_selector_trials,'observed_model_trials':len(selector_trials),
        'counterfactuals_complete':bool(expected_selector_trials) and len(selector_trials)==expected_selector_trials,
        'api_attempts':sum(t.get('api_requests',0) for t in selector_trials),'not_additional_independent_instances':True}
    selector_quality=read(E/selector_run/'summary.json')
    for method in (selector_quality or {}).get('methods',{}).values():
        chosen=[t for t in selector_trials if t['split']=='evaluation' and t['model_id']==method['choice']]
        times=[t['elapsed_seconds'] for t in chosen]
        method.update(task_success_wilson_95=wilson(method['successes'],method['tasks']),
            selection_accuracy_wilson_95=wilson(method['correct_selections'],method['known_oracle_tasks']),
            task_p50_seconds=median(times) if times else None,task_p95_seconds=percentile(times,.95),
            task_peak_tree_rss_bytes=max((t['resources']['peak_process_tree_rss_bytes'] for t in chosen if (t.get('resources') or {}).get('peak_process_tree_rss_bytes') is not None),default=None),
            task_sampled_cpu_seconds=sum(t['resources']['process_cpu_seconds'] for t in chosen if (t.get('resources') or {}).get('process_cpu_seconds') is not None) if any((t.get('resources') or {}).get('process_cpu_seconds') is not None for t in chosen) else None)
    selector_model_metrics=[]
    for model in selector_protocol.get('models',[]):
        trials=[t for t in selector_trials if t['split']=='evaluation' and t['model_id']==model['repo_id']]
        selector_model_metrics.append({'model_id':model['repo_id'],'n':len(trials),'successes':sum(t['strict_success'] for t in trials),
            'p50_seconds':median(t['elapsed_seconds'] for t in trials) if trials else None,
            'p95_seconds':percentile([t['elapsed_seconds'] for t in trials],.95),
            'api_attempts':sum(t.get('api_requests',0) for t in trials)})
    core_file='core-tools-final.json' if (E/'core-tools-final.json').exists() else 'core-qualified3.json'
    output={'created_utc':datetime.now(timezone.utc).isoformat(),'title':'localpilot','team':'大肥鱼队','license':'MIT',
        'publication':'Private during contest; public release planned after competition; no publication performed',
        'benchmark_run':a.run,'cohort_role':'tool-contract-fixed candidate evaluation' if a.run=='bfcl-evaluation-adapted2' else 'pre-fix diagnostic cohort',
        'protocol':read(E/a.protocol),'benchmark':tables,'trials':rows,'strict_score_audit':score_audit,
        'batch_environment':{'driver':read(E/a.run/'driver-status.json'),
            'shared_local_service':read(E/a.run/'local-loaded.json'),
            'shared_local_service_after':read(E/a.run/'local-unloaded.json'),
            'task_timing_scope':'Per-instance wall clocks exclude shared local service startup/unload; driver and startup are reported separately',
            'resource_scope':'Shared local service is preloaded during the serial study. A/B have no local inference and local RSS was not sampled, not a claim of zero resident setup memory'},
        'campaign_cost':{'requests':len(calls),'known_usd_peak_standard':known_total,
            'requests_definition':'One pre-dispatch reservation per cloud request attempt; unfinished dispatch/billing remains UNKNOWN',
            'upper_usd_peak_standard':ledger['budget_charged_cny']/10,'unknown_usage_calls':sum(c.get('cost_usd_standard') is None for c in calls),
            'known_usd_time_adjusted_standard':sum(c.get('time_adjusted_standard_usd') or 0 for c in calls),
            'upper_usd_time_adjusted_standard':sum(c['time_adjusted_upper_usd'] for c in calls) if all(c.get('time_adjusted_upper_usd') is not None for c in calls) else None,
            'actual_invoice':'UNKNOWN','budget_cap_cny_upper':ledger['limit_cny'],'cny_is_budget_bound_not_exchange_rate':True},
        'cloud_cache':cache_cloud,'local_cache':cache_local,'local_cache_observations':cache_local_observations,
        'local_cache_primary_run':local_run,'selector':read(E/'selector-audit.json'),
        'selector_quality':selector_quality,'selector_quality_execution':selector_execution,'selector_candidate_metrics':selector_model_metrics,
        'selector_quality_history':[{'run':name,'summary':read(E/name/'summary.json')} for name in ['selector-quality1','selector-quality2'] if (E/name/'summary.json').exists()],
        'cloud_cache_delayed':read(E/'cloud-cache-delayed2.json',read(E/'cloud-cache-delayed.json')),
        'cloud_cache_delayed_history':[read(p) for p in sorted(E.glob('cloud-cache-delayed*.json')) if not p.name.endswith('.ledger.json')],
        'selector_training':read(E/'selector-training.json'),
        'core_qualification':{k:v for k,v in (read(E/core_file,{}) or {}).items() if k in {'tests_run','failures','errors','skips','wall_seconds','successful'}},
        'demo':read(E/'live-demo7/result.json',read(E/'live-demo6/result.json')),
        'video_demo':read(E/'live-demo6/result.json'),
        'video_scope':'Video is the real earlier live-demo6 SDK run; current tool-contract prompt is rechecked by live-demo7, not a native GUI acceptance',
        'native_context_audit':read(E/'native-context-audit.json'),
        'protocol_execution_audit':read(E/'protocol-execution-audit.json'),
        'limits':['Adapted BFCL, not an official leaderboard score','Terminal-Bench and SWE-bench BLOCKED_NO_CONTAINER_RUNTIME',
            *(['Pre-fix diagnostic DSH cloud model catalog advertised 1M instead of intended64K; strictly fixed-context comparison is unqualified'] if a.run=='bfcl-evaluation-final1' else []),
            'The small independent instance count cannot establish statistical noninferiority',
            'MLP throughput target does not establish task quality; formal quality replacement NO_GO',
            'Native GUI/full consumer-release qualification NOT_RUN in this candidate']}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    (a.output.parent/'raw-cost-ledger.json').write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')
    (a.output.parent/'strict-score-audit.json').write_text(json.dumps({'official_checker_modified':False,'execution_traces_modified':False,'corrections':score_audit},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'arms':[{'arm':r['arm'],'n':r['n'],'successes':r['successes']} for r in tables],'campaign_cost':output['campaign_cost']}))


if __name__=='__main__':main()
