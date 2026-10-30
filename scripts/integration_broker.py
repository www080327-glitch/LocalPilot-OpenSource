"""Native credential broker: fixed provider/model, durable reservation, synthetic tests."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,threading,time,ssl,subprocess,os
from pathlib import Path
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*a,**k):raise ValueError('Redirect refused')

class Broker:
    def __init__(self,key,output,limit=.20,max_requests=24,tls=False):
        self.key=key;self.root=Path(output);self.root.mkdir(parents=True,exist_ok=False)
        self.limit=limit;self.max_requests=max_requests;self.lock=threading.Lock();self.rows=[];self.reserved=0;self.active='qualification'
        broker=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_POST(self):
                try:broker.request(self)
                except (BrokenPipeError,ConnectionResetError):pass
                except Exception:
                    try:self.send_error(502,'Native broker failure')
                    except OSError:pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.scheme='http';self.ca_file=None
        if tls:
            private=Path.home()/('.cache/localpilot-unified-20261025/tls-broker-'+str(self.server.server_port))
            private.mkdir(mode=0o700,parents=True,exist_ok=False)
            cert=private/'localhost.pem';secret=private/'localhost.key'
            subprocess.run(['/usr/bin/openssl','req','-x509','-nodes','-newkey','rsa:2048','-keyout',str(secret),'-out',str(cert),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1,DNS:localhost'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            secret.chmod(0o600);context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,secret);self.server.socket=context.wrap_socket(self.server.socket,server_side=True)
            self.scheme='https';self.ca_file=cert
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    @property
    def port(self):return self.server.server_port
    def save(self):
        p=self.root/'BUDGET.json';temporary=p.with_suffix('.tmp')
        temporary.write_text(json.dumps({'limit_usd_peak':self.limit,'max_requests':self.max_requests,'reserved_usd_peak':self.reserved,'actual_invoice':'UNKNOWN','rows':self.rows},indent=2)+'\n');temporary.replace(p)
    def request(self,h):
        size=int(h.headers.get('Content-Length','0'))
        if not 0<size<=550000:h.send_error(413);return
        raw=h.rfile.read(size);payload=json.loads(raw)
        if h.path not in {'/chat/completions','/v1/chat/completions','/v1/messages'} or payload.get('model')!='deepseek-flash' or b'data:image' in raw:
            h.send_error(403);return
        maximum=payload.get('max_tokens',2048)
        if type(maximum) is not int or not 0<maximum<=2048:h.send_error(400,'Output budget refused');return
        reserve=(len(raw)*.3+maximum*1.2)/1000000
        with self.lock:
            if len(self.rows)>=self.max_requests or self.reserved+reserve>self.limit:h.send_error(429,'Qualification budget exhausted');return
            row={'number':len(self.rows)+1,'case':self.active,'request_bytes':len(raw),'max_output_tokens':maximum,'reservation_usd_peak':reserve,'status':'RESERVED'}
            self.rows.append(row);self.reserved+=reserve;self.save()
            number=row['number']
        stem=self.root/f'wire-{number:03d}'
        stem.with_suffix('.request.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        messages=h.path.endswith('/messages');url='https://api.deepseek.com/anthropic/v1/messages' if messages else 'https://api.deepseek.com/chat/completions'
        headers={'Content-Type':'application/json'}
        if messages:headers.update({'x-api-key':self.key,'anthropic-version':'2023-06-01'})
        else:headers['Authorization']='Bearer '+self.key
        start=time.monotonic()
        try:
            with build_opener(NoRedirect()).open(Request(url,data=raw,headers=headers),timeout=50) as response:
                body=response.read(4000001);content_type=response.headers.get('Content-Type','application/json')
                if len(body)>4000000:raise ValueError('Provider reply too large')
            stem.with_suffix('.response').write_bytes(body);usage={}
            if payload.get('stream'):
                for line in body.splitlines():
                    if not line.startswith(b'data:'):continue
                    try:event=json.loads(line[5:])
                    except ValueError:continue
                    usage.update(event.get('usage') or {})
                    usage.update((event.get('message') or {}).get('usage') or {})
            else:usage=json.loads(body).get('usage') or {}
            hit=usage.get('cache_read_input_tokens') if messages else usage.get('prompt_cache_hit_tokens')
            miss=(usage.get('input_tokens',0)+usage.get('cache_creation_input_tokens',0)) if messages else usage.get('prompt_cache_miss_tokens')
            output=usage.get('output_tokens') if messages else usage.get('completion_tokens')
            cost=(hit*.006+miss*.3+output*1.2)/1000000 if all(type(v)is int for v in [hit,miss,output]) else None
            with self.lock:
                if cost is not None:self.reserved+=cost-reserve
                row.update(status='COMPLETE',usage=usage,estimated_usd_peak=cost,estimated_usd_offpeak=cost/2 if cost is not None else None);self.save()
            h.send_response(200);h.send_header('Content-Type',content_type);h.send_header('Content-Length',str(len(body)));h.end_headers();h.wfile.write(body)
        except HTTPError as e:
            with self.lock:row.update(status='HTTP_ERROR',code=e.code);self.save()
            e.close();h.send_error(502,'Provider request failed; reservation retained')
        except Exception as e:
            with self.lock:row.update(status='UNKNOWN',error_type=type(e).__name__);self.save()
            h.send_error(502,'Provider outcome unknown; reservation retained')
        finally:
            with self.lock:row['seconds']=time.monotonic()-start;self.save()
    def close(self):self.server.shutdown();self.thread.join(5);self.server.server_close();self.key=None
