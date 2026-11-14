"""Optional official Harbor API contracts; not a container/model score."""
import asyncio
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest


@unittest.skipUnless(importlib.util.find_spec('harbor'), 'Pinned Harbor evaluation environment required')
class HarborAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_official_base_agent_and_configured_product_backend(self):
        from harbor.agents.base import BaseAgent
        from localpilot_service.backend_contract import ServiceOpenAIBackend
        from scripts.localpilot_harbor import LocalPilotHarborAgent
        with tempfile.TemporaryDirectory() as directory:
            agent = LocalPilotHarborAgent(directory, 'fixture', endpoint='http://127.0.0.1:9/v1')
            self.assertIsInstance(agent, BaseAgent)
            self.assertIsInstance(agent.backend, ServiceOpenAIBackend)
            self.assertEqual(agent.to_agent_info().name, 'localpilot')
            with self.assertRaisesRegex(RuntimeError, 'setup'):
                await agent.run('must not execute', None, None)

    async def test_invalid_provider_and_missing_credentials_fail_before_run(self):
        from scripts.localpilot_harbor import LocalPilotHarborAgent
        with tempfile.TemporaryDirectory() as directory:
            for options in ({'provider_kind':'guess'}, {'provider_kind':'remote-openai'},
                            {'mcp_servers':[object()]}, {'skills_dir':'unqualified'}):
                with self.subTest(options=list(options)), self.assertRaises(ValueError):
                    LocalPilotHarborAgent(directory, 'fixture', endpoint='http://127.0.0.1:9/v1', **options)

    async def test_shell_protocol_runs_on_the_harbor_loop_and_preserves_failure(self):
        from harbor.environments.base import ExecResult
        from scripts.localpilot_harbor import ContainerShell
        loop = asyncio.get_running_loop()
        calls = []

        class ProtocolFixture:
            async def exec(self, **kwargs):
                calls.append((asyncio.get_running_loop(), kwargs))
                return ExecResult(return_code=7, stdout='partial', stderr='failed')

        shell = ContainerShell(ProtocolFixture(), loop, '/task')
        result = await asyncio.to_thread(shell, '/host-identity-only', 'fixture-command', 17)
        self.assertEqual(calls, [(loop, {'command':'fixture-command', 'cwd':'/task', 'timeout_sec':17})])
        self.assertEqual(result['exit_code'], 7)
        self.assertEqual(result['status'], 'nonzero_exit')
        self.assertTrue(result['partial_effects_possible'])
        self.assertFalse(result['replay_allowed'])

    async def test_dispatched_transport_failure_is_not_retried(self):
        from scripts.localpilot_harbor import ContainerShell
        calls = []

        class ProtocolFixture:
            async def exec(self, **kwargs):
                calls.append(kwargs)
                raise TimeoutError('effect is unknown')

        shell = ContainerShell(ProtocolFixture(), asyncio.get_running_loop(), '/task')
        with self.assertRaises(TimeoutError):
            await asyncio.to_thread(shell, '/host-identity-only', 'fixture-command')
        self.assertEqual(len(calls), 1)

    async def test_product_session_drives_http_tool_call_through_environment_protocol(self):
        from harbor.environments.base import ExecResult
        from harbor.models.agent.context import AgentContext
        from scripts.localpilot_harbor import LocalPilotHarborAgent
        from tests.test_local_http_backend import completion, tool_call
        calls = []

        class ProtocolFixture:
            async def exec(self, **kwargs):
                calls.append(kwargs)
                return ExecResult(return_code=0, stdout='/task\n' if kwargs['command'] == 'pwd' else 'CONTAINER-FIXTURE', stderr='')

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                raw = b'{"data":[{"id":"fixture"}]}'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                observed = any(message['role'] == 'tool' for message in request['messages'])
                response = completion('Observed CONTAINER-FIXTURE' if observed else '', calls=[] if observed else [tool_call('shell', {'command':'fixture-command'}, 'container-call')])
                raw = json.dumps(response).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                agent = LocalPilotHarborAgent(directory, 'fixture', endpoint=f'http://127.0.0.1:{server.server_port}/v1')
                # The fixture serves ordinary JSON; real providers use SSE.
                from dataclasses import replace
                agent.backend.capabilities = replace(agent.backend.capabilities, supports_streaming=False)
                environment = ProtocolFixture()
                await agent.setup(environment)
                context = AgentContext()
                try:
                    await agent.run('Inspect the task container', environment, context)
                except RuntimeError:
                    self.fail((Path(directory)/'localpilot-result.json').read_text())
                result = json.loads((Path(directory)/'localpilot-result.json').read_text())
                self.assertEqual(result['text'], 'Observed CONTAINER-FIXTURE')
                self.assertEqual(context.metadata['runtime_status'], 'completed')
                self.assertEqual([row['command'] for row in calls], ['pwd', 'fixture-command'])
                self.assertEqual(calls[1]['cwd'], '/task')
                self.assertIsNone(context.cost_usd)
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            thread.join(2)
