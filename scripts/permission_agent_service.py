"""Actual provider acceptance service with isolated private state and public test files.
No scripted model, operator auto-approval, model loading or user desktop mutation.
"""
import json,os,secrets,sys
from pathlib import Path
from localpilot_service.cli import save
from localpilot_service.deployment import build

home=Path(sys.argv[1]).resolve();work=Path(sys.argv[2]).resolve();port=int(sys.argv[3])
home.mkdir(parents=True,exist_ok=True,mode=0o700);work.mkdir(parents=True,exist_ok=True)
if not (home/'service.json').exists():
 tokens={f'LOCALPILOT_{name.upper()}_TOKEN':secrets.token_urlsafe(32) for name in ['http','codex','dsh','operator']}
 (home/'clients.env').write_text(''.join(f'export {k}={v}\n' for k,v in tokens.items()));(home/'clients.env').chmod(0o600)
 route={'workspace':str(work),'engine':'v5','backend':{'kind':'deepseek-native','model':'deepseek-flash','key_file':str(Path.home()/'Desktop/aic竞赛/LocalPilot/.localpilot/secrets/deepseek.key'),'timeout':45},'thinking':'none','permissions':'approve-mutations','capabilities':{'read':True,'write':True,'execute':False},'cloud_egress':'CLOUD_ALLOWED','cloud_egress_paths':['.','source.md','analysis.txt','documents/source.md','image.png','archive.zip','report.pdf','source.py','letter.txt'],'budgets':{'max_steps':20,'max_tool_calls':32,'max_output_tokens':2048,'max_subagents_per_turn':0}}
 read={**route,'capabilities':{'read':True,'write':False,'execute':False},'verification':{'id':'actual-host-read-analysis','files':{'analysis.txt':__import__('hashlib').sha256(b'LOCALPILOT-PERMISSION-AGENT-REAL').hexdigest()},'required_text':'LOCALPILOT-PERMISSION-AGENT-REAL'}}
 clients=[{'subject':n,'token_env':f'LOCALPILOT_{n.upper()}_TOKEN','routes':{'localpilot':'organize','analysis':'analysis'}} for n in ['http','codex','dsh']]
 clients.append({'subject':'operator','token_env':'LOCALPILOT_OPERATOR_TOKEN','operator':True,'scopes':['read','control','cancel'],'approval_for':['http','codex','dsh'],'routes':{}})
 save(home/'service.json',{'schema_version':1,'port':port,'data_dir':str(home/'data'),'clients':clients,'routes':{'organize':route,'analysis':read}})
 save(home/'connection.json',{'url':f'http://127.0.0.1:{port}','token_env':'LOCALPILOT_HTTP_TOKEN'})
for line in (home/'clients.env').read_text().splitlines():
 k,v=line.removeprefix('export ').split('=',1);os.environ[k]=v
if os.environ.get('LP_ACCEPTANCE_FAULT')=='post-copy-verification':
 import agent.safe_files as sf
 original=sf.digest_fd
 def fail_after_copy(fd):
  target=work/'uncertain-copy.txt'
  if target.exists() and os.fstat(fd).st_ino==target.stat().st_ino:
   raise OSError('Acceptance-only injected post-dispatch verification failure')
  return original(fd)
 sf.digest_fd=fail_after_copy
server=build(home/'service.json')
print(json.dumps({'status':'ready','origin':f'http://127.0.0.1:{server.server_port}','home':str(home),'workspace':str(work)}),flush=True)
try:server.serve_forever(poll_interval=.1)
finally:server.service.suspend();server.server_close();server.access.close()
