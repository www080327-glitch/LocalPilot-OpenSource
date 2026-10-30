from pathlib import Path
import tempfile
import unittest
from localpilot_suite.download_journal import download

class Manager:
    base='http://127.0.0.1:1'
    count=0
    def request(self,path,body=None):
        if path.endswith('/tasks'):return {'tasks':[]}
        self.count+=1;raise TimeoutError('response lost')

class DownloadJournalTests(unittest.TestCase):
    def test_unknown_download_is_not_replayed_with_a_new_process(self):
        with tempfile.TemporaryDirectory() as root:
            manager=Manager()
            with self.assertRaises(TimeoutError):download(manager,Path(root),'fixture/model')
            with self.assertRaises(ValueError):download(manager,Path(root),'fixture/model')
            self.assertEqual(manager.count,1)
