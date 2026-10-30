"""Host-only configuration to existing Registry, Gateway, Backend and Session."""
import os
import hashlib
import json
from pathlib import Path

from agent.backends import LocalBackend
from agent.hybrid import CloudEgressPolicy, HybridPolicy
from agent.policy import DataPolicy
from agent.registry import create_default_registry, ToolRegistry
from agent.retry import RetryPolicy
from agent.safety import CapabilityPolicy
from agent.session import AgentSession, SessionBudgets
from localpilot_api.service import TaskService
from .security import AccessPolicy, Principal, private_json
from .server import ServiceServer
from .backend_contract import ServiceDeepSeekBackend, ServiceDeepSeekOptimizedBackend, ServiceDeepSeekNativeBackend, ServiceOpenAIBackend, ServiceOMLXBackend, ServiceVLLMBackend, ManagedLocalBackend, generation_options
from .verification import configured_verifier, configured_execution_check


def build(config_path):
    config = private_json(config_path)
    if config.get("schema_version") != 1 or set(config) - {"schema_version", "host", "port", "data_dir", "log_dir", "clients", "routes", "max_sessions", "max_tasks", "max_handlers", "restore_path_migration"}:
        raise ValueError("Unsupported service configuration schema")
    data = Path(config["data_dir"]).expanduser().resolve()
    logs = Path(config.get("log_dir", str(data / "logs"))).expanduser().resolve()
    for folder in (data, logs):
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        if folder.stat().st_uid != os.getuid() or folder.stat().st_mode & 0o077:
            raise ValueError("Service data/log directories must be private to the operator")
    from .workspaces import WorkspaceGrants
    workspace_grants=WorkspaceGrants(data/"workspace-grants.json",(data,logs,Path(config_path).parent))
    principals = []
    for value in config["clients"]:
        value = dict(value)
        env = value.pop("token_env")
        value["token"] = os.environ.get(env, "")
        value["scopes"] = frozenset(value.get("scopes", ["submit", "read", "cancel"]))
        value["approval_for"] = tuple(value.get("approval_for", ()))
        principals.append(Principal(**value))
    routes, catalog, model_hosts = {}, {}, {}
    managed_profiles = {}
    for name, spec in config["routes"].items():
        if set(spec) - {"workspace", "backend", "permissions", "capabilities", "budgets", "cloud_egress", "cloud_egress_paths", "thinking", "deployment_status", "verification", "acceptance", "strict_task", "cache_stable_prefix", "prompt_profile", "tool_profile", "reasoning_only", "managed_local_model", "engine", "routing_rank", "cooperation", "plugins", "computer_use"}:
            raise ValueError("Unsupported route parameters")
        workspace = Path(spec["workspace"]).expanduser().resolve(strict=True)
        if data.is_relative_to(workspace) or logs.is_relative_to(workspace):
            raise ValueError("Private service data and logs must be outside every tool workspace")
        backend_spec = spec["backend"]
        engine = spec.get('engine', 'legacy')
        if engine not in {'legacy', 'v5'}: raise ValueError('Unknown internal agent engine')
        kind = backend_spec["kind"]
        if kind not in {"vllm", "remote-vllm", "omlx", "local-openai", "deepseek", "deepseek-native", "remote-openai", "unavailable"}:
            raise ValueError("Unknown backend adapter")
        allowed = {"kind", "model", "base_url", "context_budget", "timeout", "api_key_env", "key_file", "capabilities", "reasoning_efforts", "generation_parameters"}
        if kind in {"vllm", "remote-vllm", "omlx", "local-openai", "remote-openai"}:
            allowed.update({"include_stream_usage", "chat_template_kwargs"})
        if kind == "deepseek":
            allowed.add("agent_engine")
        if set(backend_spec) - allowed:
            raise ValueError("Unsupported backend configuration")
        if backend_spec.get("agent_engine", "legacy") not in {"legacy", "deepseek_optimized"}:
            raise ValueError("Unknown agent engine")
        if type(backend_spec.get("include_stream_usage", False)) is not bool:
            raise ValueError("include_stream_usage must be a boolean host option")
        generation_options(backend_spec.get("generation_parameters", {}))
        cloud = kind in {"deepseek", "deepseek-native", "remote-openai", "remote-vllm"}
        cooperation=spec.get('cooperation')
        partner=None
        cooperative_policy=None
        cooperative_profiles=None
        if cooperation is not None:
            if (not isinstance(cooperation,dict) or set(cooperation)-{'cloud_route','optimizer','profiles'} or 'cloud_route' not in cooperation
                    or kind not in {'omlx','vllm','local-openai'} or spec.get('managed_local_model')):
                raise ValueError('Cooperation requires a registered local primary and exact cloud_route')
            if 'optimizer' in cooperation:
                from agent.cooperative import CooperativePolicy
                cooperative_policy=CooperativePolicy(**cooperation['optimizer'])
                cooperative_profiles=cooperation.get('profiles')
            elif kind!='omlx' or set(cooperation)!={'cloud_route'}:
                raise ValueError('Legacy cooperation requires its existing oMLX contract')
            partner=config['routes'].get(cooperation['cloud_route'])
            if not partner or partner['backend']['kind'] not in {'deepseek','deepseek-native'} or Path(partner['workspace']).expanduser().resolve()!=workspace:
                raise ValueError('Cooperation partner must be a registered DeepSeek provider in the same workspace')
            partner={**partner['backend'],'_host_thinking':partner.get('thinking')}
        egress = spec.get("cloud_egress", "REQUIRES_APPROVAL" if cloud or partner else "LOCAL_ONLY")
        if not cloud and not partner and egress != "LOCAL_ONLY":
            raise ValueError("Local route must retain LOCAL_ONLY egress")
        model_host = None
        if spec.get("managed_local_model") is not None:
            from .cached_omlx import CachedOmlxHost, MODEL
            profile=spec["managed_local_model"]
            if kind!="local-openai" or backend_spec.get("model")!=MODEL or "api_key_env" in backend_spec:
                raise ValueError("Managed cached model requires its exact local backend without client credentials")
            expected="http://127.0.0.1:"+str(profile.get("port",8048))+"/v1"
            if backend_spec.get("base_url")!=expected:
                raise ValueError("Managed model must use its direct numeric loopback origin")
            identity=hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()
            if identity not in managed_profiles:
                managed_profiles[identity]=CachedOmlxHost(profile,data/"managed-models"/identity[:16])
            model_host=managed_profiles[identity]
            model_hosts[name]=model_host
        if cooperative_policy and spec.get('computer_use'):
            raise ValueError('Experimental cooperative routing is not qualified for Computer Use')
        if partner and egress!='REQUIRES_APPROVAL' and not (cooperative_policy and egress=='CLOUD_ALLOWED'):
            raise ValueError('Cooperation requires an explicit host cloud-egress grant')
        hard_policy = DataPolicy(local_only=not (cloud or partner))
        budget = SessionBudgets(**spec.get("budgets", {}))
        capability_values = spec.get("capabilities", {})
        if (not isinstance(capability_values, dict) or set(capability_values) - {"read", "write", "execute", "read_only"}
                or any(type(v) is not bool for v in capability_values.values())):
            raise ValueError("Tool capabilities must be explicit boolean host grants")
        capabilities = CapabilityPolicy(**capability_values)
        permission = spec.get("permissions", "approve-mutations")
        prompt_profile = spec.get("prompt_profile", "standard")
        tool_profile = spec.get("tool_profile", "full")
        reasoning_only = spec.get("reasoning_only", False)
        plugins = spec.get('plugins')
        if plugins is not None:
            if (reasoning_only or not isinstance(plugins, dict) or set(plugins)-{'home', 'skill_home', 'skills'}
                    or not isinstance(plugins.get('home'), str) or not Path(plugins['home']).is_absolute()):
                raise ValueError('Plugin configuration requires an explicit absolute private home on a tool-enabled route')
            for private in (plugins['home'], plugins.get('skill_home')):
                if private and (not Path(private).is_absolute() or Path(private).resolve().is_relative_to(workspace)):
                    raise ValueError('Native plugin/credential and user Skill storage must stay outside the tool workspace')
            if not isinstance(plugins.get('skills', []), list) or any(not isinstance(entry, dict) or
                    set(entry)!={'id','scope'} or entry['scope'] not in {'user','project'} for entry in plugins.get('skills', [])):
                raise ValueError('Host must explicitly select Skill identifiers and scopes')
        if prompt_profile not in {"standard", "minimal_0", "minimal_1"} or tool_profile not in {"full", "compact"} or type(reasoning_only) is not bool:
            raise ValueError("Invalid host prompt/tool/reasoning profile")
        if reasoning_only and (capabilities.read or capabilities.write or capabilities.execute):
            raise ValueError("Reasoning-only routes cannot grant tool capabilities")
        cache_stable_prefix = spec.get("cache_stable_prefix", False)
        if type(cache_stable_prefix) is not bool:
            raise ValueError("cache_stable_prefix must be a host boolean")
        computer_config = spec.get('computer_use')
        if computer_config is not None:
            if engine != 'v5' or partner or reasoning_only:
                raise ValueError('Computer Use requires V5, tools, and one inference backend')
            if not isinstance(computer_config,dict) or not Path(computer_config.get('evidence_directory','')).expanduser().resolve().is_relative_to(data):
                raise ValueError('Computer evidence must stay inside protected private service data')
        verification = spec.get("verification")
        verifier = configured_verifier(workspace, verification)
        strict_task = spec.get('strict_task', False)
        if type(strict_task) is not bool:
            raise ValueError('strict_task must be a host boolean')
        if spec.get('acceptance') is not None:
            from agent.acceptance import HostPythonAcceptance
            acceptance = spec['acceptance']
            if verification is not None or not isinstance(acceptance, dict) or set(acceptance) - {'assertions', 'outputs', 'required_line', 'timeout'}:
                raise ValueError('Use one host acceptance contract')
            verifier = HostPythonAcceptance(workspace, **acceptance)
            if any(verifier.assertions.is_relative_to(Path(other['workspace']).expanduser().resolve()) for other in config['routes'].values()):
                raise ValueError('Host assertions must be outside every Agent workspace')
            strict_task = True
        if permission not in {"approve-all", "approve-mutations"}:
            raise ValueError("Packaged service requires host approval for mutations")
        def factory(callback, b=dict(backend_spec), w=workspace, p=permission, cap=capabilities,
                    dp=hard_policy, budgets=budget, is_cloud=cloud, ep=egress,
                    paths=tuple(spec.get("cloud_egress_paths", ())), thinking=spec.get("thinking"),
                    verification=verification, verifier=verifier, cache_stable_prefix=cache_stable_prefix,
                    prompt_profile=prompt_profile, tool_profile=tool_profile, reasoning_only=reasoning_only, model_host=model_host, engine=engine, partner=partner,
                    strict_task=strict_task, plugins=plugins, computer_config=computer_config,
                    cooperative_policy=cooperative_policy, cooperative_profiles=cooperative_profiles):
            kind = b["kind"]
            if kind == "unavailable":
                backend = LocalBackend(b.get("model", "not-deployed"))
            elif kind in {"deepseek", "deepseek-native"}:
                backend_type = ServiceDeepSeekNativeBackend if kind == 'deepseek-native' else ServiceDeepSeekOptimizedBackend if b.get("agent_engine") == "deepseek_optimized" else ServiceDeepSeekBackend
                backend = backend_type(model=b["model"], key_file=b.get("key_file"),
                    api_key=os.environ.get(b["api_key_env"]) if b.get("api_key_env") else None,
                    base_url=b.get("base_url", "https://api.deepseek.com/anthropic" if kind == 'deepseek-native' else "https://api.deepseek.com"),
                    effective_context=b.get("context_budget", 131072), timeout=b.get("timeout", 30), data_policy=dp,
                    generation_parameters=b.get("generation_parameters"))
            else:
                bc = b.get("capabilities", {})
                key = os.environ.get(b["api_key_env"]) if b.get("api_key_env") else None
                if kind in {"remote-openai", "remote-vllm"} and (not key or not b["base_url"].startswith("https://")):
                    raise ValueError("Remote inference requires HTTPS and an explicit API token")
                backend_type = ManagedLocalBackend if model_host else ServiceVLLMBackend if kind in {'vllm','remote-vllm'} else ServiceOMLXBackend if kind == 'omlx' else ServiceOpenAIBackend
                backend = backend_type(**({"manager":model_host} if model_host else {"api_key":key}), base_url=b["base_url"], model=b["model"],
                    effective_context=b.get("context_budget", 131072), timeout=b.get("timeout", 30),
                    allow_remote=kind in {"remote-openai","remote-vllm"},
                    supports_tool_calling=bc.get("tool_calling", kind not in {'vllm','remote-vllm'}), supports_streaming=bc.get("streaming", True),
                    supports_vision=bc.get("vision", False),
                    supports_reasoning=bc.get("reasoning"), reasoning_efforts=b.get("reasoning_efforts", ()),
                    include_stream_usage=b.get("include_stream_usage", kind in {'omlx', 'vllm', 'remote-vllm'}),
                    chat_template_kwargs=b.get("chat_template_kwargs"),
                    generation_parameters=b.get("generation_parameters"))
                backend.is_local = not is_cloud
            if model_host and hasattr(backend,"service_contract"):
                backend.service_contract["managed_local_model"]={"model":model_host.status()["model"],"revision":model_host.status()["revision"],"idle_seconds":model_host.idle,"memory_bytes":model_host.memory}
            if reasoning_only:
                backend.service_reasoning_only = True
                if hasattr(backend, "service_contract"):
                    backend.service_contract["reasoning_only"] = True
            if cache_stable_prefix:
                backend.service_cache_stable_prefix = True
                if hasattr(backend, "service_contract"):
                    backend.service_contract["cache_stable_prefix"] = True
                    backend.service_contract["cache_layout_version"] = 1
                    backend.service_contract["system_prompt_update"] = "in-history" if getattr(backend, "supports_in_history_system_prompt", False) else "replace"
            if verification is not None and hasattr(backend, "service_contract"):
                backend.service_contract["host_verification"] = verification
            registry = (ToolRegistry if reasoning_only else create_default_registry)(w, permission_mode=p, capabilities=cap, data_policy=dp, tool_profile=tool_profile)
            from agent.engine_v5 import EngineV5Policy
            secondary=None
            if partner:
                cls=ServiceDeepSeekNativeBackend if partner['kind']=='deepseek-native' else ServiceDeepSeekBackend
                secondary=cls(model=partner['model'],key_file=partner.get('key_file'),
                    api_key=os.environ.get(partner['api_key_env']) if partner.get('api_key_env') else None,
                    base_url=partner.get('base_url','https://api.deepseek.com/anthropic' if partner['kind']=='deepseek-native' else 'https://api.deepseek.com'),
                    effective_context=partner.get('context_budget',131072),timeout=partner.get('timeout',45),data_policy=dp,
                    generation_parameters=partner.get('generation_parameters'))
                if partner.get('_host_thinking') is not None:
                    from dataclasses import replace
                    if partner['_host_thinking'] not in secondary.capabilities.supported_thinking_efforts:raise ValueError('Partner thinking is unsupported')
                    secondary.capabilities=replace(secondary.capabilities,default_thinking_effort=partner['_host_thinking'])
                    secondary.service_contract['default_thinking']=partner['_host_thinking']
            computer = None
            if computer_config is not None:
                registry=ToolRegistry(w,permission_mode=p,capabilities=cap,data_policy=dp,tool_profile=tool_profile)
                from computer.native_macos import configured_native_runtime
                computer = configured_native_runtime(computer_config, cloud_egress=CloudEgressPolicy(ep, paths))
            session_verifier=verifier
            execution_check=(verifier.execution_check if hasattr(verifier, 'execution_check') else configured_execution_check(w,verification)) if engine=='v5' else None
            if computer and computer.completion_conditions:
                old_verifier=session_verifier; old_execution=execution_check
                def session_verifier(root,result,_old=old_verifier,_computer=computer):
                    ui=_computer.host_verification(root,result)
                    return _old(root,result) if ui.status=='passed' and _old else ui
                def execution_check(root,projection,_old=old_execution,_computer=computer):
                    ui=_computer.host_verification(root)
                    return _old(root,projection) if ui.status=='passed' and _old else ui
            runtime = AgentSession(registry, cloud_backend=secondary or (backend if is_cloud else None),
                local_backend=None if is_cloud else backend, data_policy=dp,
                policy=cooperative_policy.mode if cooperative_policy else "local-first" if partner else "cloud-only" if is_cloud else "local-only", thinking=thinking, budgets=budgets,
                prompt_profile=prompt_profile, runtime_tools=not reasoning_only,
                computer_runtime=computer,
                hybrid_policy=HybridPolicy(CloudEgressPolicy(ep, paths), automatic_failover=bool(cooperative_policy and cooperative_policy.mode not in {'local-only','cloud-only'})) if computer is None else None,
                hybrid_backends={"selected": backend, **({'cloud':secondary} if secondary else {})} if computer is None else None, hybrid_primary="selected" if computer is None else None,
                cooperative_policy=cooperative_policy, cooperative_profiles=cooperative_profiles,
                engine_policy=EngineV5Policy() if engine == 'v5' else None,
                strict_task=strict_task, completion_check=execution_check,
                event_callback=callback, retry_policy=RetryPolicy(max_attempts=2 if engine == 'v5' or b.get("agent_engine") == "deepseek_optimized" else 1), verification_callback=session_verifier)
            runtime._workspace_grants=workspace_grants
            if plugins is not None:
                from localpilot_plugins.adapter import configure_session
                configure_session(runtime, **plugins)
            return runtime
        routes[name] = factory
        bc = backend_spec.get("capabilities", {})
        ranking = spec.get('routing_rank', {})
        if not isinstance(ranking, dict) or set(ranking)-{'speed','quality','efficiency','balanced'} or any(type(v) is not int or not 0<=v<=100 for v in ranking.values()):
            raise ValueError('routing_rank must contain bounded host priority integers')
        catalog[name] = {"model": backend_spec.get("model", "UNKNOWN"), "adapter": kind,
            "deployment_status": spec.get("deployment_status", "not_deployed" if kind == "unavailable" else "ready"),
            "capabilities": [k for k,v in bc.items() if v] if bc else ["tool_calling", "streaming"] if kind != "unavailable" else [],
            "context_budget": backend_spec.get("context_budget", 131072),
            "provenance": "operator_configuration_not_live_health", "cloud_egress": egress, "cache_stable_prefix":cache_stable_prefix, "prompt_profile":prompt_profile, "tool_profile":tool_profile, "reasoning_only":reasoning_only,
            "routing_rank": ranking, "agent_engine":engine, "thinking":spec.get('thinking'),
            "cloud_egress_paths":list(spec.get('cloud_egress_paths',())),
            "tool_capabilities":capability_values,"workspace":str(workspace),"permission_mode":permission,"budgets":spec.get("budgets",{}),
            "reasoning_efforts":[], "thinking_scope":"host_route_configuration"}
        if kind in {'vllm','remote-vllm'}:
            catalog[name]['capabilities']=[key for key,enabled in {
                'streaming':bc.get('streaming',True),'tool_calling':bc.get('tool_calling',False),
                'reasoning':bc.get('reasoning',False)}.items() if enabled]
        if reasoning_only:catalog[name]['capabilities']=[c for c in catalog[name]['capabilities'] if c!='tool_calling']
    for manager in set(model_hosts.values()):
        names={name for name,host in model_hosts.items() if host is manager}
        owners={p.subject for p in principals if not p.operator and set(p.routes.values()) & names}
        if len(owners)!=1:raise ValueError("Managed model pools require one ordinary client namespace")
    # Validate host route/capability configuration before accepting any task.
    # Construction performs no inference or model loading.
    model_backends = {}
    for route_name, factory in routes.items():
        if catalog[route_name]["adapter"] == "unavailable":
            continue  # Deliberately undeployed routes remain valid registry entries.
        try:
            probe = factory(lambda event: None)
            if catalog[route_name]['adapter'] == 'omlx':
                model_backends[route_name] = probe.current_backend
            catalog[route_name]['reasoning_efforts']=list(probe.current_backend.capabilities.supported_thinking_efforts)
            if catalog[route_name]['adapter']=='omlx':
                observed=probe.current_backend.thinking_toggle_observation()
                if observed['supported']:
                    catalog[route_name].update(reasoning_efforts=['none','high'],reasoning_toggle=observed,
                        default_reasoning_effort='high' if observed['default'] else 'none')
                    if 'reasoning' not in catalog[route_name]['capabilities']:catalog[route_name]['capabilities'].append('reasoning')
            catalog[route_name]['thinking_scope']='session' if catalog[route_name]['reasoning_efforts'] else 'host_route_configuration'
            probe.close()
        except Exception as exc:
            raise ValueError("Invalid route configuration for " + route_name + ": " + type(exc).__name__) from exc
    access = AccessPolicy(principals, audit_path=logs / "audit.jsonl")
    service = None
    documents = None
    try:
        from .documents import DocumentEngine
        documents = DocumentEngine(data / 'documents-v2')
        from .restore_migration import path_migration
        service = TaskService(routes, persistence=data / "runtime.sqlite3", auto_resume=False,
            configuration_migration=path_migration(config.get('restore_path_migration')),
            session_initializer=documents.initialize_session,
            resource_finalizer=documents.close,
            max_sessions=config.get("max_sessions", 64), max_tasks=config.get("max_tasks", 512))
        service.documents = documents
        server = ServiceServer((config.get("host", "127.0.0.1"), config.get("port", 8765)), service,
                              access=access, catalog=catalog, max_handlers=config.get("max_handlers", 32))
        server.workspace_grants=workspace_grants
        server.model_hosts=model_hosts
        server.model_backends=model_backends
        from .model_resources import ModelResources
        server.model_resources=ModelResources(server,data/'model-resource-operations.json')
        server.resources.set_path(data/"resource-control.json")
        return server
    except BaseException:
        if service:
            service.suspend()
        if documents:
            documents.close()
        access.close()
        raise
