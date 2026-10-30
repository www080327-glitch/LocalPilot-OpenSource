"""Persistent release gate for false completion and uncertain-effect replay.

Uses current source, real files/HTTP/SQLite/OS with scripted models and host
answers. Does not call a provider or establish model/GUI end-to-end quality.
"""
import argparse
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
if a.output.exists():raise SystemExit('Existing regression evidence is immutable; select a fresh output file')
modules=['tests.test_scope_escalation','tests.test_host_tools','tests.test_tool_protocol_reliability',
         'tests.test_harness_reliability','tests.test_finalization_recovery','tests.test_agent_service',
         'tests.test_v5_completion_controls']
suite=unittest.defaultTestLoader.loadTestsFromNames(modules)
result=unittest.TextTestRunner(verbosity=2).run(suite)
report={'kind':'REAL_FILES_HTTP_SQLITE_OS_SCRIPTED_MODELS','tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'skipped':len(result.skipped),'passed':result.wasSuccessful(),
        'axes':['Execution from durable intent and actual receipts','Delivery from finalization state','Verification from trusted host checks','Engineering separate from model prose'],
        'coverage':['permission insufficient','approval rejected','tool not dispatched','partial effect','timeout','effect before lost receipt/checkpoint','UNKNOWN quarantine','model success prose cannot settle failed obligations','resubmission after recovery'],
        'test_modules':modules,'real_model_calls':False,'gui_acceptance':False}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(0 if result.wasSuccessful() else 1)
