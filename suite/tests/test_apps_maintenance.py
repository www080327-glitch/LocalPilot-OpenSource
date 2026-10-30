import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from localpilot_suite.apps import cleanup,digest


class CleanupSafetyTests(unittest.TestCase):
    def test_changed_bundle_refuses_cleanup_before_archiving(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);app=root/'LocalPilot.app';app.mkdir();(app/'file').write_text('before')
            plan=root/'plan.json';plan.write_text(json.dumps({'apps':[{'path':str(app),'sha256':digest(app),'eligible':True}]}))
            (app/'file').write_text('changed')
            with patch('localpilot_suite.apps.archive') as archive:
                with self.assertRaises(ValueError):cleanup(plan,root/'archives')
                archive.assert_not_called()
            self.assertTrue(app.is_dir())
    def test_running_bundle_retained_and_no_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);app=root/'LocalPilot.app';app.mkdir();(app/'file').write_text('before')
            plan=root/'plan.json';plan.write_text(json.dumps({'apps':[{'path':str(app),'sha256':digest(app),'eligible':True}]}))
            with patch('localpilot_suite.apps.processes',return_value=[{'bundle_paths':[str(app)]}]),patch('localpilot_suite.apps.archive') as archive:
                result=cleanup(plan,root/'archives');archive.assert_not_called()
            self.assertEqual(result[0]['status'],'retained_running');self.assertTrue(app.is_dir())
    def test_reference_added_after_plan_retains_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);app=root/'LocalPilot.app';app.mkdir()
            plan=root/'plan.json';plan.write_text(json.dumps({'apps':[{'path':str(app),'sha256':digest(app),'eligible':True}]}))
            with patch('localpilot_suite.apps.processes',return_value=[]),patch('localpilot_suite.apps.current_references',return_value={str(app):['profile.json']}),patch('localpilot_suite.apps.archive') as archive:
                result=cleanup(plan,root/'archives');archive.assert_not_called()
            self.assertEqual(result[0]['status'],'retained_referenced');self.assertTrue(app.is_dir())
