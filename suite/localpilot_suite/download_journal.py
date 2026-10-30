"""A bounded model-manager receipt journal, never an Agent execution loop."""
import fcntl
import hashlib
import os
from pathlib import Path
import time
from localpilot_service.cli import private_dir,save
from localpilot_service.security import private_json


def download(admin,home,repo):
    home=private_dir(home);path=home/'model-downloads.json'
    fd=os.open(home/'model-downloads.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        values=private_json(path) if path.exists() else {}
        identity=hashlib.sha256((admin.base+'\0'+repo).encode()).hexdigest();old=values.get(identity)
        if old and old['status'] in {'started','UNKNOWN','queued'}:
            jobs=admin.request('/admin/api/hf/tasks').get('tasks',[])
            matches=[j for j in jobs if j.get('repo_id')==repo and (j.get('task_id')==old.get('task_id') or not old.get('task_id') and j.get('created_at',0)>=old['at'])]
            if len(matches)==1:
                old.update(status='queued',task_id=matches[0]['task_id'],recovered_by_observation=True);save(path,values)
                return {'success':True,'task':matches[0],'replayed':False}
            raise ValueError('UNKNOWN：先在下载任务中核对原请求；未重新下载或覆盖文件')
        record={'repo_id':repo,'status':'started','at':time.time(),'original_unknown':False};values[identity]=record;save(path,values)
        try:
            result=admin.request('/admin/api/hf/download',{'repo_id':repo})
            task=result.get('task',{})
            if task.get('repo_id')!=repo or not isinstance(task.get('task_id'),str):raise ValueError('Missing bound download receipt')
            record.update(status='queued',task_id=task['task_id']);save(path,values);return result
        except Exception as error:
            record.update(status='rejected' if getattr(error,'definitive_rejection',False) else 'UNKNOWN',original_unknown=not getattr(error,'definitive_rejection',False));save(path,values);raise


def model_deleted(admin,home,model):
    path=Path(home)/'model-downloads.json'
    if not path.exists():return
    values=private_json(path)
    for record in values.values():
        if model in {record['repo_id'].split('/')[-1],record['repo_id'].replace('/','--')}:
            record.update(status='deleted',deleted_at=time.time())
    save(path,values)
