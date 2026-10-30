"""Real official HTTP/Gateway/SQLite, scripted model; no platform or real model."""
from pathlib import Path
import json
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
from localpilot_suite import channel_product as gui, channel_tasks as tasks, channels
from localpilot_channels.adapter import Adapter
from tests.channel_fixtures import RealOfficial, configuration, ENV, WX, WA

class ChannelTaskViewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.home=gui.private_directory(self.root/'home',create=True)
        self.host=RealOfficial(self.root);self.addCleanup(self.host.close)
        self.hub,_=gui.roots(self.home,'wechat',True)
        self.state={'binding':True,'generation':'preparation','channel':WX,'subjects':['wa','wb']}
        gui.store_settings(self.hub,self.state);channels.save(self.hub/'credentials.json',ENV)
        self.runtime=gui.runtime_root(self.hub,self.state);gui.private_directory(self.runtime,create=True)
        self.storage=gui.private_directory(self.root/'transport',create=True)
        config=configuration(self.host.url);config['channels']=config['channels'][1:]
        channels.save(self.runtime/'configuration.json',{'adapter':config,'port':1,'state':str(self.storage)})
        self.adapter=Adapter(config,self.storage/'adapter',environment=ENV,wait_seconds=.2);self.addCleanup(self.adapter.close)
        channels.save(self.home/'connection.json',{'url':self.host.url,'token_env':'WA','client_subject':'wa'})
        gui.replace_env(self.home/'clients.env','export WA='+ENV['WA']+'\nexport LOCALPILOT_OPERATOR_TOKEN='+ENV['OP']+'\n')
    def submit(self,text):
        mid='m_'+uuid4().hex+uuid4().hex
        _,result=self.adapter.dispatch('/messages',{'channel':WX,'sender_id':WA,'message_id':mid,'text':text},WX)
        for _ in range(100):
            _,result=self.adapter.dispatch('/tasks/query',{'channel':WX,'sender_id':WA,'task_id':mid},WX)
            if result['status']!='processing':break
            time.sleep(.02)
        return result
    def test_stopped_adapter_view_uses_original_official_facts_without_message_content(self):
        result=self.submit('list')
        viewed=tasks.receipts(self.home,self.hub,self.state,self.runtime)
        row=viewed['tasks'][0]
        self.assertEqual(row['official_task_id'],result['official_task_id']);self.assertEqual(row['status'],'completed')
        self.assertTrue(row['receipts']);self.assertNotIn('PRIVATE_CONTENT',json.dumps(viewed))
        self.assertFalse(row['automatic_resolution']);self.assertTrue(viewed['read_only'])
    def test_host_review_rejects_stale_preview_and_uses_existing_core_approval(self):
        result=self.submit('write approval')
        row=tasks.receipts(self.home,self.hub,self.state,self.runtime)['tasks'][0]
        self.assertTrue(row['can_approve'])
        args={'task_id':row['official_task_id'],'approval_id':row['approval_id'],'preview_fingerprint':'0'*64,'decision_id':uuid4().hex,'decision':'approve','confirmed':True}
        with self.assertRaisesRegex(ValueError,'CHANGED_EXPIRED'):tasks.decide(self.home,self.hub,self.state,self.runtime,args)
        self.assertFalse((self.host.workspace/'approved.txt').exists())
        args['preview_fingerprint']=row['preview_fingerprint']
        observed=tasks.decide(self.home,self.hub,self.state,self.runtime,args)
        self.assertEqual(observed['tool_verification'],'QUERY_ORIGINAL_RECEIPTS')
        for _ in range(100):
            if (self.host.workspace/'approved.txt').exists():break
            time.sleep(.02)
        self.assertEqual((self.host.workspace/'approved.txt').read_text(),'OK')
        with self.assertRaisesRegex(ValueError,'CHANGED_EXPIRED'):tasks.decide(self.home,self.hub,self.state,self.runtime,args)
        # A file appearing is earlier than the worker yielding its Core lease.
        # Teardown must not race the still-running authorized continuation.
        for _ in range(250):
            current=self.host.service.tasks[row['official_task_id']]
            if not current.executing and not current.control_pending:break
            time.sleep(.02)
        self.assertFalse(current.executing)
        self.assertFalse(current.control_pending)
        final=tasks.receipts(self.home,self.hub,self.state,self.runtime)['tasks'][0]
        self.assertEqual(final['status'],'completed')
        self.assertTrue(final['receipts'])
    def test_cancel_uses_ordinary_owner_and_preserves_prior_unknown(self):
        from dataclasses import replace
        principal=self.host.access.principals['wa']
        self.host.access.principals['wa']=replace(principal,scopes=principal.scopes|{'cancel'})
        self.submit('reject')
        row=tasks.receipts(self.home,self.hub,self.state,self.runtime)['tasks'][0]
        channels.save(self.hub/'host-decisions.json',{row['official_task_id']:{'status':'UNKNOWN','generation':'preparation','decision_id':'old-uncertain'}})
        result=tasks.cancel(self.home,self.hub,self.state,self.runtime,{'task_id':row['official_task_id'],'confirmed':True})
        self.assertEqual(result['tool_verification'],'QUERY_ORIGINAL_RECEIPTS')
        self.assertEqual(tasks.journal(self.hub)[row['official_task_id']]['prior']['status'],'UNKNOWN')
        self.assertEqual(tasks.journal(self.hub)[row['official_task_id']]['status'],'UNKNOWN')
        self.assertTrue(tasks.receipts(self.home,self.hub,self.state,self.runtime)['tasks'][0]['host_decision_unknown'])
        self.assertFalse((self.host.workspace/'rejected.txt').exists())
        for _ in range(100):
            current=self.host.service.tasks[row['official_task_id']]
            if not current.executing and not current.control_pending:break
            time.sleep(.02)
    def test_unknown_cancel_cannot_be_reposted_with_another_request(self):
        self.submit('reject')
        row=tasks.receipts(self.home,self.hub,self.state,self.runtime)['tasks'][0]
        channels.save(self.hub/'host-decisions.json',{row['official_task_id']:{'status':'UNKNOWN','kind':'cancel','generation':'preparation'}})
        from localpilot_channels.client import ServiceClient
        original=ServiceClient.request
        with patch.object(ServiceClient,'request',autospec=True,side_effect=original) as request:
            with self.assertRaisesRegex(ValueError,'CANCELLATION_UNKNOWN'):
                tasks.cancel(self.home,self.hub,self.state,self.runtime,{'task_id':row['official_task_id'],'confirmed':True})
            request.assert_not_called()
    def test_legacy_cancellation_record_retains_unknown_hold(self):
        self.submit('reject')
        row=tasks.receipts(self.home,self.hub,self.state,self.runtime)['tasks'][0]
        channels.save(self.hub/'host-decisions.json',{row['official_task_id']:{'status':'cancellation_observed_prior_unknown_preserved','kind':'cancel','generation':'preparation','prior':{'status':'UNKNOWN'}}})
        self.assertTrue(tasks.receipts(self.home,self.hub,self.state,self.runtime)['tasks'][0]['host_decision_unknown'])
    def test_lost_decision_response_is_persisted_and_never_reposted(self):
        self.submit('write approval')
        row=tasks.receipts(self.home,self.hub,self.state,self.runtime)['tasks'][0]
        args={'task_id':row['official_task_id'],'approval_id':row['approval_id'],'preview_fingerprint':row['preview_fingerprint'],'decision_id':uuid4().hex,'decision':'approve','confirmed':True}
        class Lost:
            def request(self,*args,**kwargs):raise OSError('fixture response lost')
        with patch('localpilot_suite.product_control.operator',return_value=(Lost(),{})):
            with self.assertRaisesRegex(ValueError,'UNKNOWN_QUERY_ORIGINAL'):tasks.decide(self.home,self.hub,self.state,self.runtime,args)
        self.assertEqual(tasks.journal(self.hub)[row['official_task_id']]['status'],'UNKNOWN')
        with patch('localpilot_suite.product_control.operator') as operator:
            with self.assertRaisesRegex(ValueError,'UNKNOWN_QUERY_ORIGINAL'):tasks.decide(self.home,self.hub,self.state,self.runtime,{**args,'decision_id':uuid4().hex})
            operator.assert_not_called()

if __name__=='__main__':unittest.main()
