import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from companion.config import Config
from companion.runtime.service import Companion
from companion.runtime.pet import agent_profile, pet_scope
from companion.model.worker import validate_request

class PetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=Companion(Config(data_dir=str(Path(self.temp.name).resolve()/'data'),backend='disabled',localpilot_endpoint='',watch_dirs=(),native_observation_enabled=False))
    def tearDown(self):
        self.app.store.close();self.temp.cleanup()
    def test_rules_dont_call_model(self):
        self.app.model.complete=Mock(side_effect=AssertionError('model called'))
        r=self.app.command({'command':'pet_ask','text':'你好'})
        self.assertEqual(r['model']['status'],'not_called')
    def test_profiles_are_advisory_not_submissions(self):
        for q,p in [('帮我读取文件夹内的文件','minimal'),('请修改多个文件并重构项目','standard')]:
            self.assertEqual(agent_profile(q),p)
            r=self.app.command({'command':'pet_ask','text':q})
            self.assertEqual(r['agent_profile'],p)
            self.assertEqual(r['task_execution'],'not_started')
            self.assertEqual(r['cloud_transfer'],'not_authorized')
    def test_memory_off_blocks_read_and_write_even_after_reopen(self):
        self.app.command({'command':'pet_memory','enabled':False})
        self.app.command({'command':'pet_ask','text':'你好'})
        self.assertEqual(self.app.store.db.execute('select count(*) from memories').fetchone()[0],0)
        self.app.retrieve=Mock(side_effect=AssertionError('memory read'))
        self.app.observation_context=Mock(side_effect=AssertionError('observation read'))
        self.app.command({'command':'pet_ask','text':'一加一等于几'})
        self.app.store.close()
        self.app.lock.close()
        self.app.channel.stop()
        self.app=Companion(Config(data_dir=str(Path(self.temp.name).resolve()/'data'),backend='disabled',localpilot_endpoint=''))
        self.assertFalse(self.app.command({'command':'pet_memory'})['enabled'])
    def test_scope_restores_on_failure(self):
        auto=self.app.config.localpilot_auto_local
        with self.assertRaises(RuntimeError):
            with pet_scope(self.app):
                self.assertFalse(self.app.config.localpilot_auto_local)
                raise RuntimeError()
        self.assertEqual(self.app.config.localpilot_auto_local,auto)
        self.assertFalse(self.app.pet_request)
    def test_clear_physically_removes_memory_and_preserves_disabled_setting(self):
        self.app.command({'command':'remember','type':'preference','text':'喜欢薄荷绿'})
        self.app.command({'command':'pet_memory','enabled':False})
        self.app.command({'command':'clear','confirmation':'DELETE_COMPANION_MEMORY'})
        self.assertEqual(self.app.command({'command':'pet_export'})['memories'],[])
        self.assertFalse(self.app.command({'command':'pet_memory'})['enabled'])
        self.assertTrue(self.app.store.get('observation_paused'))
    def test_no_permission_grant_from_chat(self):
        self.app.localpilot.submit=Mock(side_effect=AssertionError('submitted'))
        r=self.app.command({'command':'pet_ask','text':'帮我删除文件'})
        self.assertEqual(r['task_execution'],'not_started')
    def test_worker_stream_is_text_only(self):
        base={'messages':[{'role':'user','content':'你好'}],'max_tokens':20,'stream':True}
        validate_request(base)
        for extra in [{'tools':[]},{'stream':'yes'},{'command':'rm'}]:
            with self.assertRaises(ValueError):validate_request(base|extra)


class PetStreamTransportTests(unittest.TestCase):
    def test_authenticated_stream_and_no_generic_tool_endpoint(self):
        from companion.channels.server import LocalChannel
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        calls=[]
        def enqueue(command,future):
            calls.append(command['command'])
            command['_on_delta']('真实通道契约样本')
            future.set_result({'status':'ok','text':'通道样本；非真实模型'})
        channel=LocalChannel(0,'fixture-token-only',enqueue);channel.start()
        def request(body,token='fixture-token-only',origin=None):
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
            if origin:headers['Origin']=origin
            return urlopen(Request(f'http://127.0.0.1:{channel.port}/pet-stream',data=json.dumps(body).encode(),headers=headers),timeout=3)
        try:
            with request({'command':'pet_ask','text':'问候'}) as response:
                data=response.read().decode()
            self.assertIn('"event": "draft"',data)
            self.assertIn('"event": "final"',data)
            for args in [({'command':'pet_ask','text':'x'},'wrong'),({'command':'submit_task'},),({'command':'pet_ask','text':'x'},'fixture-token-only','https://example.invalid')]:
                with self.assertRaises(HTTPError) as raised:request(*args)
                self.assertIn(raised.exception.code,[400,403])
                raised.exception.close()
            self.assertEqual(calls,['pet_ask'])
        finally:channel.stop()

if __name__=='__main__': unittest.main()
