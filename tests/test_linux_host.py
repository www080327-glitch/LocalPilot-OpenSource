"""Actual Linux subprocess, namespace, file and transport boundaries; no model claims."""
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import hardware
from agent.acceptance import HostPythonAcceptance
from agent.host_tools import shell, shell_capabilities
from localpilot_service import cli
from localpilot_service.lifecycle import unregister


class LinuxRequestContextTests(unittest.TestCase):
    def test_arbitrary_shell_does_not_claim_native_host_permissions(self):
        from agent.engine_v5 import EngineV5Policy
        from agent.host_tools import qualified_shell
        from agent.permissions import ToolRiskMetadata
        from agent.registry import create_default_registry
        from agent.scope_permissions import configure
        from agent.session import AgentSession
        from tests.test_runtime_api import Backend, answer
        for policy in ('absent', 'none', 'configured'):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as temporary:
                registry = create_default_registry(temporary)
                if policy == 'none':
                    registry.scope_policy = None
                elif policy == 'configured':
                    configure(registry, 'workspace', revision=3)
                registry.register('shell', lambda workspace_root: 'container tool',
                    ToolRiskMetadata(read_only=True, mutating=False),
                    schema={'type':'function','function':{'name':'shell','parameters':{
                        'type':'object','properties':{},'additionalProperties':False}}})
                self.assertFalse(qualified_shell(registry, 'shell'))
                backend = Backend(answer('Done'))
                runtime = AgentSession(registry, backend=backend, policy='cloud-only',
                    engine_policy=EngineV5Policy())
                try:
                    result = runtime.run_turn('Inspect the environment')
                    self.assertEqual(result.status, 'completed')
                    request = backend.requests[0]
                    self.assertTrue(any(tool['function']['name'] == 'shell' for tool in request['tools']))
                    state = json.loads(request['messages'][-1].content.split('\n',1)[1])
                    self.assertNotIn('host_shell', state)
                finally:
                    runtime.close()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux native host context')
    def test_legacy_cache_keeps_approved_snapshot_prefix_and_frozen_contract(self):
        from agent.persistence import configuration, snapshot_runtime, restore_runtime
        from agent.registry import create_default_registry
        from agent.session import AgentSession
        from localpilot_service.desktop_sessions import apply_options
        from tests.test_runtime_api import Backend, answer
        with tempfile.TemporaryDirectory() as temporary:
            backend = Backend(answer('First'), answer('After restart'))
            backend.service_cache_stable_prefix = True
            options = {'permission_mode':'full','agent_profile':'standard',
                       'scope_revision':3,'prompt_revision':2}
            runtime = AgentSession(create_default_registry(temporary), backend=backend, policy='cloud-only')
            restored = AgentSession(create_default_registry(temporary), backend=backend, policy='cloud-only')
            try:
                apply_options(runtime, options)
                apply_options(restored, options)
                frozen = configuration(runtime)
                system = next(m.content for m in runtime.messages if m.role == 'system')
                self.assertEqual(runtime.run_turn('First legacy request').status, 'completed')
                saved = snapshot_runtime(runtime)
                restore_runtime(restored, saved)
                restored._refresh_prompt()
                self.assertEqual(restored.run_turn('Continue legacy request').status, 'completed')
                first, second = ([m.to_dict() for m in request['messages']] for request in backend.requests)
                self.assertEqual(first, second[:len(first)])
                self.assertIn('"host_shell"', first[-1]['content'])
                self.assertIn(first[-1], saved['messages'])
                self.assertEqual(configuration(restored), frozen)
                self.assertEqual(next(m.content for m in restored.messages if m.role == 'system'), system)
            finally:
                runtime.close()
                restored.close()


@unittest.skipUnless(sys.platform == 'linux' and shutil.which('bwrap'), 'Linux bubblewrap required')
class LinuxShellTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root / 'work'
        self.work.mkdir()

    def test_workspace_symlink_cannot_write_outside_allowed_mount(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as outside:
            (self.work / 'outside').symlink_to(outside, target_is_directory=True)
            result = shell(self.work, 'printf denied > outside/symlink-target', mode='workspace')
            self.assertNotEqual(result['exit_code'], 0, result)
            self.assertFalse(Path(outside, 'symlink-target').exists())

    def test_workspace_allows_existing_os_temp_scope(self):
        target = self.root / 'temporary-output'
        result = shell(self.work, 'printf allowed > ' + shlex.quote(str(target)), mode='workspace')
        self.assertEqual(result['exit_code'], 0, result)
        self.assertEqual(target.read_text(), 'allowed')

    def test_isolated_can_read_without_modifying_real_files(self):
        target = self.work / 'original'
        target.write_text('readable')
        read = shell(self.work, 'cat original', mode='isolated')
        self.assertEqual(read['stdout'], 'readable', read)
        for command in ('printf changed > original', 'rm original', 'touch new-file'):
            with self.subTest(command=command):
                result = shell(self.work, command, mode='isolated')
                self.assertNotEqual(result['exit_code'], 0, result)
                self.assertEqual(target.read_text(), 'readable')
                self.assertFalse((self.work / 'new-file').exists())

    def test_scoped_shell_retains_the_declared_loopback_network(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            server.settimeout(3)
            port = server.getsockname()[1]
            payload = "import socket; s=socket.create_connection(('127.0.0.1'," + str(port) + "),timeout=2); s.sendall(b'linux-scoped'); s.close()"
            result = shell(self.work, shlex.join([sys.executable, '-I', '-c', payload]), mode='isolated')
            self.assertEqual(result['exit_code'], 0, result)
            connection, _ = server.accept()
            with connection:
                self.assertEqual(connection.recv(32), b'linux-scoped')
        self.assertEqual(result['network'], 'available')

    def test_scoped_cancellation_reaps_real_descendants(self):
        import psutil
        cancel = threading.Event()
        result = []
        worker = threading.Thread(target=lambda: result.append(shell(self.work,
            'sleep 60 & printf started > started; wait', mode='workspace', cancel_event=cancel)))
        worker.start()
        try:
            deadline = time.monotonic() + 4
            while not (self.work / 'started').exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue((self.work / 'started').exists())
            children = psutil.Process().children(recursive=True)
            self.assertTrue(any(child.name() == 'sleep' for child in children))
            cancel.set()
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result[0]['status'], 'cancelled')
            self.assertTrue(result[0]['action_may_have_applied'])
            self.assertFalse(result[0]['replay_allowed'])
            _, live = psutil.wait_procs(children, timeout=2)
            self.assertEqual([child.pid for child in live if child.status() != psutil.STATUS_ZOMBIE], [])
        finally:
            cancel.set()
            worker.join(3)

    def test_missing_bubblewrap_never_falls_back_to_unrestricted_shell(self):
        with patch.dict(os.environ, {'PATH': ''}):
            with self.assertRaisesRegex(ValueError, 'bubblewrap'):
                shell(self.work, 'touch never', mode='workspace')
            self.assertFalse((self.work / 'never').exists())
            result = shell(self.work, 'printf explicitly-full > full-file', mode='full')
            self.assertEqual(result['exit_code'], 0, result)
            self.assertEqual((self.work / 'full-file').read_text(), 'explicitly-full')
        capabilities = shell_capabilities()
        self.assertEqual(capabilities['scoped_backend'], 'bubblewrap')
        self.assertEqual(capabilities['scoped_execution'], 'NOT_PROBED')


@unittest.skipUnless(sys.platform == 'linux' and shutil.which('bwrap') and shutil.which('unshare'), 'Linux namespace tools required')
class LinuxAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root / 'work'
        self.work.mkdir()
        self.output = self.work / 'result.txt'
        self.output.write_text('verified-fixture')
        self.assertions = self.root / 'assertions.py'

    def verify(self, source):
        self.assertions.write_text(source)
        return HostPythonAcceptance(self.work, self.assertions, ['result.txt'])(self.work, None)

    def test_assertions_cannot_read_unmounted_host_siblings_or_write_outputs(self):
        private = self.root / 'host-only-secret'
        private.write_text('not-visible-to-code')
        source = (
            'from pathlib import Path\n'
            f'assert not Path({str(private)!r}).exists()\n'
            f'output=Path({str(self.output)!r})\n'
            'assert output.read_text()=="verified-fixture"\n'
            'try: output.write_text("rewritten")\n'
            'except OSError: pass\n'
            'else: raise AssertionError("workspace was writable")\n')
        self.assertEqual(self.verify(source).status, 'passed')
        self.assertEqual(self.output.read_text(), 'verified-fixture')

    def test_assertions_cannot_connect_to_host_loopback_service(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            server.settimeout(.1)
            source = (
                'import socket\n'
                f'try: socket.create_connection(("127.0.0.1",{server.getsockname()[1]}),timeout=.2)\n'
                'except OSError: pass\n'
                'else: raise AssertionError("host network reached")\n')
            self.assertEqual(self.verify(source).status, 'passed')
            with self.assertRaises(TimeoutError):
                server.accept()


class LinuxPowerInputTests(unittest.TestCase):
    def test_observed_sysfs_power_and_unknown_device_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertIsNone(hardware._linux_external_power(root))
            supply = root / 'AC'
            supply.mkdir()
            (supply / 'type').write_text('Mains\n')
            (supply / 'online').write_text('1\n')
            self.assertIs(hardware._linux_external_power(root), True)
            (supply / 'online').write_text('0\n')
            self.assertIs(hardware._linux_external_power(root), False)
            (supply / 'online').write_text('unknown\n')
            self.assertIsNone(hardware._linux_external_power(root))
            (supply / 'online').write_text('1\n')
            (supply / 'scope').write_text('Device\n')
            self.assertIsNone(hardware._linux_external_power(root))

    def test_any_observed_system_supply_takes_precedence_over_offline_port(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, kind, online in [('USB', 'USB_C', '0'), ('AC', 'Mains', '1')]:
                supply = root / name
                supply.mkdir()
                (supply / 'type').write_text(kind)
                (supply / 'online').write_text(online)
            self.assertIs(hardware._linux_external_power(root), True)

    @unittest.skipUnless(sys.platform == 'linux', 'real Linux hardware discovery required')
    def test_actual_hardware_reports_memory_and_cpu_without_gpu_claim(self):
        result = hardware.get_hardware()
        self.assertGreater(result['memory'], 0)
        self.assertNotEqual(result['chip'], 'Unknown')
        self.assertEqual(result['mps_availability'], 'NOT_PROBED')


@unittest.skipUnless(sys.platform == 'linux', 'Linux service management required')
class LinuxLifecycleTests(unittest.TestCase):
    def test_unregister_detached_service_has_no_launchd_dependency(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / 'service'
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = cli.main(['--home', str(home), '--json', 'service-unregister'])
            self.assertEqual(status, 0, output.getvalue())
            result = json.loads(output.getvalue())
            self.assertEqual(result, unregister(home))
            self.assertEqual(result['manager'], 'detached')
            self.assertFalse(result['login_autostart'])


if __name__ == '__main__':
    unittest.main()
