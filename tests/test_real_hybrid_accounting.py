"""Offline evidence accounting controls; not real-model acceptance."""
import json
from pathlib import Path
import tempfile
import unittest
from benchmarks.summarize_real_hybrid import summarize_case


class RealEvidenceAccountingTests(unittest.TestCase):
    def test_partial_usage_and_process_orphan_are_not_lost(self):
        with tempfile.TemporaryDirectory() as d:
            c=Path(d)/'case';c.mkdir()
            (c/'spec.json').write_text(json.dumps({'assignments':[]}))
            (c/'result.json').write_text(json.dumps({'status':'failed'}))
            def write(name,rows):(c/name).write_text(''.join(json.dumps(r)+'\n' for r in rows))
            write('model-requests.jsonl',[{'kind':'REAL_CLOUD'}]*3)
            write('model-responses.jsonl',[{'kind':'REAL_CLOUD','started':1,'ended':2,'usage':None,'error':'Length'},
                                          {'kind':'REAL_CLOUD','started':5,'ended':5.01,'usage':None,'error':'HostInjection'}])
            write('wire-requests.jsonl',[{'kind':'REAL_CLOUD','at':1.1},{'kind':'REAL_CLOUD','at':3}])
            write('wire-responses.jsonl',[{'kind':'REAL_CLOUD','at':1.9,'response':{'usage':{'prompt_tokens':100,'completion_tokens':50,'prompt_cache_hit_tokens':0,'prompt_cache_miss_tokens':100}}}])
            row=summarize_case(c)['models']['cloud']
            self.assertEqual(row['adapter_invocations'],3)
            self.assertEqual(row['actual_api_requests'],2)
            self.assertEqual(row['process_interrupted_api_requests'],1)
            self.assertEqual(row['known_input_tokens'],100)
            self.assertEqual(row['known_output_tokens'],50)
            self.assertEqual(row['unknown_usage_calls'],2)
            self.assertEqual(row['actual_api_cost'],'UNKNOWN')

    def test_no_known_usage_never_means_zero_total_cost(self):
        with tempfile.TemporaryDirectory() as d:
            c=Path(d)/'case';c.mkdir()
            (c/'spec.json').write_text(json.dumps({'assignments':[]}))
            (c/'result.json').write_text(json.dumps({'status':'failed'}))
            (c/'wire-requests.jsonl').write_text(json.dumps({'kind':'REAL_CLOUD','at':3})+'\n')
            row=summarize_case(c)['models']['cloud']
            self.assertEqual(row['actual_api_requests'],1)
            self.assertEqual(row['unknown_cost_calls'],1)
            self.assertEqual(row['actual_api_cost'],'UNKNOWN')
