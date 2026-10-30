"""Restore keeps citation data and historical grant IDs without granting access."""
from contextlib import closing
from pathlib import Path
import json,tempfile,unittest
import test_installation_first_run as installation_fixture
from localpilot_suite.product_backup import backup,restore
from localpilot_service.documents import DocumentEngine
from localpilot_service.workspaces import WorkspaceGrants

class RestoreDocumentGrantTests(unittest.TestCase):
    def test_document_blobs_citations_and_revoked_grants_survive(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();(root/'workspace').mkdir();home=installation_fixture.RecoveryTests().fixture(root)
            grants=WorkspaceGrants(home/'data/workspace-grants.json')
            grant=grants.create('http',str(root/'workspace'),'read',[])
            engine=DocumentEngine(home/'data/documents-v2');source=root/'public.txt';source.write_text('Public citation marker')
            file=engine.ingest('http','session',[str(source)])['files'][0];engine.process('http','session',file['id']);node=next(n for n in engine.read('http','session',file['id'])['nodes'] if 'Public citation marker' in n['text']);self.assertTrue(engine.verify('http','session',node['citation'],'Public citation marker')['verified']);engine.close()
            backup(home,root/'backup');restore(root/'backup',root/'restored')
            restored=root/'restored';current=WorkspaceGrants(restored/'core-data/workspace-grants.json');self.assertTrue(current.get(grant['id'])['revoked'])
            with self.assertRaises(PermissionError):current.validate(grant['id'])
            docs=DocumentEngine(restored/'core-data/documents-v2')
            try:self.assertTrue(docs.verify('http','session',node['citation'],'Public citation marker')['verified'])
            finally:docs.close()
            self.assertFalse(grants.get(grant['id'])['revoked'])
            config=json.loads((restored/'service.json').read_text());self.assertEqual(config['restore_path_migration']['version'],1)

    def test_documents_without_folder_grants_keep_every_parent_private(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();home=installation_fixture.RecoveryTests().fixture(root)
            engine=DocumentEngine(home/'data/documents-v2');source=root/'public.txt';source.write_text('No grants required')
            engine.ingest('http','session',[str(source)]);engine.close()
            backup(home,root/'backup');restore(root/'backup',root/'restored')
            for name in ['core-data','core-data/documents-v2','core-data/documents-v2/blobs']:
                self.assertEqual((root/'restored'/name).stat().st_mode&0o777,0o700)
            restored=DocumentEngine(root/'restored/core-data/documents-v2');restored.close()
