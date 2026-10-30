"""Final bundled Companion -> ordinary official Core -> real cached Qwen35.
Synthetic read-only workspace, normal system power policy, no guard override.
Native Companion control-window interaction remains a separate NOT_RUN gate.
"""
import argparse,hashlib,http.client,json,os,socket,subprocess,time
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit

def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2)+'\n');p.chmod(0o600)
def port():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bundle=a.bundle.resolve(strict=True);out=a.out.resolve();out.mkdir(mode=0o700,parents=True,exist_ok=False)
 import companion
 from companion.config import Config
 from companion.runtime.power import LowPowerPolicy,system_power_source
 from companion.escalation.service_v491 import LocalPilotProvider
 assert str(bundle/'runtime') in companion.__file__
 home=out/'core';home.mkdir(mode=0o700);work=out/'workspace';work.mkdir(mode=0o700);source=work/'source.txt';nonce='LOCALPILOT-35B-COMPANION-B3-'+uuid4().hex[:10];source.write_text(nonce+'\n');expected=sha(source);cli=bundle/'localpilot';daily=[Path.home()/'.omlx/settings.json',Path.home()/'.omlx/model_settings.json'];before={str(p):sha(p) for p in daily if p.is_file()}
 report={'kind':'REAL_PACKAGED_COMPANION_ORDINARY_TRANSPORT_LOCAL_AGENT','model':'Qwen3.6-35B-A3B-4bit','revision':'38740b847e4cb78f352aba30aa41c76e08e6eb46','companion_version':companion.__version__,'companion_import':companion.__file__,'power_source':system_power_source(),'system_low_power_active':LowPowerPolicy(Config(low_power_policy='system')).active(),'guard_override':False,'native_control_window':'NOT_RUN','real_platforms':'NOT_RUN','cloud_calls':0,'operator_credential_supplied_to_companion':False}
 env={k:v for k,v in os.environ.items() if not k.startswith(('LOCALPILOT_','DEEPSEEK_','OPENAI_','OMLX_')) and k not in {'PYTHONHOME','PYTHONPATH'}};env.update(PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
 def invoke(args):
  r=subprocess.run([str(cli),'--home',str(home),'--json',*args],env=env,cwd=out,capture_output=True,text=True,timeout=150);values=[]
  for line in r.stdout.splitlines():
   try:values.append(json.loads(line))
   except ValueError:pass
  value=values[-1] if values else {'error':'no_json'}
  if r.returncode:raise RuntimeError('CLI_'+str(r.returncode)+':'+str(value.get('error','failed')))
  return value
 try:
  invoke(['init','--workspace',str(work),'--model',report['model'],'--managed-qwen35','--port',str(port())]);path=home/'service.json';config=json.loads(path.read_text());model_port=port()
  for route in config['routes'].values():
   if route.get('managed_local_model'):route['managed_local_model']['port']=model_port;route['backend']['base_url']=f'http://127.0.0.1:{model_port}/v1'
   route['engine']='v5';route['budgets']={'max_steps':8,'max_tool_calls':8,'max_output_tokens':512,'max_token_units':131072}
  route=config['routes']['companion-execution'];route['capabilities']={'read':True,'write':False,'execute':False};route['verification']={'id':'companion-readonly-nonce','files':{'source.txt':expected},'required_text':nonce};write(path,config)
  invoke(['product-control','--request-json',json.dumps({'version':1,'operation':'service_control','args':{'module':'core','action':'start','confirmed':True}})])
  connection=json.loads((home/'connection.json').read_text());tokens=dict(l.removeprefix('export ').split('=',1) for l in (home/'clients.env').read_text().splitlines());os.environ['LP_REAL_COMPANION_ORDINARY']=tokens['LOCALPILOT_LOCAL_TOKEN'];cfg=Config(data_dir=str(out/'companion-data'),backend='disabled',watch_dirs=(),native_observation_enabled=False,localpilot_endpoint=connection['url'],localpilot_client_subject='local',localpilot_route='localpilot',localpilot_api_key_env='LP_REAL_COMPANION_ORDINARY',localpilot_host_local_only=True,localpilot_task_timeout_seconds=360,low_power_policy='system');provider=LocalPilotProvider(cfg);ticket=uuid4().hex;started=time.monotonic()
  result=provider.submit({'user_request':'请读取 source.txt，用中文简要报告并逐字包含第一行。只读，不运行 Shell，不修改任何文件。','privacy_scope':{'local_only':True}},approved=True,control_ticket=ticket,submission_id='companion-b3-'+uuid4().hex);write(out/'submission.json',result);task_id=result.get('task_id');report['task_id']=task_id
  if not task_id:report.update(status='BLOCKED_OR_UNKNOWN_SUBMISSION',submission=result);return
  origin=urlsplit(connection['url']);last_beat=0;deadline=time.monotonic()+370
  while time.monotonic()<deadline:
   if time.monotonic()-last_beat>=8:provider.control_heartbeat(task_id,ticket);last_beat=time.monotonic()
   client=http.client.HTTPConnection(origin.hostname,origin.port,timeout=15)
   try:client.request('GET','/localpilot/v1/tasks/'+task_id,headers={'Authorization':'Bearer '+tokens['LOCALPILOT_LOCAL_TOKEN']});response=client.getresponse();assert response.status==200;task=json.loads(response.read())
   finally:client.close()
   if task.get('status')=='requires_approval' or task.get('quiescent') and task.get('status') in {'completed','failed','incomplete','cancelled','timed_out','requires_human'}:break
   time.sleep(2)
  write(out/'official-task.json',task);view=provider.status(task_id);write(out/'companion-view.json',view);tools=[t for t in task.get('tools',[]) if t.get('payload',{}).get('ok') is True and t.get('receipt_reused') is False and t.get('side_effect_status')!='unknown'];oracle=task.get('status')=='completed' and bool(tools) and nonce in (task.get('result') or {}).get('text','') and sha(source)==expected and view.get('task_id')==task_id
  report.update(status=task.get('status'),host_oracle=oracle,pass_result=oracle,successful_non_reused_receipts=len(tools),core_verification=task.get('verification_summary'),companion_view_same_official_task=view.get('task_id')==task_id,elapsed_seconds=round(time.monotonic()-started,3))
 except Exception as error:report.update(status='FAILED_OR_BLOCKED',error_type=type(error).__name__,error=str(error)[:500])
 finally:
  try:report['stop_result']=invoke(['product-control','--request-json',json.dumps({'version':1,'operation':'service_control','args':{'module':'core','action':'stop','confirmed':True}})])
  except Exception:report['stop_result']={'status':'UNKNOWN','force_kill':False}
  report['daily_configuration_unchanged']=before=={str(p):sha(p) for p in daily if p.is_file()};write(out/'acceptance.json',report);print(json.dumps({k:v for k,v in report.items() if k!='submission'}),flush=True)
if __name__=='__main__':main()
