"""Deterministic permission policy. This is not an OS or container sandbox."""

import math
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from .permissions import PermissionMode, RiskAssessment, ToolRiskMetadata
from .policy import DataPolicy

PERMISSION_MODES = ("all_confirm", "cautious", "permissive", "full", *(mode.value for mode in PermissionMode))
READ_TOOLS = {"read_file", "list_directory", "search_text", "file_info", "list_entries", "inspect_file"}
BLOCKED_PROGRAMS = {
    "sudo", "su", "doas", "rm", "rmdir", "unlink", "shred", "dd", "mkfs",
    "diskutil", "fdisk", "format", "mount", "umount", "chmod", "chown",
    "chgrp", "reboot", "shutdown", "launchctl", "systemctl", "kill", "pkill",
    "killall", "sh", "bash", "zsh", "fish", "dash", "csh", "cmd", "powershell",
    "pwsh", "env", "eval", "exec", "xargs", "find", "osascript", "open",
    "truncate", "srm", "halt", "poweroff", "chflags", "defaults", "installer",
    "hdiutil", "tmutil", "crontab", "at", "nohup", "nice", "setsid", "time",
    "watch", "busybox", "tar", "unzip", "ln",
    "curl", "wget", "ssh", "scp", "rsync", "nc", "netcat", "pip", "pip3",
    "npm", "npx", "brew", "apt", "apt-get", "node", "ruby", "perl", "lua",
}
PROTECTED_PARTS = {".git", ".env"}


@dataclass(frozen=True)
class CapabilityPolicy:
    """Capabilities are host choices, independent of prompts and approval modes."""

    read: bool = True
    write: bool = True
    execute: bool = False  # Host execution requires an explicit experimental opt-in.
    read_only: bool = False


def sensitive_path(path):
    from .permission_context import full_access
    if full_access(): return False
    parts = Path(path).parts
    return any(parts[i:i + 2] == ('.localpilot', 'secrets') for i in range(len(parts))) or any(part in {".git", ".ssh", ".env"} or
               (part.startswith(".env.") and part != ".env.example")
               for part in parts)


def resolve_workspace_path(workspace_root, path, *, must_exist=True, writing=False):
    """Check lexical and resolved paths before requiring existence."""
    root = Path(workspace_root).resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Workspace root is not a directory: {root}")
    if not isinstance(path, str) or not path or len(path) > 4096 or "\x00" in path:
        raise ValueError("path must be a non-empty string up to 4096 characters without NUL")
    requested = Path(path)
    if requested.is_absolute() or ".." in requested.parts:
        raise ValueError("Paths must be relative and cannot contain '..'.")
    target = (root / requested).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ValueError("The requested path is outside the workspace root.") from error
    if sensitive_path(requested) or sensitive_path(target.relative_to(root)):
        raise ValueError("Access to protected credentials or Git metadata is blocked.")
    if writing:
        if PROTECTED_PARTS.intersection(requested.parts):
            raise ValueError("Writes to .git or .env are blocked.")
        current = root
        for part in requested.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("Writes through symlinks are blocked.")
        if target.exists() and target.is_file() and target.stat().st_nlink > 1:
            raise ValueError("Writes to files with multiple hard links are blocked.")
    return target.resolve(strict=True) if must_exist else target


class PermissionGateway:
    """Host-selected policy and bounds; no model-visible approval override."""

    def __init__(self, workspace_root, mode="cautious", max_timeout=30, max_output_bytes=16000,
                 capabilities=None, data_policy=None, judge=None, plan_read_only=False):
        self.root = resolve_workspace_path(workspace_root, ".")
        mode = mode.value if isinstance(mode, PermissionMode) else mode
        if mode not in PERMISSION_MODES:
            raise ValueError(f"mode must be one of {PERMISSION_MODES}")
        if not isinstance(max_timeout, (int, float)) or isinstance(max_timeout, bool) or not math.isfinite(max_timeout) or not 0 < max_timeout <= 60:
            raise ValueError("max_timeout must be finite and between 0 and 60 seconds")
        if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or not 1 <= max_output_bytes <= 64000:
            raise ValueError("max_output_bytes must be between 1 and 64000")
        self.mode = mode
        self.capabilities = capabilities or CapabilityPolicy()
        self.data_policy = data_policy or DataPolicy()
        self.judge = judge
        self.plan_read_only = plan_read_only
        self._approval = ContextVar(f"gateway_approval_{id(self)}", default=None)
        self.max_timeout = max_timeout
        self.max_output_bytes = max_output_bytes
        self.audit = []

    @contextmanager
    def approving(self, operation, approved=False):
        """Permit one host-approved decision for this call, then discard it."""
        token = self._approval.set(operation if approved else None)
        try:
            yield
        finally:
            self._approval.reset(token)

    def decide(self, operation, risk, reasons, resource, *, blocked=False, metadata=None):
        new_mode = self.mode in {mode.value for mode in PermissionMode}
        read_only = operation in READ_TOOLS or (new_mode and operation not in {"execute", "apply_patch"}
                                                and isinstance(metadata, ToolRiskMetadata)
                                                and metadata.read_only and not metadata.mutating
                                                and not (metadata.potentially_destructive or
                                                         metadata.external_side_effect or
                                                         metadata.requires_shell or metadata.network_access))
        if operation=='shell' and isinstance(resource,dict) and resource.get('enforced_read_only_shell') is True:
            read_only=True
        capability = (self.capabilities.read if read_only else
                      self.capabilities.write if operation == "apply_patch" or
                      (new_mode and operation != "execute") else self.capabilities.execute)
        local_network_forbidden=(self.data_policy.local_only and isinstance(metadata,ToolRiskMetadata) and metadata.network_access)
        if not capability or local_network_forbidden or (operation == "execute" and self.data_policy.local_only):
            blocked = True
            reasons = [*reasons, "Capability disabled, or local_only forbids network access or unsandboxed host execution."]
        if not read_only and (self.plan_read_only or self.capabilities.read_only):
            blocked = True
            reasons = [*reasons, "Read-only plan or capability forbids mutation."]
        if blocked:
            status = "denied"
        elif self.mode == PermissionMode.FULL_PERMISSION.value:
            status = "allowed"
        elif risk not in {"low","medium","high","critical"}:
            status = "approval_required"
        elif isinstance(metadata, ToolRiskMetadata) and metadata.requires_host_approval:
            status = "approval_required"
        elif new_mode:
            status = self._new_mode_status(operation, risk, reasons, resource, read_only, metadata)
        elif self.mode == "all_confirm":
            status = "approval_required"
        elif self.mode == "cautious" and risk != "low":
            status = "approval_required"
        elif self.mode == "permissive" and risk == "high":
            status = "approval_required"
        else:
            status = "allowed"
        if status == "approval_required" and self._approval.get() == operation:
            self._approval.set(None)
            status = "allowed"
        decision = {
            "status": status,
            "risk_summary": {"operation": operation, "level": risk, "reasons": reasons,
                             "resource": resource, "permission_mode": self.mode, "risk_class": "SAFE" if risk == "low" else "UNCERTAIN" if risk == "medium" else "RISKY"},
        }
        self.record(decision)
        return decision

    def _new_mode_status(self, operation, risk, reasons, resource, read_only, metadata):
        mode = self.mode
        if mode in {PermissionMode.ASSIST_LOW.value, PermissionMode.ASSIST_HIGH.value}:
            # Deterministic risk floor. Unknown metadata never becomes SAFE.
            category = "SAFE" if risk == "low" else "UNCERTAIN" if risk == "medium" else "RISKY"
            if operation=="execute":category="RISKY"
            if isinstance(metadata, ToolRiskMetadata) and (metadata.potentially_destructive or metadata.external_side_effect or metadata.network_access or metadata.requires_shell):
                category = "RISKY"
            return "allowed" if category == "SAFE" or category == "UNCERTAIN" and mode == PermissionMode.ASSIST_HIGH.value else "approval_required"
        if mode == PermissionMode.WORKSPACE_AUTO.value:
            return "allowed" if operation in READ_TOOLS | {"apply_patch", "make_directory", "move_file", "copy_file", "shell", "http_get"} else "approval_required"
        if mode == PermissionMode.APPROVE_ALL.value:
            return "approval_required"
        if mode == PermissionMode.APPROVE_MUTATIONS.value:
            return "allowed" if read_only else "approval_required"
        if mode == PermissionMode.FULL_PERMISSION.value:
            return "allowed"
        if read_only:
            return "allowed"
        if self.judge is None:
            return "approval_required"
        try:
            assessment = self.judge(operation, risk, reasons, resource)
            if not isinstance(assessment, RiskAssessment):
                raise ValueError("Judge must return RiskAssessment")
            # Validate even if a subclass bypassed the dataclass constructor.
            RiskAssessment(assessment.risk_level, assessment.reason,
                           assessment.potential_impact, assessment.recommended_action)
        except Exception as error:
            self.record({"operation": operation, "status": "judge_unavailable",
                         "error_type": type(error).__name__})
            return "approval_required"
        if assessment.recommended_action == "deny":
            return "approval_required"
        if assessment.recommended_action == "approval_required":
            return "approval_required"
        levels = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        effective_risk = levels[assessment.risk_level.lower()]
        if risk in {"high", "critical"}:
            effective_risk = max(effective_risk, levels[risk])
        if operation == "execute":
            # Any host program can mutate files or produce outside effects.
            effective_risk = max(effective_risk, 2)
        if isinstance(metadata, ToolRiskMetadata):
            if metadata.potentially_destructive or metadata.external_side_effect or metadata.network_access or metadata.requires_shell:
                effective_risk = max(effective_risk, 2)
            elif metadata.mutating:
                effective_risk = max(effective_risk, 1)
        threshold = 0 if mode == PermissionMode.LOCAL_JUDGE_CONSERVATIVE.value else 1
        return "allowed" if effective_risk <= threshold else "approval_required"

    def record(self, event):
        # Bounded metadata only. The host may persist these events separately.
        from copy import deepcopy
        import hashlib,json
        event=deepcopy(event)
        if "risk_summary" in event:
            resource=event["risk_summary"].get("resource")
            if isinstance(resource,dict) and any(k in resource for k in ("arguments","argv","changes")):
                event["risk_summary"]["resource"]={"sha256":hashlib.sha256(json.dumps(resource,sort_keys=True).encode()).hexdigest(),"content_omitted":True}
        self.audit.append(event)
        del self.audit[:-1000]

    def command_decision(self, argv):
        if not isinstance(argv, list) or not argv or len(argv) > 100:
            raise ValueError("argv must contain 1 to 100 strings")
        if any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in argv):
            raise ValueError("argv entries must be non-empty strings without NUL")
        if sum(len(arg) for arg in argv) > 16000:
            raise ValueError("argv is too long")
        program = Path(argv[0]).name.lower()
        summary = {"program": program, "argv": list(argv)}
        if self.mode == PermissionMode.FULL_PERMISSION.value:
            return self.decide("execute", "high", ["Host selected full access without application approval."], summary)
        if program in BLOCKED_PROGRAMS or program.startswith("mkfs"):
            return self.decide("execute", "high", ["Blocked destructive, privileged, shell, network, or installer command."], summary, blocked=True)
        # No shell is started, and shell syntax is rejected rather than guessed.
        if any(any(mark in arg for mark in (";", "|", "&", "`", "$", "\n", "\r", ">", "<")) for arg in argv):
            return self.decide("execute", "high", ["Shell syntax is unsupported."], summary, blocked=True)
        python = program.startswith("python")
        if python:
            args = list(argv[1:])
            while args and args[0] in {"-B", "-u"}:
                args.pop(0)
            valid = (args == ["--version"] or args == ["-V"] or
                     (len(args) >= 2 and args[0] == "-m" and args[1] in {"unittest", "pytest"}) or
                     (args and not args[0].startswith("-") and args[0].endswith(".py")))
            if not valid:
                return self.decide("execute", "high", ["Python accepts only workspace .py scripts, unittest/pytest or version checks; no inline/stdin code."], summary, blocked=True)
        if program == "git":
            if len(argv) < 2 or argv[1] not in {"status", "diff", "log", "show", "ls-files"}:
                return self.decide("execute", "high", ["Only read-only Git subcommands are supported."], summary, blocked=True)
            if any(arg.startswith(("--output", "--ext-diff", "--textconv", "--exec", "--config", "--git-dir", "--work-tree")) or arg in {"-c", "-C"} for arg in argv[2:]):
                return self.decide("execute", "high", ["Git output, helper, configuration and cwd overrides are blocked."], summary, blocked=True)
        # Conservative argument scan; not a parser for arbitrary programs.
        for arg in argv[1:]:
            value = arg.split("=", 1)[-1] if arg.startswith("-") and "=" in arg else arg
            if value.startswith("-"):
                if "/" in value or ".." in value:
                    return self.decide("execute", "high", ["Attached path options are unsupported; use separate relative-path arguments."], summary, blocked=True)
                continue
            candidate = self.root / value
            if Path(value).is_absolute() or ".." in Path(value).parts or "/" in value or candidate.exists() or candidate.is_symlink():
                try:
                    resolve_workspace_path(self.root, value, must_exist=False, writing=True)
                except (ValueError, OSError) as error:
                    return self.decide("execute", "high", [str(error)], summary, blocked=True)
        if program in {"echo", "pwd", "cat", "ls", "head", "tail", "wc", "true", "false"}:
            # Fail closed for flags which might change a known command's behavior.
            safe_flags = {"-n", "-a", "-l", "-h", "-c", "-w", "-q", "-v", "--", "-la", "-al"}
            if all(not arg.startswith("-") or arg in safe_flags or arg[1:].isdigit() for arg in argv[1:]):
                return self.decide("execute", "low", ["Known inspection command; no shell."], summary)
        if program == "git":
            return self.decide("execute", "medium", ["Git may read repository configuration; no write subcommands."], summary)
        return self.decide("execute", "medium", ["Runs code or an unclassified program with host-user permissions; may write files or access the network."], summary)
