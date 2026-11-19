"""Explicit desktop model configuration; saves new routes without touching live tasks."""
from copy import deepcopy
import ipaddress
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, Request

MODES = {'local-first', 'balanced', 'cloud-first', 'local-only', 'cloud-only'}
CLOUD = {'deepseek', 'deepseek-native', 'openai', 'remote-openai', 'remote-vllm'}
LOCAL = {'local-openai', 'omlx', 'vllm'}
BUDGETS = {'max_steps': 48, 'max_tool_calls': 64, 'max_token_units': 4194304,
           'max_output_tokens': 4096, 'max_worker_steps': 12, 'max_worker_tool_calls': 16,
           'max_worker_token_units': 524288, 'max_worker_output_tokens': 2048,
           'max_subagents_per_turn': 4, 'max_primary_switches_per_turn': 2}
ASYNC_LIMITS = {'max_running_children': 4, 'max_running_per_session': 2,
                'max_model_requests': 2, 'max_local_model_requests': 1, 'max_cloud_model_requests': 2}


def command(home, operation, args):
    from localpilot_service.security import private_json
    from localpilot_service.cli import save
    path = home / 'service.json'
    if not path.exists():
        if operation == 'model_configuration' and not args:
            return {'models': [], 'configured': False, 'restart_required': False, 'restart_modules': []}
        raise ValueError('请先选择工作文件夹并准备 LocalPilot 组件，再保存模型配置')
    before = private_json(path)
    config = deepcopy(before)
    connection = private_json(home / 'connection.json')
    token_env = connection.get('token_env')
    principal = next((row for row in config['clients'] if
        (row['token_env'] == token_env if token_env else row['subject'] == connection['client_subject'])), None)
    if principal is None or principal.get('operator'):
        raise ValueError('A regular desktop client is required to select model routes')
    mapping = principal['routes']
    if operation == 'model_configuration':
        if args:
            raise ValueError('Model configuration catalog accepts no arguments')
        pending = pending_configuration(home)
        return {'models': [{'id': alias, 'model': config['routes'][name]['backend'].get('model'),
                            'workspace': config['routes'][name]['workspace'],
                            'adapter': config['routes'][name]['backend']['kind'],
                            'thinking': config['routes'][name].get('thinking'),
                            'cooperation_supported': _supports(config['routes'][name])}
                           for alias, name in mapping.items()], 'configured': True,
                'restart_required': bool(pending['modules']), 'restart_modules': pending['modules']}
    pending = pending_configuration(home)
    name = args.get('name')
    if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{1,63}', name):
        raise ValueError('Choose a new route name using 2–64 lowercase letters, digits, underscores or hyphens')
    if name in config['routes'] or any(name in row.get('routes', {}) for row in config['clients']):
        raise ValueError('Route already exists; existing routes and Sessions are preserved')
    companion = None
    resource_credential = None
    if operation == 'configure_cooperation':
        from localpilot_service.protocol import manifest
        capabilities = manifest()['capabilities']
        if 'route_orchestration_v1' not in capabilities:
            raise ValueError('先升级 Core：当前已安装版本未声明 route_orchestration_v1 能力')
        members, route = _cooperation(config, mapping, args)
        if route['cooperation'].get('roles') and 'worker_roles_v1' not in capabilities:
            raise ValueError('先升级 Core：当前已安装版本未声明 worker_roles_v1 探索/审阅分工能力')
    elif operation == 'configure_local_endpoint':
        members, route, companion = _local_endpoint(home, config, mapping, args)
    else:
        raise ValueError('Unsupported model configuration operation')
    config['routes'][name] = route
    for client in config['clients']:
        if not client.get('operator') and members <= set(client['routes'].values()):
            client['routes'][name] = name
    if companion is not None:
        resource_credential = _companion_routes(config, members, route, name, companion)
    backup = home / ('service.before-model-' + str(time.time_ns()) + '.json')
    save(backup, before)
    if resource_credential:
        key, token = resource_credential
        fd = os.open(home / 'clients.env', os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as stream:
            stream.write(f'export {key}={token}\n')
    save(path, config)
    if companion is not None:
        companion_path = home / 'companion.json'
        save(home / ('companion.before-model-' + str(time.time_ns()) + '.json'), private_json(companion_path))
        save(companion_path, companion)
    wanted = set(pending['modules']) | {'core'} | ({'companion'} if companion else set())
    modules = [module for module in ('core', 'companion') if module in wanted]
    save(home / 'model-configuration-pending.json', {'modules': modules})
    return {'status': 'configured', 'route': name, 'model': route['backend']['model'],
            'restart_required': True, 'restart_modules': modules,
            'backup': str(backup), 'existing_routes_preserved': True, 'inference': 'NOT_RUN',
            'connection': 'NOT_PROBED', 'budgets': route.get('budgets', {}),
            'orchestration_mode': route.get('orchestration_mode', 'sync'),
            'companion_power_policy': companion.get('low_power_policy', 'always') if companion else None,
            'companion_reasoning_route': companion.get('localpilot_analysis_route') if companion else None,
            'next': '等待活动任务结束后，点击应用配置并重启服务。已有 Session 与收据保留；连接和模型能力另行检查。'}


def pending_configuration(home):
    from localpilot_service.security import private_json
    path = home / 'model-configuration-pending.json'
    if not path.exists():
        return {'modules': []}
    value = private_json(path)
    if (not isinstance(value, dict) or set(value) != {'modules'} or not isinstance(value['modules'], list)
            or any(not isinstance(module, str) or module not in {'core', 'companion'} for module in value['modules'])):
        raise ValueError('Pending model configuration is invalid; original configuration is preserved')
    return value


def activate_configuration(home, args):
    from .installation import service
    if args != {'confirmed': True}:
        raise ValueError('Explicit service restart confirmation required')
    pending = pending_configuration(home)
    if not pending['modules']:
        return {'status': 'unchanged', 'restart_required': False, 'services': {}, 'inference': 'NOT_RUN'}
    # Core's existing stop refuses active tasks and outstanding approvals.
    stopped = service(home, 'core', 'stop')
    if stopped.get('status') != 'stopped':
        raise ValueError('Core 尚未停止；配置仍待生效，请查看服务诊断')
    if 'companion' in pending['modules']:
        service(home, 'companion', 'stop')
    services = {'core': service(home, 'core', 'recover')}
    if 'companion' in pending['modules']:
        services['companion'] = service(home, 'companion', 'recover')
    (home / 'model-configuration-pending.json').unlink()
    return {'status': 'activated', 'restart_required': False, 'services': services,
            'existing_sessions_preserved': True, 'inference': 'NOT_RUN',
            'next': '服务已恢复，请选择新模型并检查连接，然后提交真实任务。'}


def discover_endpoint(args):
    from .product_control import NoBackendRedirects
    if set(args) != {'base_url'}:
        raise ValueError('Exact local endpoint required')
    endpoint = local_endpoint_url(args['base_url'])
    try:
        opener = build_opener(ProxyHandler({}), NoBackendRedirects())
        with opener.open(Request(endpoint + '/models'), timeout=10) as response:
            raw = response.read(1048577)
        if len(raw) > 1048576:
            raise ValueError('Local model catalog exceeds 1 MiB')
        value = json.loads(raw)
    except HTTPError as error:
        raise ValueError(f'本机模型列表请求失败（HTTP {error.code}）；未提交推理请求') from None
    except (OSError, URLError, json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError('无法读取本机模型列表，请确认服务地址、启动状态和访问设置；未提交推理请求') from None
    rows = value.get('data') if isinstance(value, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not valid_model_id(row.get('id')) for row in rows):
        raise ValueError('Local service did not return an OpenAI-compatible model catalog')
    return {'models': [{'id': name} for name in sorted({row['id'] for row in rows})],
            'connection': 'REACHABLE', 'inference': 'NOT_RUN', 'context_budget': 'USER_REQUIRED',
            'next': '选择模型并填写服务实际配置的上下文窗口；模型列表可访问不代表任务能力已通过验证。'}


def _supports(route):
    return (route['backend']['kind'] in CLOUD | LOCAL and not route.get('reasoning_only')
            and not route.get('managed_local_model') and not route.get('computer_use')
            and route['backend'].get('capabilities', {}).get('tool_calling', route['backend']['kind'] not in {'vllm', 'remote-vllm'}))


def _cooperation(config, mapping, args):
    required = {'name', 'primary', 'partners', 'mode', 'async_enabled'}
    if not required <= set(args) or set(args) - required - {'roles'}:
        raise ValueError('Exact primary, partners, five-mode preference and async setting required')
    primary, partners, mode = args['primary'], args['partners'], args['mode']
    if (not isinstance(primary, str) or primary not in mapping or not isinstance(partners, list)
            or not partners or any(not isinstance(value, str) or value not in mapping for value in partners)
            or len(set(partners)) != len(partners) or primary in partners or not isinstance(mode, str) or mode not in MODES
            or type(args['async_enabled']) is not bool):
        raise ValueError('Select a primary and distinct registered worker models with a valid five-mode preference')
    names = [mapping[primary], *(mapping[value] for value in partners)]
    if len(set(names)) != len(names):
        raise ValueError('Aliases of the same registered route cannot be selected twice')
    roles = args.get('roles', {})
    if (not isinstance(roles, dict) or set(roles) - {'search', 'review'}
            or any(not isinstance(alias, str) or alias not in partners for alias in roles.values())):
        raise ValueError('探索/审阅职责只能选择已勾选的子 Agent 模型')
    routes = [config['routes'][value] for value in names]
    if any(not _supports(value) for value in routes):
        raise ValueError('Cooperation requires tool-capable unmanaged inference routes without Computer Use')
    if len({str(Path(value['workspace']).expanduser().resolve()) for value in routes}) != 1:
        raise ValueError('Cooperating models must share the same authorized workspace')
    locations = {'cloud' if value['backend']['kind'] in CLOUD else 'local' for value in routes}
    if mode == 'local-only' and 'local' not in locations or mode == 'cloud-only' and 'cloud' not in locations:
        raise ValueError('Selected source mode has no matching model')
    route = deepcopy(routes[0])
    for key in ('verification', 'acceptance'):
        route.pop(key, None)
    route.update(engine='v5', cooperation={'routes': names[1:], 'optimizer': {'mode': mode}},
                 prompt_profile='standard', tool_profile='full', budgets=dict(BUDGETS),
                 orchestration_mode='async' if args['async_enabled'] else 'sync',
                 cloud_egress='LOCAL_ONLY' if mode == 'local-only' or 'cloud' not in locations else 'REQUIRES_APPROVAL')
    if roles:
        route['cooperation']['roles'] = {role: mapping[alias] for role, alias in roles.items()}
    if args['async_enabled'] and 'async_policy' not in config:
        # Existing persisted Sessions keep their synchronous runtime fingerprint.
        for old in config['routes'].values():
            old.setdefault('orchestration_mode', 'sync')
        config['async_policy'] = dict(ASYNC_LIMITS)
    return set(names), route


def _local_endpoint(home, config, mapping, args):
    from localpilot_service.security import private_json
    required = {'name', 'base_url', 'model', 'context_budget', 'companion'}
    if not required <= set(args) or set(args) - required - {'companion_power_policy', 'disable_thinking'}:
        raise ValueError('Exact local endpoint, model, context budget and Companion choice required')
    model, endpoint, context = args['model'], args['base_url'], args['context_budget']
    if (not valid_model_id(model) or type(context) is not int or not 4096 <= context <= 1048576
            or type(args['companion']) is not bool):
        raise ValueError('Provide a model ID and its actual supported context window (4096–1048576)')
    endpoint = local_endpoint_url(endpoint)
    power = args.get('companion_power_policy', 'preserve')
    thinking = args.get('disable_thinking', False)
    if not isinstance(power, str) or power not in {'preserve', 'system', 'off'} or type(thinking) is not bool:
        raise ValueError('Choose an explicit Companion power policy and boolean thinking preference')
    if not args['companion'] and power != 'preserve':
        raise ValueError('Companion power policy requires selecting this endpoint for Companion')
    template = next((name for name in mapping.values() if config['routes'][name]['backend']['kind'] not in CLOUD), None)
    if template is None:
        raise ValueError('An authorized local workspace route must already exist')
    route = deepcopy(config['routes'][template])
    for key in ('cooperation', 'managed_local_model', 'computer_use', 'verification', 'acceptance', 'thinking'):
        route.pop(key, None)
    route.update(engine='v5', backend={'kind': 'local-openai', 'model': model.strip(),
                 'base_url': endpoint, 'context_budget': context, 'timeout': 120},
                 cloud_egress='LOCAL_ONLY', deployment_status='ready', reasoning_only=False,
                 prompt_profile='standard', tool_profile='full', budgets=dict(BUDGETS), orchestration_mode='sync')
    route.pop('cloud_egress_paths', None)
    route['budgets']['max_output_tokens'] = min(BUDGETS['max_output_tokens'], context // 4)
    route['budgets']['max_worker_output_tokens'] = min(BUDGETS['max_worker_output_tokens'], context // 4)
    if thinking:
        route['backend']['chat_template_kwargs'] = {'enable_thinking': False}
    companion = None
    if args['companion']:
        companion = private_json(home / 'companion.json')
        companion.update(backend='local-http', http_model_endpoint=endpoint,
                         http_model_name=model.strip(), http_model_api_key_env='', http_model_host_local_only=True,
                         model_context_tokens=context, model_routing_enabled=False, model_adapter_path='')
        companion['max_output_tokens'] = min(companion.get('max_output_tokens', 160), context // 4)
        if thinking or 'http_model_disable_thinking' in companion:
            companion['http_model_disable_thinking'] = thinking
        if power != 'preserve':
            companion['low_power_policy'] = power
    return {template}, route, companion


def _companion_routes(config, members, route, name, companion):
    import secrets
    subject = companion.get('localpilot_client_subject', 'companion')
    client = next((c for c in config['clients'] if c['subject'] == subject and not c.get('operator')), None)
    if client is None or client['routes'].get(name) != name:
        raise ValueError('Companion client does not share this authorized workspace route')
    analysis_name = name[:54] + '-reasoning'
    if analysis_name in config['routes'] or any(analysis_name in c.get('routes', {}) for c in config['clients']):
        raise ValueError('Companion reasoning route already exists; choose a different new route name')
    analysis = deepcopy(route)
    analysis.update(reasoning_only=True, prompt_profile='minimal_0', tool_profile='compact',
                    capabilities={'read': False, 'write': False, 'execute': False})
    analysis['budgets']['max_subagents_per_turn'] = 0
    config['routes'][analysis_name] = analysis
    for client in config['clients']:
        if not client.get('operator') and members <= set(client['routes'].values()):
            client['routes'][analysis_name] = analysis_name
    resource = next((c for c in config['clients'] if c.get('operator')
        and 'resource_control' in c.get('scopes', []) and subject in c.get('approval_for', [])), None)
    credential = None
    if resource is None:
        if any(c['subject'] == 'endpoint-resource' or c['token_env'] == 'LOCALPILOT_ENDPOINT_RESOURCE_TOKEN' for c in config['clients']):
            raise ValueError('Endpoint resource identity is already used by another configuration')
        resource = {'subject': 'endpoint-resource', 'token_env': 'LOCALPILOT_ENDPOINT_RESOURCE_TOKEN',
                    'operator': True, 'scopes': ['read', 'resource_control'], 'approval_for': [subject], 'routes': {}}
        config['clients'].append(resource)
        credential = resource['token_env'], secrets.token_urlsafe(32)
    companion.update(localpilot_route=name, localpilot_analysis_route=analysis_name,
        localpilot_expected_local_model=route['backend']['model'],
        localpilot_resource_key_env=resource['token_env'], desktop_control_enabled=True)
    return credential


def valid_model_id(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 256 and not any(ord(c) < 32 for c in value)


def local_endpoint_url(endpoint):
    if not isinstance(endpoint, str):
        raise ValueError('Local endpoint must be a URL')
    try:
        parsed = urlsplit(endpoint.strip())
        loopback = parsed.hostname == 'localhost' or ipaddress.ip_address(parsed.hostname).is_loopback
        port = parsed.port if parsed.port is not None else 80
    except (ValueError, TypeError):
        raise ValueError('A direct local OpenAI-compatible endpoint such as http://127.0.0.1:1234/v1 is required') from None
    if (parsed.scheme != 'http' or not loopback or not port or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path.rstrip('/') not in {'', '/v1'}):
        raise ValueError('A direct local OpenAI-compatible endpoint such as http://127.0.0.1:1234/v1 is required')
    host = '127.0.0.1' if parsed.hostname == 'localhost' else parsed.hostname
    if ':' in host:
        host = '[' + host + ']'
    return f'http://{host}:{port}/v1'
