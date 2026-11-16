"""Configured inference transports shared by main and worker routes."""
from dataclasses import replace
import os
from pathlib import Path

from agent.backends import LocalBackend
from agent.cooperative import CooperativePolicy
from .backend_contract import (ManagedLocalBackend, ServiceDeepSeekBackend,
    ServiceDeepSeekNativeBackend, ServiceDeepSeekOptimizedBackend, ServiceOMLXBackend,
    ServiceOpenAIBackend, ServiceOpenAICloudBackend, ServiceVLLMBackend)


CLOUD_KINDS = {'deepseek', 'deepseek-native', 'remote-openai', 'remote-vllm', 'openai'}
LOCAL_KINDS = {'omlx', 'vllm', 'local-openai'}


def build_backend(spec, data_policy, *, manager=None, worker_thinking=None, cache_stable_prefix=False):
    kind = spec['kind']
    cloud = kind in CLOUD_KINDS
    if kind == 'unavailable':
        backend = LocalBackend(spec.get('model', 'not-deployed'))
    elif kind in {'deepseek', 'deepseek-native'}:
        adapter = (ServiceDeepSeekNativeBackend if kind == 'deepseek-native' else
                   ServiceDeepSeekOptimizedBackend if spec.get('agent_engine') == 'deepseek_optimized' else
                   ServiceDeepSeekBackend)
        backend = adapter(model=spec['model'], key_file=spec.get('key_file'),
            api_key=os.environ.get(spec['api_key_env']) if spec.get('api_key_env') else None,
            base_url=spec.get('base_url', 'https://api.deepseek.com/anthropic' if kind == 'deepseek-native' else 'https://api.deepseek.com'),
            effective_context=spec.get('context_budget', 131072), timeout=spec.get('timeout', 30),
            data_policy=data_policy, generation_parameters=spec.get('generation_parameters'))
    else:
        capabilities = spec.get('capabilities', {})
        key_env = spec.get('api_key_env', 'OPENAI_API_KEY' if kind == 'openai' else None)
        key = os.environ.get(key_env) if key_env else None
        base_url = spec.get('base_url', 'https://api.openai.com/v1') if kind == 'openai' else spec['base_url']
        if cloud and kind != 'openai' and (not key or not base_url.startswith('https://')):
            raise ValueError('Remote inference requires HTTPS and an explicit API token')
        adapter = (ManagedLocalBackend if manager else ServiceVLLMBackend if kind in {'vllm','remote-vllm'} else
                   ServiceOMLXBackend if kind == 'omlx' else ServiceOpenAICloudBackend if kind == 'openai' else
                   ServiceOpenAIBackend)
        backend = adapter(**({'manager':manager} if manager else {'api_key':key}),
            base_url=base_url, model=spec['model'],
            effective_context=spec.get('context_budget', 131072), timeout=spec.get('timeout', 30), allow_remote=cloud,
            supports_tool_calling=capabilities.get('tool_calling', kind not in {'vllm','remote-vllm'}),
            supports_streaming=capabilities.get('streaming', True), supports_vision=capabilities.get('vision', False),
            supports_reasoning=capabilities.get('reasoning'), reasoning_efforts=spec.get('reasoning_efforts', ()),
            include_stream_usage=spec.get('include_stream_usage', kind in {'omlx','vllm','remote-vllm','openai'}),
            chat_template_kwargs=spec.get('chat_template_kwargs'),
            generation_parameters=spec.get('generation_parameters'))
        backend.is_local = not cloud
    if worker_thinking is not None:
        if worker_thinking not in backend.capabilities.supported_thinking_efforts:
            raise ValueError('Partner thinking is unsupported')
        backend.capabilities = replace(backend.capabilities, default_thinking_effort=worker_thinking)
        backend.service_contract['default_thinking'] = worker_thinking
    if cache_stable_prefix:
        backend.service_cache_stable_prefix = True
        if hasattr(backend, 'service_contract'):
            backend.service_contract.update(cache_stable_prefix=True, cache_layout_version=1,
                system_prompt_update='in-history' if getattr(backend, 'supports_in_history_system_prompt', False) else 'replace')
    return backend


def cooperation_routes(route_name, spec, routes, workspace):
    cooperation = spec.get('cooperation')
    if cooperation is None:
        return {}, None, None
    if (not isinstance(cooperation, dict)
            or set(cooperation) - {'cloud_route', 'local_route', 'routes', 'optimizer', 'profiles'}
            or sum(key in cooperation for key in ('cloud_route', 'local_route', 'routes')) != 1
            or spec.get('managed_local_model') or spec.get('reasoning_only')):
        raise ValueError('Cooperation requires registered worker routes and a tool-capable primary')
    kind = spec['backend']['kind']
    if kind not in CLOUD_KINDS | LOCAL_KINDS:
        raise ValueError('Cooperation requires an inference backend')
    modern = 'routes' in cooperation
    if modern:
        names = cooperation['routes']
        if (not isinstance(names, list) or not names or any(not isinstance(n, str) for n in names)
                or len(set(names)) != len(names) or route_name in names):
            raise ValueError('Worker routes must be distinct registered route names')
        aliases = {'route:' + name: name for name in names}
    else:
        local = 'local_route' in cooperation
        if local != (kind in CLOUD_KINDS):
            raise ValueError('The legacy partner must use the opposite model location')
        aliases = {'local' if local else 'cloud': cooperation['local_route' if local else 'cloud_route']}
    workers = {}
    for alias, name in aliases.items():
        if not isinstance(name, str):
            raise ValueError('Worker route name must be a string')
        partner = routes.get(name)
        if (partner is None or partner['backend']['kind'] not in CLOUD_KINDS | LOCAL_KINDS
                or partner.get('managed_local_model') or partner.get('reasoning_only')
                or partner.get('computer_use')):
            if not modern and alias == 'local':
                raise ValueError('Local cooperation partner must be a registered unmanaged local inference route')
            raise ValueError('Worker must be a registered unmanaged inference route with tools')
        if Path(partner['workspace']).expanduser().resolve() != workspace:
            raise ValueError('Cooperation partners must use the same workspace')
        if not modern and (partner['backend']['kind'] in LOCAL_KINDS) != (alias == 'local'):
            raise ValueError('Partner route location does not match its declared role')
        backend = dict(partner['backend'])
        thinking = partner.get('thinking')
        if not modern:
            # Preserve the identity of already persisted legacy partner routes.
            if backend['kind'] in {'deepseek', 'deepseek-native'}:
                backend.setdefault('timeout', 45)
                backend.pop('agent_engine', None)
            else:
                thinking = None
        workers[alias] = {'backend': backend, 'thinking': thinking,
                         'cache_stable_prefix': bool(modern and partner.get('cache_stable_prefix', False))}
    policy = CooperativePolicy(**cooperation['optimizer']) if 'optimizer' in cooperation else None
    if policy is None and (modern or kind != 'omlx' or set(cooperation) != {'cloud_route'}):
        raise ValueError('Cooperation requires a typed five-mode optimizer')
    return workers, policy, cooperation.get('profiles')


def initial_backend(catalog, policy):
    if policy is None or policy.mode == 'balanced':
        return 'selected'
    local = policy.mode in {'local-only', 'local-first'}
    target = next((name for name, backend in catalog.items() if backend.is_local == local), None)
    if target is None and policy.mode in {'local-only', 'cloud-only'}:
        raise ValueError('The selected source mode has no configured inference backend')
    return target or 'selected'
