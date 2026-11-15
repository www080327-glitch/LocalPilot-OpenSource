import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from localpilot_service.cache_budget import LIMIT_BYTES, reserve, status


class OwnedCacheBudgetTests(unittest.TestCase):
    def test_global_reservations_refuse_overcommit_without_deleting_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);home=root/'ledger';first=root/'first';second=root/'second'
            reserve(first,LIMIT_BYTES,home=home)
            sentinel=first/'live-provider-block';sentinel.write_bytes(b'PRESERVE')
            before=hashlib.sha256(sentinel.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError,'exceed'):
                reserve(second,1,home=home)
            self.assertEqual(hashlib.sha256(sentinel.read_bytes()).hexdigest(),before)
            self.assertEqual(status(home=home)['reserved_bytes'],LIMIT_BYTES)

    def test_same_root_is_idempotent_and_capacity_change_needs_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);home=root/'ledger';cache=root/'cache'
            reserve(cache,100,home=home);reserve(cache,100,home=home)
            self.assertEqual(status(home=home)['reserved_bytes'],100)
            with self.assertRaisesRegex(ValueError,'immutable'):
                reserve(cache,99,home=home)
            self.assertEqual(status(home=home)['reserved_bytes'],100)

    def test_external_directories_are_not_discovered_or_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);external=root/'model-weights';external.mkdir();(external/'weight').write_bytes(b'NOT A CACHE')
            reserve(root/'owned',1024,home=root/'ledger')
            report=status(home=root/'ledger')
            self.assertEqual(len(report['entries']),1)
            self.assertEqual(report['entries'][0]['logical_file_bytes'],0)
            self.assertEqual(report['cleanup'],'NO_DELETION_API')
            self.assertTrue((external/'weight').exists())

    def test_removed_fixture_roots_do_not_leak_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cache=root/'first';reserve(cache,LIMIT_BYTES,home=root/'ledger')
            cache.rmdir()
            reserve(root/'second',LIMIT_BYTES,home=root/'ledger')
            self.assertEqual(status(home=root/'ledger')['reserved_bytes'],LIMIT_BYTES)
