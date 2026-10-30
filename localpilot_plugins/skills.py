"""Explicit Skill bundles: skill.json + SKILL.md, never arbitrary Markdown scans."""
from pathlib import Path
import re

from .security import digest, identifier, locked, private_dir, read_json, save_json

MAX_SKILL = 32768


def parse_bundle(path):
    import json
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version
    path = Path(path).expanduser().absolute()
    if any(p.is_symlink() for p in (path, path / "skill.json", path / "SKILL.md")):
        raise ValueError("Skill bundle symlinks are not allowed")
    with (path / "skill.json").open('rb') as source:
        raw = source.read(MAX_SKILL + 1)
    with (path / "SKILL.md").open('rb') as source:
        text = source.read(MAX_SKILL + 1)
    if len(raw) > MAX_SKILL or len(text) > MAX_SKILL:
        raise ValueError("Skill files must each be at most 32 KiB")
    value = json.loads(raw)
    required = {"id", "version", "description", "requires_localpilot", "dependencies", "tools", "inputs", "outputs"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Skill manifest requires explicit metadata, version, compatibility, dependencies, tools, inputs and outputs")
    identifier(value["id"])
    Version(value["version"])
    SpecifierSet(value["requires_localpilot"])
    if not isinstance(value["description"], str) or not 1 <= len(value["description"]) <= 512:
        raise ValueError("Skill description must be 1–512 characters")
    if not isinstance(value["dependencies"], dict) or len(value["dependencies"]) > 32:
        raise ValueError("Invalid Skill dependencies")
    for name, constraint in value["dependencies"].items():
        identifier(name)
        SpecifierSet(constraint)
    if (not isinstance(value["tools"], list) or len(value["tools"]) > 64 or
            any(not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", name) for name in value["tools"])):
        raise ValueError("Invalid Skill tool requirements")
    if any(not isinstance(value[key], dict) for key in ("inputs", "outputs")):
        raise ValueError("Skill inputs and outputs must be JSON Schemas")
    from .security import validate_schema
    validate_schema(value["inputs"])
    validate_schema(value["outputs"])
    content = text.decode("utf-8")
    if not content.strip() or "\x00" in content:
        raise ValueError("Skill instructions must be UTF-8 text without NUL")
    return {"manifest": value, "instructions": content, "bundle_sha256": digest([value, content])}


class SkillRegistry:
    def __init__(self, user_home, project=None):
        self.user = private_dir(user_home)
        self.reviews = private_dir(self.user / 'reviews')
        self.project = Path(project).resolve(strict=True) if project else None

    def review_path(self, name, scope):
        return self.reviews / (digest([str(self.project) if scope == 'project' else 'user', identifier(name)]) + '.json')

    def folder(self, scope, *, create=False):
        if scope not in {"user", "project"}:
            raise ValueError("Skill scope must be user or project")
        if scope == "user":
            return self.user
        if self.project is None:
            raise ValueError("Select a project for project Skills")
        path = self.project / ".localpilot" / "skills"
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("Skill storage cannot use symlinks")
        return private_dir(path) if create or path.exists() else path

    def install(self, bundle, scope="user", *, replace=False):
        value = parse_bundle(bundle)
        folder = self.folder(scope, create=True)
        path = folder / (value["manifest"]["id"] + ".json")
        with locked(folder):
            if replace:
                read_json(path)  # Explicit update requires an existing owned record.
            save_json(path, {**value, "enabled": False, "reviewed_sha256": None, "scope": scope}, exclusive=not replace)
            self.review_path(value['manifest']['id'], scope).unlink(missing_ok=True)
        return {"id": value["manifest"]["id"], "scope": scope, "status": "installed_disabled",
                "bundle_sha256": value["bundle_sha256"], "authority_granted": False}

    def list(self):
        result = []
        for scope in (["user", "project"] if self.project else ["user"]):
            folder = self.folder(scope)
            if folder.exists():
                for path in sorted(folder.glob("*.json")):
                    value = read_json(path)
                    result.append({"id": value["manifest"]["id"], "version": value["manifest"]["version"],
                        "scope": scope, "enabled": value["enabled"], "bundle_sha256": value["bundle_sha256"]})
        return result

    def get(self, name, scope):
        return read_json(self.folder(scope) / (identifier(name) + ".json"))

    def enable(self, name, scope, *, reviewed_sha256=None, enabled=True):
        folder = self.folder(scope)
        with locked(folder):
            value = self.get(name, scope)
            actual = digest([value["manifest"], value["instructions"]])
            if enabled and (actual != reviewed_sha256 or actual != value["bundle_sha256"]):
                raise ValueError("Enable requires explicit review of the exact Skill bundle digest")
            value.update(enabled=enabled, reviewed_sha256=reviewed_sha256 if enabled else None)
            if enabled:
                save_json(self.review_path(name, scope), {'bundle_sha256': actual})
            else:
                self.review_path(name, scope).unlink(missing_ok=True)
            save_json(folder / (name + ".json"), value)
        return {"id": name, "scope": scope, "enabled": enabled}

    def remove(self, name, scope):
        with locked(self.folder(scope)):
            self.get(name, scope)
            (self.folder(scope) / (identifier(name) + ".json")).unlink()
            self.review_path(name, scope).unlink(missing_ok=True)
        return {"id": name, "status": "removed"}

    def load(self, name, scope, available_tools=(), version="5.0.0b16"):
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
        stack = []
        loaded = {}

        def visit(current):
            if current in stack or len(stack) >= 16:
                raise ValueError("Cyclic or excessively deep Skill dependency")
            if current in loaded:
                return
            value = self.get(current, scope)
            manifest = value["manifest"]
            actual = digest([manifest, value["instructions"]])
            approval_path = self.review_path(current, scope)
            approval = read_json(approval_path) if approval_path.exists() else {}
            if not value["enabled"] or actual != value["reviewed_sha256"] or actual != value["bundle_sha256"] or actual != approval.get('bundle_sha256'):
                raise ValueError("Skill disabled or changed since review")
            if Version(version) not in SpecifierSet(manifest["requires_localpilot"]):
                raise ValueError("Skill is incompatible with this LocalPilot version")
            if set(manifest["tools"]) - set(available_tools):
                raise ValueError("Skill tool requirements unavailable; a Skill cannot install or authorize tools")
            stack.append(current)
            for dependency, constraint in manifest["dependencies"].items():
                dependency_value = self.get(dependency, scope)
                if Version(dependency_value["manifest"]["version"]) not in SpecifierSet(constraint):
                    raise ValueError("Skill dependency version mismatch")
                visit(dependency)
            stack.pop()
            loaded[current] = {"id": current, "version": manifest["version"],
                "instructions": value["instructions"], "inputs": manifest["inputs"], "outputs": manifest["outputs"]}
        visit(identifier(name))
        return {"status": "ok", "scope": scope, "skills": list(loaded.values()),
                "trust": "reviewed_user_guidance_below_host_policy", "authority_granted": False}
