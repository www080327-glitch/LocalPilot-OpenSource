"""Actual pipe framing tests with tiny scripted helpers; not native AX evidence."""
import sys
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch

from computer.macos import MacOSAXAdapter


class TransportTests(unittest.TestCase):
    def adapter(self, code):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "helper.py"
        path.write_text(code)
        with patch("computer.macos.sys.platform", "darwin"):
            adapter = MacOSAXAdapter([str(path)], binary=sys.executable, timeout=.2)
        self.addCleanup(adapter.close)
        return adapter

    def test_partial_frame_obeys_total_deadline_and_closes_helper(self):
        adapter = self.adapter('import sys,time\nsys.stdin.readline()\nsys.stdout.write("{\\\"status\\\":")\nsys.stdout.flush()\ntime.sleep(5)\n')
        start = time.monotonic()
        with self.assertRaisesRegex(TimeoutError, "read failed; no action dispatched"):
            adapter.request(op="environment")
        self.assertLess(time.monotonic() - start, 1)
        self.assertIsNotNone(adapter.process.poll())

    def test_mutation_partial_frame_reports_unknown_and_never_retries(self):
        adapter = self.adapter('import sys,time\nsys.stdin.readline()\nsys.stdout.write("{\\\"status\\\":")\nsys.stdout.flush()\ntime.sleep(5)\n')
        with self.assertRaisesRegex(TimeoutError, "action outcome UNKNOWN"):
            adapter.request(op="action")

    def test_fragmented_complete_frame_is_valid(self):
        adapter = self.adapter('import sys,time\nsys.stdin.readline()\nsys.stdout.write("{\\\"status\\\":")\nsys.stdout.flush()\ntime.sleep(.02)\nsys.stdout.write("\\\"ok\\\"}\\n")\nsys.stdout.flush()\n')
        adapter.timeout = 2  # Successful framing is not a 200 ms interpreter-startup benchmark.
        self.assertEqual(adapter.request(op="environment"), {"status": "ok"})

    def test_invalid_json_is_fail_closed(self):
        adapter = self.adapter('import sys\nsys.stdin.readline()\nprint("not json",flush=True)\n')
        adapter.timeout = 2  # Keep the negative partial-frame deadline tests unchanged.
        with self.assertRaisesRegex(RuntimeError, "Invalid AX helper JSON"):
            adapter.request(op="environment")
        self.assertIsNotNone(adapter.process.poll())

    def test_healthy_close_delivers_EOF_and_waits_for_clean_exit(self):
        adapter=self.adapter('import sys\nfor line in sys.stdin: print("{\\\"status\\\":\\\"ok\\\"}",flush=True)\nsys.exit(0)\n')
        adapter.timeout=2
        self.assertEqual(adapter.request(op='environment')['status'],'ok')
        adapter.close();self.assertEqual(adapter.process.returncode,0)
