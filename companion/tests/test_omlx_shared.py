import json
from pathlib import Path
import tempfile
import os
import plistlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from companion.config import Config
from companion.model.backend import ModelManager


class SharedOmlxTests(unittest.TestCase):
    def test_desktop_control_proof_is_user_bound_and_conversations_are_isolated(self):
        from companion.runtime.inference_controls import InferenceControls
        class Store:
            def get(self,*a):return None
            def set(self,*a):pass
        with tempfile.TemporaryDirectory() as folder:
            contents=Path(folder)/'Desktop.app/Contents';(contents/'MacOS').mkdir(parents=True)
            executable=contents/'MacOS/localpilot-desktop';executable.write_text('fixture')
            (contents/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'io.localpilot.desktop.fixture'}))
            controls=InferenceControls(SimpleNamespace(config=Config(desktop_control_enabled=True),store=Store()))
            process=SimpleNamespace(exe=lambda:str(executable),uids=lambda:SimpleNamespace(real=os.getuid()),create_time=lambda:1.0)
            policy={'version':'1.0','source':'local_only','objective':'quality'}
            controls.current={'id':'first','phase':'prepared','kind':'local'}
            with patch('psutil.Process',return_value=process),patch.object(controls,'ack',return_value={'status':'ready_to_start'}):
                self.assertEqual(controls.desktop_presented('first',1,policy)['status'],'ready_to_start')
                first=controls.current['conversation_id']
                controls.current={'id':'second','phase':'prepared','kind':'local'}
                controls.desktop_presented('second',1,policy)
                self.assertNotEqual(first,controls.current['conversation_id'])
                process.uids=lambda:SimpleNamespace(real=os.getuid()+1)
                self.assertEqual(controls.desktop_presented('second',1,policy)['status'],'ui_required')
    def test_unloaded_service_never_falls_back_or_starts_worker(self):
        config=Config(backend='omlx',model_path='/not-loaded',http_model_endpoint='http://127.0.0.1:9/v1',http_model_name='small')
        model=ModelManager(config)
        with patch('companion.runtime.power.local_model_block_reason',return_value=None),patch('companion.model.omlx.loaded_model',side_effect=ValueError('not loaded')):
            result=model.complete([{'role':'user','content':'synthetic'}])
        self.assertEqual(result['error_stage'],'omlx_admission');self.assertEqual(model.inferences,0);self.assertIsNone(model.child)

    def test_low_power_shared_small_model_uses_bounded_nonreasoning_request(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'w.safetensors').write_bytes(b'fixture')
            (root/'config.json').write_text(json.dumps({'model_type':'qwen3_5','text_config':{'hidden_size':1024,'num_hidden_layers':24,'intermediate_size':3584}}))
            config=Config(backend='omlx',model_path=str(root),http_model_endpoint='http://127.0.0.1:9/v1',http_model_name='small',http_model_host_local_only=True)
            model=ModelManager(config)
            with patch('companion.runtime.power.local_model_block_reason',return_value=None),patch('companion.model.omlx.loaded_model',return_value={'id':'small','loaded':True,'estimated_size':700000000}),patch('companion.escalation.provider.request_chat',return_value={'status':'ok','text':'fixture'}) as request:
                result=model.complete([{'role':'user','content':'synthetic'}],max_tokens=32)
            self.assertEqual(result['backend'],'omlx');self.assertEqual(request.call_args.kwargs['chat_template_kwargs'],{'enable_thinking':False});self.assertIsNone(model.child)

if __name__=='__main__':unittest.main()
