"""Final bundled modules + real Qwen35: reviewed MCP, attachment, Companion transport.

Synthetic local fixtures only. Companion native control-window flow is NOT_RUN.
No credentials, cloud, platform login, daily service change, or guard override.
Run under the final archive's embedded Python, outside the source checkout.
"""
import argparse,hashlib,http.client,json,os,shutil,socket,subprocess,sys,time
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4
from urllib.parse import urlsplit

def sha(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=True,indent=2)+'\n');path.chmod(0o600)
def port():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--source',type=Path,required=True);a=p.parse_args();bundle=a.bundle.resolve(strict=True);out=a.out.resolve();out.mkdir(mode=0o700,parents=True,exist_ok=False)
 from localpilot_plugins.manager import PluginManager
 from companion.escalation.service_v491 import LocalPilotProvider
 from companion.config import Config
 import localpilot_service,companion,localpilot_plugins
 report={'model':'Qwen3.6-35B-A3B-4bit','revision':'38740b847e4cb78f352aba30aa41c76e08e6eb46','kind':'REAL_MODEL_SYNTHETIC_LOCAL_INPUTS','imports':{m.__name__:m.__file__ for m in (localpilot_service,companion,localpilot_plugins)},'cases':[],'native_companion_control_window':'NOT_RUN','cloud':'NOT_RUN','real_platforms':'NOT_RUN'}
 assert all(str(bundle/'runtime') in m.__file__ for m in (localpilot_service,companion,localpilot_plugins))
 work=out/'workspace';work.mkdir(mode=0o700);source=work/'source.txt';source.write_text('LOCALPILOT-35B-COMPANION-READ\n')
 docs=out/'authorized-attachments';docs.mkdir(mode=0o700);document=docs/'acceptance-note.txt';marker='LOCALPILOT-35B-DOCUMENT-READ-7d230a';document.write_text(marker+'\n预算 73，负责人 Lin。\n')
 home=out/'core';home.mkdir(mode=0o700);cli=bundle/'localpilot';daily=[Path.home()/'.omlx/settings.json',Path.home()/'.omlx/model_settings.json'];before={str(p):sha(p) for p in daily if p.is_file()}
 env={k:v for k,v in os.environ.items() if not (k.startswith(('LOCALPILOT_','DEEPSEEK_','OPENAI_','OMLX_')) or k in {'PYTHONHOME','PYTHONPATH'})};env.update(PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
 def invoke(args,timeout=150):
  r=subprocess.run([str(cli),'--home',str(home),'--json',*args],env=env,cwd=out,capture_output=True,text=True,timeout=timeout);values=[]
  for line in r.stdout.splitlines():
   try:values.append(json.loads(line))
   except ValueError:pass
  value=values[-1] if values else {'error':'no_json'}
  if r.returncode:raise RuntimeError('CLI_'+str(r.returncode)+':'+str(value.get('error','failed')))
  return value
 def request(path,body=None,operator=False):
  connection=json.loads((home/'connection.json').read_text());tokens={}
  for line in (home/'clients.env').read_text().splitlines():
   name,value=line.removeprefix('export ').split('=',1);tokens[name]=value
  origin=urlsplit(connection['url']);assert origin.hostname=='127.0.0.1' and origin.scheme=='http';client=http.client.HTTPConnection(origin.hostname,origin.port,timeout=25)
  try:
   client.request('POST' if body is not None else 'GET',path,body=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer '+tokens['LOCALPILOT_OPERATOR_TOKEN' if operator else 'LOCALPILOT_LOCAL_TOKEN'],'Content-Type':'application/json'});r=client.getresponse();value=json.loads(r.read())
   if not 200<=r.status<300:raise RuntimeError('HTTP_'+str(r.status)+':'+str((value.get('error') or {}).get('code','failed')))
   return value
  finally:client.close()
 def finish(name,initial,oracle,heartbeat=None):
  task_id=initial['id'];deadline=time.monotonic()+400
  while time.monotonic()<deadline:
   value=request('/localpilot/v1/tasks/'+task_id)
   if heartbeat:heartbeat(task_id)
   if name=='reviewed-mcp' and value.get('status')=='requires_approval':
    action=value.get('required_action') or {};requests=action.get('requests',[])
    if len(requests)!=1:raise RuntimeError('UNEXPECTED_MCP_APPROVAL_PRESERVED')
    resource=requests[0].get('preview',{}).get('risk_summary',{}).get('resource',{})
    if not (requests[0].get('name','').startswith('mcp_public_notes_tool_lookup_public_no_') and resource.get('server_id')=='public-notes' and resource.get('tool_id')=='lookup_public_note' and resource.get('arguments')=={'topic':'mcp'} and resource.get('network_access') is False and resource.get('potential_side_effect')=='observation' and resource.get('catalog_sha256')==report['plugin_review']['catalog_sha256']):raise RuntimeError('UNREVIEWED_MCP_ACTION_PRESERVED')
    write(out/'mcp-reviewed-action.json',action)
    invoke(['task','approve',task_id,'--action-id',action['id'],'--operator-token-env','LOCALPILOT_OPERATOR_TOKEN'])
    continue
   if value.get('status')=='requires_approval' or value.get('quiescent') and value.get('status') in {'completed','failed','incomplete','cancelled','timed_out','requires_human'}:break
   time.sleep(2)
  write(out/(name+'-task.json'),value)
  if not value.get('quiescent'):raise RuntimeError('UNSETTLED_TASK_NO_RETRY')
  passed=value.get('status')=='completed' and oracle(value)
  item={'case':name,'task_id':task_id,'status':value.get('status'),'host_oracle':passed,'core_verification':value.get('verification_summary'),'tool_count':len(value.get('tools',[])),'pass':passed};report['cases'].append(item);write(out/'acceptance.json',report);print(json.dumps(item),flush=True);return value
 def good_tools(v):return [t for t in v.get('tools',[]) if t.get('payload',{}).get('ok') is True and t.get('receipt_reused') is False and t.get('side_effect_status')!='unknown']
 try:
  invoke(['init','--workspace',str(work),'--model',report['model'],'--managed-qwen35','--port',str(port())])
  plugin_source=out/'reviewed-public-notes.py';shutil.copyfile(a.source/'examples/plugins/public_notes/server.py',plugin_source);review=json.loads((a.source/'examples/plugins/public_notes/review.json').read_text());manager=PluginManager(out/'plugins');manager.add({'id':'public-notes','transport':'stdio','command':sys.executable,'args':[str(plugin_source)],'source_files':[str(plugin_source)],'timeout':15});found=manager.discover('public-notes',source_reviewed=True,license_id='MIT');manager.review('public-notes',found['catalog_sha256'],review);manager.enable('public-notes');report['plugin_review']={'source_sha256':sha(plugin_source),'catalog_sha256':found['catalog_sha256'],'network_access':False,'license':'MIT'}
  path=home/'service.json';config=json.loads(path.read_text());model_port=port()
  for route in config['routes'].values():
   if route.get('managed_local_model'):route['managed_local_model']['port']=model_port;route['backend']['base_url']=f'http://127.0.0.1:{model_port}/v1'
   route['engine']='v5';route['budgets']={'max_steps':14,'max_tool_calls':14,'max_output_tokens':1024,'max_token_units':180000}
  template=deepcopy(config['routes']['companion-execution']);template['capabilities']={'read':True,'write':False,'execute':False}
  plugin=deepcopy(template);plugin['plugins']={'home':str(out/'plugins')};doc=deepcopy(template);comp=deepcopy(template);comp['verification']={'id':'companion-independent-source','files':{'source.txt':sha(source)},'required_text':'LOCALPILOT-35B-COMPANION-READ'}
  config['routes'].update({'qualification-mcp':plugin,'qualification-document':doc,'qualification-companion':comp})
  next(c for c in config['clients'] if c['subject']=='local')['routes'].update({name:name for name in ('qualification-mcp','qualification-document','qualification-companion')});write(path,config)
  invoke(['product-control','--request-json',json.dumps({'version':1,'operation':'service_control','args':{'module':'core','action':'start','confirmed':True}})])
  task=invoke(['agent','Use the reviewed public notes MCP tool to look up topic mcp. Quote its exact one-sentence note. No shell or local files.','--model','qualification-mcp','--timeout','380','--key','supplement-mcp-'+uuid4().hex,'--detach'])
  finish('reviewed-mcp',task,lambda v:any(t['name'].startswith('mcp_') for t in good_tools(v)) and 'MCP connects hosts to tools, resources and prompts.' in str((v.get('result') or {}).get('text','')))
  sid=request('/localpilot/v1/sessions',{'model':'qualification-document'})['id'];batch=request('/localpilot/v2/attachments',{'operation':'import','session_id':sid,'client_subject':'local','paths':[str(document)]},True);write(out/'document-import.json',batch)
  task=invoke(['agent','Use document_list and document_read to read the authorized attachment acceptance-note.txt. Quote the exact first line and use document_verify with that quote. Include the returned lpdoc citation in your answer. Do not read local workspace files or use shell.','--model','qualification-document','--session',sid,'--timeout','380','--key','supplement-document-'+uuid4().hex,'--detach'])
  value=finish('document-attachment',task,lambda v:any(t['name']=='document_read' for t in good_tools(v)) and any(t['name']=='document_verify' and t.get('payload',{}).get('result',{}).get('verified') is True for t in good_tools(v)) and marker in str((v.get('result') or {}).get('text','')) and 'lpdoc:' in str((v.get('result') or {}).get('text','')) and sha(document)==hashlib.sha256((marker+'\n预算 73，负责人 Lin。\n').encode()).hexdigest())
  connection=json.loads((home/'connection.json').read_text());tokens={line.removeprefix('export ').split('=',1)[0]:line.split('=',1)[1] for line in (home/'clients.env').read_text().splitlines()};os.environ['LP_SUPPLEMENT_COMPANION_TOKEN']=tokens['LOCALPILOT_LOCAL_TOKEN']
  provider=LocalPilotProvider(Config(data_dir=str(out/'companion-data'),backend='disabled',watch_dirs=(),native_observation_enabled=False,localpilot_endpoint=connection['url'],localpilot_client_subject='local',localpilot_route='qualification-companion',localpilot_api_key_env='LP_SUPPLEMENT_COMPANION_TOKEN',localpilot_host_local_only=True,localpilot_task_timeout_seconds=380,low_power_policy='system'))
  ticket=uuid4().hex
  delegation=provider.submit({'user_request':'Read source.txt and quote its first line exactly. Do not modify files or use shell.','privacy_scope':{'local_only':True}},approved=True,submission_id='supplement-companion-'+uuid4().hex,control_ticket=ticket);write(out/'companion-submission.json',delegation)
  task_id=delegation.get('task_id')
  if not task_id:
   report['cases'].append({'case':'companion-delegation-transport','status':'BLOCKED_BEFORE_SUBMISSION','reason':delegation.get('error'),'pass':False,'policy_overridden':False});report['status']='MEASURED_WITH_BLOCKED_CASE';return
  last_heartbeat=[0.0]
  def heartbeat(task_id):
   if time.monotonic()-last_heartbeat[0]>=8:provider.control_heartbeat(task_id,ticket);last_heartbeat[0]=time.monotonic()
  value=finish('companion-delegation-transport',{'id':task_id},lambda v:bool(good_tools(v)) and 'LOCALPILOT-35B-COMPANION-READ' in str((v.get('result') or {}).get('text','')) and sha(source)==hashlib.sha256(b'LOCALPILOT-35B-COMPANION-READ\n').hexdigest(),heartbeat);view=provider.status(task_id);write(out/'companion-final-view.json',view);report['companion_namespace']='ordinary local owner in this isolated Core; no Operator credential in Companion';report['companion_view_matches_task']=view.get('task_id')==task_id
  report['status']='MEASURED'
 except Exception as error:report.update(status='FAILED_OR_BLOCKED',error_type=type(error).__name__,error=str(error)[:500]);print(json.dumps({'status':report['status'],'error':report['error']}),flush=True)
 finally:
  try:report['stop_result']=invoke(['product-control','--request-json',json.dumps({'version':1,'operation':'service_control','args':{'module':'core','action':'stop','confirmed':True}})])
  except Exception:report['stop_result']={'status':'UNKNOWN','force_kill':False}
  report['daily_configuration_unchanged']=before=={str(p):sha(p) for p in daily if p.is_file()};write(out/'acceptance.json',report)
if __name__=='__main__':main()
