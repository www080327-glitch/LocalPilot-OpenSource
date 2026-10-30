"""Lifecycle management contracts; real job migration is separately qualified."""
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from localpilot_service.lifecycle import launch

class UpgradeLifecycleTests(unittest.TestCase):
    def test_stopped_job_rebinds_to_new_runtime_before_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            (home/'core-launch-agent.plist').write_bytes(plistlib.dumps({'ProgramArguments':['/old/python']}))
            calls=[]
            def command(*args):
                calls.append(args);return subprocess.CompletedProcess(args,0,'state = not running','')
            with patch('localpilot_service.lifecycle.command',side_effect=command):launch(home)
            self.assertEqual([c[0] for c in calls],['print','bootout','bootstrap'])
            spec=plistlib.loads((home/'core-launch-agent.plist').read_bytes())
            self.assertEqual(spec['ProgramArguments'][0],sys.executable);self.assertFalse(spec['KeepAlive'])
            self.assertEqual(spec['ProcessType'],'Interactive')
    def test_active_job_cannot_be_silently_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);calls=[]
            def command(*args):
                calls.append(args);return subprocess.CompletedProcess(args,0,'state = running\n pid = 123','')
            with patch('localpilot_service.lifecycle.command',side_effect=command):
                with self.assertRaises(ValueError):launch(home)
            self.assertEqual([c[0] for c in calls],['print'])
