"""Read official task facts and perform explicit, scoped Desktop reviews.

Not an Agent/approval engine. Core owns decisions, receipts and verification.
No input messages or unfiltered results cross this UI contract.
"""
import hashlib
import json
import re
import sqlite3
from urllib.error import HTTPError
from pathlib import Path
from . import channels
from .channel_paths import private_file, private_json

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=True).encode()).hexdigest()

def mappings(root,state,limit=10000):
    config=channels.configured(root)
    path=Path(config['state'])/'adapter/channels.sqlite3'
    if not path.exists():return config,[]
    private_file(path);db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:raw=list(db.execute("SELECT id,data FROM items WHERE id LIKE 'message:%' ORDER BY rowid DESC LIMIT ?",(limit,)))
    finally:db.close()
    found=[]
    for key,text in raw:
        record=json.loads(text);external=record.get('external_id')
        if not isinstance(external,str):raise ValueError('CHANNEL_RECORD_IDENTITY_INVALID')
        for sender in config['adapter']['channels'][0]['senders']:
            if key=='message:'+digest([state['channel'],sender['sender_id'],external]):
                found.append((record,sender));break
    return config,found

def redact(value,secrets):
    if isinstance(value,dict):return {key:('[已隐藏]' if key.lower() in {'token','password','secret','api_key','app_secret','authorization','credentials'} else redact(item,secrets)) for key,item in value.items()}
    if isinstance(value,list):return [redact(item,secrets) for item in value]
    if isinstance(value,str):
        for secret in sorted((v for v in secrets if isinstance(v,str) and v),key=len,reverse=True):value=value.replace(secret,'[已隐藏]')
    return value

def snapshot(home,hub,config,record,sender,*,historical=False):
    from .channel_product import credentials
    from localpilot_channels.client import ServiceClient
    task_id=record.get('official_id')
    if not isinstance(task_id,str) or not re.fullmatch('resp_[a-f0-9]{32}',task_id):
        raise ValueError('CHANNEL_OFFICIAL_TASK_NOT_CONFIRMED')
    if historical:
        from .product_control import operator
        client,_=operator(home);task=client.request('/localpilot/v1/tasks/'+task_id)
    else:
        client=ServiceClient(config['adapter']['service_url'],credentials(hub)[sender['token_env']],sender['subject'],timeout=5)
        client.identity();task=client.task(task_id)
    if task.get('id')!=task_id or task.get('service',{}).get('client_subject')!=sender['subject']:
        raise ValueError('CHANNEL_TASK_SUBJECT_MISMATCH')
    return task

def journal(hub):
    path=hub/'host-decisions.json'
    return private_json(path) if path.exists() else {}

def decision_unknown(record):
    # Older cancellation receipts nested the unresolved decision under prior.
    # Observing a cancellation cannot establish what an earlier write did.
    for _ in range(128):
        if not isinstance(record,dict):return False
        if record.get('status')=='UNKNOWN':return True
        record=record.get('prior')
    return True

def view(home,hub,config,state,record,sender,historical=False):
    task=snapshot(home,hub,config,record,sender,historical=historical)
    from .channel_product import credentials
    action=task.get('required_action') or {}
    preview=redact(action,credentials(hub).values())
    truncated=len(json.dumps(preview,ensure_ascii=False).encode())>16384
    redacted=preview!=action
    hold=decision_unknown(journal(hub).get(task['id']))
    pending=task.get('status')=='requires_approval' and isinstance(action.get('id'),str)
    return {'official_task_id':task['id'],'status':task['status'],'local_mapping_status':record.get('status'),
        'receipt_summary':task.get('receipt_summary'), 'verification_summary':task.get('verification_summary'),
        'receipts':[{key:row.get(key) for key in ('receipt_id','name','side_effect_status','receipt_reused')} for row in task.get('tools',[])],
        'required_action':{} if truncated else preview,'preview_truncated':truncated,'preview_redacted':redacted,
        'preview_fingerprint':digest(action),'approval_id':action.get('id'),
        'can_approve':pending and not (historical or hold or truncated or redacted),
        'can_reject':pending and not (historical or hold),'host_decision_unknown':hold,
        'can_cancel':not historical and task.get('status') not in {'completed','incomplete','failed','cancelled','timed_out'},
        'historical':historical,'automatic_resolution':False,'source':'official_core_agent_service'}

def receipts(home,hub,state,root,historical=False):
    config,records=mappings(root,state,100)
    rows=[]
    for record,sender in records[:20]:
        try:rows.append(view(home,hub,config,state,record,sender,historical))
        except Exception:rows.append({'official_task_id':record.get('official_id'),'status':'UNKNOWN','can_approve':False,'can_reject':False})
    return {'source':'official_core_agent_service','tasks':rows,'read_only':True,
        'messages_included':False,'unknown_not_cleared':True,'historical':historical}

def decide(home,hub,state,root,args):
    task_id=args['task_id']
    if (not isinstance(task_id,str) or not re.fullmatch('resp_[a-f0-9]{32}',task_id)
        or args['decision'] not in {'approve','reject'} or not isinstance(args['approval_id'],str)
        or not re.fullmatch('[A-Za-z0-9_.:@-]{1,256}',args['approval_id'])
        or not isinstance(args['decision_id'],str) or not re.fullmatch('[A-Za-z0-9_-]{16,128}',args['decision_id'])
        or not isinstance(args['preview_fingerprint'],str) or not re.fullmatch('[a-f0-9]{64}',args['preview_fingerprint'])):
        raise ValueError('CHANNEL_DECISION_REQUEST_INVALID')
    pending=journal(hub)
    if decision_unknown(pending.get(task_id)):
        raise ValueError('CHANNEL_DECISION_UNKNOWN_QUERY_ORIGINAL_NO_RETRY')
    config,records=mappings(root,state)
    pair=next(((record,sender) for record,sender in records if record.get('official_id')==task_id),None)
    if pair is None:raise ValueError('CHANNEL_TASK_NOT_IN_THIS_BINDING')
    record,sender=pair
    current=view(home,hub,config,state,record,sender)
    if (current['approval_id']!=args['approval_id'] or current['preview_fingerprint']!=args['preview_fingerprint']
        or not current['can_'+args['decision']]):
        raise ValueError('CHANNEL_APPROVAL_CHANGED_EXPIRED_OR_PREVIEW_UNAVAILABLE')
    from .product_control import operator
    client,_=operator(home)
    # Persist uncertainty BEFORE transmission. A lost reply never triggers replay.
    pending[task_id]={'status':'UNKNOWN','generation':state.get('generation','preparation'),
        'approval_id':args['approval_id'],'decision_id':args['decision_id'],'decision':args['decision'],
        'preview_fingerprint':args['preview_fingerprint']}
    channels.save(hub/'host-decisions.json',pending)
    try:
        client.request('/localpilot/v1/tasks/'+task_id+'/'+args['decision'],
            {'action_id':args['approval_id'],'reason':'Explicit LocalPilot Desktop channel review'},
            key=digest([task_id,args['approval_id'],args['decision_id']]))
    except Exception as error:
        status=error.code if isinstance(error,HTTPError) else getattr(error,'status',None)
        if status in {400,401,403,404,409,413,422,429}:
            pending[task_id].update(status='refused_not_tool_verification',http_code=status)
            channels.save(hub/'host-decisions.json',pending)
            raise ValueError('CHANNEL_DECISION_REFUSED_REFRESH_IDENTITY_AND_ACTION') from None
        for component in (config['adapter']['channels'][0]['kind'],'adapter'):
            try:channels.main(['stop',component],root.parent)
            except Exception:pass
        raise ValueError('CHANNEL_DECISION_UNKNOWN_QUERY_ORIGINAL_NO_RETRY') from None
    pending[task_id]['status']='response_observed_not_tool_verification'
    channels.save(hub/'host-decisions.json',pending)
    return {'status':'decision_response_observed','official_task_id':task_id,
        'tool_verification':'QUERY_ORIGINAL_RECEIPTS','replayed':False}

def cancel(home,hub,state,root,args):
    from .channel_product import credentials
    from localpilot_channels.client import ServiceClient
    task_id=args['task_id']
    if not isinstance(task_id,str) or not re.fullmatch('resp_[a-f0-9]{32}',task_id):raise ValueError('CHANNEL_DECISION_REQUEST_INVALID')
    entries=journal(hub);previous=entries.get(task_id)
    if previous and previous.get('kind')=='cancel' and decision_unknown(previous):
        raise ValueError('CHANNEL_CANCELLATION_UNKNOWN_QUERY_ORIGINAL_NO_RETRY')
    config,records=mappings(root,state)
    pair=next(((record,sender) for record,sender in records if record.get('official_id')==task_id),None)
    if pair is None:raise ValueError('CHANNEL_TASK_NOT_IN_THIS_BINDING')
    record,sender=pair;snapshot(home,hub,config,record,sender)
    client=ServiceClient(config['adapter']['service_url'],credentials(hub)[sender['token_env']],sender['subject'],timeout=5)
    entries[task_id]={'status':'UNKNOWN','kind':'cancel','generation':state.get('generation','preparation'),'prior':previous}
    channels.save(hub/'host-decisions.json',entries)
    try:result=client.request('POST','/localpilot/v1/tasks/'+task_id+'/cancel',{})
    except Exception as error:
        status=error.code if isinstance(error,HTTPError) else getattr(error,'status',None)
        if status in {400,401,403,404,409,413,422,429}:
            entries[task_id].update(status='UNKNOWN' if decision_unknown(previous) else 'cancel_refused',http_code=status)
            channels.save(hub/'host-decisions.json',entries)
            raise ValueError('CHANNEL_CANCELLATION_REFUSED_REFRESH_IDENTITY') from None
        raise ValueError('CHANNEL_CANCELLATION_UNKNOWN_QUERY_ORIGINAL') from None
    if result.get('quiescent') and result.get('status') in {'completed','incomplete','failed','cancelled','timed_out'}:
        entries[task_id]['status']='UNKNOWN' if decision_unknown(previous) else 'cancellation_observed'
        entries[task_id]['cancellation_status']='quiescent_response_observed'
        channels.save(hub/'host-decisions.json',entries)
    return {'status':'cancellation_requested','official_task_id':task_id,'prior_unknown_preserved':True,'tool_verification':'QUERY_ORIGINAL_RECEIPTS'}
