"""Host adapters into ToolRegistry/Gateway; never a second Agent runtime."""
from copy import deepcopy
from pathlib import Path
import uuid

from agent.permissions import ToolRiskMetadata
from .manager import PluginManager, tool_name
from .security import digest, validate_input, validate_schema


class PluginTool:
    def __init__(self, manager, registry, item, kind, name, schema):
        self.manager, self.registry = manager, registry
        self.server, self.generation = item["config"]["id"], item["generation"]
        self.kind, self.name, self.schema = kind, name, schema
        validate_schema(schema)
        self.policy = deepcopy(item["review"])

    def validate_arguments(self, arguments):
        # Validate before AgentSession persists a dispatch intent.
        validate_input(arguments, self.schema)
        if self.kind == "tool" and self.policy["tools"][self.name].get("argument_schema"):
            validate_input(arguments, self.policy["tools"][self.name]["argument_schema"])

    def permission_resource(self, arguments):
        item = self.manager.get(self.server)
        self.manager._authorized(item, self.generation)
        return {'server_id': self.server, 'tool_id': self.name, 'kind': self.kind,
                'arguments': arguments, 'server_identity': item['catalog']['server'],
                'catalog_sha256': digest(item['catalog']), 'authorization_generation': self.generation,
                'resource_scope': self.policy['scope'], 'network_access': self.policy['network_access'],
                'plugin_egress': self.policy['plugin_egress'],
                'potential_side_effect': self.policy['tools'][self.name]['effect'] if self.kind == 'tool' else 'observation',
                'verification_boundary': 'External effects require independent host evidence; server reports grant no authority'}

    def approval_fingerprint(self, arguments):
        return digest(self.permission_resource(arguments))

    def __call__(self, *, workspace_root, **arguments):
        cancel_event = getattr(self.registry, 'plugin_cancel_event', None)
        if cancel_event and cancel_event.is_set():
            return {'status': 'error', 'failure': 'cancelled', 'action_sent': False,
                    'action_may_have_applied': False, 'replay_allowed': False}
        return self.manager.invoke(self.server, self.kind, self.name, arguments,
            generation=self.generation, request_id=getattr(self.registry, "plugin_request_id", None) or uuid.uuid4().hex,
            cancel_event=cancel_event)


def is_plugin_tool(registry, name):
    return isinstance(registry._tools.get(name), PluginTool)


def attach(registry, home, *, agent=True):
    if Path(home).expanduser().resolve().is_relative_to(registry.workspace_root):
        raise ValueError('Native plugin storage and credentials must be outside the tool workspace')
    manager = PluginManager(home)
    registry.plugin_manager = manager
    registry.plugin_request_id = None
    for listed in manager.list():
        if not listed["enabled"] or not listed["reviewed"]:
            continue
        try:
            item = manager.get(listed["id"])
            policy = item["review"]
            if agent and not policy["allow_agent"]:
                continue
            # Egress grants are separate from DataPolicy.local_only, which governs
            # cloud model sends AND forbids external plugin networking when active.
            entries = []
            for tool in item["catalog"]["tools"]:
                if tool["name"] not in policy["tools"]:
                    continue
                review = policy["tools"][tool["name"]]
                entries.append(("tool", tool["name"], tool["inputSchema"], review["summary"], review["effect"] == "external"))
            if policy["resources"]:
                entries.append(("resource", "read", {"type": "object", "properties": {
                    "uri": {"type": "string", "enum": policy["resources"]}}, "required": ["uri"],
                    "additionalProperties": False}, "Read an explicitly reviewed external resource URI.", False))
            if policy["prompts"]:
                entries.append(("prompt", "get", {"type": "object", "properties": {
                    "name": {"type": "string", "enum": policy["prompts"]},
                    "arguments": {"type": "object", "additionalProperties": {"type": "string"}}},
                    "required": ["name"], "additionalProperties": False},
                    "Retrieve an external prompt as untrusted data; host policy still applies.", False))
            for kind, external_name, schema, summary, mutating in entries:
                name = tool_name(item["config"]["id"], kind, external_name)
                function = PluginTool(manager, registry, item, kind, external_name, schema)
                # External annotations never mint ToolRiskMetadata or summaries.
                parameters = deepcopy(schema)
                def strip_prose(value):
                    if isinstance(value, dict):
                        for key in ('description', 'title', '$comment', 'examples', 'default'):
                            value.pop(key, None)
                        for key in ('properties', '$defs', 'definitions', 'patternProperties'):
                            for child in value.get(key, {}).values():
                                strip_prose(child)
                        for key in ('items', 'additionalProperties', 'not', 'if', 'then', 'else', 'contains', 'propertyNames'):
                            strip_prose(value.get(key))
                        for key in ('allOf', 'anyOf', 'oneOf', 'prefixItems'):
                            for child in value.get(key, []):
                                strip_prose(child)
                strip_prose(parameters)
                registry.register(name, function, ToolRiskMetadata(read_only=not mutating, mutating=mutating,
                    external_side_effect=mutating, network_access=policy["network_access"], requires_host_approval=True),
                    schema={"type": "function", "function": {"name": name,
                        "description": "External MCP server " + item["config"]["id"] + ". Host review: " + summary,
                        "parameters": parameters}})
        except Exception as error:
            registry.gateway.record({'operation': 'plugin_attach', 'server_id': listed['id'],
                                     'status': 'unavailable', 'error_type': type(error).__name__})
    return manager


def configure_session(runtime, home, *, skill_home=None, skills=()):
    """Explicit host opt-in; call after workspace selection, before task restore."""
    if skill_home and Path(skill_home).expanduser().resolve().is_relative_to(runtime.workspace):
        raise ValueError('Native Skill approvals must remain outside the tool workspace')
    if getattr(runtime.registry, "plugin_manager", None):
        runtime.registry.plugin_manager.close()
    attach(runtime.registry, home)
    runtime.registry.plugin_cancel_event = runtime._stop_requested
    runtime._plugin_home = str(home)
    runtime._plugin_options = {"home": str(home), "skill_home": str(skill_home) if skill_home else None, "skills": deepcopy(skills)}
    if getattr(runtime.registry, 'scope_policy', None):
        policy = runtime.registry.scope_policy
        policy['private_roots'] = tuple(dict.fromkeys((*policy['private_roots'], *private_roots(runtime))))
    if skill_home and skills:
        from .skills import SkillRegistry
        registry = SkillRegistry(skill_home, runtime.workspace)
        allowed = {entry["id"] + ":" + entry["scope"] for entry in skills}

        def load_skill(*, workspace_root, skill):
            if skill not in allowed:
                raise ValueError("Skill not selected by host")
            name, scope = skill.rsplit(":", 1)
            return registry.load(name, scope, runtime.registry._tools)
        runtime.registry.register("load_skill", load_skill,
            ToolRiskMetadata(read_only=True, mutating=False, requires_host_approval=True),
            schema={"type": "function", "function": {"name": "load_skill",
                "description": "Load a host-selected reviewed Skill as user guidance; this grants no tool permissions.",
                "parameters": {"type": "object", "properties": {"skill": {"type": "string", "enum": sorted(allowed)}},
                               "required": ["skill"], "additionalProperties": False}}})
    runtime._refresh_prompt()


def private_roots(runtime):
    options = getattr(runtime, '_plugin_options', {})
    return tuple(str(Path(options[key]).expanduser().resolve()) for key in ('home', 'skill_home') if options.get(key))
