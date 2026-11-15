"""Host-authorized model changes preserve canonical history and worker provenance."""
from copy import deepcopy

from localpilot_api.service import APIError

def switch_model(server, principal, session_id, body):
    """Host-selected route migration, using the existing canonical checkpoint."""
    from .desktop_sessions import apply_options
    from copy import deepcopy
    from agent.persistence import configuration, digest, dumps, PersistenceError
    from .routing import select_route
    subject, client = _model_switch_request(server, principal, body)
    server.refresh_models(client)
    selected, _ = select_route(client.routes, server.catalog, explicit=body['model'],
        required=['tool_calling'], routing_preferences={'version':'1.0', 'source':body['source'], 'objective':'balanced'})
    route = client.routes[selected]
    if server.catalog.get(route, {}).get('reasoning_only'):
        raise APIError('Choose an Agent route', 'model_capability_insufficient', 409)
    service = server.service
    with service.condition:
        service._available()
        session = service._session(session_id)
        _model_switch_boundary(service, session, subject)
        previous = next((k for k,v in client.routes.items() if v == session.model), session.model)
        if route == session.model:
            result = service.session_snapshot(session_id)
            result['model'] = selected
            return result
        if client.routes.get(body['expected_model']) != session.model:
            raise APIError('Model changed in another client; refresh this conversation', 'model_conflict', 409)
        options = deepcopy(session.desktop_options)
        options.pop('context_length', None)
        options.pop('thinking_toggle', None)
        context = (server.catalog.get(route, {}).get('model_state') or {}).get('context_budget')
        if type(context) is int and 1024 <= context <= 262144:
            options['context_length'] = context
        declared = server.catalog.get(route, {}).get('reasoning_toggle')
        if declared and declared.get('supported'):
            options['thinking_toggle'] = {'model':declared['model'], 'default':declared['default']}
        if options.get('workspace_grant'):
            server.workspace_grants.get(options['workspace_grant'], subject)
            try:
                server.workspace_grants.validate(options['workspace_grant'])
            except (PermissionError, OSError):
                raise APIError('文件夹授权已失效，请重新选择文件夹后切换模型。', 'workspace_reauthorization_required', 403) from None
        try:
            candidate = service.routes[route](None)
        except Exception:
            raise APIError('Target route could not be prepared; the original conversation is unchanged', 'model_switch_unavailable', 503) from None
        old_runtime = session.runtime
        old = (session.model, session.runtime, session.base_prompt, session.desktop_options, session.thinking_override, session.child_route_contexts)
        try:
            apply_options(candidate, options)
            effort = body.get('reasoning_effort', session.thinking_override)
            if effort is not None:
                try:
                    candidate.set_thinking(effort)
                except ValueError as exc:
                    raise APIError(str(exc), 'thinking_not_supported', 409) from None
            candidate._service_extensions = deepcopy(session.extensions or {})
            if service.session_initializer:
                service.session_initializer(candidate, session_id, subject)
            from localpilot_api.session_history import retain_child_routes, retained_child_parents
            contexts = retain_child_routes(session)
            saved = {'id': session_id, 'owner_subject': subject, 'child_route_contexts': contexts}
            try:
                with retained_child_parents(service, saved) as child_parents:
                    _migrate_model_checkpoint(old_runtime, candidate, options, child_parents)
            except PersistenceError as error:
                raise APIError(str(error), 'model_switch_children_incompatible', 409) from None
            session.child_route_contexts = contexts or None
            candidate._persistence_config = digest(dumps(configuration(candidate)))
            session.model, session.runtime, session.base_prompt = route, candidate, candidate.base_prompt
            session.desktop_options, session.thinking_override = options, effort
            service._attach_persistence(session)
            candidate._emit('HostModelChanged', previous_model=old[0], model=route,
                            canonical_history_retained=True, automatic_tool_replay=False)
            service._checkpoint(session_id, 'desktop_model_changed')
        except Exception as error:
            session.model, session.runtime, session.base_prompt, session.desktop_options, session.thinking_override, session.child_route_contexts = old
            candidate._persistence_hook = None
            candidate.close()
            if isinstance(error, APIError):
                raise
            if isinstance(error, PersistenceError):
                raise APIError('模型切换检查点未确认，服务已停止写入；请重启并核对当前会话模型，勿重复执行任务。', 'model_switch_storage_unavailable', 503) from None
            raise APIError('Target route could not retain this Session; the original conversation is unchanged', 'model_switch_failed', 503) from None
        candidate.events.callback = lambda event: service._runtime_event(session_id, event)
        old_runtime._persistence_hook = None
        old_runtime.events.callback = None
        old_runtime.close()
        result = service.session_snapshot(session_id)
        result['model'] = selected
    server.access.audit(operation='desktop_model_changed', subject=principal.subject,
        client_subject=subject, session_id=session_id, previous=previous, model=selected)
    return result


def _model_switch_request(server, principal, body):
    if not principal.operator or 'control' not in principal.scopes:
        raise APIError('Separate host operator required', 'control_required', 403)
    required = {'client_subject','model','expected_model','source'}
    if (not isinstance(body, dict) or not required <= set(body)
            or set(body) - required - {'reasoning_effort'}
            or any(not isinstance(body[k], str) for k in required)
            or body.get('reasoning_effort') is not None and not isinstance(body['reasoning_effort'], str)):
        raise APIError('Exact Desktop model selection required')
    subject = body['client_subject']
    if subject not in principal.approval_for:
        raise APIError('Subject denied', 'scope_forbidden', 403)
    return subject, server.access.principals[subject]


def _model_switch_boundary(service, session, subject):
    from agent.persistence import recovery_class
    from agent.session import SessionState
    if session.owner_subject != subject:
        raise APIError('Session owner denied', 'scope_forbidden', 403)
    if not session.desktop_options or session.closed:
        raise APIError('Open Desktop session required', 'model_switch_unavailable', 409)
    runtime = session.runtime
    if (session.active_task or any(t.session_id == session.id and (t.executing or t.control_pending)
            for t in service.tasks.values()) or runtime.state not in {SessionState.SESSION_IDLE, SessionState.TURN_FINISHED}
            or runtime.pending_approval or runtime._queue or runtime._durable_intent):
        raise APIError('当前任务尚未结束，不能切换模型。请先完成或取消任务；副作用未知时请先核对原结果。', 'session_busy', 409)
    if recovery_class(runtime) == 'UNKNOWN_BLOCKED':
        raise APIError('原会话仍有 UNKNOWN 或部分完成的收据；切换模型不能消除这些记录。请先核对原结果。', 'model_switch_unknown_blocked', 409)
    if runtime.computer or runtime.adaptive:
        raise APIError('Native Computer / calibrated adaptive sessions do not support route migration yet', 'model_switch_runtime_incompatible', 409)
    from agent.persistence import nodes
    for child in list(nodes(runtime))[1:]:
        if (child.pending_approval or child._queue or child._durable_intent
                or child.state not in {SessionState.SESSION_IDLE, SessionState.TURN_FINISHED, SessionState.SESSION_FINISHED}):
            raise APIError('A child still has unfinished execution or approval; settle it before changing the main model', 'session_busy', 409)


def _migrate_model_checkpoint(current, target, options, child_parents=None):
    from copy import deepcopy
    from agent.persistence import configuration, snapshot_runtime, restore_runtime, pack, unpack
    from agent.hybrid import sha
    before, after = configuration(current), configuration(target)
    # A selected provider changes routing, context and thinking. Host tool scope,
    # budgets, verification, plugins and execution policy must remain identical.
    route_fields = {'cloud','local','workers','policy','data_policy','thinking','hybrid','async'}
    changed = sorted(k for k in set(before) | set(after)
                     if k not in route_fields and before.get(k) != after.get(k))
    if target.computer or target.adaptive or changed:
        reason = ', '.join(changed) or 'computer/adaptive runtime'
        raise APIError('Target route has an incompatible host contract: ' + reason, 'model_switch_contract_incompatible', 409)
    if before['data_policy'] != after['data_policy'] and options.get('scope_revision') != 3:
        raise APIError('This older Session does not authorize changing its local/cloud data boundary', 'model_switch_egress_incompatible', 409)
    if bool(current.hybrid) != bool(target.hybrid):
        raise APIError('Target route uses a different Hybrid execution contract', 'model_switch_contract_incompatible', 409)
    snapshot = snapshot_runtime(current)
    if target.async_policy:
        from agent.async_runtime import policy_snapshot
        snapshot['async'] = {'policy': policy_snapshot(target.async_policy)}
    else:
        snapshot.pop('async', None)
    fields = unpack(snapshot['fields'])
    fields.update(primary=target.primary, _turn_primary_restore=None, thinking_mode=target.thinking_mode)
    snapshot['fields'] = pack(fields)
    # Only host system instructions change. All user/model/tool messages,
    # native reasoning records, receipts and completed call IDs stay canonical.
    snapshot['messages'] = ([m.to_dict(include_reasoning=True) for m in target.messages if m.role == 'system']
                            + [m for m in snapshot['messages'] if m['role'] != 'system'])
    if target.hybrid:
        old_contract, new_contract = deepcopy(before['hybrid']), deepcopy(after['hybrid'])
        for contract in (old_contract, new_contract):
            for key in ('catalog','initial_backend_id'):
                contract.pop(key)
            contract['policy']['egress'].pop('mode')
            contract['policy'].pop('rates')
        if old_contract != new_contract:
            raise APIError('Target route changes Hybrid cooperation or egress limits', 'model_switch_contract_incompatible', 409)
        state = deepcopy(target.hybrid.state)
        prior = snapshot['hybrid']['state']
        for key in ('task','attempts','handoffs','egress','parent_handoff','cooperative'):
            if key in state:
                state[key] = deepcopy(prior[key])
        state['generation'] = prior['generation'] + 1
        # Provider-bound approvals/cache provenance are not transferable. Past
        # attempts retain their recorded provider/model instead of being relabeled.
        snapshot['hybrid'] = {'configuration':sha(target.hybrid.configuration()), 'state':state}
    restore_runtime(target, snapshot, child_parents=child_parents)
    target._effective_thinking()
