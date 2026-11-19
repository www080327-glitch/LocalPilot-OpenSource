"""Runtime audit regressions using real sessions, reviewed bundles and files."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from agent.registry import create_default_registry
from agent.hybrid import CloudEgressPolicy, HybridPolicy
from agent.persistence import snapshot_runtime, restore_runtime
from agent.retry import RetryPolicy
from agent.safe_files import copy_file, inspect_file, move_file
from agent.session import AgentSession, SessionBudgets
from agent.tool_protocol import ToolArgumentsError
from localpilot_api.service import APIError
from localpilot_plugins.skills import SkillRegistry
from localpilot_service import VERSION
from localpilot_service.desktop_sessions import apply_options
from tests.test_runtime_session import ScriptBackend, call, response


class RuntimeAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.work = self.root / 'work'
        self.work.mkdir()
        self.runtimes = []

    def tearDown(self):
        for runtime in self.runtimes:
            runtime.close()
        self.temp.cleanup()

    def runtime(self, backend=None, *, profile='standard', **kwargs):
        registry = create_default_registry(self.work, profile=profile, permission_mode='full-permission')
        runtime = AgentSession(registry, backend=backend or ScriptBackend(response('done')),
                               policy='cloud-only', **kwargs)
        self.runtimes.append(runtime)
        return runtime

    def test_skill_compatibility_uses_installed_core_version(self):
        bundle = self.root / 'bundle'
        bundle.mkdir()
        manifest = {'id': 'current-core', 'version': '1.0.0', 'description': 'Current Core guide',
                    'requires_localpilot': '==' + VERSION, 'dependencies': {}, 'tools': [],
                    'inputs': {'type': 'object'}, 'outputs': {'type': 'object'}}
        (bundle / 'skill.json').write_text(json.dumps(manifest))
        (bundle / 'SKILL.md').write_text('Read the current Core documentation.')
        skills = SkillRegistry(self.root / 'skills')
        installed = skills.install(bundle)
        skills.enable('current-core', 'user', reviewed_sha256=installed['bundle_sha256'])
        self.assertEqual(skills.load('current-core', 'user')['status'], 'ok')
        with self.assertRaisesRegex(ValueError, 'incompatible'):
            skills.load('current-core', 'user', version='1.0.0')

    def test_cancel_interrupts_model_retry_delay_without_another_request(self):
        backend = ScriptBackend(ConnectionError('temporary outage'), response('must not run'))
        runtime = self.runtime(backend, retry_policy=RetryPolicy(base_delay=1, max_delay=1, jitter=0))

        def cancel_retry(event):
            if event.type == 'ModelRetry':
                runtime.request_cancel()

        runtime.events.callback = cancel_retry
        started = time.monotonic()
        result = runtime.run_turn('Answer one question.')
        self.assertEqual(result.status, 'cancelled')
        self.assertLess(time.monotonic() - started, .5)
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(runtime._attempts, 1)

    def test_child_keeps_parent_minimal_tool_profile(self):
        backend = ScriptBackend(response(None, call('delegate', {
            'backend_preference': 'cloud', 'task': 'Summarize the empty directory.', 'read_only': True})),
            response('No entries.'), response('No entries.'))
        runtime = self.runtime(backend, profile='minimal',
            hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED')),
            hybrid_backends={'cloud': backend}, hybrid_primary='cloud', budgets=SessionBudgets(
            max_steps=10, max_token_units=1000000, max_worker_token_units=300000))
        self.assertEqual(runtime.run_turn('Delegate the directory summary.').status, 'completed')
        child = runtime._children['1.1']
        self.assertEqual(child.registry.profile, runtime.registry.profile)
        self.assertEqual(child.registry.tool_profile, runtime.registry.tool_profile)
        saved = snapshot_runtime(runtime)
        restored = self.runtime(ScriptBackend(), profile='minimal',
            hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED')),
            hybrid_backends={'cloud': backend}, hybrid_primary='cloud', budgets=runtime.budgets)
        restore_runtime(restored, saved)
        self.assertEqual(snapshot_runtime(restored)['children'], saved['children'])

    def test_invalid_desktop_options_leave_runtime_untouched(self):
        runtime = self.runtime()
        original = (runtime.permission_mode, runtime.prompt_profile, runtime.messages[:],
                    dict(runtime.registry._tools))
        with self.assertRaises(APIError):
            apply_options(runtime, {'permission_mode': 'isolated', 'agent_profile': 'minimal',
                                    'scope_revision': 3, 'context_length': 1})
        self.assertEqual((runtime.permission_mode, runtime.prompt_profile, runtime.messages,
                          runtime.registry._tools), original)

    def test_legacy_standard_child_restores_under_a_minimal_parent(self):
        from unittest.mock import patch
        from agent.child_sessions import create_child
        backend = ScriptBackend(response(None, call('delegate', {
            'backend_preference': 'cloud', 'task': 'Summarize.', 'read_only': True})),
            response('Summary.'), response('Collected.'))
        options = dict(profile='minimal', hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED')),
            hybrid_backends={'cloud': backend}, hybrid_primary='cloud',
            budgets=SessionBudgets(max_steps=10, max_token_units=1000000, max_worker_token_units=300000))
        runtime = self.runtime(backend, **options)
        with patch('agent.child_sessions.create_child',
                   side_effect=lambda *args, **kw: create_child(*args, **kw, inherit_profile=False)):
            self.assertEqual(runtime.run_turn('Delegate the summary.').status, 'completed')
        saved = snapshot_runtime(runtime)
        self.assertEqual(saved['children']['1.1']['child_tool_contract']['revision'], 1)
        restored = self.runtime(backend, **options)
        restore_runtime(restored, saved)
        self.assertEqual(restored._children['1.1'].registry.profile, 'standard')
        self.assertEqual(snapshot_runtime(restored)['children'], saved['children'])

    def test_full_session_can_switch_to_each_supported_permission_mode(self):
        runtime = self.runtime()
        for mode in ('full', 'ask', 'safe', 'uncertain', 'workspace', 'isolated', 'request'):
            with self.subTest(mode=mode):
                apply_options(runtime, {'permission_mode': mode, 'agent_profile': 'standard',
                                        'scope_revision': 3})
                self.assertEqual(runtime.registry.scope_policy['mode'], mode)
                if mode == 'ask':
                    (self.work / 'note.txt').write_text('visible')
                    self.assertEqual(runtime.registry.call('read_file', {'path': 'note.txt'})['status'],
                                     'approval_required')

    def test_hardlinked_source_can_be_copied_and_moved_without_changing_alias(self):
        source = self.work / 'source.txt'
        source.write_text('Shared source bytes')
        os.link(source, self.work / 'alias.txt')
        digest = inspect_file(self.work, 'source.txt')['sha256']
        copied = copy_file(self.work, 'source.txt', 'copy.txt', digest)
        self.assertEqual(copied['status'], 'ok')
        moved = move_file(self.work, 'source.txt', 'moved.txt', digest)
        self.assertEqual(moved['status'], 'ok')
        self.assertFalse(source.exists())
        self.assertEqual((self.work / 'alias.txt').read_text(), 'Shared source bytes')
        self.assertEqual((self.work / 'moved.txt').stat().st_ino, (self.work / 'alias.txt').stat().st_ino)
        self.assertNotEqual((self.work / 'copy.txt').stat().st_ino, (self.work / 'alias.txt').stat().st_ino)

    def test_file_info_reads_metadata_of_a_large_file_without_hashing_contents(self):
        size = 65 * 1024 * 1024
        with (self.work / 'archive.bin').open('wb') as stream:
            stream.truncate(size)
        registry = self.runtime().registry
        self.assertEqual(registry.call('file_info', {'path': 'archive.bin'}),
                         {'path': 'archive.bin', 'type': 'file', 'size_bytes': size})
        with self.assertRaisesRegex(ValueError, '64 MiB'):
            inspect_file(self.work, 'archive.bin')

    def test_extended_budget_is_explicit_and_can_return_to_route_defaults(self):
        runtime = self.runtime()
        standard = runtime.budgets
        options = {'permission_mode': 'full', 'agent_profile': 'standard', 'scope_revision': 3}
        apply_options(runtime, options)
        self.assertEqual(runtime.budgets, standard)

        apply_options(runtime, {**options, 'execution_budget': 'extended'})
        self.assertEqual(runtime.budgets.max_steps, 2048)
        self.assertEqual(runtime.budgets.max_tool_calls, 4096)
        self.assertEqual(runtime.budgets.max_token_units, 64 * 1024 * 1024)
        apply_options(runtime, {**options, 'execution_budget': 'standard'})
        self.assertEqual(runtime.budgets, standard)

    def test_shell_model_arguments_cannot_override_host_isolation(self):
        runtime = self.runtime()
        apply_options(runtime, {'permission_mode': 'isolated', 'agent_profile': 'standard', 'scope_revision': 3})
        for overrides in ({'mode': 'full'}, {'max_timeout': 86400}, {'private_roots': []}):
            with self.subTest(overrides=overrides), self.assertRaises(ToolArgumentsError):
                runtime.registry.call('shell', {'command': 'printf escaped > forbidden.txt', **overrides})
        self.assertFalse((self.work / 'forbidden.txt').exists())

    def test_extended_shell_timeout_is_host_bound_and_inherited(self):
        runtime = self.runtime()
        options = {'permission_mode': 'full', 'agent_profile': 'standard', 'scope_revision': 3}
        apply_options(runtime, options)
        with self.assertRaises(ToolArgumentsError):
            runtime.registry.call('shell', {'command': 'true', 'timeout': 7200})
        apply_options(runtime, {**options, 'execution_budget': 'extended'})
        self.assertEqual(runtime.registry.call('shell', {'command': 'true', 'timeout': 7200})['status'], 'ok')
        from agent.child_sessions import create_child
        child = create_child(runtime, {'id': 'audit-child', 'backend': 'cloud', 'read_only': False},
                             SessionBudgets(), None, inherit_tools=True)
        self.runtimes.append(child)
        self.assertEqual(child.registry._tools['shell'].keywords['max_timeout'], 86400)
        with self.assertRaises(ToolArgumentsError):
            runtime.registry.call('shell', {'command': 'true', 'timeout': 86401})
        apply_options(runtime, {**options, 'execution_budget': 'standard'})
        self.assertEqual(runtime.registry._tools['shell'].keywords['max_timeout'], 3600)


if __name__ == '__main__':
    unittest.main()
