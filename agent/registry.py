"""One registry and gateway shared by Standard and Minimal profiles."""

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from functools import partial
import inspect
import json

from .commands import execute
from .patches import apply_patch
from .permissions import PermissionMode, ToolRiskMetadata
from .safety import PermissionGateway, READ_TOOLS, resolve_workspace_path
from .schemas import TOOL_SCHEMAS, FILE_SCHEMAS
from .profiles import TOOL_PROFILES
from .safe_files import list_entries, make_directory, move_file, copy_file, inspect_file
from .tools import file_info, list_directory, read_file, search_text
from .tool_protocol import validate_arguments

PROFILES = {
    "standard": "full",
    "minimal": "compact",
}


class ToolRegistry:
    def __init__(self, workspace_root, profile="standard", permission_mode="cautious", *,
                 tool_profile=None, capabilities=None, data_policy=None, judge=None,
                 plan_read_only=False):
        if profile not in PROFILES:
            raise ValueError(f"Unknown tool profile: {profile}")
        self.tool_profile = tool_profile or PROFILES[profile]
        if self.tool_profile not in TOOL_PROFILES:
            raise ValueError(f"Unknown tool profile: {self.tool_profile}")
        self.gateway = PermissionGateway(workspace_root, mode=permission_mode,
                                         capabilities=capabilities, data_policy=data_policy,
                                         judge=judge, plan_read_only=plan_read_only)
        self.workspace_root = self.gateway.root
        self.profile = profile
        self._tools = {}
        self._metadata = {}
        self._metadata_declared = {}
        self._extension_schemas = []
        self.read_cache = None  # Session-owned, bounded, host-only.
        self.last_read_receipt = None
        self._read_source = None
        self.last_dispatch_started = False

    def register(self, name, function, metadata=None, *, schema=None):
        reserved={'read_file':read_file,'list_directory':list_directory,'search_text':search_text,'file_info':file_info,
            'list_entries':list_entries,'inspect_file':inspect_file,'make_directory':make_directory,'move_file':move_file,'copy_file':copy_file,
            'apply_patch':apply_patch,'execute':execute}
        if name in reserved and (function.func if isinstance(function,partial) else function) is not reserved[name]:
            raise ValueError('Reserved built-in tool implementation cannot be replaced by an extension')
        if name in self._tools:
            raise ValueError(f"Tool is already registered: {name}")
        if metadata is not None and not isinstance(metadata, ToolRiskMetadata):
            raise TypeError("metadata must be ToolRiskMetadata")
        if schema is not None:
            if schema.get("function", {}).get("name") != name:
                raise ValueError("Extension schema must match the registered tool")
            self._extension_schemas.append(deepcopy(schema))
        self._tools[name] = function
        self._metadata[name] = metadata or ToolRiskMetadata()
        self._metadata_declared[name] = metadata is not None

    def metadata(self, name):
        name = "execute" if name == "run_command" else name
        try:
            return self._metadata[name]
        except KeyError as error:
            raise ValueError(f"Unknown tool: {name}") from error

    def validate_extension_arguments(self, name, arguments):
        """Owning validators run before AgentSession records any dispatch intent."""
        validator = getattr(self._tools.get(name), 'validate_arguments', None)
        if validator is not None:
            validator(arguments)

    def is_plugin_tool(self, name):
        if not getattr(self, 'plugin_manager', None):
            return False
        from localpilot_plugins.adapter import is_plugin_tool
        return is_plugin_tool(self, name)

    def call(self, name, arguments, *, approved=False, receipt_id=None, scope_approval=None):
        """Dispatch only host-registered tools; model arguments cannot change policy."""
        self.last_dispatch_started = False
        self.last_read_receipt = None
        self._read_source = receipt_id
        self.last_read_failure = None
        if not isinstance(approved, bool):
            raise TypeError("approved must be a host boolean")
        name = "execute" if name == "run_command" else name
        try:
            function = self._tools[name]
        except KeyError as error:
            raise ValueError(f"Unknown tool: {name}") from error
        if not isinstance(arguments, dict):
            raise TypeError("Tool arguments must be a dictionary.")
        if {"workspace_root", "gateway", "permission_mode", "approved"}.intersection(arguments):
            raise ValueError("Tool arguments cannot override workspace or permission policy.")
        from .scope_permissions import workspace_arguments
        arguments = workspace_arguments(self, name, arguments)
        validate_arguments(name, arguments, self.schemas())
        self.validate_extension_arguments(name, arguments)
        inspect.signature(function).bind(workspace_root=self.workspace_root, **arguments)
        from .scope_permissions import proposal, execute as scoped_execute
        request = proposal(self, name, arguments)
        if request:
            from .scope_permissions import automatic
            if scope_approval is None and automatic(self,name):scope_approval=request
            if scope_approval is not None:
                return scoped_execute(self, name, arguments, scope_approval, receipt_id)
            return {"status": "approval_required", "scope_request": request,
                "action_sent": False, "risk_summary": {"operation": name, "level": "low" if name in READ_TOOLS else "medium",
                "reasons": [request['reason']], "resource": {"targets": request['targets']}}}
        guard=getattr(self,"authorization_guard",None)
        with guard(name,arguments) if guard else nullcontext():
            with self.gateway.approving(name, approved):
                return self._invoke(name, function, arguments)

    def _invoke(self, name, function, arguments):
        if name in READ_TOOLS:
            resolve_workspace_path(self.workspace_root, arguments.get("path", "."),
                must_exist=not (name == 'file_info' and function is file_info or
                    name == 'read_file' and function is read_file and getattr(self, 'record_read_absence', False)))
            decision = self.gateway.decide(name, "low", ["Read-only workspace inspection."],
                                           {"path": arguments.get("path", ".")})
            if decision["status"] != "allowed":
                return self._bound_result(decision)
        elif name not in {"execute", "apply_patch"}:
            metadata = self.metadata(name)
            if not self._metadata_declared.get(name,False) and self.gateway.mode in {'assist-low-risk','assist-high-risk','full-permission'}:
                metadata=replace(metadata,requires_host_approval=True)
            host_constraint = getattr(function, "_requires_host_approval", None)
            if host_constraint is not None and host_constraint():
                metadata = replace(metadata, requires_host_approval=True)
            new_mode = self.gateway.mode in {mode.value for mode in PermissionMode}
            risk = ("high" if (metadata.potentially_destructive or metadata.external_side_effect or
                               metadata.requires_shell or metadata.network_access) else
                    "low" if (metadata.read_only and not metadata.mutating or name == "make_directory" and function is make_directory) else "medium") if new_mode else "medium"
            resource = {"tool": name, "arguments": arguments}
            resource_provider = getattr(function, 'permission_resource', None)
            if resource_provider is not None:
                resource = resource_provider(arguments)
            decision = self.gateway.decide(name, risk,
                ["Trusted host extension with declared read-only behavior." if risk == "low" else
                 "Trusted host extension with unclassified or mutating behavior."],
                resource, metadata=metadata)
            if decision["status"] != "allowed":
                return self._bound_result(decision)
        try:
            # Host observation: validation/authorization above cannot have invoked
            # the extension. Once entered, an exception is no proof of no effect.
            self.last_dispatch_started = True
            if name == "read_file" and function is read_file and self.read_cache is not None:
                # Authorization and containment above run even on cache hits.
                result, self.last_read_receipt = self.read_cache.read(
                    self.workspace_root, arguments["path"], function, self._bound_result, self._read_source)
            else:
                result = function(workspace_root=self.workspace_root, **arguments)
        except Exception as error:
            builtin = function.func if isinstance(function, partial) else function
            if name == 'apply_patch' and builtin is apply_patch and not self.gateway._patch_effect_started:
                self.last_dispatch_started = False
            if name == 'read_file' and function is read_file and type(error) is FileNotFoundError:
                # Only the authorized built-in read path can mint this fact.
                # It proves neither content/version nor task verification.
                self.last_read_failure = {'source': 'authorized_builtin_read_file',
                    'observation': 'target_not_found', 'path': arguments['path'],
                    'scope': 'failed read at observation time; no content or version evidence'}
            self.gateway.record({"operation": name, "status": "error", "error_type": type(error).__name__})
            raise
        self.gateway.record({"operation": name, "status": "reused" if self.last_read_receipt and self.last_read_receipt["reused"] else result.get("status", "ok") if isinstance(result, dict) else "ok"})
        return self._bound_result(result)

    def _bound_result(self, result):
        """Bound serialized tool data without hiding unsuccessful status."""
        limit = self.gateway.max_output_bytes
        encoded = json.dumps(result, ensure_ascii=False)
        if len(encoded.encode("utf-8")) <= limit:
            return result
        if isinstance(result, dict) and "status" in result:
            bounded = dict(result)
            for field in ("changes", "applied"):
                if field in bounded:
                    bounded[field] = [{key: value for key, value in item.items() if key != "diff"}
                                      for item in bounded[field]]
                    bounded["diffs_omitted"] = True
            if len(json.dumps(bounded, ensure_ascii=False).encode("utf-8")) <= limit:
                return bounded
        # Eightfold headroom also covers escaping control characters in previews.
        preview = encoded.encode("utf-8")[:limit // 8].decode("utf-8", errors="replace")
        bounded = {"status": result.get("status", "ok") if isinstance(result, dict) else "ok",
                   "truncated": True, "result_preview": preview}
        if isinstance(result, dict):
            for field in ("exit_code", "timeout_seconds", "action_sent", "action_may_have_applied",
                          "replay_allowed", "verification", "receipt_id", "server_id", "tool_id",
                          "trust", "server_reported_success", "stage", "verified"):
                if field in result:
                    bounded[field] = result[field]
            if "risk_summary" in result:
                risk = result["risk_summary"]
                bounded["risk_summary"] = {key: risk[key] for key in ("operation", "level", "permission_mode")}
                bounded["risk_summary"]["reasons"] = ["Result exceeded output limit; obtain focused evidence."]
        return bounded

    def schemas(self):
        schemas = deepcopy([schema for schema in TOOL_SCHEMAS + FILE_SCHEMAS if schema["function"]["name"] in self._tools] + self._extension_schemas)
        if self.tool_profile == "compact":
            # Remove prose only: names, types, required fields and constraints stay identical.
            def strip_descriptions(value):
                if isinstance(value, dict):
                    value.pop("description", None)
                    for child in value.values():
                        strip_descriptions(child)
                elif isinstance(value, list):
                    for child in value:
                        strip_descriptions(child)
            strip_descriptions(schemas)
        return schemas


def create_default_registry(workspace_root, profile="standard", permission_mode="cautious", *,
                            tool_profile=None, capabilities=None, data_policy=None, judge=None,
                            plan_read_only=False, file_operations=False):
    registry = ToolRegistry(workspace_root, profile=profile, permission_mode=permission_mode,
                            tool_profile=tool_profile, capabilities=capabilities, data_policy=data_policy,
                            judge=judge, plan_read_only=plan_read_only)
    functions = {"read_file": read_file, "list_directory": list_directory,
                 "search_text": search_text, "file_info": file_info,
                 "execute": partial(execute, gateway=registry.gateway),
                 "apply_patch": partial(apply_patch, gateway=registry.gateway)}
    if file_operations:
        functions.update(inspect_file=inspect_file,list_entries=list_entries,make_directory=make_directory,move_file=move_file,copy_file=copy_file)
    for name in functions:
        metadata = (ToolRiskMetadata(read_only=True, mutating=False) if name in READ_TOOLS else
                    ToolRiskMetadata(potentially_destructive=True, external_side_effect=True,
                                     network_access=True) if name == "execute" else
                    ToolRiskMetadata())
        registry.register(name, functions[name], metadata=metadata)
    return registry
