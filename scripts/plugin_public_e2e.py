"""Reviewed upstream MCP example qualification; isolated native home, public data.

Requires the four source-reviewed example packages from official SDK v1.26.0.
Run from the checkout with its plugins extra installed. No user config writes.
"""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

from agent.registry import create_default_registry
from agent.session import AgentSession, SessionState
from localpilot_plugins.adapter import attach
from localpilot_plugins.manager import PluginManager, tool_name
from localpilot_plugins.security import digest
from tests.test_runtime_session import ScriptBackend, call, response

PUBLIC_URL = "https://www.rfc-editor.org/rfc/rfc1149.txt"


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def qualify(destination):
    report = {"protocol": "2025-11-25", "upstream": "modelcontextprotocol/python-sdk@3d9d34552a9ab8988acf8d06e4a705bd799fc32b",
              "scope": "Four reviewed upstream example servers; no user accounts", "servers": [], "checks": {}}
    import hashlib
    report["source_sha256"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(Path("localpilot_plugins").glob("*.py"))}
    temp = tempfile.TemporaryDirectory(prefix="localpilot-public-e2e-")
    root = Path(temp.name).resolve()
    workspace = root / "workspace"
    workspace.mkdir()
    manager = PluginManager(root / "plugins")
    attached, http = None, None
    port = free_port()
    try:
        modules = {"fetch": "mcp_simple_tool", "resource": "mcp_simple_resource",
                   "prompt": "mcp_simple_prompt", "http": "mcp_simple_streamablehttp"}
        for server, module in modules.items():
            package = Path(importlib.util.find_spec(module).origin).parent
            files = [str(p) for p in package.glob("*.py")]
            config = {"id": server, "timeout": 12, "source_files": files}
            if server == "http":
                http = subprocess.Popen([sys.executable, "-m", module, "--port", str(port), "--log-level", "WARNING"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    env={"PATH": os.defpath, "HOME": str(root)}, start_new_session=True)
                for _ in range(100):
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=.1):
                            break
                    except OSError:
                        time.sleep(.05)
                config.update(transport="streamable-http", url=f"http://127.0.0.1:{port}/mcp/")
            else:
                config.update(transport="stdio", command=sys.executable, args=["-m", module])
            manager.add(config)
            discovered = manager.discover(server, source_reviewed=True, license_id="MIT")
            catalog = discovered["catalog"]
            policy = {"tools": {tool["name"]: {"effect": "observation", "summary": "Fetch the pinned public RFC 1149" if server == "fetch" else "Emit synthetic test notifications"}
                       for tool in catalog["tools"]},
                "resources": [r["uri"] for r in catalog["resources"]],
                "prompts": [p["name"] for p in catalog["prompts"]],
                "plugin_egress": "allow", "network_access": server in {"fetch", "http"},
                "scope": "Public RFC 1149 and fixed upstream synthetic examples only", "allow_agent": True}
            if server == "fetch":
                policy["tools"]["fetch"]["argument_schema"] = {"type": "object", "properties": {"url": {"const": PUBLIC_URL}},
                    "required": ["url"], "additionalProperties": False}
            manager.review(server, discovered["catalog_sha256"], policy)
            manager.enable(server)
            report["servers"].append({"id": server, "server_identity": catalog["server"],
                "capabilities": catalog["capabilities"], "tools": [t["name"] for t in catalog["tools"]],
                "resources": policy["resources"], "prompts": policy["prompts"],
                "catalog_sha256": digest(catalog), "health": manager.doctor(server)})
        registry = create_default_registry(workspace, permission_mode="approve-all")
        attached = attach(registry, manager.home)

        def invoke(server, kind, name, args, key):
            registry.plugin_request_id = key
            result = registry.call(tool_name(server, kind, name), args, approved=True)
            report["checks"][key] = result
            return result

        denied = registry.call(tool_name("fetch", "tool", "fetch"), {"url": PUBLIC_URL})
        report["checks"]["gateway_approval"] = {"status": "PASS" if denied["status"] == "approval_required" else "FAIL", "decision": denied["status"]}
        resource = invoke("resource", "resource", "read", {"uri": "file:///greeting.txt"}, "resource-read")
        prompt = invoke("prompt", "prompt", "get", {"name": "simple", "arguments": {"topic": "public MCP examples"}}, "prompt-read")
        fetch = invoke("fetch", "tool", "fetch", {"url": PUBLIC_URL}, "public-fetch")
        invoke("http", "tool", "start-notification-stream", {"interval": .01, "count": 2, "caller": "public-test"}, "http-sse-tool")
        attached.close()
        attached = attach(registry := create_default_registry(workspace, permission_mode="approve-all"), manager.home)
        invoke("resource", "resource", "read", {"uri": "file:///greeting.txt"}, "resource-after-restart")
        # This proves the actual Session -> approval -> Gateway -> MCP path;
        # scripted selection does NOT qualify autonomous model tool selection.
        backend = ScriptBackend(response(None, call(tool_name("resource", "resource", "read"), {"uri": "file:///greeting.txt"})), response("Read the sample greeting"))
        runtime = AgentSession(registry, backend=backend)
        runtime.run_turn("Read the public greeting resource")
        approval = runtime.state == SessionState.TOOL_AWAITING_APPROVAL
        runtime.approve()
        report["scripted_agent"] = {"selection": "SCRIPTED", "approval_required": approval,
            "receipts": runtime.tool_history, "autonomous_model_selection": "NOT_RUN"}
        runtime.close()
        manager.remove("resource")
        try:
            registry.call(tool_name("resource", "resource", "read"), {"uri": "file:///greeting.txt"}, approved=True)
            report["checks"]["uninstall_revocation"] = {"status": "FAIL"}
        except OSError:
            report["checks"]["uninstall_revocation"] = {"status": "PASS"}
        report["checks"]["independent_observation"] = {
            "resource_marker": "Hello! This is a sample text resource." in json.dumps(resource),
            "prompt_marker": "public MCP examples" in json.dumps(prompt),
            "public_rfc_marker": "1149" in json.dumps(fetch) and fetch.get("server_reported_success") is True}
        report["status"] = "PASS" if all(v.get("status") not in {"FAIL", "error", "unknown", "blocked"} for v in report["checks"].values()) and all(report["checks"]["independent_observation"].values()) else "FAIL"
    except Exception as error:
        report["status"] = "FAIL"
        report["error"] = {"type": type(error).__name__, "message": str(error)[:256]}
    finally:
        if attached:
            attached.close()
        manager.close()
        if http:
            http.terminate()
            try:
                http.wait(timeout=3)
            except subprocess.TimeoutExpired:
                http.kill()
                http.wait()
        temp.cleanup()
        Path(destination).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "report": str(destination)}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(qualify(sys.argv[1]))
