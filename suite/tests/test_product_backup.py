import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from localpilot_service.cli import save
from localpilot_suite.product_backup import backup

class UpgradeBackupTests(unittest.TestCase):
    def test_both_independent_databases_are_snapshotted_without_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);home=root/'home';home.mkdir(mode=0o700);data=home/'data';data.mkdir();comp=home/'companion';comp.mkdir(mode=0o700)
            save(home/'service.json',{'data_dir':str(data)});save(home/'companion.json',{'data_dir':str(comp)})
            for p in [data/'runtime.sqlite3',comp/'memory.sqlite3']:
                db=sqlite3.connect(p);db.execute('CREATE TABLE evidence (value TEXT)');db.execute("INSERT INTO evidence VALUES ('preserved')");db.commit();db.close();p.chmod(0o644 if p.name=='memory.sqlite3' else 0o600)
            original_mode=(comp/'memory.sqlite3').stat().st_mode
            out=root/'backup';result=backup(home,out)
            self.assertEqual((comp/'memory.sqlite3').stat().st_mode,original_mode)
            self.assertEqual(result['databases'],2);self.assertFalse(result['data_overwritten'])
            for name in ['core.sqlite3','companion.sqlite3']:
                db=sqlite3.connect(out/name);self.assertEqual(db.execute('SELECT value FROM evidence').fetchone()[0],'preserved');db.close()
            with self.assertRaises(ValueError):backup(home,out)
