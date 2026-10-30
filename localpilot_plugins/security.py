"""Host-owned configuration, source identities and bounded JSON Schemas."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid
from urllib.parse import urlsplit

MAX_FRAME = 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", value):
        raise ValueError("Use an identifier of 1–32 lowercase letters, digits or hyphens")
    return value


def private_dir(path):
    path = Path(path).expanduser().absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Private plugin paths cannot use symlinks")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Plugin storage must be owner-only (700)")
    return path


def read_json(path):
    from localpilot_service.security import private_json
    return private_json(path)


def save_json(path, value, *, exclusive=False):
    data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    if len(data) > MAX_FRAME:
        raise ValueError("Plugin record exceeds 1 MiB")
    path = Path(path)
    target = path if exclusive else path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if not exclusive:
            os.replace(target, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if not exclusive:
            target.unlink(missing_ok=True)


@contextmanager
def locked(folder):
    fd = os.open(folder / "manager.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Unsafe plugin lock")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def validate_schema(schema):
    """Draft 2020-12, local references only; never retrieve remote schema URLs."""
    from jsonschema import Draft202012Validator
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValueError("MCP input schema must be an object schema")
    count = 0

    def walk(value, depth=0):
        nonlocal count
        count += 1
        if depth > 24 or count > 4096:
            raise ValueError("Schema exceeds complexity budget")
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"$dynamicRef", "$recursiveRef", "pattern", "patternProperties"}:
                    raise ValueError("Dynamic references and regex schemas require unsupported execution budgets")
                if key == "$ref" and (not isinstance(child, str) or not child.startswith("#/")):
                    raise ValueError("Only local JSON Schema references are supported")
                walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1)
    walk(schema)
    # Reject cycles: recursive schemas can exhaust a validator independently of input depth.
    refs = []

    def dereference(value, ancestors=()):
        if isinstance(value, dict):
            ref = value.get("$ref")
            if ref:
                if ref in ancestors:
                    raise ValueError("Recursive schemas are unsupported")
                target = schema
                for part in ref[2:].split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]
                refs.append(ref)
                if len(refs) > 128:
                    raise ValueError("Schema reference expansion exceeds budget")
                dereference(target, (*ancestors, ref))
            for key, child in value.items():
                if key != "$ref":
                    dereference(child, ancestors)
        elif isinstance(value, list):
            for child in value:
                dereference(child, ancestors)
    dereference(schema)
    Draft202012Validator.check_schema(schema)
    if len(json.dumps(schema).encode()) > 32768:
        raise ValueError("Schema exceeds 32 KiB")
    return schema


def validate_input(value, schema):
    import subprocess
    import sys
    from agent.tool_protocol import ToolArgumentsError
    validate_schema(schema)
    if len(json.dumps(value, allow_nan=False).encode()) > 32768:
        raise ToolArgumentsError(["Arguments exceed 32 KiB"])
    errors = []
    try:
        # JSON Schema is executable validation work. Keep its CPU/memory faults
        # outside Core as well as those of the actual external server.
        payload = json.dumps({'schema': schema, 'value': value}, allow_nan=False).encode()
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('schema_worker.py'))],
            input=payload, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3,
            env={'PATH': os.defpath, 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
        errors = json.loads(result.stdout) if result.returncode == 0 and len(result.stdout) <= 8192 else ['Schema validator unavailable']
    except (subprocess.TimeoutExpired, RecursionError, KeyError, ValueError, OSError):
        errors.append("Schema validation budget exceeded or validator unavailable")
    if errors:
        raise ToolArgumentsError(errors)


def manifest(value):
    allowed = {"id", "transport", "command", "args", "url", "credential_env", "bearer_credential",
               "timeout", "source_files"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("Unknown plugin manifest fields; no inline credentials or environment allowed")
    identifier(value["id"])
    transport = value.get("transport")
    if transport not in {"stdio", "streamable-http"}:
        raise ValueError("Use stdio or streamable-http")
    timeout = value.get("timeout", 15)
    if type(timeout) not in {int, float} or not 1 <= timeout <= 60:
        raise ValueError("Plugin timeout must be 1–60 seconds")
    value = {**value, "timeout": timeout}
    if transport == "stdio":
        if "url" in value or "bearer_credential" in value:
            raise ValueError("HTTP fields are invalid for stdio")
        executable = Path(value["command"])
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("Reviewed stdio executable must be an absolute executable path")
        if not isinstance(value.get("args", []), list) or len(value.get("args", [])) > 64 or any(
                not isinstance(arg, str) or len(arg) > 4096 or "\x00" in arg for arg in value.get("args", [])):
            raise ValueError("Invalid stdio arguments")
        env = value.get("credential_env", {})
        if not isinstance(env, dict) or any(not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", key) or
                key.startswith(("PYTHON", "LD_", "DYLD_")) or key in {"PATH", "HOME", "SHELL", "ENV", "BASH_ENV"}
                for key in env):
            raise ValueError("Only named credential environment bindings are allowed")
        for ref in env.values():
            identifier(ref)
    else:
        if any(key in value for key in ("command", "args", "credential_env")):
            raise ValueError("stdio fields are invalid for HTTP")
        url = urlsplit(value["url"])
        if (url.username or url.password or url.query or url.fragment or not url.hostname or
                (url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "::1"}))):
            raise ValueError("HTTP plugins require HTTPS, or an explicit loopback IP; no URL credentials/query")
        if value.get("bearer_credential"):
            identifier(value["bearer_credential"])
    files = value.get("source_files", [])
    if not isinstance(files, list) or len(files) > 128:
        raise ValueError("Review up to 128 source files")
    for file in files:
        if not Path(file).is_absolute() or not Path(file).is_file():
            raise ValueError("Source review files must be absolute regular files")
    return value


def source_identity(config):
    paths = set(config.get("source_files", []))
    if config["transport"] == "stdio":
        paths.add(config["command"])
        paths.update(arg for arg in config.get("args", []) if Path(arg).is_absolute() and Path(arg).is_file())
    hashes = {}
    for path in sorted(paths):
        with open(path, "rb") as source:
            hasher = hashlib.sha256()
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                hasher.update(chunk)
            hashes[path] = hasher.hexdigest()
    return digest({"manifest": config, "files": hashes})


def redact(value, secrets):
    encoded = json.dumps(value, ensure_ascii=False)
    for secret in secrets:
        encoded = encoded.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "[REDACTED]")
    return json.loads(encoded)


def resource_allowed(uri, catalog):
    """Review exact concrete URIs; support simple RFC6570 path variables only."""
    if uri in {r['uri'] for r in catalog['resources']}:
        return True
    if not isinstance(uri, str) or len(uri) > 4096:
        return False
    for template in catalog.get('resource_templates', []):
        pattern = template['uriTemplate']
        variables = re.findall(r'\{([A-Za-z_][A-Za-z0-9_]*)\}', pattern)
        if not variables or len(variables) > 16:
            continue
        for variable in variables:
            pattern = pattern.replace('{' + variable + '}', '\x00', 1)
        if '{' in pattern or '}' in pattern:
            continue
        pattern = re.escape(pattern).replace('\x00', r'[A-Za-z0-9_.~%\-]+')
        if re.fullmatch(pattern, uri):
            return True
    return False
