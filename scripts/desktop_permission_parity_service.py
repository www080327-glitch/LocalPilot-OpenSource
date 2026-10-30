"""Isolated real-provider acceptance, generated public files only, no auto approval."""
import json,os,secrets,sys
from pathlib import Path
from localpilot_service.cli import save
from localpilot_service.deployment import build
home=Path(sys.argv[1]).resolve();work=Path(sys.argv[2]).resolve();port=int(sys.argv[3])
home.mkdir(parents=True,exist_ok=True,mode=0o700);work.mkdir(parents=True,exist_ok=True)
if not (home/'service.json').exists():
 tokens={f'LOCALPILOT_{n.upper()}_TOKEN':secrets.token_urlsafe(32) for n in ['http','operator','dsh']}
 env=home/'clients.env';env.write_text(''.join(f'export {k}={v}\n' for k,v in tokens.items()));env.chmod(0o600)
 route={'workspace':str(work),'engine':'v5','backend':{'kind':'deepseek-native','model':'deepseek-flash','key_file':str(Path.home()/'Desktop/aic竞赛/LocalPilot/.localpilot/secrets/deepseek.key'),'timeout':45},'thinking':'none','permissions':'approve-mutations','capabilities':{'read':True,'write':True,'execute':False},'cloud_egress':'CLOUD_ALLOWED','cloud_egress_paths':['.','source.txt','note.txt','sorted/source.txt','copied.txt','sorted','ordinary.txt'],'budgets':{'max_steps':24,'max_tool_calls':64,'max_output_tokens':4096,'max_token_units':1048576,'max_subagents_per_turn':0}}
 # Only generated public fixtures may be projected by these exact paths.
 save(home/'service.json',{'schema_version':1,'port':port,'data_dir':str(home/'data'),'clients':[{'subject':n,'token_env':f'LOCALPILOT_{n.upper()}_TOKEN','routes':{'desktop-parity':'desktop-parity'}} for n in ['http','dsh']]+[{'subject':'operator','token_env':'LOCALPILOT_OPERATOR_TOKEN','operator':True,'scopes':['read','control','cancel'],'approval_for':['http','dsh'],'routes':{}}],'routes':{'desktop-parity':route}})
 save(home/'connection.json',{'url':f'http://127.0.0.1:{port}','token_env':'LOCALPILOT_HTTP_TOKEN'})
for line in (home/'clients.env').read_text().splitlines():
 k,v=line.removeprefix('export ').split('=',1);os.environ[k]=v
server=build(home/'service.json');print(json.dumps({'status':'ready','origin':f'http://127.0.0.1:{server.server_port}','home':str(home),'workspace':str(work)}),flush=True)
try:server.serve_forever(poll_interval=.1)
finally:server.service.suspend();server.server_close();server.access.close()
