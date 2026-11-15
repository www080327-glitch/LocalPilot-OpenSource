"""Explicit desktop model configuration; saves new routes without touching live tasks."""
from copy import deepcopy
import ipaddress
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

MODES = {'local-first', 'balanced', 'cloud-first', 'local-only', 'cloud-only'}
CLOUD = {'deepseek', 'deepseek-native', 'remote-openai', 'remote-vllm'}
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
    before = private_json(path)
    config = deepcopy(before)
    connection = private_json(home / 'connection.json')
    principal = next((row for row in config['clients'] if row['subject'] == connection['client_subject']), None)
    if principal is None or principal.get('operator'):
        raise ValueError('A regular desktop client is required to select model routes')
    mapping = principal['routes']
    if operation == 'model_configuration':
        if args:
            raise ValueError('Model configuration catalog accepts no arguments')
        return {'models': [{'id': alias, 'model': config['routes'][name]['backend'].get('model'),
                            'workspace': config['routes'][name]['workspace'],
                            'adapter': config['routes'][name]['backend']['kind'],
                            'cooperation_supported': _supports(config['routes'][name])}
                           for alias, name in mapping.items()], 'restart_required': False}
    name = args.get('name')
    if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{1,63}', name):
        raise ValueError('Choose a new route name using 2–64 lowercase letters, digits, underscores or hyphens')
    if name in config['routes'] or any(name in row.get('routes', {}) for row in config['clients']):
        raise ValueError('Route already exists; existing routes and Sessions are preserved')
    companion = None
    if operation == 'configure_cooperation':
        from localpilot_service.protocol import manifest
        if 'route_orchestration_v1' not in manifest()['capabilities']:
            raise ValueError('先升级 Core：当前已安装版本未声明 route_orchestration_v1 能力')
        members, route = _cooperation(config, mapping, args)
    elif operation == 'configure_local_endpoint':
        members, route, companion = _local_endpoint(home, config, mapping, args)
    else:
        raise ValueError('Unsupported model configuration operation')
    config['routes'][name] = route
    for client in config['clients']:
        if not client.get('operator') and members <= set(client['routes'].values()):
            client['routes'][name] = name
    backup = home / ('service.before-model-' + str(time.time_ns()) + '.json')
    save(backup, before)
    save(path, config)
    if companion is not None:
        companion_path = home / 'companion.json'
        save(home / ('companion.before-model-' + str(time.time_ns()) + '.json'), private_json(companion_path))
        save(companion_path, companion)
    return {'status': 'configured', 'route': name, 'model': route['backend']['model'],
            'restart_required': True, 'restart_modules': ['core', 'companion'] if companion else ['core'],
            'backup': str(backup), 'existing_routes_preserved': True, 'inference': 'NOT_RUN',
            'connection': 'NOT_PROBED', 'budgets': route.get('budgets', {}),
            'orchestration_mode': route.get('orchestration_mode', 'sync'),
            'next': '等待活动任务结束，在安装、服务与数据恢复中显式停止并恢复所列服务；新路由随后出现。'}


def _supports(route):
    return (route['backend']['kind'] in CLOUD | LOCAL and not route.get('reasoning_only')
            and not route.get('managed_local_model') and not route.get('computer_use')
            and route['backend'].get('capabilities', {}).get('tool_calling', route['backend']['kind'] not in {'vllm', 'remote-vllm'}))


def _cooperation(config, mapping, args):
    if set(args) != {'name', 'primary', 'partners', 'mode', 'async_enabled'}:
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
    if args['async_enabled'] and 'async_policy' not in config:
        # Existing persisted Sessions keep their synchronous runtime fingerprint.
        for old in config['routes'].values():
            old.setdefault('orchestration_mode', 'sync')
        config['async_policy'] = dict(ASYNC_LIMITS)
    return set(names), route


def _local_endpoint(home, config, mapping, args):
    from localpilot_service.security import private_json
    if set(args) != {'name', 'base_url', 'model', 'context_budget', 'companion'}:
        raise ValueError('Exact local endpoint, model, context budget and Companion choice required')
    model, endpoint, context = args['model'], args['base_url'], args['context_budget']
    if (not isinstance(model, str) or not model.strip() or len(model) > 256 or any(ord(c) < 32 for c in model)
            or not isinstance(endpoint, str) or type(context) is not int or not 4096 <= context <= 1048576
            or type(args['companion']) is not bool):
        raise ValueError('Provide a model ID and its actual supported context window (4096–1048576)')
    parsed = urlsplit(endpoint)
    try:
        loopback = parsed.hostname == 'localhost' or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = False
    if (parsed.scheme != 'http' or not loopback or not parsed.port or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path.rstrip('/') != '/v1'):
        raise ValueError('A direct local OpenAI-compatible endpoint such as http://127.0.0.1:1234/v1 is required')
    template = next((name for name in mapping.values() if config['routes'][name]['backend']['kind'] not in CLOUD), None)
    if template is None:
        raise ValueError('An authorized local workspace route must already exist')
    route = deepcopy(config['routes'][template])
    for key in ('cooperation', 'managed_local_model', 'computer_use', 'verification', 'acceptance', 'thinking'):
        route.pop(key, None)
    route.update(engine='v5', backend={'kind': 'local-openai', 'model': model.strip(),
                 'base_url': endpoint.rstrip('/'), 'context_budget': context, 'timeout': 120},
                 cloud_egress='LOCAL_ONLY', deployment_status='ready', reasoning_only=False,
                 prompt_profile='standard', tool_profile='full', budgets=dict(BUDGETS), orchestration_mode='sync')
    route.pop('cloud_egress_paths', None)
    companion = None
    if args['companion']:
        companion = private_json(home / 'companion.json')
        companion.update(backend='local-http', http_model_endpoint=endpoint.rstrip('/'),
                         http_model_name=model.strip(), http_model_api_key_env='', http_model_host_local_only=True,
                         model_context_tokens=context, model_routing_enabled=False)
    return {template}, route, companion
