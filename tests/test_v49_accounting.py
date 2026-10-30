"""Cost reporting must preserve concurrent identity and unknown usage."""
import tempfile,unittest,json
from pathlib import Path
from benchmarks.v49_analysis import account,price,pair_test
class V49Accounting(unittest.TestCase):
    def write(self,root,name,rows):
        (root/name).write_text(''.join(json.dumps(x)+'\n' for x in rows))
    def test_concurrent_out_of_order_usage_bound_by_id(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);q=[{'request_id':x,'at':1791851400+i,'role':'child','effort':'low'} for i,x in enumerate(['a','b'])]
            self.write(p,'wire-requests.jsonl',q)
            self.write(p,'wire-responses.jsonl',[{'request_id':x,'response':{'model':'deepseek-flash','usage':{'prompt_tokens':n,'prompt_cache_hit_tokens':n-2,'prompt_cache_miss_tokens':2,'completion_tokens':3,'completion_tokens_details':{'reasoning_tokens':1}}}} for x,n in [('b',20),('a',10)]])
            self.write(p,'transport.jsonl',[{**x,'ended':x['at']+2,'thread':x['request_id'],'latency_seconds':2} for x in q])
            a=account(p);self.assertEqual([r['input'] for r in a['requests']],[10,20]);self.assertEqual(a['input_tokens'],30);self.assertEqual(a['parallel_child_pairwise_overlap_seconds'],1);self.assertEqual(a['cost_unknown_attempts'],0)
    def test_missing_usage_does_not_become_free_or_full_cache_statistic(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.write(p,'wire-requests.jsonl',[{'request_id':'a','at':1791851400,'role':'parent','effort':'none'}])
            a=account(p);self.assertEqual(a['cost_unknown_attempts'],1);self.assertEqual(a['usage_unknown_attempts'],1);self.assertIsNone(a['cache_hit_ratio']);self.assertIsNone(a['requests'][0]['estimated_usd']);self.assertEqual(a['invoice'],'UNKNOWN')
    def test_inconsistent_cache_counts_refuse_estimate(self):
        self.assertIsNone(price({'prompt_tokens':10,'prompt_cache_hit_tokens':4,'prompt_cache_miss_tokens':3,'completion_tokens':2},1791851400))
    def test_paired_success_not_confused_by_missing_mode(self):
        rows=[{'common_task':'a','treatment':'one','verified_success':True},{'common_task':'a','treatment':'two','verified_success':False},{'common_task':'b','treatment':'one','verified_success':True}]
        self.assertEqual(pair_test(rows,'one','two')['a_only_success'],1);self.assertEqual(pair_test(rows,'one','two')['ties'],0)
if __name__=='__main__':unittest.main()
