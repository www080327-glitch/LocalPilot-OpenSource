"""Final packaged Companion: rules, actual small local model, advisory delegation."""
import argparse,json,os,secrets,subprocess,sys,threading,time
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request,urlopen
from agent.omlx import OMLXBackend
from localpilot_service.security import private_json,Principal
from localpilot_service.model_resources import ModelResources

def main():
 p=argparse.ArgumentParser();p.add_argument('--private',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--settings',type=Path,required=True);a=p.parse_args();a.private.mkdir(mode=0o700,parents=True,exist_ok=False);a.evidence.mkdir(parents=True,exist_ok=False)
 settings=private_json(a.settings);key=settings['auth']['api_key'];model='mlx-community--Qwen3.5-0.8B-4bit';base=f"http://127.0.0.1:{settings['server']['port']}/v1";backend=OMLXBackend(base_url=base,model=model,api_key=key)
 before=backend.inspect_service();row=next(m for m in before['models'] if m['id']==model)
 if before.get('active_requests')!=0:raise RuntimeError('Provider busy')
 ordinary=Principal('companion-qualification',secrets.token_urlsafe(32),routes={'local':'local'});host=Principal('host',secrets.token_urlsafe(32),operator=True,scopes=frozenset({'resource_control'}),approval_for=(ordinary.subject,),routes={})
 resources=ModelResources(SimpleNamespace(access=SimpleNamespace(principals={ordinary.subject:ordinary}),model_backends={'local':backend},service=SimpleNamespace(condition=threading.Condition(),tasks={})),a.private/'resource.json');body={'client_subject':ordinary.subject,'model':'local','operation':'load','confirmed':True,'max_memory_bytes':4*1024**3}
 with backend._open('/models/status') as response:raw_models=json.load(response)['models']
 actual_path=next(m['model_path'] for m in raw_models if m['id']==model)
 owned=False;process=None;report={'classification':'REAL_PACKAGED_COMPANION_HTTP_STREAM','cloud_calls':0,'gui_interaction':'NOT_RUN','cases':[]}
 try:
  if not row['loaded']:
   r=resources.operate(host,body,'companion-load');owned=r.get('status')=='completed'
   if not owned:raise RuntimeError('Small model load unconfirmed')
  cfg={'data_dir':str(a.private/'data'),'model_path':actual_path,'backend':'omlx','http_model_endpoint':base,'http_model_name':model,'http_model_api_key_env':'LP_COMPANION_OMLX','http_model_host_local_only':True,'model_routing_enabled':False,'localpilot_endpoint':'','watch_dirs':[],'native_observation_enabled':False,'notifications':False,'proactive_level':'off','proactive_delivery':'silent','low_power_policy':'system','max_output_tokens':160,'local_model_min_available_bytes':4*1024**3}
  filename=a.private/'companion.json';filename.write_text(json.dumps(cfg));filename.chmod(0o600);env={**os.environ,'LP_COMPANION_OMLX':key};log=(a.private/'service.log').open('w')
  process=subprocess.Popen([sys.executable,'-m','companion','--config',str(filename),'run'],env=env,cwd=a.private,stdout=log,stderr=log)
  runtimefile=a.private/'data/runtime.json';deadline=time.monotonic()+20
  while not runtimefile.exists() and time.monotonic()<deadline:time.sleep(.1)
  rt=private_json(runtimefile)
  def request(command,stream=False):
   req=Request(f"http://127.0.0.1:{rt['port']}/"+('pet-stream' if stream else 'command'),data=json.dumps(command,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+rt['token'],'Content-Type':'application/json'})
   with urlopen(req,timeout=120) as response:
    raw=response.read().decode()
   if not stream:return json.loads(raw)
   return [json.loads(line[5:]) for line in raw.splitlines() if line.startswith('data:')]
  request({'command':'pet_memory','enabled':False})
  for name,text in [('rules','你好'),('small_real_model','二加三等于几？'),('advisory_delegation','帮我读取文件夹里的文件')]:
   events=request({'command':'pet_ask','text':text},True);(a.evidence/(name+'.json')).write_text(json.dumps(events,ensure_ascii=False,indent=2)+'\n');report['cases'].append({'case':name,'stream_events':len(events),'last':events[-1] if events else None})
 except Exception as e:report['error_type']=type(e).__name__;report['error']=str(e)[:250]
 finally:
  if process and process.poll()is None:process.terminate();process.wait(15)
  if owned:resources.operate(host,{**body,'operation':'unload'},'companion-unload')
  (a.evidence/'RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
