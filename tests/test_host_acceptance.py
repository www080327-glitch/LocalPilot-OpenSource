"""Actual host-owned assertion process; generated synthetic code, no model."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import sys
import unittest
from agent.acceptance import HostPythonAcceptance

@unittest.skipUnless(sys.platform == 'darwin', 'macOS executor only')
class HostAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve(); self.work = self.root / 'work'; self.work.mkdir()
        self.source = self.work / 'invoice.py'
        self.runner = self.root / 'host_assertions.py'
        self.runner.write_text("import sys\nsys.path.insert(0, sys.argv[1])\nfrom invoice import invoice\nassert invoice('0.29', 3) == 87\nassert invoice('1.00', 2) == 200\n")
        self.verify = HostPythonAcceptance(self.work, self.runner, ['invoice.py'], required_line='DELIVERED')
    def correct(self):
        self.source.write_text("from decimal import Decimal\ndef invoice(price, count): return int(Decimal(price) * count * 100)\n")
    def test_wrong_amount_and_forged_pass_fail_then_correct_code_passes(self):
        self.source.write_text('def invoice(price, count): return 0\n')
        self.assertEqual(self.verify(self.work, SimpleNamespace(text='PASS\nDELIVERED')).status, 'failed')
        self.correct()
        self.assertEqual(self.verify(self.work, SimpleNamespace(text='DELIVERED')).status, 'passed')
    def test_delivery_line_is_independent_of_code_assertions(self):
        self.correct()
        self.assertEqual(self.verify.execution_check(self.work, {}).status, 'passed')
        self.assertEqual(self.verify(self.work, SimpleNamespace(text='Done DELIVERED')).status, 'failed')
    def test_workspace_cannot_skip_or_modify_host_assertions(self):
        self.source.write_text('from pathlib import Path\nPath('+repr(str(self.runner))+').write_text("pass")\ndef invoice(price, count): return 87\n')
        before = self.runner.read_bytes()
        self.assertEqual(self.verify(self.work, SimpleNamespace(text='DELIVERED')).status, 'failed')
        self.assertEqual(self.runner.read_bytes(), before)
    def test_identity_change_and_timeout_fail_closed(self):
        self.correct(); self.runner.write_text('pass\n')
        self.assertEqual(self.verify(self.work, SimpleNamespace(text='DELIVERED')).status, 'blocked')
        self.runner.write_text('import time\ntime.sleep(2)\n')
        verifier = HostPythonAcceptance(self.work, self.runner, ['invoice.py'], timeout=.1)
        self.assertEqual(verifier(self.work, SimpleNamespace(text='done')).status, 'unknown')
