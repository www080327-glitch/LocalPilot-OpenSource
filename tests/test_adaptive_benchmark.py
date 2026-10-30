"""Independent oracle and contamination-boundary controls."""
import json,tempfile,unittest
from pathlib import Path
from benchmarks.adaptive_tasks import tasks,build,verify_artifacts,check_code
from benchmarks.adaptive_profiles import build as profiles


class BenchmarkTests(unittest.TestCase):
    def test_thirty_distinct_public_contracts_and_ten_categories(self):
        rows=tasks();self.assertEqual(len(rows),30);self.assertEqual(len({r['id'] for r in rows}),30)
        self.assertEqual(len({r['category'] for r in rows}),10)
        self.assertEqual(sum(r['split']=='tune' for r in rows),20)
        self.assertFalse(any('oracle' in r['public_files'] for r in rows))
    def test_public_inputs_are_immutable_and_wrong_arithmetic_fails(self):
        s=build('file',1)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for p,t in s['public_files'].items():(root/p).write_text(t)
            (root/'output0.json').write_text(json.dumps(s['oracle']['output0.json']))
            self.assertTrue(all(verify_artifacts(s,root).values()))
            value=dict(s['oracle']['output0.json']);value['sum']+=1
            (root/'output0.json').write_text(json.dumps(value));self.assertFalse(verify_artifacts(s,root)['artifact:output0.json'])
            (root/'input0.json').write_text('[]');self.assertFalse(verify_artifacts(s,root)['input:input0.json'])
    def test_code_oracle_accepts_equivalent_arithmetic_rejects_bug_and_imports(self):
        oracle={'function':'add','op':'Add'}
        self.assertTrue(check_code('def add(a,b):\n return b+a\n',oracle))
        self.assertFalse(check_code('def add(a,b):\n return a-b\n',oracle))
        self.assertFalse(check_code('import os\ndef add(a,b):\n return a+b\n',oracle))
        self.assertFalse(check_code('def add():\n return a+b\n',oracle))
        self.assertFalse(check_code('unused=4\ndef add(a,b):\n return a+b\n',oracle))
    def test_evaluation_outcomes_cannot_update_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'matrix.json').write_text(json.dumps([{'split':'eval'}]))
            with self.assertRaises(ValueError):profiles(root)
    def test_pre_mutation_or_truncated_read_cannot_attest_current_deliverable(self):
        from benchmarks.adaptive_runtime import current_read_paths
        item={'tool':'read_file','path':'module.py','version':{'sha256':'before'},'coverage':{'kind':'full_file','truncated':False}}
        self.assertEqual(current_read_paths([item],{'module.py':'after'}),set())
        item['version']['sha256']='after'
        self.assertEqual(current_read_paths([item],{'module.py':'after'}),{'module.py'})
        item['coverage']['truncated']=True
        self.assertEqual(current_read_paths([item],{'module.py':'after'}),set())
    def test_extra_output_rejected(self):
        s=build('file',1)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for p,t in s['public_files'].items():(root/p).write_text(t)
            (root/'output0.json').write_text(json.dumps(s['oracle']['output0.json']));(root/'unexpected.txt').write_text('extra')
            self.assertFalse(verify_artifacts(s,root)['scope'])


if __name__=='__main__':unittest.main()
