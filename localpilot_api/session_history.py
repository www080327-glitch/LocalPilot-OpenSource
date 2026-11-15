"""Retain completed workers against their original host route after a model change."""
from contextlib import contextmanager
from copy import deepcopy

from agent.async_runtime import policy_snapshot
from agent.persistence import PersistenceError, configuration, digest, dumps


def retain_child_routes(session):
    contexts = deepcopy(session.child_route_contexts or {})
    current = session.runtime
    descriptor = {
        'model': session.model,
        'desktop_options': deepcopy(session.desktop_options),
        'thinking_override': session.thinking_override,
        'extensions': deepcopy(session.extensions or {}),
        'configuration_sha256': digest(dumps(configuration(current))),
        'async_policy': policy_snapshot(current.async_policy) if current.async_policy else None,
    }
    for worker_id in current._children:
        contexts.setdefault(worker_id, deepcopy(descriptor))
    return contexts


@contextmanager
def retained_child_parents(service, saved):
    parents, sources = {}, {}
    try:
        for worker_id, descriptor in (saved.get('child_route_contexts') or {}).items():
            identity = digest(dumps(descriptor))
            if identity not in sources:
                parent = _restore_parent(service, saved, descriptor)
                sources[identity] = (parent, descriptor['configuration_sha256'])
            parent, configuration_sha256 = sources[identity]
            descriptor['configuration_sha256'] = configuration_sha256
            parents[worker_id] = parent
        yield parents
    finally:
        for parent, _ in sources.values():
            parent.close()


def _restore_parent(service, saved, descriptor):
    from localpilot_service.desktop_sessions import apply_options

    model = descriptor['model']
    if model not in service.routes:
        raise PersistenceError('Historical child route is no longer configured: ' + model)
    parent = service.routes[model](None)
    try:
        if descriptor['desktop_options'] is not None:
            apply_options(parent, descriptor['desktop_options'])
        if descriptor['thinking_override'] is not None:
            parent.set_thinking(descriptor['thinking_override'])
        parent._service_extensions = deepcopy(descriptor['extensions'])
        if service.session_initializer:
            service.session_initializer(parent, saved['id'], saved.get('owner_subject'))
        contract = configuration(parent)
        # The shared scheduler may have been explicitly migrated at a later
        # idle boundary. Historical worker backends and tool contracts still pin.
        if descriptor['async_policy'] is None:
            contract.pop('async', None)
        else:
            contract['async'] = descriptor['async_policy']
        actual = digest(dumps(contract))
        if actual != descriptor['configuration_sha256']:
            migration = getattr(service.configuration_migration, 'historical_child_paths', None)
            if migration is None or not migration(parent,
                    {'configuration':descriptor['configuration_sha256']}, host_configuration=contract):
                raise PersistenceError('Historical child route contract changed: ' + model)
            descriptor['configuration_sha256'] = actual
        return parent
    except BaseException:
        parent.close()
        raise
