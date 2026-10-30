#!/usr/bin/env python3
"""Write a checkpoint with the exact baseline source, restore it with this tree."""
import io,json,os
from pathlib import Path
import subprocess,sys,tarfile

BASE='36b6b72ba286c6a0c13b89f8f40b7b71bf0bc8aa'
ROOT=Path(__file__).resolve().parents[1]
out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=False)
private=out/'.private';private.mkdir(mode=0o700)
baseline=private/'baseline';baseline.mkdir()
raw=subprocess.check_output(['git','archive',BASE,'agent','computer','localpilot_api','localpilot_service','catalog.py','hardware.py','recommender.py'],cwd=ROOT)
with tarfile.open(fileobj=io.BytesIO(raw)) as archive:archive.extractall(baseline,filter='data')
script='''
import json,sys
from pathlib import Path
from agent.backends import BackendCapabilities, ModelInfo
from agent.registry import create_default_registry
from agent.session import AgentSession
from localpilot_api.service import TaskService
class B:
 is_local=False
 capabilities=BackendCapabilities(supports_tool_calling=True)
 model_info=ModelInfo('compatibility-script','scripted',131072)
def factory(callback):return AgentSession(create_default_registry(Path(sys.argv[1])/'workspace',permission_mode='approve-mutations'),backend=B(),policy='cloud-only',event_callback=callback)
root=Path(sys.argv[1]);(root/'workspace').mkdir(exist_ok=True)
service=TaskService({'localpilot':factory},persistence=root/'runtime.sqlite3')
if not service.sessions:service.create_session(owner_subject='migration-test')
print(json.dumps({'sessions':list(service.sessions),'model_calls':0}))
service.suspend()
'''
def run(source):
 env={k:v for k,v in os.environ.items() if k in {'PATH','LANG','LC_ALL'}}
 env['PYTHONPATH']=str(source)
 return json.loads(subprocess.check_output([sys.executable,'-c',script,str(private)],cwd=source,env=env,text=True))
old=run(baseline);new=run(ROOT)
result={'baseline':BASE,'baseline_write':old,'current_restore':new,'same_session_restored':old['sessions']==new['sessions'],'inference':'NOT_RUN; checkpoint compatibility only'}
(out/'compatibility.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
sys.exit(0 if result['same_session_restored'] else 1)
