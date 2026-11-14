"""Restore checkpoints created by an actual pre-catalog checkout, without replay."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from agent.persistence import PersistenceError
from agent.permissions import ToolRiskMetadata
from agent.registry import create_default_registry
from agent.session import AgentSession
from localpilot_api.service import TaskRequest, TaskService
from localpilot_plugins.adapter import configure_session
from localpilot_plugins.security import digest
from localpilot_plugins.skills import SkillRegistry
from localpilot_service.backup import copy_database
from tests.test_runtime_api import Backend, answer, call


def route(root, backend, mode='full-permission'):
    def create(callback):
        registry = create_default_registry(root/'workspace', permission_mode=mode)
        def effect(workspace_root):
            with (Path(workspace_root)/'effects').open('a') as stream:
                stream.write('one\n')
            raise OSError('fixture interrupted after effect')
        registry.register('interrupted_effect', effect, ToolRiskMetadata(mutating=True),
            schema={'type':'function','function':{'name':'interrupted_effect',
                'parameters':{'type':'object','properties':{},'additionalProperties':False}}})
        runtime = AgentSession(registry, backend=backend, policy='cloud-only',
            permission_mode=mode, event_callback=callback)
        configure_session(runtime, root/'plugins', skill_home=root/'skills',
            skills=[{'id':'public-notes','scope':'user'}])
        return runtime
    return create


def legacy_fixture(root):
    (root/'workspace').mkdir()
    skills = SkillRegistry(root/'skills', root/'workspace')
    bundle = skills.install(Path(__file__).resolve().parents[1]/'examples/skills/public-notes')
    skills.enable('public-notes','user',reviewed_sha256=bundle['bundle_sha256'])
    backend = Backend(answer(None,call('load_skill',{'skill':'public-notes:user'})), answer('Loaded reviewed notes'),
        answer(None,call('interrupted_effect',{},id='effect')), answer('Stopped'))
    service = TaskService({'localpilot':route(root,backend)},persistence=root/'legacy.sqlite3')
    request = TaskRequest('Load notes',idempotency_key='legacy-loaded')
    task = service.create_task(request); result = service.wait(task['id'])
    if result['status']=='requires_approval':
        service.act(task['id'],'approve',result['required_action']['id'])
        result = service.wait(task['id'])
    sid = result['session_id']
    unknown = service.create_task(TaskRequest('Interrupted effect',session_id=sid,idempotency_key='legacy-unknown'))
    unknown = service.wait(unknown['id'])
    payload = service.store.load()[0]
    (root/'before.json').write_text(json.dumps({'loaded':result,'unknown':unknown,'payload':payload,'configuration':__import__('agent.persistence',fromlist=['configuration']).configuration(service.sessions[sid].runtime)}))
    service.suspend()


@unittest.skipUnless(os.environ.get('LOCALPILOT_LEGACY_SOURCE'),'needs an actual pinned pre-catalog checkout')
class SkillCatalogMigrationTests(unittest.TestCase):
    def test_actual_legacy_restore_preserves_messages_receipts_models_unknown_and_idempotency(self):
        from localpilot_service.restore_migration import skill_catalog_migration
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve(); source=os.environ['LOCALPILOT_LEGACY_SOURCE']
            revision=subprocess.check_output(['git','-C',source,'rev-parse','HEAD'],text=True).strip()
            self.assertEqual(revision,'94e0e6ff2c8da974d20530d7a0faa50844d052f4')
            entry="import sys,runpy;sys.path.insert(0,sys.argv[1]);runpy.run_path(sys.argv[2],run_name='legacy_fixture')['legacy_fixture'](__import__('pathlib').Path(sys.argv[3]))"
            subprocess.run([sys.executable,'-c',entry,source,str(Path(__file__).resolve()),str(root)],check=True,cwd=source)
            before=json.loads((root/'before.json').read_text());payload=before['payload'];sid=payload['session']['id']
            original=hashlib.sha256((root/'legacy.sqlite3').read_bytes()).hexdigest()
            bundle=SkillRegistry(root/'skills',root/'workspace').load('public-notes','user',create_default_registry(root/'workspace')._tools)
            spec={'version':1,'sessions':[{'session_id':sid,'configuration_sha256':payload['configuration'],
                'bundle_sha256':{'public-notes:user':digest(bundle)}}]}
            db=root/'restored.sqlite3';copy_database(root/'legacy.sqlite3',db)
            backend=Backend()
            with self.assertRaises(PersistenceError):
                TaskService({'localpilot':route(root,backend)},persistence=db)
            service=TaskService({'localpilot':route(root,backend)},persistence=db,
                configuration_migration=skill_catalog_migration(spec))
            runtime=service.sessions[sid].runtime
            self.assertEqual([m.to_dict(include_reasoning=True) for m in runtime.messages],payload['runtime']['messages'])
            self.assertEqual(runtime.tool_history,payload['runtime']['history'])
            self.assertTrue(any(r['side_effect_status']=='unknown' for r in runtime.tool_history))
            self.assertEqual(service.task_snapshot(before['loaded']['id'])['model'],before['loaded']['model'])
            repeated=service.create_task(TaskRequest('Load notes',idempotency_key='legacy-loaded'))
            self.assertEqual(repeated['id'],before['loaded']['id'])
            self.assertEqual(backend.requests,[])
            self.assertEqual((root/'workspace/effects').read_text(),'one\n')
            service.suspend()
            reopened=TaskService({'localpilot':route(root,backend)},persistence=db)
            reopened.suspend()
            with sqlite3.connect(root/'legacy.sqlite3') as old, sqlite3.connect(db) as new:
                history=old.execute('select * from journal order by revision').fetchall()
                self.assertEqual(new.execute('select * from journal order by revision').fetchall()[:len(history)],history)
            self.assertEqual(hashlib.sha256((root/'legacy.sqlite3').read_bytes()).hexdigest(),original)
            for kind in ('wrong_session','wrong_old_digest','wrong_bundle','permission'):
                with self.subTest(kind=kind):
                    failed=root/(kind+'.sqlite3');copy_database(root/'legacy.sqlite3',failed)
                    plan=deepcopy(spec)
                    if kind=='wrong_session':plan['sessions'][0]['session_id']='other'
                    if kind=='wrong_old_digest':plan['sessions'][0]['configuration_sha256']='0'*64
                    if kind=='wrong_bundle':plan['sessions'][0]['bundle_sha256']['public-notes:user']='0'*64
                    with self.assertRaises(PersistenceError):
                        TaskService({'localpilot':route(root,Backend(),'read-only' if kind=='permission' else 'full-permission')},
                            persistence=failed,configuration_migration=skill_catalog_migration(plan))
            changed=root/'changed-bundle';changed.mkdir()
            source_bundle=Path(__file__).resolve().parents[1]/'examples/skills/public-notes'
            (changed/'skill.json').write_bytes((source_bundle/'skill.json').read_bytes())
            (changed/'SKILL.md').write_text('Changed instructions after the old task loaded its Skill.')
            skills=SkillRegistry(root/'skills',root/'workspace')
            changed_bundle=skills.install(changed,replace=True)
            skills.enable('public-notes','user',reviewed_sha256=changed_bundle['bundle_sha256'])
            current_bundle=skills.load('public-notes','user',create_default_registry(root/'workspace')._tools)
            changed_spec=deepcopy(spec)
            changed_spec['sessions'][0]['bundle_sha256']['public-notes:user']=digest(current_bundle)
            changed_db=root/'changed-loaded-skill.sqlite3';copy_database(root/'legacy.sqlite3',changed_db)
            with self.assertRaises(PersistenceError):
                TaskService({'localpilot':route(root,Backend())},persistence=changed_db,
                    configuration_migration=skill_catalog_migration(changed_spec))


if __name__=='__main__':
    unittest.main()
