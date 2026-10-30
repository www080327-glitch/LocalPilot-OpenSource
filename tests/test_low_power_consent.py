import unittest
from unittest.mock import patch
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from agent.omlx import OMLXBackend
from agent.local_http import LocalBackendError
from agent.power_consent import task_consent, allowed


class LowPowerConsentTests(unittest.TestCase):
    def backend(self):
        backend = object.__new__(OMLXBackend)
        backend.model = 'local-weights'
        backend.inspect_service = lambda: {'models': [{'id': backend.model, 'loaded': True, 'deployment_status': 'ready', 'size_bytes': 3_000_000_000}]}
        return backend

    def test_task_opt_in_admits_only_inside_scope(self):
        backend = self.backend()
        with patch('agent.omlx.sys.platform', 'darwin'), patch('agent.omlx.subprocess.run', return_value=SimpleNamespace(stdout='lowpowermode 1')):
            with self.assertRaises(LocalBackendError): backend._admit()
            with task_consent(True): backend._admit()
            with self.assertRaises(LocalBackendError): backend._admit()

    def test_permission_cannot_leak_to_concurrent_task(self):
        with ThreadPoolExecutor(max_workers=1) as worker:
            with task_consent(True):
                self.assertTrue(allowed())
                self.assertFalse(worker.submit(allowed).result())
        self.assertFalse(allowed())

    def test_exception_and_nonboolean_do_not_leave_consent(self):
        with self.assertRaises(RuntimeError):
            with task_consent(True): raise RuntimeError('task failed')
        self.assertFalse(allowed())
        with task_consent('true'): self.assertFalse(allowed())

    def test_http_consent_applies_to_one_task_not_next_turn(self):
        from tests.test_agent_service import AgentServiceTests
        case = AgentServiceTests('test_client_isolation_and_operator_binding')
        case.setUp()
        observed = []
        original = case.backend.request
        def request(*args, **kwargs):
            observed.append(allowed())
            return original(*args, **kwargs)
        case.backend.request = request
        try:
            first = case.codex.request('/localpilot/v1/tasks', {'input': 'hello', 'low_power_consent': True}, key='power-first')
            case.service.wait(first['id'])
            second = case.codex.request('/localpilot/v1/tasks', {'input': 'again', 'session_id': first['session_id']}, key='power-next')
            case.service.wait(second['id'])
            self.assertEqual(observed, [True, False])
            self.assertIs(case.service.tasks[first['id']].service_metadata['low_power_consent'], True)
            self.assertIs(case.service.tasks[second['id']].service_metadata['low_power_consent'], False)
        finally:
            case.tearDown()

if __name__ == '__main__': unittest.main()
