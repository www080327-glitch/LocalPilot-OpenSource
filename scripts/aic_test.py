"""Single-process structured regression evidence, including every skip/subtest."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    records=[]
    class Result(unittest.TextTestResult):
        def addSuccess(self,test):super().addSuccess(test);records.append({'id':test.id(),'status':'PASS'})
        def addSkip(self,test,reason):super().addSkip(test,reason);records.append({'id':test.id(),'status':'SKIP','reason':reason})
        def addFailure(self,test,error):super().addFailure(test,error);records.append({'id':test.id(),'status':'FAIL','reason':str(error[1])})
        def addError(self,test,error):super().addError(test,error);records.append({'id':test.id(),'status':'ERROR','reason':str(error[1])})
        def addSubTest(self,test,subtest,error):
            super().addSubTest(test,subtest,error);records.append({'id':subtest.id(),'status':'SUBTEST_PASS' if error is None else 'SUBTEST_FAIL','reason':str(error[1]) if error else None})
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),top_level_dir=str(ROOT));start=time.monotonic()
    result=unittest.TextTestRunner(verbosity=1,resultclass=Result).run(suite)
    sources={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for d in ['agent','localpilot_service','tests'] for f in (ROOT/d).rglob('*.py')}
    a.output.write_text(json.dumps({'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'skips':len(result.skipped),'wall_seconds':time.monotonic()-start,'successful':result.wasSuccessful(),
        'source_hashes':sources,'records':records,'live_model_quality_evaluation':False},indent=2)+'\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__=='__main__':main()
