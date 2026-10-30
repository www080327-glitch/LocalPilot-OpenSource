"""Host-authorized settings on the existing AgentSession, persisted with the session."""
from localpilot_api.service import APIError
import hashlib,json,re
MODES = {"isolated":"approve-all", "request":"approve-mutations", "workspace":"workspace-auto", "ask":"approve-all", "safe":"assist-low-risk", "uncertain":"assist-high-risk", "full":"full-permission"}

def apply_options(runtime, options):
    if not isinstance(options, dict) or set(options)-{"permission_mode","agent_profile","context_length","prompt_revision","workspace_grant","scope_revision"} or not {"permission_mode","agent_profile"}<=set(options) or options["permission_mode"] not in MODES or options["agent_profile"] not in {"standard","minimal"} or type(options.get('prompt_revision',1)) is not int or options.get('prompt_revision',1) not in {1,2}:
        raise APIError("Unsupported Desktop session settings")
    if "workspace_grant" in options and (not isinstance(options["workspace_grant"],str) or not re.fullmatch(r"grant_[0-9a-f]{32}",options["workspace_grant"])):
        raise APIError("Invalid folder authorization identity")
    if options.get("workspace_grant"):
        runtime._workspace_grants.bind(runtime,options["workspace_grant"])
    runtime.permission_mode=runtime.registry.gateway.mode=MODES[options["permission_mode"]]
    if options.get("scope_revision") not in {None, 1, 2}:raise APIError("Unsupported file scope revision")
    if options["permission_mode"] in {"isolated", "request", "workspace"} or options.get("scope_revision") in {1,2}:
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
        if options.get('scope_revision')==2:
            from agent.host_tools import register
            register(runtime.registry,options['permission_mode'],private_roots)
    from agent.profiles import prompt_text
    runtime.prompt_profile=("minimal_agent_v2" if options.get('prompt_revision',1)==2 else "minimal_0") if options["agent_profile"]=="minimal" else "standard"
    runtime.base_prompt=prompt_text(runtime.prompt_profile)
    # Only called for a newly constructed host Session or before restoring it.
    runtime.messages=[m for m in runtime.messages if m.role!='system']
    context=options.get('context_length')
    if context is not None:
        if type(context) is not int or not 1024<=context<=262144:raise APIError('Invalid negotiated local context')
        from dataclasses import replace
        backend=runtime.current_backend
        backend.model_info=replace(backend.model_info,effective_context=context)
        if hasattr(backend,'profile'):backend.profile=replace(backend.profile,configured_context=context)
    runtime._refresh_prompt()

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
        for session in server.service.sessions.values():
            if session.desktop_key==identity:
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
    options['prompt_revision']=2
    if options.get('permission_mode') in {'isolated','request','workspace','full'}:options['scope_revision']=2
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
    if not isinstance(body,dict) or set(body)!={'client_subject','agent_profile','expected_profile'} or not isinstance(body['agent_profile'],str) or not isinstance(body['expected_profile'],str) or body['agent_profile'] not in {'standard','minimal'} or body['expected_profile'] not in {'standard','minimal'}:
        raise APIError('Exact Agent profile selection required')
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
            raise APIError('Finish or stop the active task before switching','session_busy',409)
        current=options['agent_profile']
        if current==body['agent_profile'] and options.get('prompt_revision')==2:
            return service.session_snapshot(session_id)
        if current!=body['expected_profile']:
            raise APIError('Agent profile changed in another client','profile_conflict',409)
        runtime=session.runtime
        old=(runtime.messages[:],runtime.prompt_profile,runtime.base_prompt,getattr(runtime,'_persistence_config',None),session.base_prompt)
        metadata={t.id:deepcopy(t.execution_metadata) for t in service.tasks.values() if t.session_id==session_id}
        updated={**options,'agent_profile':body['agent_profile'],'prompt_revision':2}
        try:
            for tid in metadata:
                task=service.tasks[tid]
                task.execution_metadata={**(task.execution_metadata or {})}
                task.execution_metadata.setdefault('desktop_options',deepcopy(options))
            apply_options(runtime,updated)
            session.desktop_options=updated
            session.base_prompt=runtime.base_prompt
            runtime._persistence_config=digest(dumps(configuration(runtime)))
            service._checkpoint(session_id,'desktop_profile_changed')
        except Exception:
            runtime.messages,runtime.prompt_profile,runtime.base_prompt,runtime._persistence_config,session.base_prompt=old
            session.desktop_options=options
            for tid,value in metadata.items():service.tasks[tid].execution_metadata=value
            raise
        result=service.session_snapshot(session_id)
    server.access.audit(operation='desktop_profile_changed',subject=principal.subject,client_subject=subject,session_id=session_id,previous=current,agent_profile=updated['agent_profile'])
    return result
