"""A restore rebase accepts only private exclusion paths and retains UNKNOWN."""
from pathlib import Path
import tempfile,unittest
from agent.registry import create_default_registry
from agent.session import AgentSession
from agent.scope_permissions import configure
from agent.permissions import ToolRiskMetadata
from agent.persistence import PersistenceError
from localpilot_api.service import TaskService,TaskRequest,APIError
from localpilot_service.backup import copy_database
from localpilot_service.restore_migration import path_migration
from tests.test_runtime_api import Backend,answer,call

class RestorePathMigrationTests(unittest.TestCase):
    def test_rebase_preserves_unknown_and_rejects_unrelated_permission_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();work=root/'workspace';work.mkdir();old=root/'old';old.mkdir();new=root/'new';new.mkdir()
            def factory(private,mode='request'):
                def create(callback):
                    registry=create_default_registry(work,permission_mode='full-permission')
                    configure(registry,mode,[private/'data',private/'data/logs',private])
                    def effect(workspace_root):
                        (Path(workspace_root)/'effect').write_text('one effect');raise OSError('after effect')
                    registry.register('effect',effect,ToolRiskMetadata(mutating=True),schema={'type':'function','function':{'name':'effect','parameters':{'type':'object','properties':{}}}})
                    return AgentSession(registry,backend=Backend(answer(None,call('effect',{})),answer('done')),policy='cloud-only',event_callback=callback)
                return create
            old_service=TaskService({'localpilot':factory(old)},persistence=old/'runtime.db')
            task=old_service.create_task(TaskRequest('one effect',idempotency_key='old-effect'));done=old_service.wait(task['id']);old_service.suspend()
            self.assertEqual(done['tools'][0]['side_effect_status'],'unknown')
            copy_database(old/'runtime.db',new/'runtime.db')
            spec={'version':1,'private_roots':[{'source':str(old/'data'),'destination':str(new/'data')},{'source':str(old/'data/logs'),'destination':str(new/'data/logs')},{'source':str(old),'destination':str(new)}]}
            with self.assertRaises(PersistenceError):TaskService({'localpilot':factory(new)},persistence=new/'runtime.db')
            restored=TaskService({'localpilot':factory(new)},persistence=new/'runtime.db',configuration_migration=path_migration(spec))
            snap=restored.task_snapshot(task['id']);self.assertEqual(snap['tools'][0]['side_effect_status'],'unknown');self.assertEqual((work/'effect').read_text(),'one effect')
            self.assertEqual(snap['recovery'].get('effect_state',snap['recovery']['class']),'UNKNOWN_BLOCKED')
            restored.suspend()
            # New fingerprints persist after the explicit one-time rebase.
            reopened=TaskService({'localpilot':factory(new)},persistence=new/'runtime.db');reopened.suspend()
            other=root/'other';other.mkdir();copy_database(old/'runtime.db',other/'runtime.db')
            wrong={'version':1,'private_roots':[{'source':str(old/'data'),'destination':str(other/'data')},{'source':str(old/'data/logs'),'destination':str(other/'data/logs')},{'source':str(old),'destination':str(other)}]}
            with self.assertRaises(PersistenceError):TaskService({'localpilot':factory(other,'workspace')},persistence=other/'runtime.db',configuration_migration=path_migration(wrong))
