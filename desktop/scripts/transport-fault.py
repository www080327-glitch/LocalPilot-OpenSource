"""Real-byte loopback transport fault, not a model/UI mock. Drops the first SSE stream.
HTTP Authorization is forwarded in memory only, never written or printed.
"""
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from http.client import HTTPConnection
from pathlib import Path
(Path(__file__).resolve().parents[1]/'docs/evidence/runs/v0.2.0').mkdir(parents=True,exist_ok=True)
import json,threading,socket
ROOT=Path(__file__).resolve().parents[1];REPORT=ROOT/'docs/evidence/runs/transport-fault.json';lock=threading.Lock();state={'evidence_class':'REAL_MODEL_WITH_SCRIPTED_TRANSPORT_FAULT','requests':[],'sse_connections':0,'dropped_streams':0,'task_submissions':0}
class H(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):self.proxy()
 def do_POST(self):self.proxy()
 def proxy(self):
  size=int(self.headers.get('Content-Length','0'));body=self.rfile.read(size) if size else None
  headers={k:v for k,v in self.headers.items() if k.lower() not in {'host','connection'}}
  stream='/events?' in self.path
  with lock:
   state['requests'].append({'method':self.command,'path':self.path})
   if stream:state['sse_connections']+=1
   drop=stream and state['sse_connections']==1
   if self.command=='POST' and self.path=='/localpilot/v1/tasks':state['task_submissions']+=1
   REPORT.write_text(json.dumps(state,indent=2))
  conn=HTTPConnection('127.0.0.1',8876,timeout=40)
  try:
   conn.request(self.command,self.path,body,headers);res=conn.getresponse();self.send_response(res.status)
   for k,v in res.getheaders():
    if k.lower() not in {'connection','transfer-encoding'}:self.send_header(k,v)
   self.send_header('Connection','close');self.end_headers();self.close_connection=True
   if stream:
    while True:
     line=res.readline()
     if not line:break
     self.wfile.write(line);self.wfile.flush()
     if drop and line.strip()==b'':
      with lock:state['dropped_streams']+=1;REPORT.write_text(json.dumps(state,indent=2))
      self.connection.shutdown(socket.SHUT_RDWR);break
   else:self.wfile.write(res.read())
  except (BrokenPipeError,ConnectionResetError,TimeoutError):pass
  finally:conn.close()
server=ThreadingHTTPServer(('127.0.0.1',8886),H);print('loopback fault proxy ready on 8886',flush=True);server.serve_forever()
