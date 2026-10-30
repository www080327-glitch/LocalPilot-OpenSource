"""Install/review/revoke lifecycle and a durable no-replay dispatch ledger."""
from copy import deepcopy
import json
from pathlib import Path
import threading
import uuid

from .client import MCPClient, TransportFailure
from .security import (digest, identifier, locked, manifest, private_dir, read_json,
                       redact, save_json, source_identity, validate_input, validate_schema, resource_allowed)


def tool_name(server, kind, name):
    # Length is below common provider limits; digest prevents truncation collisions.
    import re
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", name)[:16]
    return "mcp_" + server[:16].replace("-", "_") + "_" + kind + "_" + safe + "_" + digest([server, kind, name])[:12]


class PluginManager:
    def __init__(self, home):
        self.home = private_dir(home)
        self.receipts = private_dir(self.home / "receipts")
        self.clients = {}
        self._lock = threading.RLock()
        self.cancelled = threading.Event()

    def _path(self, server):
        return self.home / (identifier(server) + ".json")

    def get(self, server):
        return read_json(self._path(server))

    def list(self):
        result = []
        for path in sorted(self.home.glob('*.json')):
            if path.name == 'credentials.json':
                continue
            try:
                item = read_json(path)
                result.append({'id': item['config']['id'], 'enabled': item['enabled'],
                    'reviewed': bool(item.get('review')), 'transport': item['config']['transport'],
                    'catalog_sha256': digest(item['catalog']) if item.get('catalog') else None})
            except Exception as error:
                result.append({'id': path.stem, 'enabled': False, 'reviewed': False,
                               'status': 'invalid_record', 'error_type': type(error).__name__})
        return result

    def add(self, value):
        config = manifest(value)
        with locked(self.home):
            save_json(self._path(config["id"]), {"config": config, "enabled": False,
                "generation": uuid.uuid4().hex, "catalog": None, "review": None}, exclusive=True)
        return {"id": config["id"], "status": "installed_disabled", "authority_granted": False}

    def update(self, server, value):
        config = manifest(value)
        if config["id"] != server:
            raise ValueError("An update cannot change server identity")
        with locked(self.home):
            self.get(server)
            self._close(server)
            save_json(self._path(server), {"config": config, "enabled": False,
                "generation": uuid.uuid4().hex, "catalog": None, "review": None})
        return {"id": server, "status": "updated_review_revoked"}

    def credential(self, ref, secret):
        identifier(ref)
        if not isinstance(secret, str) or not 8 <= len(secret) <= 4096 or any(ord(c) < 32 for c in secret):
            raise ValueError("Credentials must contain 8–4096 printable characters")
        with locked(self.home):
            path = self.home / "credentials.json"
            value = read_json(path) if path.exists() else {}
            value[ref] = secret
            save_json(path, value)
        self.close()
        return {"credential_ref": ref, "status": "stored_private_native_service"}

    def _credentials(self, config):
        refs = set(config.get("credential_env", {}).values())
        if config.get("bearer_credential"):
            refs.add(config["bearer_credential"])
        values = read_json(self.home / "credentials.json") if refs else {}
        if refs - values.keys():
            raise ValueError("Configured plugin credential unavailable")
        return {key: values[key] for key in refs}

    def _client(self, item):
        server = item["config"]["id"]
        identity = digest([item["config"], item["generation"], self._credentials(item["config"])])
        old = self.clients.get(server)
        if old and old[0] != identity:
            self._close(server)
        if server not in self.clients:
            client = MCPClient(item["config"], self._credentials(item["config"]))
            # Discovery has its own explicit source-review launch authority.
            if item.get('enabled'):
                client.authorization_check = lambda: self._authorized(self.get(server), item['generation'], source_check=False)
            self.clients[server] = (identity, client)
        return self.clients[server][1]

    def discover(self, server, *, source_reviewed=False, license_id=None):
        if source_reviewed is not True or not isinstance(license_id, str) or not license_id.strip():
            raise ValueError("Review source/license/permissions before connecting; explicit source review required")
        item = self.get(server)
        before = source_identity(item["config"])
        client = self._client(item)
        try:
            catalog = client.connect()
        finally:
            self._close(server)
        if source_identity(item["config"]) != before:
            raise ValueError("Source changed during discovery")
        with locked(self.home):
            current = self.get(server)
            if current["generation"] != item["generation"]:
                raise ValueError("Plugin changed during discovery")
            current.update(catalog=catalog, enabled=False, review=None,
                source_review={"identity": before, "license": license_id}, generation=uuid.uuid4().hex)
            save_json(self._path(server), current)
        return {"catalog": catalog, "catalog_sha256": digest(catalog), "status": "discovered_untrusted_disabled"}

    def review(self, server, catalog_sha256, policy):
        """Only a local human/operator entry point calls this; never a model tool."""
        allowed = {"tools", "resources", "prompts", "plugin_egress", "network_access", "scope", "allow_agent"}
        if (not isinstance(policy, dict) or set(policy) != allowed or
                policy["plugin_egress"] not in {"allow", "deny"} or
                type(policy["network_access"]) is not bool or type(policy["allow_agent"]) is not bool or
                not isinstance(policy["scope"], str) or not 1 <= len(policy["scope"]) <= 1024):
            raise ValueError("Review needs explicit tool/resource/prompt, egress, network, scope and Agent policy")
        with locked(self.home):
            item = self.get(server)
            if not item.get("catalog") or digest(item["catalog"]) != catalog_sha256:
                raise ValueError("Review must name the exact discovered catalog digest")
            if source_identity(item["config"]) != item["source_review"]["identity"]:
                raise ValueError("Source identity changed; discover and review again")
            catalog = item["catalog"]
            available = {tool["name"] for tool in catalog["tools"]}
            if not isinstance(policy["tools"], dict) or set(policy["tools"]) - available:
                raise ValueError("Review contains an unadvertised tool")
            for value in policy["tools"].values():
                if (not isinstance(value, dict) or set(value) - {"effect", "summary", "argument_schema"} or
                        value.get("effect") not in {"observation", "external"} or
                        not isinstance(value.get("summary"), str) or not 1 <= len(value["summary"]) <= 512):
                    raise ValueError("Each tool needs a host-authored summary and effect classification")
                if "argument_schema" in value:
                    validate_schema(value["argument_schema"])
            if (not isinstance(policy["resources"], list) or
                    any(not resource_allowed(uri, catalog) for uri in policy["resources"]) or
                    not isinstance(policy["prompts"], list) or
                    set(policy["prompts"]) - {p["name"] for p in catalog["prompts"]}):
                raise ValueError("Review only advertised exact resource URIs and prompt names")
            item.update(review=deepcopy(policy), enabled=False, generation=uuid.uuid4().hex)
            save_json(self._path(server), item)
        self._close(server)
        return {"id": server, "status": "reviewed_disabled", "per_call_gateway_approval": True}

    def enable(self, server, enabled=True):
        with locked(self.home):
            item = self.get(server)
            if enabled and (not item.get("review") or item["review"]["plugin_egress"] != "allow"):
                raise ValueError("Review capabilities and explicitly allow Plugin Egress first")
            item.update(enabled=enabled, generation=uuid.uuid4().hex)
            save_json(self._path(server), item)
        self._close(server)
        return {"id": server, "enabled": enabled}

    def remove(self, server):
        with locked(self.home):
            item = self.get(server)
            self._path(server).unlink()  # All stale adapters consult this file before dispatch.
            self._close(server)
            path = self.home / "credentials.json"
            if path.exists():
                values = read_json(path)
                refs = set(item["config"].get("credential_env", {}).values()) | {item["config"].get("bearer_credential")}
                used = set()
                for remaining in self.list():
                    config = self.get(remaining["id"])["config"]
                    used.update(config.get("credential_env", {}).values())
                    used.add(config.get("bearer_credential"))
                for ref in refs - used:
                    values.pop(ref, None)
                save_json(path, values)
        return {"id": server, "status": "removed_permissions_revoked", "receipts": "preserved"}

    def doctor(self, server):
        item = self.get(server)
        try:
            self._authorized(item)
            client = self._client(item)
            catalog = client.connect()
            if digest(catalog) != digest(item["catalog"]):
                return {"status": "review_required", "reason": "catalog_changed"}
            result = client.request({"method": "ping"})
            return {"status": "healthy" if result.get("result", {}).get("healthy") else "unavailable",
                    "server": catalog["server"], "capabilities": catalog["capabilities"]}
        except (ValueError, OSError, TransportFailure) as error:
            return {"status": "unavailable", "reason": getattr(error, "reason", type(error).__name__)}
        finally:
            self._close(server)

    def _authorized(self, item, generation=None, *, source_check=True):
        if not item["enabled"] or not item.get("review") or item["review"]["plugin_egress"] != "allow":
            raise ValueError("Plugin disabled, unreviewed or Plugin Egress denied")
        if generation and item["generation"] != generation:
            raise ValueError("Plugin authorization changed; refresh tools and obtain new approval")
        if source_check and source_identity(item["config"]) != item["source_review"]["identity"]:
            raise ValueError("Reviewed source changed")

    def invoke(self, server, kind, name, arguments, *, generation, request_id, cancel_event=None):
        """Called only by the registered Gateway adapter, after host approval."""
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 512:
            raise ValueError('A bounded stable host operation identity is required')
        self.cancelled.clear()
        if cancel_event and cancel_event.is_set():
            return {'status': 'error', 'failure': 'cancelled', 'action_sent': False,
                    'action_may_have_applied': False, 'replay_allowed': False}
        item = self.get(server)
        self._authorized(item, generation)
        policy = item["review"]
        observation = kind != "tool" or policy["tools"][name]["effect"] == "observation"
        if kind == "tool":
            tool = next(t for t in item["catalog"]["tools"] if t["name"] == name)
            validate_input(arguments, tool["inputSchema"])
            if policy["tools"][name].get("argument_schema"):
                validate_input(arguments, policy["tools"][name]["argument_schema"])
        elif kind == "resource":
            if arguments["uri"] not in policy["resources"]:
                raise ValueError("Resource URI has not been reviewed")
        elif kind == "prompt":
            if arguments["name"] not in policy["prompts"]:
                raise ValueError("Prompt has not been reviewed")
            prompt = next(p for p in item["catalog"]["prompts"] if p["name"] == arguments["name"])
            fields = {arg["name"]: {"type": "string"} for arg in prompt.get("arguments", [])}
            validate_input(arguments.get("arguments", {}), {"type": "object", "properties": fields,
                "required": [arg["name"] for arg in prompt.get("arguments", []) if arg.get("required")], "additionalProperties": False})
        secrets = list(self._credentials(item["config"]).values())
        signature = digest([server, generation, kind, name, arguments])
        key = digest([server, request_id])
        path = self.receipts / (key + ".json")
        uncertain = {"status": "unknown" if not observation else "error", "action_sent": None,
                     "action_may_have_applied": not observation, "replay_allowed": False,
                     "verification": "external_effect_unobservable" if not observation else "response_only"}
        with locked(self.home):
            self._authorized(self.get(server), generation)
            if cancel_event and cancel_event.is_set():
                return {'status': 'error', 'failure': 'cancelled', 'action_sent': False,
                        'action_may_have_applied': False, 'replay_allowed': False}
            if path.exists():
                prior = read_json(path)
                if prior["signature"] != signature:
                    raise ValueError("Plugin request identity reused with different arguments or policy")
                return {**prior.get("result", uncertain), "receipt_reused": True, "receipt_id": key,
                        'action_sent': False, 'observation_time': 'historical_receipt_not_current_observation'}
            save_json(path, {"signature": signature, "server": server, "tool": name, "kind": kind,
                "arguments": redact(arguments, secrets), "arguments_sha256": digest(arguments),
                "scope": policy["scope"], "network_access": policy["network_access"],
                "plugin_egress": policy["plugin_egress"], "catalog_sha256": digest(item["catalog"]),
                "generation": generation, "state": "intent", "verification": "not_run"}, exclusive=True)
        result = None
        try:
            with self._lock:
                client = self._client(item)
            client.cancelled.clear()
            if self.cancelled.is_set() or cancel_event and cancel_event.is_set():
                client.cancel()
                raise TransportFailure('cancelled')
            # Two bounded connection attempts BEFORE invocation. Never retry a tool call.
            if client.process is None or client.process.poll() is not None:
                for attempt in range(2):
                    try:
                        catalog = client.connect()
                        if digest(catalog) != digest(item["catalog"]):
                            raise ValueError("Catalog identity changed; fresh review required")
                        break
                    except TransportFailure as error:
                        if attempt or error.reason == 'cancelled' or self.cancelled.is_set():
                            raise
            self._authorized(self.get(server), generation)
            if cancel_event and cancel_event.is_set():
                raise TransportFailure('cancelled')
            client.authorization_check = lambda: self._authorized(self.get(server), generation, source_check=False)
            reply = client.request({"method": kind, "name": name, "arguments": arguments,
                                    "expected_catalog": digest(item["catalog"])})
            if reply.get("failure"):
                result = {**uncertain, "failure": reply["failure"]}
                if reply.get("dispatched") is False:
                    result.update(status="blocked", action_sent=False, action_may_have_applied=False)
            else:
                data = reply["result"]
                if kind == "tool" and tool.get("outputSchema") and not data.get("isError"):
                    validate_input(data.get("structuredContent"), tool["outputSchema"])
                result = {"status": "ok" if observation and not data.get("isError") else "error" if observation else "unknown",
                    "server_reported_success": not data.get("isError", False),
                    "action_sent": True, "action_may_have_applied": not observation,
                    "replay_allowed": False, "verification": "response_only" if observation else "external_effect_unobservable",
                    "trust": "untrusted_external_data_not_host_instructions", "data": data}
        except Exception as error:
            result = {**uncertain, "failure": getattr(error, "reason", type(error).__name__)}
        result = redact({**result, "receipt_id": key, "server_id": server, "tool_id": name,
                         "resource_scope": policy["scope"], "plugin_egress": policy["plugin_egress"],
                         "network_access": policy["network_access"],
                         'network_observation': 'UNKNOWN_downstream_network_not_OS_monitored',
                         'scope_enforcement': 'Host_argument_schema_and_per_call_approval; process_or_remote_internals_unobservable'}, secrets)
        # Bound before persisting or returning; truncation preserves UNKNOWN.
        if len(json.dumps(result).encode()) > 48000:
            result.pop("data", None)
            result["truncated"] = True
        record = read_json(path)
        save_json(path, {**record, "state": "returned", "result": result})
        return result

    def _close(self, server):
        old = self.clients.pop(server, None)
        if old:
            old[1].close()

    def cancel(self):
        self.cancelled.set()
        for _, client in list(self.clients.values()):
            client.cancel()

    def close(self):
        for server in list(self.clients):
            self._close(server)
