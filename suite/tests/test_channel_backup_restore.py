"""Channel restore preserves UNKNOWN and never reuses original process control."""
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
import test_installation_first_run as fixture
from localpilot_suite import channels,channel_product
from localpilot_suite.channel_paths import private_directory
from localpilot_suite.product_backup import backup,restore

class ChannelBackupRestoreTests(unittest.TestCase):
    def test_channel_database_and_account_data_restore_quarantined(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();home=fixture.RecoveryTests().fixture(root)
            hub,state=channel_product.roots(home,'qq',True)
            channel_product.store_settings(hub,{'generation':'preparation','binding':False})
            private_directory(state,create=True)
            channels.save(state/'state.json',{'version':1,'appId':'12345','messages':{},'blocked':{'q_'+'a'*64:True},'peers':[]})
            control=channel_product.runtime_root(hub,{})
            private_directory(control,create=True)
            storage=home/'message-state/qq/preparation/services';private_directory(storage/'adapter',create=True)
            config={'instance_id':'fixture','service_url':'http://127.0.0.1:8765','channels':[]}
            channels.save(control/'configuration.json',{'adapter':config,'state':str(storage),'port':8003})
            channels.save(control/'adapter.json',config)
            channels.save(control/'qq.process.json',{'pid':12345,'created':1.0,'argv':['/foreign/original'],'executable':'/foreign/node'})
            database=storage/'adapter/channels.sqlite3'
            db=sqlite3.connect(database);db.execute('CREATE TABLE items(id TEXT,data TEXT)');db.execute('INSERT INTO items VALUES (?,?)',('unknown','{"status":"unknown"}'));db.commit();db.close();database.chmod(0o600)
            original=(state/'state.json').read_bytes()
            backup(home,root/'backup');result=restore(root/'backup',root/'restored')
            target=root/'restored';record=json.loads((target/'restoration.json').read_text())
            self.assertTrue(record['channels_quarantined']['qq']);self.assertFalse(result['service_started'])
            copied=target/'message-state/qq/preparation/bridge/state.json'
            self.assertEqual(copied.read_bytes(),original);self.assertEqual((state/'state.json').read_bytes(),original)
            self.assertFalse((target/'message-platforms/qq/generations/preparation/channels/qq.process.json').exists())
            self.assertTrue((target/'restoration-forensics/message-platforms/qq/generations/preparation/channels/qq.process.json').exists())
            migrated=json.loads((target/'message-platforms/qq/generations/preparation/channels/configuration.json').read_text())
            self.assertTrue(Path(migrated['state']).is_relative_to(target));self.assertNotEqual(migrated['adapter']['service_url'],'http://127.0.0.1:8765')
            observed=channel_product.command(target,'qq','status',{})
            self.assertEqual(observed['status'],'restore_review_required');self.assertFalse(observed['connected'])
            self.assertEqual(channel_product.command(target,'qq','stop',{'confirmed':True})['signals_sent'],False)
            with self.assertRaisesRegex(ValueError,'RESTORED_DATA_REVIEW_REQUIRED'):
                channel_product.command(target,'qq','start',{'confirmed':True})
            restored_db=sqlite3.connect(target/'message-state/qq/preparation/services/adapter/channels.sqlite3')
            try:self.assertEqual(restored_db.execute('SELECT data FROM items').fetchone()[0],'{"status":"unknown"}')
            finally:restored_db.close()

if __name__=='__main__':unittest.main()
