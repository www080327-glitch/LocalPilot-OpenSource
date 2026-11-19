"""Real TLS Responses requests preserve the configured parent/child efforts."""
import json
from pathlib import Path
import tempfile

from agent.engine_v5 import EngineV5Policy
from agent.hybrid import CloudEgressPolicy, HybridPolicy
from agent.policy import DataPolicy
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets
from localpilot_service.route_backends import build_backend
from tests.test_openai_cloud_backend import OpenAICloudFixture
from tests.test_openai_responses import response_payload


class WorkerRoleResponsesTests(OpenAICloudFixture):
    def test_luna_high_parent_keeps_sol_medium_review_requests(self):
        delegated = response_payload()
        delegated['output'] = [{'type': 'function_call', 'call_id': 'review-once',
            'name': 'delegate', 'arguments': json.dumps({'task': 'Read fact.txt and review its contents.',
                'backend_preference': 'cloud', 'role': 'review'})}]
        for response in (delegated, response_payload(call=True),
                         response_payload(text='OBSERVED-7319'), response_payload(text='Collected OBSERVED-7319.')):
            self.model.add(response)
        parent = self.backend(model='gpt-6-luna', protocol='responses', capabilities={'streaming': False})
        worker = build_backend({'kind': 'openai', 'protocol': 'responses', 'model': 'gpt-6.1-sol',
            'base_url': self.model.base_url, 'capabilities': {'streaming': False}}, DataPolicy(), worker_thinking='medium')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'fact.txt').write_text('OBSERVED-7319')
            runtime = AgentSession(create_default_registry(root, permission_mode='full-permission'),
                cloud_backend=parent, policy='cloud-only', thinking='high', streaming=False,
                hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED', ('fact.txt',))),
                hybrid_backends={'selected': parent, 'route:review': worker}, hybrid_primary='selected',
                worker_roles={'review': 'route:review'}, engine_policy=EngineV5Policy(),
                budgets=SessionBudgets(max_steps=16, max_tool_calls=20, max_token_units=8000000,
                    max_worker_steps=6, max_worker_tool_calls=4, max_worker_token_units=1000000),
                retry_policy=RetryPolicy(max_attempts=1))
            try:
                result = runtime.run_turn('Ask the configured reviewer to inspect fact.txt.')
                self.assertEqual(result.status, 'completed')
                self.assertEqual(runtime.subagents[0]['receipts'][0]['payload']['result'], 'OBSERVED-7319')
                self.assertEqual(runtime.hybrid.state['backend_id'], 'selected')
            finally:
                runtime.close()
        self.assertEqual([body['model'] for body in self.model.requests],
                         ['gpt-6-luna', 'gpt-6.1-sol', 'gpt-6.1-sol', 'gpt-6-luna'])
        self.assertEqual([body['reasoning'] for body in self.model.requests],
                         [{'effort': 'high'}, {'effort': 'medium'}, {'effort': 'medium'}, {'effort': 'high'}])
        delegate = next(tool for tool in self.model.requests[0]['tools'] if tool['name'] == 'delegate')
        self.assertEqual(delegate['parameters']['properties']['role']['enum'], ['review'])
        self.assertNotIn('tier', delegate['parameters']['properties'])
        child_tools = {tool['name'] for tool in self.model.requests[1]['tools']}
        self.assertNotIn('request_model_switch', child_tools)
        self.assertNotIn('apply_patch', child_tools)
        self.assertNotIn('shell', child_tools)
        self.assertEqual([path for path, _ in self.model.headers], ['/v1/responses'] * 4)
