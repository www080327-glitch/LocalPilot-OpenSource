"""Exercise the role qualification runner against real TLS/Core/SQLite paths."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.error import HTTPError

from localpilot_service import cli
from scripts import qualify_openai_worker_roles as qualification
from scripts.qualify_openai_agent import CloudCore
from tests.test_openai_cloud_backend import OpenAICloudFixture
from tests.test_openai_responses import response_payload


class WorkerRoleQualificationPreflightTests(unittest.TestCase):
    def test_preflight_requires_fresh_output_and_does_not_claim_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'preflight'
            command = [sys.executable, str(Path(qualification.__file__).resolve()),
                '--output', str(output), '--preflight-only']
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((output / 'RESULTS.json').read_text())
            protocol = json.loads((output / 'PROTOCOL.json').read_text())
            self.assertEqual(report['inference_status'], 'NOT_RUN')
            self.assertEqual(report['preflight']['cloud_calls'], 0)
            self.assertTrue(report['preflight']['missing_evidence_rejected'])
            self.assertFalse((output / 'core-private').exists())
            self.assertEqual(protocol['models'], qualification.MODELS)
            self.assertEqual(protocol['max_children'], 2)
            self.assertEqual(protocol['session_boundary'], qualification.BOUNDARY)
            self.assertEqual(protocol['capabilities'], qualification.CAPABILITIES)
            self.assertIsNone(protocol['desktop_options'])
            again = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(again.returncode, 2)
            self.assertIn('prior attempts are preserved', again.stderr)


class WorkerRoleQualificationTLS(OpenAICloudFixture):
    def test_actual_runner_checks_roles_receipts_usage_and_restart(self):
        self.run_scope_case()

    def test_outside_reads_fail_for_parent_and_children_without_body_egress(self):
        self.run_scope_case(outside_probe=True)

    def run_scope_case(self, outside_probe=False):
        self.model.models = ['gpt-6.1-sol', 'gpt-6-luna']
        final_requests = []
        outside_marker = 'LP-OUTSIDE-BODY-MUST-STAY-LOCAL-972113'

        def provider(body):
            reply = response_payload()
            reply.update(model=body['model'], id='resp_role_' + str(len(self.model.requests)))
            tools = {tool['name'] for tool in body.get('tools', [])}
            calls = [item for item in body['input'] if item.get('type') == 'function_call']
            previous = [item['name'] for item in calls]
            read_paths = [json.loads(item['arguments']).get('path') for item in calls if item['name'] == 'read_file']
            if outside_probe and '../outside-sentinel.txt' not in read_paths:
                actions = [('read_file', {'path': path}, 'outside-' + str(index))
                    for index, path in enumerate((str(outside), '../outside-sentinel.txt'))]
            elif 'delegate' in tools and 'delegate' not in previous:
                actions = [('delegate', {'task': 'Read both role fixture files.', 'backend_preference': 'cloud',
                    'role': role, 'mode': 'async', 'read_only': True, 'budget': {'steps': 8, 'tools': 8}},
                    'delegate-' + role) for role in ('search', 'review')]
            elif 'delegate' in tools and 'wait_children' not in previous:
                actions = [('wait_children', {}, 'collect')]
            elif 'delegate' not in tools and not set(read_paths) & set(qualification.FIXTURES):
                actions = [('read_file', {'path': path}, 'read-' + str(index))
                    for index, path in enumerate(qualification.FIXTURES)]
            else:
                final_requests.append(body)
                text = ('search and review completed read_file on role-marker.txt and role-fixture.py.'
                    if 'delegate' in tools else qualification.MARKER + ' clamp uses defaults 0 and 10.')
                reply = response_payload(text=text)
                reply.update(model=body['model'], id='resp_role_' + str(len(self.model.requests)))
                return reply
            reply['output'] = [{'type': 'function_call', 'call_id': identifier,
                'name': name, 'arguments': json.dumps(arguments)} for name, arguments, identifier in actions]
            return reply

        for _ in range(20):
            self.model.add(provider)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            key = root / 'synthetic.key'
            key.write_text('fixture-not-a-real-key')
            key.chmod(0o600)
            output = root / 'run'
            output.mkdir(mode=0o700)
            outside = output / 'outside-sentinel.txt'
            outside.write_text(outside_marker)
            core = CloudCore(output, key, 'gpt-6.1-sol', 'medium')
            qualification.configure_roles(core)
            config = json.loads((core.home / 'service.json').read_text())
            for route in config['routes'].values():
                route['backend'].update(base_url=self.model.base_url,
                    capabilities={'streaming': False, 'tool_calling': True})
            cli.save(core.home / 'service.json', config)
            try:
                try:
                    result = qualification.run_case(core)
                except HTTPError as error:
                    self.fail(error.read().decode())
                except RuntimeError as error:
                    self.fail(str(error) + '\n' + (output / 'core.log').read_text()[-4000:])
                task = json.loads((output / 'worker-roles-task.json').read_text())
                evidence = json.loads((output / 'ROLE_EVIDENCE_BEFORE_RESTART.json').read_text())
                wire = json.dumps(self.model.requests)
                self.assertNotIn(outside_marker, wire)
                self.assertNotIn(outside_marker, json.dumps(task))
                self.assertNotIn(str(key), wire)
                self.assertNotIn(str(core.home), wire)
                self.assertNotIn(str(qualification.ROOT), wire)
                self.assertTrue(all(not qualification.FORBIDDEN_TOOLS & {tool['name'] for tool in body.get('tools', [])}
                    for body in self.model.requests))
                self.assertEqual(len(result['host_delegate_approvals']), 2)
                self.assertEqual(set(result['workspace_after']['sha256']), {*qualification.FIXTURES, 'fact.txt'})
                self.assertFalse(result['workspace_after']['symlinks'])
                self.assertEqual(result['workspace_before'], result['workspace_after'])
                self.scope_evidence = {'result': result, 'runtime_evidence': evidence, 'task': task}
                if outside_probe:
                    self.assertFalse(result['passed'])
                    receipts = task['tools']
                    failures = [row for row in receipts if row['name'] == 'read_file'
                        and json.loads(row['arguments'])['path'] in {str(outside), '../outside-sentinel.txt'}]
                    self.assertEqual(len(failures), 6, receipts)
                    self.assertTrue(all(row['status'] == 'failed' and not row.get('read_receipt') for row in failures))
                    self.assertEqual({row.get('worker_id') for row in failures}, {None, '1.1', '1.2'})
                    self.assertTrue(all(row['payload']['error']['type'] == 'ValueError' for row in failures))
                    self.assertTrue(all(result['checks'][key] for key in result['checks'] if 'workspace_boundary' in key))
                    return
                self.assertTrue(result['passed'], {**result['checks'], 'task': task})
                self.assertEqual(result['model_call_count'], 7)
                self.assertEqual(len(self.model.requests), 7)
                self.assertEqual(result['provider_usage_once'],
                    {'input_tokens': 112, 'output_tokens': 63, 'prompt_cache_hit_tokens': 28})
                self.assertEqual([body['reasoning']['effort'] for body in self.model.requests
                    if body['model'] == 'gpt-6-luna'], ['high', 'high'])
                self.assertTrue(all(body['reasoning']['effort'] == 'medium'
                    for body in self.model.requests if body['model'] == 'gpt-6.1-sol'))
                self.assertEqual(len(final_requests), 3)
                for body in final_requests:
                    if 'delegate' in {tool['name'] for tool in body.get('tools', [])}:
                        self.assertTrue(all(value in json.dumps(body) for value in qualification.fixture_hashes().values()))
                    else:
                        self.assertIn(qualification.MARKER, json.dumps(body))
                broken = deepcopy(task)
                broken['subagents'][0]['receipts'].pop()
                self.assertFalse(all(qualification.acceptance(broken, evidence, qualification.fixture_hashes()).values()))
                broken_evidence = deepcopy(evidence)
                child_id = next(key for key in broken_evidence['nodes'] if key != 'parent')
                broken_evidence['nodes'][child_id]['capabilities']['write'] = True
                self.assertFalse(all(qualification.acceptance(task, broken_evidence, qualification.fixture_hashes()).values()))
                public = [path for path in output.glob('*.json')]
                self.assertTrue(public)
                self.assertTrue(all('fixture-not-a-real-key' not in path.read_text() for path in public))
            finally:
                core.stop()


if __name__ == '__main__':
    unittest.main()
