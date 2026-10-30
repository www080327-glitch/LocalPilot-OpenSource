"""Real released Core HTTP; deterministic model fixture. No cloud, user files or keys.
Launched by the ignored Rust integration test. Temporary owner-only state is removed at exit.
"""
import json, os, secrets, tempfile, threading, sys, socket
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from localpilot_service.deployment import build

class Model(BaseHTTPRequestHandler):
 def do_POST(self):
  self.rfile.read(int(self.headers.get('Content-Length',0)))
  body=json.dumps({'id':'fixture','model':'desktop-scripted','choices':[{'index':0,'message':{'role':'assistant','content':'SCRIPTED-CORE-RECOVERY'},'finish_reason':'stop'}],'usage':{'prompt_tokens':4,'completion_tokens':2}}).encode()
  self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def log_message(self,*a):pass

with tempfile.TemporaryDirectory(prefix='lp-native-recovery-') as tmp:
 root=Path(tmp);root.chmod(0o700);work=root/'workspace';work.mkdir(mode=0o700)
 model=ThreadingHTTPServer(('127.0.0.1',0),Model);threading.Thread(target=model.serve_forever,daemon=True).start()
 routes={'localpilot':{'workspace':str(work),'backend':{'kind':'local-openai','base_url':f'http://127.0.0.1:{model.server_port}/v1','model':'desktop-scripted','capabilities':{'streaming':False}},'cloud_egress':'LOCAL_ONLY','reasoning_only':True,'capabilities':{'read':False,'write':False,'execute':False},'budgets':{'max_steps':2,'max_tool_calls':0,'max_output_tokens':64}}}
 token_a=secrets.token_hex(24);token_b=secrets.token_hex(24)
 os.environ['LP_GUI_FIXTURE_A']=token_a;os.environ['LP_GUI_FIXTURE_B']=token_b
 config={'schema_version':1,'port':0,'data_dir':str(root/'data'),'routes':routes,'clients':[{'subject':'fixture-a','token_env':'LP_GUI_FIXTURE_A'},{'subject':'fixture-b','token_env':'LP_GUI_FIXTURE_B'}]}
 cfg=root/'service.json';cfg.write_text(json.dumps(config));cfg.chmod(0o600)
 srv=build(cfg);threading.Thread(target=srv.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{srv.server_port}'
 opener=build_opener(ProxyHandler({}))
 def request(path,body=None,method=None):
  r=Request(origin+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers={'Authorization':'Bearer '+token_a,'Content-Type':'application/json'})
  with opener.open(r,timeout=15) as f:return json.load(f)
 session=request('/localpilot/v1/sessions',{'model':'localpilot'})
 request('/localpilot/v1/sessions/'+session['id'],method='DELETE')
 class CutOnce(BaseHTTPRequestHandler):
  dropped=False
  def do_POST(self):
   body=self.rfile.read(int(self.headers.get('Content-Length',0)))
   r=Request(origin+self.path,data=body,headers={k:v for k,v in self.headers.items() if k.lower() not in {'host','content-length','connection'}})
   try:
    with opener.open(r,timeout=15) as f: status=f.status;payload=f.read()
   except HTTPError as e:status=e.code;payload=e.read()
   if self.path=='/localpilot/v1/tasks' and not CutOnce.dropped and 200<=status<300:
    CutOnce.dropped=True;self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
   self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
  def log_message(self,*a):pass
 proxy=ThreadingHTTPServer(('127.0.0.1',0),CutOnce);threading.Thread(target=proxy.serve_forever,daemon=True).start()
 for name,token in [('a',token_a),('b',token_b)]:
  home=root/name;home.mkdir(mode=0o700)
  (home/'connection.json').write_text(json.dumps({'url':origin,'token_env':'LP_GUI_FIXTURE_'+name.upper()}));(home/'connection.json').chmod(0o600)
  (home/'clients.env').write_text('export LP_GUI_FIXTURE_'+name.upper()+'='+token+'\n');(home/'clients.env').chmod(0o600)
 print(json.dumps({'home_a':str(root/'a'),'home_b':str(root/'b'),'origin':origin,'proxy':f'http://127.0.0.1:{proxy.server_port}','closed_session':session['id'],'state':str(root/'journal')}),flush=True)
 try:sys.stdin.read()
 finally:
  proxy.shutdown();srv.shutdown();model.shutdown();srv.service.shutdown();srv.server_close();srv.access.close();model.server_close();proxy.server_close()
