"""Real image HTTP serialization to a local scripted provider, no model claim."""
import base64,io,json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile,threading,unittest
from PIL import Image
from agent.local_http import LocalHTTPBackend, LocalBackendError
from agent.hybrid import CloudEgressPolicy
from localpilot_service.documents import DocumentEngine, DocumentError
from localpilot_service.documents.vision import infer,prepare


class TransportTests(unittest.TestCase):
    def test_real_http_pixels_capability_denial_and_original_integrity(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                body=json.dumps({'choices':[{'message':{'role':'assistant','content':'scripted provider'},'finish_reason':'stop'}],
                                 'model':'fixture-vision','usage':{'prompt_tokens':10,'completion_tokens':2}}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        t=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02});t.start()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();p=root/'red.png';Image.new('RGB',(128,64),'red').save(p);original=p.read_bytes()
            engine=DocumentEngine(root/'store');aid=engine.ingest('u','s',[str(p)])['files'][0]['id']
            backend=LocalHTTPBackend(base_url=f'http://127.0.0.1:{server.server_port}/v1',model='fixture-vision',supports_vision=True)
            try:
                result=infer(engine,'u','s',[aid],'Name the background color',backend,CloudEgressPolicy('LOCAL_ONLY'))
                self.assertEqual(result['usage']['completion_tokens'],2)
                packet=requests[0];url=packet['messages'][1]['content'][1]['image_url']['url']
                im=Image.open(io.BytesIO(base64.b64decode(url.split(',')[1])));r,g,b=im.getpixel((50,30))
                self.assertGreater(r,240);self.assertLess(g,10);self.assertLess(b,10)
                self.assertEqual(p.read_bytes(),original);self.assertNotIn(str(root),json.dumps(packet))
                unsupported=LocalHTTPBackend(base_url=backend.base_url,model='text-only')
                with self.assertRaises(LocalBackendError):unsupported._payload(requests[0]['messages'],None,10)
                with self.assertRaises(DocumentError):infer(engine,'u','s',[aid],'Name color',unsupported,CloudEgressPolicy('LOCAL_ONLY'))
                self.assertEqual(len(requests),1)
            finally:engine.close();server.shutdown();t.join();server.server_close()


if __name__=='__main__':unittest.main()
