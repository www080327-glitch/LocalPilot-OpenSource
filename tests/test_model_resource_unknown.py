"""No inferred permission can replay an ambiguous model resource operation."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from localpilot_service.model_resources import ModelResources
from localpilot_api.service import APIError

class Backend:
    model='fixture'
    calls=0
    def inspect_service(self):return {'active_requests':0,'models':[{'id':'fixture','loaded':True,'size_bytes':100,'trust_remote_code':False}]}
    def _open(self,*args,**kwargs):self.calls+=1;raise TimeoutError('ambiguous provider result')

class ResourceUnknownTests(unittest.TestCase):
    def test_new_key_cannot_replay_unknown_resource_effect_even_after_restart(self):
        with tempfile.TemporaryDirectory() as root:
            b=Backend();client=SimpleNamespace(routes={'local':'route'})
            server=SimpleNamespace(access=SimpleNamespace(principals={'client':client}),model_backends={'route':b})
            operator=SimpleNamespace(operator=True,scopes={'resource_control'},subject='operator',approval_for=['client'])
            path=Path(root)/'records.json';manager=ModelResources(server,path)
            body={'client_subject':'client','model':'local','operation':'unload','confirmed':True,'max_memory_bytes':1024}
            first=manager.operate(operator,body,'first')
            self.assertEqual(first['status'],'UNKNOWN');self.assertEqual(b.calls,1)
            manager=ModelResources(server,path)
            self.assertEqual(manager.operate(operator,body,'first')['status'],'UNKNOWN')
            with self.assertRaises(APIError) as caught:manager.operate(operator,body,'new-key')
            self.assertEqual(caught.exception.code,'resource_unknown_blocked');self.assertEqual(b.calls,1)

    def test_http_rejection_is_reported_without_crashing_http_serializer(self):
        from urllib.error import HTTPError
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            b=Backend(); b._open=lambda *a,**kw: (_ for _ in ()).throw(HTTPError('http://127.0.0.1',409,'rejected',{},None))
            client=SimpleNamespace(routes={'local':'route'})
            server=SimpleNamespace(access=SimpleNamespace(principals={'client':client}),model_backends={'route':b})
            operator=SimpleNamespace(operator=True,scopes={'resource_control'},subject='operator',approval_for=['client'])
            manager=ModelResources(server,Path(root)/'records.json')
            body={'client_subject':'client','model':'local','operation':'unload','confirmed':True,'max_memory_bytes':1024}
            self.assertEqual(manager.operate(operator,body,'first')['status'],'rejected')
            self.assertEqual(manager.operate(operator,body,'second')['status'],'rejected')
