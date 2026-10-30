"""Bounded real local-model selection test using reviewed public MCP resources.

Uses native-only existing local endpoint credentials; none enter model context.
No cloud inference, model download, user data, or service configuration edits.
"""
import importlib.util
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from types import SimpleNamespace

from agent.omlx import OMLXBackend
from agent.policy import DataPolicy
from agent.registry import ToolRegistry
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets, SessionState
from localpilot_plugins.adapter import attach
from localpilot_plugins.manager import PluginManager
from localpilot_service.cli import environment
from localpilot_service.model_resources import ModelResources
from localpilot_service.security import Principal

MODEL = 'mlx-community--Qwen3.5-0.8B-4bit'


def main(home, output):
    report = {'selection': 'REAL_LOCAL_MODEL', 'model': MODEL, 'cloud_inference': False,
              'test_data': 'Upstream fixed public greeting', 'status': 'NOT_RUN'}
    import hashlib
    report["source_sha256"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(Path("localpilot_plugins").glob("*.py"))}
    temp = tempfile.TemporaryDirectory(prefix='localpilot-plugin-model-')
    root = Path(temp.name).resolve()
    workspace = root / 'workspace'
    workspace.mkdir()
    manager = PluginManager(root / 'plugins')
    runtime, backend, resources, operator, loaded_by_test = None, None, None, None, False
    try:
        config = json.loads((Path(home) / 'service.json').read_text())
        env = environment(Path(home))
        local = next(s['backend'] for s in config['routes'].values() if '127.0.0.1:8020' in s['backend'].get('base_url', ''))
        backend = OMLXBackend(base_url=local['base_url'], model=MODEL, api_key=env.get(local.get('api_key_env', '')),
            effective_context=65536, size_class='0.8B', timeout=60, supports_streaming=False,
            chat_template_kwargs={'enable_thinking': False}, service_location='local')
        before = backend.inspect_service()
        model = next(m for m in before['models'] if m['id'] == MODEL)
        report['preflight'] = {k: model.get(k) for k in ('id', 'loaded', 'size_bytes', 'trust_remote_code')}
        report['preflight']['active_requests'] = before.get('active_requests')
        if before.get('active_requests') != 0:
            report.update(status='NOT_RUN', reason='Existing provider busy; preserve other work')
            return
        client = Principal('plugin-test', secrets.token_urlsafe(32), routes={'public': 'public'})
        operator = Principal('plugin-test-operator', secrets.token_urlsafe(32), scopes=frozenset({'resource_control'}),
            operator=True, approval_for=('plugin-test',))
        server = SimpleNamespace(access=SimpleNamespace(principals={'plugin-test': client}),
            model_backends={'public': backend}, service=SimpleNamespace(condition=threading.Condition(), tasks={}))
        resources = ModelResources(server, root / 'resources.json')
        body = {'client_subject': 'plugin-test', 'model': 'public', 'operation': 'load',
                'confirmed': True, 'max_memory_bytes': 4 * 1024**3}
        if not model['loaded']:
            result = resources.operate(operator, body, 'plugin-e2e-load')
            report['resource_load'] = {k: result.get(k) for k in ('status', 'loaded', 'error')}
            loaded_by_test = result.get('status') == 'completed'
            if not loaded_by_test:
                report.update(status='NOT_RUN', reason='Native resource controller did not confirm loading')
                return
        for name, module in [('resource', 'mcp_simple_resource'), ('prompt', 'mcp_simple_prompt')]:
            package = Path(importlib.util.find_spec(module).origin).parent
            manager.add({'id': name, 'transport': 'stdio', 'command': sys.executable,
                         'args': ['-m', module], 'source_files': [str(p) for p in package.glob('*.py')], 'timeout': 10})
            discovery = manager.discover(name, source_reviewed=True, license_id='MIT')
            catalog = discovery['catalog']
            manager.review(name, discovery['catalog_sha256'], {'tools': {},
                'resources': [r['uri'] for r in catalog['resources']], 'prompts': [p['name'] for p in catalog['prompts']],
                'plugin_egress': 'allow', 'network_access': False, 'scope': 'Fixed upstream synthetic examples only', 'allow_agent': True})
            manager.enable(name)
        registry = ToolRegistry(workspace, permission_mode='approve-all', data_policy=DataPolicy(local_only=True))
        attach(registry, manager.home)
        runtime = AgentSession(registry, backend=backend, policy='local-only', data_policy=DataPolicy(local_only=True),
            runtime_tools=False, streaming=False, budgets=SessionBudgets(max_steps=4, max_tool_calls=4, max_output_tokens=512),
            retry_policy=RetryPolicy(max_attempts=1))
        result = runtime.run_turn('Retrieve the greeting sample exposed by the external resource server. Then quote its exact text. Use a tool to read the sample before answering.')
        report['initial_runtime_status'] = result.status
        report['approval_required'] = runtime.state == SessionState.TOOL_AWAITING_APPROVAL
        report['before_approval_dispatch_count'] = len(list(manager.receipts.glob('*.json')))
        if report['approval_required']:
            report['approval_kind'] = runtime.pending_approval['kind']
            report['approval_actor'] = 'Isolated test operator, standing authorization for public data only; no GUI human action claimed'
            result = runtime.approve()
        report['result'] = {'status': result.status, 'text': result.text, 'verification_status': result.verification_status}
        report['receipts'] = runtime.tool_history
        observed = any(r['payload'].get('ok') and 'Hello! This is a sample text resource.' in json.dumps(r['payload']) for r in runtime.tool_history)
        report['status'] = 'PASS' if observed and report['approval_required'] and report['before_approval_dispatch_count'] == 0 and 'Hello!' in result.text else 'FAIL'
    except Exception as error:
        report.update(status='FAIL', error_type=type(error).__name__)
    finally:
        if runtime:
            runtime.close()
        manager.close()
        if loaded_by_test and resources:
            try:
                body['operation'] = 'unload'
                result = resources.operate(operator, body, 'plugin-e2e-unload')
                report['resource_cleanup'] = {k: result.get(k) for k in ('status', 'loaded', 'error')}
            except Exception as error:
                report['resource_cleanup'] = {'status': 'UNKNOWN', 'error_type': type(error).__name__}
        Path(output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
        temp.cleanup()
        print(json.dumps({'status': report['status'], 'output': output}))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
