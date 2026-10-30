"""Explicit host resource operations on an existing provider; no Agent loop."""
import hashlib
import json
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.parse import quote
from .cli import save
from .security import private_json
from localpilot_api.service import APIError,TERMINAL


class ModelResources:
    def __init__(self, server, path):
        self.server,self.path=server,Path(path)
        self.lock=threading.Lock()
        self.records=private_json(self.path) if self.path.exists() else {}
        for record in self.records.values():
            if record['status']=='started':record['status']='UNKNOWN'

    def operate(self, principal, body, key):
        if not principal.operator or 'resource_control' not in principal.scopes:
            raise APIError('Separate resource operator required','resource_control_required',403)
        if (not isinstance(body,dict) or set(body)!={'client_subject','model','operation','confirmed','max_memory_bytes'} or
            body['confirmed'] is not True or body['operation'] not in {'load','unload'} or type(body['max_memory_bytes']) is not int or body['max_memory_bytes']<=0 or
            not isinstance(key,str) or not 1<=len(key)<=128):
            raise APIError('Exact confirmed resource grant required')
        subject=body['client_subject']
        if subject not in principal.approval_for:raise APIError('Resource grant subject denied','scope_forbidden',403)
        client=self.server.access.principals[subject]
        route=client.routes.get(body['model'])
        backend=getattr(self.server,'model_backends',{}).get(route)
        if backend is None:raise APIError('Provider has no qualified resource operation','operation_unsupported',409)
        digest=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
        identity=hashlib.sha256((principal.subject+'\0'+key).encode()).hexdigest()
        with self.lock:
            prior=self.records.get(identity)
            if prior:
                if prior['fingerprint']!=digest:raise APIError('Resource key conflict','idempotency_conflict',409)
                return prior
            if any(r.get('status') in {'started','UNKNOWN'} for r in self.records.values()):
                raise APIError('A prior model resource effect is UNKNOWN; inspect the provider before any new resource operation','resource_unknown_blocked',409)
            service=getattr(self.server,'service',None)
            if body['operation']=='unload' and service is not None:
                with service.condition:
                    if any(t.model==route and t.status not in TERMINAL for t in service.tasks.values()):
                        raise APIError('Model is held by an active or waiting task','model_in_use',409)
            observation=backend.inspect_service()
            model=next((m for m in observation['models'] if m['id']==backend.model),None)
            if model and model.get('deployment_status')=='loading':raise APIError('Model is still loading','provider_busy',409)
            if model is None:raise APIError('Model was not discovered','model_unavailable',409)
            if body['operation']=='load' and model.get('files_present') is False:
                raise APIError('模型权重文件不完整，请在模型库重新下载，或选择已有完整模型。','model_files_missing',409)
            if observation.get('active_requests')!=0:raise APIError('Provider has active work','provider_busy',409)
            import psutil
            size=model.get('size_bytes')
            if body['operation']=='load':
                if model.get('trust_remote_code') is not False:raise APIError('Untrusted or unknown model code policy','untrusted_code_forbidden',409)
                if psutil.disk_usage(Path.home()).free<2*1024**3:raise APIError('Insufficient space for inference cache','resource_budget_exceeded',409)
                if type(size) is not int or size<=0 or size+2*1024**3>body['max_memory_bytes']:
                    raise APIError('Model size exceeds explicit resource grant','resource_budget_exceeded',409)
                if not model['loaded'] and psutil.virtual_memory().available<body['max_memory_bytes']+2*1024**3:
                    raise APIError('Available memory is insufficient','resource_budget_exceeded',409)
                if size>4*1024**3 and any(m['loaded'] and m['id']!=model['id'] and (m.get('size_bytes') or 0)>4*1024**3 for m in observation['models']):
                    raise APIError('Another large model is loaded; unload it separately','existing_model_preserved',409)
            record={'id':identity,'fingerprint':digest,'model':model['id'],'operation':body['operation'],'status':'started','at':time.time()}
            self.records[identity]=record;save(self.path,self.records)
            try:
                with backend._open('/models/'+quote(model['id'],safe='')+'/'+body['operation'],{}) as response:json.load(response)
                current=backend.inspect_service()
                loaded=next(m['loaded'] for m in current['models'] if m['id']==model['id'])
                record.update(status='completed' if loaded==(body['operation']=='load') else 'UNKNOWN',loaded=loaded)
            except Exception as exc:
                # Resource effect may already have happened. Never retry it.
                from urllib.error import HTTPError
                if isinstance(exc, HTTPError) and 400 <= exc.code < 500:
                    # A definitive provider rejection must not block every later model.
                    record.update(status='rejected',error=f'模型加载被推理服务拒绝（HTTP {exc.code}），请检查模型权重是否完整或选择其他模型。')
                else:
                    record.update(status='UNKNOWN',error=type(exc).__name__)
            save(self.path,self.records)
            return dict(record)
