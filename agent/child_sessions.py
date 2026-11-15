"""Construct live and restored workers with the same inherited host contract."""
from copy import deepcopy

from .policy import DataPolicy
from .registry import create_default_registry
from .safety import CapabilityPolicy


def create_child(owner, record, budgets, thinking, *, source=None, inherit_tools=False):
    from .session import AgentSession

    parent = source or owner
    target, tier = record['backend'], record.get('tier')
    backend = (parent.local_backend if target == 'local' else
               parent.cloud_worker_backends.get(tier) if tier else parent.cloud_backend)
    if parent.hybrid:
        _, backend = parent.hybrid.resolve(target, record.get('backend_id'), record.get('configured_model'), tier)
    if backend is None:
        raise ValueError('Child backend no longer configured')
    ceiling = parent.registry.gateway.capabilities
    read_only = record['read_only'] or parent._planning
    data_policy = DataPolicy(local_only=parent.hard_data_policy.local_only if parent.hybrid else target == 'local')
    registry = create_default_registry(parent.workspace, permission_mode=parent.permission_mode,
        capabilities=CapabilityPolicy(read=ceiling.read, write=ceiling.write and not read_only,
            execute=ceiling.execute and not read_only, read_only=ceiling.read_only or read_only),
        data_policy=data_policy, file_operations='move_file' in parent.registry._tools)
    registry.authorization_guard = getattr(parent.registry, 'authorization_guard', None)
    registry.scope_policy = deepcopy(getattr(parent.registry, 'scope_policy', None))
    child = AgentSession(registry, backend=backend,
        local_backend=parent.local_backend if parent.hybrid else None,
        cloud_backend=parent.cloud_backend if parent.hybrid else None,
        cloud_worker_backends=parent.cloud_worker_backends if parent.hybrid else None,
        policy=parent.routing_policy if parent.hybrid else 'local-only' if target == 'local' else 'cloud-only',
        budgets=budgets, data_policy=data_policy, thinking=thinking,
        reasoning=parent.reasoning_mode, streaming=parent.streaming, runtime_tools=False,
        depth=owner.depth + 1, retry_policy=parent.retry_policy, stabilization=parent.controls,
        engine_policy=parent.engine_policy, computer_runtime=parent.computer, computer_owner=False,
        event_callback=lambda event: owner._emit('SubagentEvent', id=record['id'], event=event.to_dict()),
        hybrid_policy=parent.hybrid.policy if parent.hybrid else None,
        hybrid_backends=parent.hybrid.catalog if parent.hybrid else None,
        hybrid_primary=record.get('backend_id'), harness_policy=parent.harness_policy,
        adaptive_policy=parent.adaptive.policy if parent.adaptive else None,
        capability_profiles=parent.adaptive.profiles if parent.adaptive else None,
        task_traits=parent._child_traits() if parent.adaptive else None)
    if inherit_tools:
        _inherit_tools(parent, child)
        child._child_tool_contract_revision = 1
    child._cancel_parent = child._ledger_parent = owner
    child._worker_id = record['id']
    child._eligible = lambda: bool(child.current_backend.health_check()) if child.primary == 'local' else False
    child._persistence_hook = owner._persistence_hook
    if owner.async_policy:
        from .judge import LocalSafetyJudge
        child._async_enabled = True
        child._state_condition, child._scheduler = owner._state_condition, owner._scheduler
        child._scheduler_owner = owner._scheduler_owner
        if isinstance(child.registry.gateway.judge, LocalSafetyJudge):
            child.registry.gateway.judge.request_context = lambda: child._scheduler.model_slot(child, child.local_backend)
    return child


def _inherit_tools(parent, child):
    scope = child.registry.scope_policy
    if scope and scope.get('revision') in {2, 3}:
        from .host_tools import register
        register(child.registry, scope['mode'], scope['private_roots'])
    options = getattr(parent, '_plugin_options', None)
    if options:
        from localpilot_plugins.adapter import configure_session
        configure_session(child, **options)
    child._desktop_cloud_context = getattr(parent, '_desktop_cloud_context', False)
    child._refresh_prompt()
