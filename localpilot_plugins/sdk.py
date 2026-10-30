"""Public manifest SDK. Plugin code speaks MCP; it never imports Core internals.

These helpers build configuration only. They do not install, connect, grant
permissions, execute tools or provide a model-visible authorization interface.
"""
from dataclasses import dataclass, field
from pathlib import Path

from . import PROTOCOL_VERSION, SDK_VERSION
from .security import manifest


@dataclass(frozen=True)
class StdioPlugin:
    id: str
    command: str
    args: tuple = ()
    source_files: tuple = ()
    timeout: int = 15
    credential_env: dict = field(default_factory=dict)

    def to_manifest(self):
        value = {"id": self.id, "transport": "stdio", "command": self.command,
                 "args": list(self.args), "source_files": list(self.source_files), "timeout": self.timeout}
        if self.credential_env:
            value['credential_env'] = dict(self.credential_env)
        return manifest(value)


@dataclass(frozen=True)
class HTTPPlugin:
    id: str
    url: str
    bearer_credential: str | None = None
    timeout: int = 15

    def to_manifest(self):
        value = {"id": self.id, "transport": "streamable-http", "url": self.url, "timeout": self.timeout}
        if self.bearer_credential:
            value["bearer_credential"] = self.bearer_credential
        return manifest(value)


def write_manifest(spec, path):
    """Create a new reviewable manifest, without overwriting an existing file."""
    import json
    with Path(path).open("x", encoding="utf-8") as output:
        json.dump(spec.to_manifest(), output, ensure_ascii=False, indent=2)
        output.write("\n")


def review_policy(*, tools, resources=(), prompts=(), plugin_egress="deny",
                  network_access=True, scope, allow_agent=False):
    """Host-authored template; all tools still require per-call Gateway approval."""
    return {"tools": tools, "resources": list(resources), "prompts": list(prompts),
            "plugin_egress": plugin_egress, "network_access": network_access,
            "scope": scope, "allow_agent": allow_agent}
