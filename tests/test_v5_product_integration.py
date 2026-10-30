"""Scripted engineering controls; no real inference claims."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from agent.backends import Message
from agent.omlx import OMLXBackend
from agent.local_http import LocalBackendError
from localpilot_service.routing import select_route, routing_contract
from localpilot_service.deployment import build
from localpilot_service.sdk import Client
from localpilot_api.service import APIError
from tests.test_local_http_backend import MockServer, completion


class ProductIntegrationTests(unittest.TestCase):
    def test_hybrid_or_unknown_provider_cannot_enter_strict_source_modes(self):
        for adapter in ['omlx','local-openai','unknown']:
            catalog={'hybrid':{'adapter':adapter,'cloud_egress':'REQUIRES_APPROVAL'}}
            for source in ['local_only','cloud_only']:
                with self.assertRaises(APIError):
                    select_route({'hybrid':'hybrid'},catalog,explicit='hybrid',
                        routing_preferences={'version':'1.0','source':source,'objective':'quality'})
            self.assertEqual(select_route({'hybrid':'hybrid'},catalog,explicit='hybrid',
                routing_preferences={'version':'1.0','source':'local_first','objective':'quality'})[0],'hybrid')

    def test_twenty_policies_apply_source_and_objective(self):
        routes={k:k for k in ('small','large','cloud')}
        catalog={
            'small':{'model':'small','adapter':'omlx','cloud_egress':'LOCAL_ONLY','routing_rank':{'speed':90,'efficiency':90,'quality':10,'balanced':30}},
            'large':{'model':'large','adapter':'omlx','cloud_egress':'LOCAL_ONLY','routing_rank':{'speed':20,'efficiency':10,'quality':90,'balanced':80}},
            'cloud':{'model':'cloud','adapter':'deepseek-native','cloud_egress':'REQUIRES_APPROVAL','routing_rank':{'speed':80,'efficiency':60,'quality':95,'balanced':90}}}
        for source in routing_contract()['sources']:
            for objective in routing_contract()['objectives']:
                policy=dict(version='1.0',source=source,objective=objective)
                selected,decision=select_route(routes,catalog,routing_preferences=policy)
                if source in {'local_only','local_first'}: self.assertNotEqual(selected,'cloud')
                if source in {'cloud_only','cloud_first'}: self.assertEqual(selected,'cloud')
                self.assertEqual(decision['routing_preferences'],policy)
                self.assertFalse(decision['backend_fallback'])
        self.assertEqual(select_route(routes,catalog,routing_preferences=dict(version='1.0',source='local_only',objective='speed'))[0],'small')
        self.assertEqual(select_route(routes,catalog,routing_preferences=dict(version='1.0',source='local_only',objective='quality'))[0],'large')
        with self.assertRaises(APIError):select_route(routes,catalog,explicit='cloud',routing_preferences=dict(version='1.0',source='local_only',objective='quality'))

    def test_local_wire_never_contains_native_signatures(self):
        backend=OMLXBackend(base_url='http://127.0.0.1:9/v1',model='qwen')
        payload=backend._payload([Message('assistant','text',reasoning_content='private',native_replay={'signature':'private'})],[],128,stream=True)
        self.assertNotIn('private',json.dumps(payload))
        self.assertEqual(payload['stream_options'],{'include_usage':True})
        with patch.object(backend,'inspect_service',return_value={'models':[{'id':'qwen','loaded':False}]}):
            with self.assertRaises(LocalBackendError): backend.request([Message('user','hi')])

    def test_low_power_blocks_large_loaded_model_before_inference(self):
        backend=OMLXBackend(base_url='http://127.0.0.1:9/v1',model='large')
        with patch('agent.omlx.sys.platform','darwin'),patch('agent.omlx.subprocess.run') as command:
            command.return_value.stdout='lowpowermode 1'
            with patch.object(backend,'inspect_service',return_value={'models':[{'id':'large','loaded':True,'deployment_status':'ready','size_bytes':30*1024**3}]}):
                with self.assertRaisesRegex(LocalBackendError,'low-power policy'):backend._admit()

    def test_api_preferences_are_durable_idempotent_and_isolated(self):
        model=MockServer()
        model.models=['fast','quality']
        try:
            for _ in range(4):model.add(completion('scripted-fixture'))
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);workspace=root/'workspace';workspace.mkdir()
                routes={name:{'workspace':str(workspace),'backend':{'kind':'local-openai','base_url':model.base_url,'model':name,'capabilities':{'streaming':False,'tool_calling':True}},'routing_rank':rank} for name,rank in [('fast',{'speed':90,'quality':10}),('quality',{'speed':10,'quality':90})]}
                config={'schema_version':1,'port':0,'data_dir':str(root/'data'),'clients':[{'subject':'test','token_env':'LP_V5_FIXTURE','routes':{k:k for k in routes}}],'routes':routes}
                path=root/'service.json';path.write_text(json.dumps(config));path.chmod(0o600)
                with patch.dict(os.environ,LP_V5_FIXTURE='x'*32): server=build(path)
                thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
                client=Client('http://127.0.0.1:'+str(server.server_port),token='x'*32)
                try:
                    speed=dict(version='1.0',source='local_only',objective='speed')
                    quality=dict(version='1.0',source='local_only',objective='quality')
                    a=client.request('/localpilot/v1/tasks',{'input':'fixture','routing_preferences':speed},key='a')
                    server.service.wait(a['id'])
                    b=client.request('/localpilot/v1/tasks',{'input':'fixture','routing_preferences':quality},key='b')
                    server.service.wait(b['id'])
                    self.assertEqual(a['model'],'fast');self.assertEqual(b['model'],'quality')
                    server.catalog['fast']['deployment_status']='unavailable'
                    retry=client.request('/localpilot/v1/tasks',{'input':'fixture','routing_preferences':speed},key='a')
                    self.assertEqual(a['id'],retry['id'])
                    with self.assertRaises(HTTPError) as raised:
                        client.request('/localpilot/v1/tasks',{'input':'fixture','routing_preferences':quality},key='a')
                    self.assertEqual(raised.exception.code,409)
                    raised.exception.close()
                    self.assertEqual(len(model.requests),2)
                    server.catalog['fast']['deployment_status']='ready'
                    c=client.request('/localpilot/v1/tasks',{'input':'second turn','session_id':a['session_id'],'routing_preferences':quality},key='c')
                    server.service.wait(c['id']);self.assertEqual(c['model'],'fast')
                finally:
                    server.shutdown();thread.join();server.service.shutdown();server.server_close();server.access.close()
        finally:model.close()

if __name__=='__main__':unittest.main()
