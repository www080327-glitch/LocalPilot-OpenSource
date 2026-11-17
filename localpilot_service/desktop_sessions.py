"""Host-authorized settings on the existing AgentSession, persisted with the session."""
from localpilot_api.service import APIError, MAX_TASK_TIMEOUT
from dataclasses import replace
import hashlib,json,re
MODES = {"isolated":"approve-mutations", "request":"approve-mutations", "workspace":"workspace-auto", "ask":"approve-all", "safe":"assist-low-risk", "uncertain":"assist-high-risk", "full":"full-permission"}
EXTENDED_BUDGET = dict(max_steps=2048, max_tool_calls=4096, max_token_units=64 * 1024 * 1024,
    max_output_tokens=4096, max_primary_switches_per_turn=8, max_subagents_per_turn=64,
    max_worker_steps=64, max_worker_tool_calls=128, max_worker_token_units=2 * 1024 * 1024,
    max_worker_output_tokens=2048)

def thinking_backends(runtime):
    candidates=[runtime.current_backend]
    if runtime.hybrid:candidates.extend(runtime.hybrid.catalog.values())
    seen=set();result=[]
    for backend in candidates:
        if id(backend) not in seen:seen.add(id(backend));result.append(backend)
    return result

def apply_options(runtime, options):
    _validate_options(options)
    toggle = options.get('thinking_toggle')
    targets = []
    if toggle is not None:
        targets = [b for b in thinking_backends(runtime) if getattr(b, 'model', None) == toggle['model']
                   and hasattr(b, 'configure_thinking_toggle')]
        if not targets:
            raise APIError('Local thinking model is not in this session')
    if not hasattr(runtime, "_desktop_base_capabilities"):
        runtime._desktop_base_capabilities = runtime.registry.gateway.capabilities
    if not hasattr(runtime, '_desktop_base_budgets'):
        runtime._desktop_base_budgets = runtime.budgets
    if runtime.hybrid and not hasattr(runtime, '_desktop_base_cloud_limits'):
        runtime._desktop_base_cloud_limits = {
            'request_bytes': runtime.hybrid.policy.egress.max_request_bytes,
            'requests': runtime.hybrid.policy.max_cloud_requests_per_turn,
        }
    runtime.budgets = (replace(runtime._desktop_base_budgets, **EXTENDED_BUDGET)
        if options.get('execution_budget', 'standard') == 'extended' else runtime._desktop_base_budgets)
    if options.get("workspace_grant"):
        runtime._workspace_grants.bind(runtime,options["workspace_grant"])
    if toggle is not None:
        for backend in targets:backend.configure_thinking_toggle(toggle['default'])
    runtime.permission_mode=runtime.registry.gateway.mode=MODES[options["permission_mode"]]
    if options.get('scope_revision')==3:
        from agent.safety import CapabilityPolicy
        from agent.policy import DataPolicy
        mode = options['permission_mode']
        base = runtime._desktop_base_capabilities
        read_grant = bool(options.get('workspace_grant') and runtime._workspace_grants.get(options['workspace_grant'])['scope']=='read')
        runtime.registry.gateway.capabilities = CapabilityPolicy(read=base.read, write=mode=='full' or base.write and mode!='isolated' and not read_grant, execute=mode!='isolated', read_only=mode=='isolated' or read_grant and mode!='full')
        runtime.registry.gateway.data_policy = DataPolicy(local_only=False)
        if mode=='full':
            runtime.registry.authorization_guard = None
        elif options.get('workspace_grant') and options.get('scope_revision')==3:
            from contextlib import contextmanager
            grant_id=options['workspace_grant']
            @contextmanager
            def validate_workspace(name,args):
                runtime._workspace_grants.validate(grant_id)
                yield
            runtime.registry.authorization_guard=validate_workspace
        # A Desktop user selects the provider and the file policy. Readable tool
        # results must remain visible to that provider, without per-round masking.
        runtime._desktop_cloud_context = True
        if runtime.hybrid:
            from agent.hybrid import CloudEgressPolicy
            ep=runtime.hybrid.policy.egress
            if ep.mode!='LOCAL_ONLY':
                limits = runtime._desktop_base_cloud_limits
                # Old persisted sessions have no explicit execution-budget field.
                # Preserve their identity until the host selects the new contract.
                use_budget = mode == 'full' and 'execution_budget' in options
                request_bytes = max(limits['request_bytes'], runtime.budgets.max_token_units) if use_budget else limits['request_bytes']
                requests = max(limits['requests'], runtime.budgets.max_steps) if use_budget else limits['requests']
                runtime.hybrid.policy = replace(runtime.hybrid.policy,
                    egress=CloudEgressPolicy('CLOUD_ALLOWED', ep.allowed_paths, request_bytes),
                    max_cloud_requests_per_turn=requests)
    elif options['permission_mode']=='isolated':
        runtime.permission_mode=runtime.registry.gateway.mode='approve-all'
    if options["permission_mode"] in {"isolated", "request", "workspace"} or options.get("scope_revision") in {1,2,3}:
        from agent.scope_permissions import configure
        from agent.safe_files import make_directory, move_file, copy_file, inspect_file, list_entries
        from agent.permissions import ToolRiskMetadata
        for name, function in {"make_directory":make_directory,"move_file":move_file,"copy_file":copy_file,"inspect_file":inspect_file,"list_entries":list_entries}.items():
            if name not in runtime.registry._tools:
                runtime.registry.register(name,function,ToolRiskMetadata(read_only=name in {"inspect_file","list_entries"},mutating=name not in {"inspect_file","list_entries"}))
        private_roots=getattr(getattr(runtime, '_workspace_grants', None), 'private_roots', ())
        if getattr(runtime, '_plugin_options', None):
            from localpilot_plugins.adapter import private_roots as plugin_private_roots
            private_roots = (*private_roots, *plugin_private_roots(runtime))
        configure(runtime.registry, options["permission_mode"], private_roots, revision=options.get('scope_revision',1))
        if options.get('scope_revision') in {2,3}:
            from agent.host_tools import register, SHELL_MAX_TIMEOUT
            max_timeout = (MAX_TASK_TIMEOUT if options['permission_mode'] == 'full'
                and options.get('execution_budget') == 'extended' else SHELL_MAX_TIMEOUT)
            register(runtime.registry,options['permission_mode'],private_roots,max_timeout=max_timeout)
    from agent.profiles import prompt_text
    runtime.prompt_profile=("minimal_agent_v2" if options.get('prompt_revision',1)==2 else "minimal_0") if options["agent_profile"]=="minimal" else "standard"
    runtime.base_prompt=prompt_text(runtime.prompt_profile)
    # Only called for a newly constructed host Session or before restoring it.
    runtime.messages=[m for m in runtime.messages if m.role!='system']
    context=options.get('context_length')
    if context is not None:
        backend=runtime.current_backend
        backend.model_info=replace(backend.model_info,effective_context=context)
        if hasattr(backend,'profile'):backend.profile=replace(backend.profile,configured_context=context)
    runtime._refresh_prompt()


def _validate_options(options):
    allowed = {'permission_mode', 'agent_profile', 'context_length', 'prompt_revision',
               'workspace_grant', 'scope_revision', 'thinking_toggle', 'execution_budget'}
    if not isinstance(options, dict) or set(options) - allowed or not {'permission_mode', 'agent_profile'} <= options.keys():
        raise APIError('Unsupported Desktop session settings')
    if (not isinstance(options['permission_mode'], str) or options['permission_mode'] not in MODES
            or options['agent_profile'] not in ('standard', 'minimal')):
        raise APIError('Unsupported Desktop session settings')
    if options.get('execution_budget', 'standard') not in ('standard', 'extended'):
        raise APIError('Unsupported execution budget')
    revision = options.get('prompt_revision', 1)
    if type(revision) is not int or revision not in (1, 2):
        raise APIError('Unsupported Desktop prompt revision')
    scope = options.get('scope_revision')
    if scope is not None and (type(scope) is not int or scope not in (1, 2, 3)):
        raise APIError('Unsupported file scope revision')
    if 'workspace_grant' in options and (not isinstance(options['workspace_grant'], str)
            or not re.fullmatch(r'grant_[0-9a-f]{32}', options['workspace_grant'])):
        raise APIError('Invalid folder authorization identity')
    context = options.get('context_length')
    if context is not None and (type(context) is not int or not 1024 <= context <= 262144):
        raise APIError('Invalid negotiated local context')
    toggle = options.get('thinking_toggle')
    if toggle is not None and (not isinstance(toggle, dict) or set(toggle) != {'model', 'default'}
            or not isinstance(toggle['model'], str) or not toggle['model'] or type(toggle['default']) is not bool):
        raise APIError('Invalid local thinking control declaration')

def create(server, principal, body, key):
    if not principal.operator or "control" not in principal.scopes:
        raise APIError("Separate host operator required", "control_required",403)
    if not isinstance(body,dict) or set(body)!={"client_subject","model","options","source"}:
        raise APIError("Exact Desktop session authorization required")
    subject=body["client_subject"]
    if subject not in principal.approval_for:raise APIError("Subject denied","scope_forbidden",403)
    client=server.access.principals[subject]
    if not isinstance(key,str) or not re.fullmatch(r'[!-~]{1,128}',key):raise APIError('Desktop authorization requires an idempotency key','idempotency_required',400)
    identity=hashlib.sha256((principal.subject+'\0'+subject+'\0'+key).encode()).hexdigest()
    fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
    def prior():
        session=server.service.session_for_key(identity)
        if session:
            if session.desktop_fingerprint!=fingerprint:raise APIError('Desktop authorization key conflict','idempotency_conflict',409)
            result=server.service.session_snapshot(session.id)
            result['model']=next(k for k,v in client.routes.items() if v==session.model)
            return result
    with server.service.condition:
        replay=prior()
        if replay:return replay
    server.refresh_models(client)

    if body["model"]=="__auto__":
        from .routing import select_route
        selected,_=select_route(client.routes,server.catalog,required=['tool_calling'],routing_preferences={'version':'1.0','source':body['source'],'objective':'balanced'})
        body=dict(body,model=selected)
    if body["model"] not in client.routes:raise APIError("Unknown route","model_not_registered",404)
    from .routing import select_route
    select_route(client.routes,server.catalog,explicit=body['model'],required=['tool_calling'],routing_preferences={'version':'1.0','source':body['source'],'objective':'balanced'})
    route=client.routes[body["model"]]
    if server.catalog.get(route,{}).get("reasoning_only"):raise APIError("Choose an Agent route","model_capability_insufficient",409)
    if not isinstance(body["options"],dict):raise APIError("Invalid Desktop session options")
    options=dict(body['options'])
    if 'workspace_grant' in options and (not isinstance(options['workspace_grant'],str) or not re.fullmatch(r'grant_[0-9a-f]{32}',options['workspace_grant'])):raise APIError('Invalid folder authorization identity')
    if options.get('workspace_grant'):
        server.workspace_grants.get(options['workspace_grant'],subject)
        try:grant=server.workspace_grants.validate(options['workspace_grant'])
        except (PermissionError,OSError):raise APIError('文件夹授权已撤销、目录身份或执行主体已变化，或系统拒绝访问；请重新选择文件夹并核对 macOS 文件与文件夹授权','workspace_reauthorization_required',403) from None
        ceiling=server.catalog.get(route,{}).get('tool_capabilities',{})
        if grant['scope']!='read' and not ceiling.get('write',True):raise APIError('Selected route disables writes; choose a route with write capability before authorizing organization','workspace_capability_insufficient',409)
    declared=server.catalog.get(route,{}).get('reasoning_toggle')
    if declared and declared.get('supported'):
        options['thinking_toggle']={'model':declared['model'],'default':declared['default']}
    options['prompt_revision']=2
    if options.get('permission_mode') in {'isolated','request','workspace','full'}:options['scope_revision']=3
    backend=getattr(server,'model_backends',{}).get(route)
    if backend:
        observation=backend.inspect_service()
        model=next((m for m in observation['models'] if m['id']==backend.model),{})
        context=model.get('context_budget')
        if type(context) is int and 1024<=context<=262144:options['context_length']=context
    with server.service.condition:
        replay=prior()
        if replay:return replay
        result=server.service.create_session(route,owner_subject=subject,desktop_options=options,desktop_key=identity,desktop_fingerprint=fingerprint)
    server.access.audit(operation="desktop_session_authorized",subject=principal.subject,client_subject=subject,session_id=result["id"],options=options)
    result["model"]=body["model"]
    return result


def switch_profile(server, principal, session_id, body):
    """Change only a host-owned prompt at an idle boundary, retaining history."""
    from copy import deepcopy
    from agent.persistence import configuration, digest, dumps
    if not principal.operator or 'control' not in principal.scopes:
        raise APIError('Separate host operator required','control_required',403)
    base_keys={'client_subject','agent_profile','expected_profile'}
    permission_keys={'permission_mode','expected_permission_mode'}
    budget_keys={'execution_budget','expected_execution_budget'}
    allowed_shapes=(base_keys,base_keys|permission_keys,base_keys|budget_keys,base_keys|permission_keys|budget_keys)
    if not isinstance(body,dict) or set(body) not in allowed_shapes or not isinstance(body['agent_profile'],str) or not isinstance(body['expected_profile'],str) or body['agent_profile'] not in {'standard','minimal'} or body['expected_profile'] not in {'standard','minimal'}:
        raise APIError('Exact Agent profile selection required')
    if 'permission_mode' in body and any(not isinstance(body[k], str) or body[k] not in MODES for k in permission_keys):
        raise APIError('Invalid permission mode')
    if 'execution_budget' in body and any(body[k] not in ('standard', 'extended') for k in budget_keys):
        raise APIError('Invalid execution budget')
    subject=body['client_subject']
    if subject not in principal.approval_for:
        raise APIError('Subject denied','scope_forbidden',403)
    service=server.service
    with service.condition:
        service._available()
        session=service._session(session_id)
        if session.owner_subject!=subject:
            raise APIError('Session owner denied','scope_forbidden',403)
        options=session.desktop_options
        if not options or session.closed:
            raise APIError('Desktop session required','profile_switch_unavailable',409)
        if session.active_task or any(t.session_id==session_id and (t.executing or t.control_pending) for t in service.tasks.values()):
            raise APIError('当前任务尚未结束，不能切换权限或 Agent 模式。请先完成或取消当前任务；若显示副作用未知，请先核对结果，勿重复执行原命令。','session_busy',409)
        current=options['agent_profile']
        desired_mode=body.get('permission_mode',options['permission_mode'])
        current_budget = options.get('execution_budget', 'standard')
        desired_budget = body.get('execution_budget', current_budget)
        declared=server.catalog.get(session.model,{}).get('reasoning_toggle')
        desired_toggle=({'model':declared['model'],'default':declared['default']} if declared and declared.get('supported') else options.get('thinking_toggle'))
        if current==body['agent_profile'] and desired_mode==options['permission_mode'] and desired_budget==current_budget and ('execution_budget' not in body or 'execution_budget' in options) and options.get('thinking_toggle')==desired_toggle and options.get('prompt_revision')==2 and (desired_mode not in {'isolated','request','workspace','full'} or options.get('scope_revision')==3):
            return service.session_snapshot(session_id)
        if 'expected_execution_budget' in body and current_budget != body['expected_execution_budget']:
            raise APIError('Execution budget changed in another client', 'budget_conflict', 409)
        if 'expected_permission_mode' in body and options['permission_mode']!=body['expected_permission_mode']:
            raise APIError('Permission mode changed in another client','permission_conflict',409)
        if current!=body['expected_profile']:
            raise APIError('Agent profile changed in another client','profile_conflict',409)
        runtime=session.runtime
        from localpilot_api.session_history import retain_child_routes
        child_contexts = retain_child_routes(session)
        tasks = [t for t in service.tasks.values() if t.session_id == session_id]
        previous_state = _profile_state(runtime, session, tasks)
        updated={**options,'agent_profile':body['agent_profile'],'permission_mode':desired_mode,'prompt_revision':2}
        if 'execution_budget' in body:
            updated['execution_budget'] = desired_budget
        if desired_mode in {'isolated','request','workspace','full'}:updated['scope_revision']=3
        if desired_toggle is not None:updated['thinking_toggle']=desired_toggle
        try:
            for task in tasks:
                task.execution_metadata={**(task.execution_metadata or {})}
                task.execution_metadata.setdefault('desktop_options',deepcopy(options))
            apply_options(runtime,updated)
            session.child_route_contexts = child_contexts or None
            session.desktop_options=updated
            session.base_prompt=runtime.base_prompt
            runtime._persistence_config=digest(dumps(configuration(runtime)))
            service._checkpoint(session_id,'desktop_profile_changed')
        except Exception:
            for owner, attributes in previous_state:
                for name, value in attributes.items():
                    setattr(owner, name, value)
            raise
        result=service.session_snapshot(session_id)
    server.access.audit(operation='desktop_profile_changed',subject=principal.subject,client_subject=subject,session_id=session_id,previous=current,agent_profile=updated['agent_profile'],previous_permission=options['permission_mode'],permission_mode=updated['permission_mode'],previous_budget=current_budget,execution_budget=desired_budget)
    return result



def _profile_state(runtime, session, tasks):
    from copy import deepcopy
    registry = runtime.registry
    gateway = registry.gateway
    state = [(runtime, {
        'messages': runtime.messages[:], 'prompt_profile': runtime.prompt_profile,
        'base_prompt': runtime.base_prompt, '_persistence_config': getattr(runtime, '_persistence_config', None),
        'budgets': runtime.budgets, 'registry': registry, 'permission_mode': runtime.permission_mode,
        'workspace': runtime.workspace, '_desktop_cloud_context': getattr(runtime, '_desktop_cloud_context', False),
    }), (session, {
        'base_prompt': session.base_prompt, 'desktop_options': session.desktop_options,
        'child_route_contexts': session.child_route_contexts,
    }), (registry, {
        'workspace_root': registry.workspace_root, 'authorization_guard': getattr(registry, 'authorization_guard', None),
        'scope_policy': deepcopy(getattr(registry, 'scope_policy', None)), '_tools': registry._tools.copy(),
        '_metadata': registry._metadata.copy(), '_extension_schemas': registry._extension_schemas[:],
        '_metadata_declared': registry._metadata_declared.copy(),
    }), (gateway, {
        'root': gateway.root, 'mode': gateway.mode, 'capabilities': gateway.capabilities, 'data_policy': gateway.data_policy,
    })]
    for backend in thinking_backends(runtime):
        attributes = {'capabilities': backend.capabilities, '_thinking_toggle': getattr(backend, '_thinking_toggle', False)}
        for name in ('model_info', 'profile'):
            if hasattr(backend, name):
                attributes[name] = getattr(backend, name)
        state.append((backend, attributes))
    if runtime.hybrid:
        state.append((runtime.hybrid, {'policy': runtime.hybrid.policy}))
    state.extend((task, {'execution_metadata': deepcopy(task.execution_metadata)}) for task in tasks)
    return state


from .session_migration import switch_model
