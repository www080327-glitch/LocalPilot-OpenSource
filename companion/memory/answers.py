"""Narrow exact-field answers and explicit unverified model sentence traces."""
import re
from pathlib import Path
from .reliability import scalar, scalar_locations


def current_field(store,question,memories):
    intent = re.sub(r'[^\s，,；;]+\.(?:txt|md|xlsx|docx|pptx|pdf)', '', question, flags=re.I)
    key,label=next(((key,label) for key,label,pattern in [('budget','预算',r'预算|budget'),('owner','负责人',r'负责人|owner'),('deadline','截止日期',r'截止日期|deadline')] if re.search(pattern,intent,re.I)),(None,None))
    if key is None:return None
    ids={r['id']:r for r in memories if r['type']=='document' and r['epistemic']=='factual'}
    named={mid:r for mid,r in ids.items() if Path(r['source_reference']).name in question}
    if named:ids=named
    if not ids:return None
    placeholders=','.join('?' for _ in ids)
    claims=store.db.execute('SELECT c.* FROM claims c JOIN source_versions v ON v.memory_id=c.memory_id WHERE v.current=1 AND c.memory_id IN ('+placeholders+') AND c.claim_key LIKE ? ORDER BY c.timestamp DESC',(*ids,'%:'+key)).fetchall()
    scopes={r['claim_key'].rsplit(':',1)[0] for r in claims if len(r['claim_key'].rsplit(':',1)[0])>=2 and r['claim_key'].rsplit(':',1)[0] in question}
    if len(scopes)==1:claims=[r for r in claims if r['claim_key'].rsplit(':',1)[0] in scopes]
    if not claims:return None
    groups = {}
    for claim in claims:
        groups.setdefault(claim['claim_key'].rsplit(':',1)[0], []).append(claim)
    if len(groups) > 1:
        text = '\n'.join(scope+'：'+('当前来源冲突，无法确认唯一'+label if len({scalar(c['value']) for c in group}) > 1 else label+'为'+group[0]['value']) for scope, group in groups.items())
    else:
        values={scalar(r['value']) for r in claims}
        text=('当前来源存在冲突，无法确认唯一'+label+'。' if len(values)>1 else '当前来源记录的'+label+'：'+claims[0]['value']+'。')
    sources=[]
    for claim in claims:
        record=ids[claim['memory_id']]
        memory=store.db.execute('SELECT metadata FROM memories WHERE id=?',(claim['memory_id'],)).fetchone()
        import json
        meta=json.loads(memory[0]);body=meta['index_text']
        locations=scalar_locations(meta, key, claim['value'])
        source=record['provenance'] | {'memory_id':claim['memory_id'],'value':claim['value'],'claim_key':claim['claim_key'],'source_location':locations}
        sources.append(source)
        text+='\n'+Path(source['source_file']).name+' '+', '.join(locations)+ '：'+claim['value']
    return {'text':text,'sources':sources,'method':'observed_field_lookup'}


def sentence_trace(text,memories):
    trace=[]
    for part in re.split(r'[。！？\n]+',text):
        part=part.strip()
        if not part:continue
        asserted=[r['id'] for r in memories if r['source_reference'] and Path(r['source_reference']).name in part]
        trace.append({'text':part,'asserted_source_ids':asserted,
                      'context_source_ids':[r['id'] for r in memories],
                      'verification':'UNVERIFIED_MODEL_CLAIM'})
    return trace
