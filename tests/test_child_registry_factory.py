"""Run host-supplied worker tools and restore their real durable receipts."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest

from agent.async_runtime import AsyncPolicy
from agent.permissions import ToolRiskMetadata
from agent.persistence import PersistenceError, configuration, snapshot_runtime
from agent.registry import ToolRegistry, create_default_registry
from agent.safety import CapabilityPolicy
from agent.session import AgentSession, SessionBudgets
from localpilot_api.service import TaskRequest, TaskService
from tests.test_runtime_api import Backend, answer, call


class LocalBackend(Backend):
    is_local = True
    is_loopback = True

    def health_check(self):
        return True


class ChildRegistryFactoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / 'host-identity'
        self.environment = self.root / 'task-environment'
        self.workspace.mkdir()
        self.environment.mkdir()
        (self.workspace / 'host.txt').write_text('Host file must remain untouched.')
        self.contract = {'kind':'task-environment', 'revision':1, 'root':str(self.environment)}
        self.description = 'Append a note inside the assigned task environment.'
        self.effects = []
        self.read_only = False
        self.capabilities = None
        self.parent_guard = self.child_guard = None
        self.async_policy = None
        self.services = []
        self.backend = LocalBackend(*([self.respond] * 16))

    def tearDown(self):
        for service in self.services:
            if not service.closed:
                service.shutdown(timeout=10)
        self.temp.cleanup()

    def respond(self, messages):
        task = next(message.content for message in reversed(messages) if message.role == 'user')
        results = [message for message in messages if message.role == 'tool']
        if task == 'external child':
            return (answer('Recorded the note.') if results else
                    answer(None, call('environment_note', {'text':'child-effect'}, 'write')))
        if not results:
            options = {'task':'external child', 'backend_preference':'local', 'read_only':self.read_only}
            if self.async_policy:
                options['mode'] = 'async'
            return answer(None, call('delegate', options, 'spawn'))
        if self.async_policy and not any(message.tool_call_id == 'join' for message in results):
            return answer(None, call('wait_children', {}, 'join'))
        return answer('Collected the child result.')

    def registry(self, workspace, *, permission_mode, capabilities, data_policy):
        registry = ToolRegistry(workspace, permission_mode=permission_mode,
                                capabilities=capabilities, data_policy=data_policy)
        registry.authorization_guard = self.child_guard

        def note(*, workspace_root, text):
            self.effects.append(text)
            with (self.environment / 'notes.txt').open('a') as output:
                output.write(text + '\n')
            return {'status':'ok', 'output':(self.environment / 'notes.txt').read_text()}

        registry.register('environment_note', note, metadata=ToolRiskMetadata(mutating=True),
            schema={'type':'function', 'function':{'name':'environment_note', 'description':self.description,
                'parameters':{'type':'object', 'properties':{'text':{'type':'string'}},
                              'required':['text'], 'additionalProperties':False}}})
        return registry

    def factory(self, callback):
        registry = create_default_registry(self.workspace, permission_mode='full-permission',
                                           capabilities=self.capabilities)
        registry.authorization_guard = self.parent_guard
        return AgentSession(registry,
            backend=self.backend, policy='local-only', streaming=False, event_callback=callback,
            async_policy=self.async_policy, child_registry_factory=self.registry,
            child_registry_contract=self.contract,
            budgets=SessionBudgets(max_steps=12, max_token_units=2000000,
                                   max_worker_steps=4, max_worker_token_units=500000))

    def service(self):
        service = TaskService({'localpilot':self.factory}, persistence=self.root / 'runtime.db',
                              async_policy=self.async_policy)
        self.services.append(service)
        return service

    def task(self, service):
        return service.wait(service.create_task(TaskRequest('parent task', idempotency_key='once'))['id'])

    def verify_recovery(self):
        service = self.service()
        task = self.task(service)
        self.assertEqual(task['status'], 'completed', task.get('error'))
        parent = service.sessions[task['session_id']].runtime
        child = parent._children['1.1']
        self.assertEqual(set(child.registry._tools), {'environment_note'})
        self.assertEqual(configuration(parent)['child_registry_contract'], self.contract)
        self.assertEqual(configuration(child)['child_registry_contract'], self.contract)
        self.assertEqual(self.effects, ['child-effect'])
        self.assertEqual((self.environment / 'notes.txt').read_text(), 'child-effect\n')
        self.assertEqual([path.name for path in self.workspace.iterdir()], ['host.txt'])
        self.assertIsNone(child.computer)
        if self.async_policy:
            self.assertIs(child._scheduler, service.scheduler)
        saved = snapshot_runtime(parent)['children']
        requests = len(self.backend.requests)
        service.suspend()
        restored = self.service()
        self.assertEqual(self.task(restored)['id'], task['id'])
        self.assertEqual(snapshot_runtime(restored.sessions[task['session_id']].runtime)['children'], saved)
        self.assertEqual(restored.task_snapshot(task['id'])['tools'], task['tools'])
        self.assertEqual(len(self.backend.requests), requests)
        self.assertEqual(self.effects, ['child-effect'])

    def test_synchronous_worker_uses_host_tool_contract_and_never_replays(self):
        self.verify_recovery()

    def test_async_worker_uses_same_scheduler_and_restores_external_receipts(self):
        self.async_policy = AsyncPolicy(max_model_requests=1, max_local_model_requests=1)
        self.verify_recovery()

    def verify_read_only(self):
        service = self.service()
        task = self.task(service)
        child = service.sessions[task['session_id']].runtime._children['1.1']
        self.assertTrue(child.registry.gateway.capabilities.read_only)
        self.assertFalse(child.registry.gateway.capabilities.write)
        denied = child.registry.call('environment_note', {'text':'must-not-run'})
        self.assertEqual(denied['status'], 'denied')
        self.assertEqual(self.effects, [])
        self.assertFalse((self.environment / 'notes.txt').exists())

    def test_read_only_worker_cannot_mutate_even_in_full_permission_mode(self):
        self.read_only = True
        self.verify_read_only()

    def test_parent_read_only_ceiling_applies_to_mutating_child_request(self):
        self.capabilities = CapabilityPolicy(read=True, write=False, execute=False, read_only=True)
        self.verify_read_only()

    def test_revoked_parent_authority_blocks_custom_worker_effect(self):
        checked = []

        @contextmanager
        def authorization(name, arguments):
            checked.append(name)
            raise PermissionError('Workspace authority revoked')
            yield

        self.parent_guard = authorization
        self.task(self.service())
        self.assertEqual(checked, ['environment_note'])
        self.assertEqual(self.effects, [])
        self.assertFalse((self.environment / 'notes.txt').exists())

    def test_parent_and_factory_authorities_both_apply(self):
        checked = []

        @contextmanager
        def parent_authorization(name, arguments):
            checked.append(('parent', name))
            yield

        @contextmanager
        def task_authorization(name, arguments):
            checked.append(('task', name))
            raise PermissionError('Task environment access revoked')
            yield

        self.parent_guard, self.child_guard = parent_authorization, task_authorization
        self.task(self.service())
        self.assertEqual(checked, [('parent', 'environment_note'), ('task', 'environment_note')])
        self.assertEqual(self.effects, [])

    def verify_restore_refused(self, change):
        service = self.service()
        self.assertEqual(self.task(service)['status'], 'completed')
        requests = len(self.backend.requests)
        service.suspend()
        change()
        with self.assertRaises(PersistenceError):
            self.service()
        self.assertEqual(len(self.backend.requests), requests)
        self.assertEqual(self.effects, ['child-effect'])

    def test_changed_task_environment_identity_refuses_restore(self):
        self.verify_restore_refused(lambda: self.contract.update(revision=2))

    def test_changed_worker_schema_refuses_restore_before_any_effect(self):
        self.verify_restore_refused(lambda: setattr(self, 'description', 'A different tool contract.'))


if __name__ == '__main__':
    unittest.main()
