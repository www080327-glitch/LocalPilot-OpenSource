"""Optional host-owned bounded file/text assertions using the existing verifier hook."""
import re
from agent.stabilization import file_version, HostVerification
from agent.safety import resolve_workspace_path


def configured_verifier(workspace, spec):
    if spec is None:
        return None
    if (not isinstance(spec, dict) or not {"id", "files", "required_text"} <= set(spec)
            or set(spec) - {"id", "files", "required_text", "required_text_mode"} or
            not isinstance(spec["id"], str) or not spec["id"] or
            not isinstance(spec["files"], dict) or not 1 <= len(spec["files"]) <= 32 or
            not isinstance(spec["required_text"], str) or not 1 <= len(spec["required_text"]) <= 4096):
        raise ValueError("Invalid host file/text verification contract")
    if spec.get("required_text_mode", "substring") not in {"substring", "line"}:
        raise ValueError("required_text_mode must be substring or line")
    for path, sha in spec["files"].items():
        resolve_workspace_path(workspace, path, must_exist=False)
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("Verification requires an exact expected file SHA256")
    def check(root, result):
        versions = {}
        for path in spec["files"]:
            try:
                versions[path] = file_version(root, path)
            except (OSError, ValueError):
                versions[path] = None
        good = all(versions[p] and versions[p]["sha256"] == sha for p,sha in spec["files"].items())
        text_good = (spec["required_text"] in [line.strip() for line in result.text.splitlines()]
                     if spec.get("required_text_mode") == "line" else spec["required_text"] in result.text)
        good = good and text_good
        return HostVerification("passed" if good else "failed", spec["id"],
            {p:v["sha256"] for p,v in versions.items() if v}, good, bool(result.text.strip()), True)
    return check


def configured_execution_check(workspace, spec):
    """File readiness only; independent of model text and final delivery format.

    Reuses the already validated host contract. No expected bytes or hashes are
    included in model feedback. Fresh version bindings are checked again by LP.
    """
    if spec is None: return None
    configured_verifier(workspace, spec)
    def check(root, projection):
        versions = {}
        for path in spec['files']:
            try: versions[path] = file_version(root, path)
            except (OSError, ValueError): versions[path] = None
        good = all(versions[p] and versions[p]['sha256'] == sha for p, sha in spec['files'].items())
        return HostVerification('passed' if good else 'failed', spec['id'] + ':execution-files-only',
            {p:v['sha256'] for p,v in versions.items() if v}, good, good, True)
    return check
