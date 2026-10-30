"""Predefined transparent checks. These cannot detect every paraphrased hallucination."""
import re
import statistics


def ratio(a,b):return a/b if b else None

def matches(pattern,text):
    return bool(re.search(re.sub(r"\s+", "", pattern), re.sub(r"\s+", "", text), re.I))

def score(case,result):
    text=result.get('text','');complete=result.get('status')=='ok'
    required=[complete and matches(p,text) for p in case.get('must',[])]
    # A quoted assertion inside an explicit denial is not a positive claim.
    clauses=re.split(r'[。！？\n]+',text)
    negatives=r'无法|不能|没有|尚未|不确定|不再|未曾|不是|not |unknown|no evidence'
    forbidden=[p for p in case.get('forbid',[]) if any(matches(p,c) and not re.search(negatives,c,re.I) for c in clauses)]
    metrics={'complete':complete,'required_hits':required,'forbidden_hits':forbidden,
             'fact_recall':sum(required)/len(required) if required else None,
             'detected_hallucination':bool(forbidden)}
    if case['category']=='uncertainty':
        metrics['detected_hallucination']=not all(required)
    if case['category']=='greeting':
        good=[all(required),complete and len(text)<=100,
              not any(s in text for s in ('克制的','作为','本地Companion','本地 Companion','需要确认')),
              not any(s in text for s in ('亲爱的','宝贝','超级','太棒','!!!','！！！')),
              not any(s in text for s in ('你昨天完成','你今天完成','你已经完成','你去旅行','你一直在忙'))]
        metrics.update(greeting_checks=good,greeting_quality=sum(good)/len(good))
    if case.get('files'):
        cites=[f for f in case['files'] if f in text]
        location=case.get('location')
        metrics['source_traceability']=bool(cites) and (not location or matches(location+'|行|页|段落|幻灯片|工作表|单元格|章节',text))
    return metrics


def confusion(rows,expected_key='expected',predicted_key='prediction',positive=lambda s:s!='quiet'):
    tp=fp=fn=tn=0
    for row in rows:
        a,b=positive(row[expected_key]),positive(row[predicted_key])
        tp+=a and b;fp+=(not a) and b;fn+=a and not b;tn+=(not a) and not b
    return {'tp':tp,'fp':fp,'fn':fn,'tn':tn,'precision':ratio(tp,tp+fp),
            'recall':ratio(tp,tp+fn),'false_interruption_rate':ratio(fp,fp+tn),
            'weighted_error_rate':ratio(5*fp+fn,5*(fp+tn)+tp+fn)}


def aggregate(rows):
    def mean(vals):
        vals=[v for v in vals if v is not None]
        return statistics.mean(vals) if vals else None
    disturbance=[r for r in rows if r['category']=='disturbance']
    escalation=[r for r in rows if r['category']=='escalation']
    d=confusion(disturbance)
    e=confusion(escalation,positive=lambda s:s=='agent')
    memory=[r for r in rows if r['category'] in {'memory','restart'}]
    grounded=[r for r in rows if r['category'] in {'memory','restart','document','uncertainty'}]
    times=[r['result']['latency_seconds'] for r in rows if 'latency_seconds' in r['result']]
    warm=[r['result']['latency_seconds'] for r in rows if r['result'].get('cold') is False]
    cold=[r['result']['latency_seconds'] for r in rows if r['result'].get('cold') is True]
    peaks=[r['result'].get('mlx_peak_bytes') for r in rows]
    return {'greeting_quality':mean(r['scores'].get('greeting_quality') for r in rows),
      'disturbance_precision':d['precision'],'disturbance_recall':d['recall'],
      'false_interruption_rate':d['false_interruption_rate'],'disturbance_confusion':d,
      'guarded_disturbance_confusion':confusion(disturbance,predicted_key='guarded_prediction'),
      'memory_recall':mean(r['scores'].get('fact_recall') for r in memory),
      'memory_precision':ratio(sum(sum(r['scores']['required_hits']) for r in memory),sum(sum(r['scores']['required_hits'])+len(r['scores']['forbidden_hits']) for r in memory)),
      'memory_precision_definition':'matched required facts / (matched required facts + explicitly detected forbidden facts); incomplete paraphrase coverage',
      'stale_memory_error_rate':mean(matches('10万',r['result'].get('text','')) for r in memory if r['id'] in {'m-budget','restart-m-budget'}),
      'hallucination_rate':mean(r['scores']['detected_hallucination'] for r in grounded),
      'hallucination_rate_definition':'finite forbidden-claim and explicit-uncertainty diagnostic; not general factuality',
      'escalation_precision':e['precision'],'escalation_recall':e['recall'],'escalation_confusion':e,
      'source_traceability':mean(r['scores'].get('source_traceability') for r in grounded),
      'latency':{'mean_seconds':mean(times),'p50_seconds':statistics.median(times) if times else None,
                 'p95_seconds':sorted(times)[max(0,int(len(times)*.95)-1)] if times else None,
                 'cold_start_seconds':cold,'warm_mean_seconds':mean(warm)},
      'peak_memory':max((v for v in peaks if v is not None),default=None),
      'peak_memory_definition':'MLX allocator peak, per-generation reset; not RSS',
      'output_format_stability':mean(r.get('format_valid') for r in rows if 'format_valid' in r),
      'completion_rate':mean(r['scores']['complete'] for r in rows)}
