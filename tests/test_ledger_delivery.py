"""Generic receipt-derived scope and final-only validation controls; no model claims."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from agent.async_runtime import AsyncPolicy
from agent.finalization import FinalizationPolicy, ledger_projection
from agent.registry import create_default_registry
from agent.session import AgentSession, SessionBudgets
from agent.retry import RetryPolicy
from agent.stabilization import HostVerification, StabilizationControls
from tests.test_runtime_api import Backend, answer, call


class LedgerDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.expected={f'artifact-{i}.txt':f'proof-{i}' for i in range(7)}
        self.hashes={p:hashlib.sha256(c.encode()).hexdigest() for p,c in self.expected.items()}
        self.check_calls=0
    def tearDown(self):self.temp.cleanup()
    def execution(self,root,projection):
        actual={p.name:p.read_text() for p in root.glob('*.txt')}
        reads={r['path']:r['version']['sha256'] for r in projection['manifest'] if r['tool']=='read_file' and r.get('version')}
        ok=actual==self.expected and reads==self.hashes and not any(projection['obligations'].values())
        return HostVerification('passed' if ok else 'blocked','seven arbitrary fixture paths',self.hashes,ok,ok,ok)
    def delivery(self,root,result):
        self.check_calls+=1
        ok=all(p in result.text for p in self.expected) and 'Summary: 7 files' in result.text
        return HostVerification('passed' if ok else 'failed','Delivery count must match 7 receipt paths',self.hashes,True,ok,True)
    def message(self,count):return answer(', '.join(self.expected)+f'\nSummary: {count} files')
    def setup_runtime(self,*answers,policy=True,checker=None):
        write=answer(None,call('apply_patch',{'changes':[{'operation':'create','path':p,'content':c} for p,c in self.expected.items()]},'batch'))
        reads=answer(None,*[call('read_file',{'path':p},f'read-{i}') for i,p in enumerate(self.expected)])
        self.backend=Backend(write,reads,*answers)
        return AgentSession(create_default_registry(self.root,permission_mode='full-permission'),backend=self.backend,
            policy='cloud-only',streaming=False,async_policy=AsyncPolicy(),
            finalization_policy=FinalizationPolicy() if policy else None,completion_check=self.execution,
            verification_callback=checker or self.delivery,retry_policy=RetryPolicy(max_attempts=1),
            stabilization=StabilizationControls(stagnation_limit=0),
            budgets=SessionBudgets(max_steps=12,max_tool_calls=16,max_token_units=1000000,max_output_tokens=1024))
    def test_counts_batch_paths_not_patch_calls_or_children(self):
        runtime=self.setup_runtime(self.message(7));result=runtime.run_turn('Create seven independent fixture files and read every file.')
        self.assertEqual(result.status,'completed');self.assertEqual(self.check_calls,1)
        scope=ledger_projection(runtime)['file_scope']
        self.assertEqual(scope['distinct_successful_mutation_paths'],7)
        self.assertEqual(scope['distinct_full_version_read_paths'],7)
        self.assertEqual(len([r for r in runtime.tool_history if r['name']=='apply_patch']),1)
        self.assertEqual(runtime.subagents,[])
    def test_bad_final_recovers_without_tools_or_replaying_batch(self):
        runtime=self.setup_runtime(self.message(8),self.message(7));result=runtime.run_turn('Create seven files and deliver exact scope.')
        self.assertEqual(result.status,'completed');self.assertEqual(self.check_calls,2)
        self.assertEqual([r['kind'] for r in result.completion['history']],['delivery_verification','delivered'])
        self.assertIsNone(self.backend.requests[-1]['tools'])
        view=json.loads(self.backend.requests[-1]['messages'][-1].content.split('\n',1)[1])
        self.assertEqual(view['file_scope']['distinct_successful_mutation_paths'],7)
        self.assertEqual(view['delivery_feedback']['kind'],'delivery_verification')
        self.assertEqual(len([r for r in runtime.tool_history if r['name']=='apply_patch']),1)
        self.assertEqual(len(list(self.root.glob('*.txt'))),7)
    def test_repeated_bad_final_is_failed_with_verified_execution(self):
        runtime=self.setup_runtime(self.message(8),self.message(8));result=runtime.run_turn('Create seven files and deliver exact scope.')
        self.assertEqual(result.status,'error');self.assertEqual(result.completion['execution'],'completed')
        self.assertEqual(result.completion['delivery'],'failed');self.assertEqual(len(self.backend.requests),4)
        self.assertEqual(len([r for r in runtime.tool_history if r['name']=='apply_patch']),1)
    def test_unknown_delivery_check_does_not_become_completed_or_retry(self):
        def unknown(root,result):return HostVerification('unknown','unknown text validation',self.hashes,True,False,True)
        runtime=self.setup_runtime(self.message(7),self.message(7),checker=unknown)
        result=runtime.run_turn('Create files and deliver.')
        self.assertEqual(result.status,'error');self.assertEqual(result.verification_status,'unknown')
        self.assertEqual(len(self.backend.requests),3)
    def test_policy_none_preserves_legacy_execution_verification_separation(self):
        runtime=self.setup_runtime(self.message(8),policy=False)
        result=runtime.run_turn('Create files and deliver.')
        self.assertEqual(result.status,'completed');self.assertEqual(result.engineering_status,'failed')
        self.assertIsNone(result.completion)
    def test_scope_excludes_unknown_or_denied_patch_resources(self):
        runtime=self.setup_runtime(self.message(7));runtime.run_turn('Create files and deliver.')
        unknown={'turn_id':runtime.turn_id,'id':'unknown','name':'apply_patch','arguments':'{}','receipt_id':'unknown',
            'payload':{'ok':True,'result':{'status':'unknown','changes':[{'path':'untrusted.txt'}]}},
            'status':'completed','side_effect_status':'completed','receipt_reused':False}
        runtime.tool_history.append(unknown)
        projection=ledger_projection(runtime)
        self.assertEqual(projection['file_scope']['distinct_successful_mutation_paths'],7)
        self.assertEqual(projection['obligations']['unknown_receipts'],1)
