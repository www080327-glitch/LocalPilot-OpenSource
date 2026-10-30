"""Local human/operator plugin and Skill management. Never exposed as Agent tools."""
import argparse
import json
from pathlib import Path
import sys

from .manager import PluginManager, tool_name


def document(path):
    with open(path, "rb") as source:
        value = source.read(262145)
    if len(value) > 262144:
        raise ValueError("Management input exceeds 256 KiB")
    return json.loads(value)


def main(argv, home):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    for name in ("add", "update"):
        p = sub.add_parser(name)
        p.add_argument("manifest", help="Explicit reviewed JSON manifest; never a package manager command")
    for name in ("remove", "enable", "disable", "show", "tools", "doctor"):
        p = sub.add_parser(name)
        p.add_argument("server")
    p = sub.add_parser("discover")
    p.add_argument("server")
    p.add_argument("--source-reviewed", action="store_true")
    p.add_argument("--license", required=True)
    p = sub.add_parser("review")
    p.add_argument("server")
    p.add_argument("--catalog-sha256", required=True)
    p.add_argument("--policy", required=True, help="Host-authored policy JSON")
    p = sub.add_parser("credential")
    p.add_argument("ref")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--stdin", action="store_true")
    group.add_argument("--private-file")
    p = sub.add_parser("call")
    p.add_argument("server")
    p.add_argument("--kind", choices=["tool", "resource", "prompt"], default="tool")
    p.add_argument("--tool", required=True, help="Original tool name, or read/get for resources/prompts")
    p.add_argument("--arguments", required=True, help="Path to JSON arguments")
    p.add_argument("--workspace", required=True)
    p.add_argument("--request-id", required=True, help="Stable operation identity; reuse for recovery")
    p.add_argument("--approve", action="store_true", help="Approve exactly these arguments after reviewing the Gateway preview")
    args = parser.parse_args(argv)
    manager = PluginManager(Path(home) / "plugins")
    try:
        action = args.action
        if action == "list":
            return {"plugins": manager.list()}
        if action in {"add", "update"}:
            value = document(args.manifest)
            return manager.add(value) if action == "add" else manager.update(value["id"], value)
        if action == "remove":
            return manager.remove(args.server)
        if action in {"enable", "disable"}:
            return manager.enable(args.server, action == "enable")
        if action in {"show", "tools"}:
            value = manager.get(args.server)
            # Credential references only; private credential store is never returned.
            return value if action == "show" else {"tools": (value.get("catalog") or {}).get("tools", []),
                "review": value.get("review"), "enabled": value["enabled"]}
        if action == "discover":
            return manager.discover(args.server, source_reviewed=args.source_reviewed, license_id=args.license)
        if action == "review":
            return manager.review(args.server, args.catalog_sha256, document(args.policy))
        if action == "doctor":
            return manager.doctor(args.server)
        if action == "credential":
            if args.private_file:
                import os
                import stat
                fd = os.open(args.private_file, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                        raise ValueError("Credential source must be an owner-only regular file")
                    secret = os.read(fd, 4098).decode().rstrip("\r\n")
                finally:
                    os.close(fd)
            else:
                secret = sys.stdin.read(4098).rstrip("\r\n")
            return manager.credential(args.ref, secret)
        if action == "call":
            from agent.registry import create_default_registry
            from .adapter import attach
            registry = create_default_registry(args.workspace, permission_mode="approve-all")
            registry.plugin_request_id = args.request_id
            attached = attach(registry, manager.home, agent=False)
            registry.plugin_request_id = args.request_id
            try:
                return registry.call(tool_name(args.server, args.kind, args.tool), document(args.arguments), approved=args.approve)
            finally:
                attached.close()
        raise ValueError("Unknown plugin operation")
    finally:
        manager.close()


def skills_main(argv, home):
    from .skills import SkillRegistry
    parser = argparse.ArgumentParser(description="Explicit reviewed project/user Skill registry")
    parser.add_argument("--project")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    for action in ("add", "update"):
        p = sub.add_parser(action)
        p.add_argument("bundle")
        p.add_argument("--scope", choices=["user", "project"], default="user")
    for action in ("show", "enable", "disable", "remove", "doctor"):
        p = sub.add_parser(action)
        p.add_argument("skill")
        p.add_argument("--scope", choices=["user", "project"], default="user")
        if action == "enable":
            p.add_argument("--reviewed-sha256", required=True)
        if action == "doctor":
            p.add_argument("--tools", default="", help="Comma separated available tool identities; diagnostic only")
    args = parser.parse_args(argv)
    registry = SkillRegistry(Path(home) / "skills", args.project)
    if args.action == "list":
        return {"skills": registry.list()}
    if args.action in {"add", "update"}:
        return registry.install(args.bundle, args.scope, replace=args.action == "update")
    if args.action == "show":
        return registry.get(args.skill, args.scope)
    if args.action in {"enable", "disable"}:
        return registry.enable(args.skill, args.scope, reviewed_sha256=getattr(args, "reviewed_sha256", None), enabled=args.action == "enable")
    if args.action == "remove":
        return registry.remove(args.skill, args.scope)
    if args.action == "doctor":
        try:
            registry.load(args.skill, args.scope, args.tools.split(","))
            return {"status": "healthy", "authority_granted": False}
        except (ValueError, OSError) as error:
            return {"status": "unavailable", "reason": str(error)}
