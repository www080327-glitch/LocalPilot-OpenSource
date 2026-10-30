"""Consumer-driven HTTP contract run in a fresh interpreter for each source pair."""
import os,sys,json,tempfile,threading,secrets,hashlib
from pathlib import Path
core,companion=map(Path,sys.argv[1:3]);sys.path.insert(0,str(companion));sys.path.insert(0,str(core))
from companion.config import Config
from companion.escalation.service_v491 import LocalPilotProvider
from companion.escalation.provider import EscalationRequest
from agent.registry import create_default_registry
from agent.session import AgentSession
from agent.retry import RetryPolicy
from localpilot_api.service import TaskService
from localpilot_service.server import ServiceServer
from localpilot_service.sdk import Client
from localpilot_service.security import AccessPolicy,Principal
from localpilot_service.verification import configured_verifier
from copy import deepcopy
from agent.backends import BackendCapabilities,BackendResponse,Message,ModelInfo,ToolCall
def answer(text="done", *calls):
    return BackendResponse(Message("assistant", text, list(calls)), {"prompt_tokens": 7, "completion_tokens": 3}, "script-provider", "tool_calls" if calls else "stop")


def call(name, args, id="call"):
    return ToolCall(id, name, json.dumps(args))


class Backend:
    is_local = False
    capabilities = BackendCapabilities(supports_tool_calling=True)
    model_info = ModelInfo("script-provider", "scripted", 131072)
    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []
    def request(self, messages, **kwargs):
        self.requests.append({"messages": deepcopy(messages), **kwargs})
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(messages) if callable(step) else step

with tempfile.TemporaryDirectory() as d:
 root=Path(d).resolve();workspace=root/'workspace';workspace.mkdir();(workspace/'fixture.txt').write_text('CONTRACT-FIXTURE')
 backend=Backend(answer(None,call('read_file',{'path':'fixture.txt'},'read')),answer('CONTRACT-FIXTURE'))
 verifier=configured_verifier(workspace,{'id':'consumer-fixture','files':{'fixture.txt':hashlib.sha256(b'CONTRACT-FIXTURE').hexdigest()},'required_text':'CONTRACT-FIXTURE'})
 def factory(callback):
  try:return AgentSession(create_default_registry(workspace,permission_mode='approve-mutations'),backend=backend,policy='cloud-only',event_callback=callback,retry_policy=RetryPolicy(max_attempts=1),verification_callback=verifier)
  except Exception:
   import traceback;traceback.print_exc();raise
 token=secrets.token_urlsafe(32);os.environ['LP_CONSUMER_TOKEN']=token
 access=AccessPolicy([Principal('companion',token)])
 service=TaskService({'localpilot':factory},persistence=root/'runtime.db')
 server=ServiceServer(('127.0.0.1',0),service,access=access,catalog={'localpilot':{'adapter':'local-openai','cloud_egress':'LOCAL_ONLY','model':'SCRIPTED_NOT_QWEN','deployment_status':'ready','prompt_profile':'standard','reasoning_only':False}})
 thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
 result={'core_source':str(core),'consumer_source':str(companion),'model':'SCRIPTED_ONLY','transport':'REAL_HTTP_SQLITE'}
 try:
  cfg=Config(data_dir=str(root/'consumer'),backend='disabled',low_power_policy='off',localpilot_endpoint='http://127.0.0.1:'+str(server.server_port),localpilot_api_key_env='LP_CONSUMER_TOKEN')
  provider=LocalPilotProvider(cfg);health=provider.health();result['health']=health
  if health['status']!='available':result['status']='FAIL_INCOMPATIBLE_PREVIOUS_CONSUMER'
  else:
   q=EscalationRequest('Read fixture.txt','contract','fixture',[],[],[],{'local_only':True,'classification':'LOCAL_ONLY'},'')
   denied=provider.submit(q,approved=False,submission_id='declined');assert not service.tasks
   task=provider.submit(q,approved=True,submission_id='stable');assert task.get('task_id'),task
   service.wait(task['task_id']);done=provider.status(task['task_id']);assert done['status']=='completed',done
   again=provider.submit(q,approved=True,submission_id='stable');assert again['task_id']==task['task_id']
   events=list(Client(cfg.localpilot_endpoint,token=token).events(task['task_id']));result.update(status='PASS',task=done,decline_no_execution=True,idempotency=True,model_requests=len(backend.requests),events=events)
 except Exception as e:
  result.update(status='FAIL',error=type(e).__name__+': '+str(e)[:500])
  try:
   from localpilot_api.service import TaskRequest
   service.create_task(TaskRequest(input='debug',idempotency_key='debug'),owner_subject='companion')
  except Exception:
   import traceback;traceback.print_exc()
 finally:
  server.shutdown();thread.join();service.shutdown();server.server_close();access.close()
 print(json.dumps(result,ensure_ascii=False))
