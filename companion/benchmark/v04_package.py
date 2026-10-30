"""Offline wheel/install/daemon acceptance in a new target, outside-source CWD.

Uses an existing dependency interpreter read-only. Does not install into it,
download dependencies, observe real documents or start native observation.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import threading
import tomllib
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def environment(target=None):
    result = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8",
              "TMPDIR": "/tmp", "PYTHONDONTWRITEBYTECODE": "1", "PIP_CONFIG_FILE": "/dev/null",
              "PIP_NO_INDEX": "1", "PIP_NO_CACHE_DIR": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
              "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    if target is not None:
        result["PYTHONPATH"] = str(target)
    return result


def source_files(package):
    excluded = {"build", "dist", "__pycache__", "node_modules", "evidence"}
    result = {}
    for path in package.rglob("*.py"):
        relative = path.relative_to(package)
        if any(part.startswith(".") or part.endswith(".egg-info") or part in excluded for part in relative.parts):
            continue
        result["companion/" + relative.as_posix()] = path
    spec = tomllib.loads((package / "pyproject.toml").read_text())
    for pattern in spec["tool"]["setuptools"]["package-data"]["companion"]:
        for path in package.glob(pattern):
            if path.is_file():
                result["companion/" + path.relative_to(package).as_posix()] = path
    return result


def run(output, python):
    package = Path(__file__).resolve().parents[1]
    python = Path(os.path.abspath(python))
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("Choose an existing dependency interpreter")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    base = package / ".data" / ("v04-package-" + stamp)
    wheels, target, docs = base / "wheels", base / "target", base / "documents"
    for directory in (wheels, target, docs):
        directory.mkdir(parents=True, exist_ok=False)
    outside = Path(tempfile.mkdtemp(prefix="companion-v04-package-")).resolve()
    result = {"created_at": datetime.now(timezone.utc).isoformat(), "base_dir": str(base),
              "outside_cwd": str(outside), "dependency_python": str(python), "version_expected": "0.5.3",
              "no_dependencies_downloaded": True, "existing_environment_modified": False,
              "native_observation": "disabled", "models": "disabled", "external_apps": "NOT_RUN",
              "source": {}, "commands": [], "acceptance": {}}
    output = Path(output).absolute()
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2))

    def execute(label, args, *, cwd=outside, installed=False, timeout=60):
        started = time.monotonic()
        response = subprocess.run([str(x) for x in args], cwd=cwd, env=environment(target if installed else None),
                                  capture_output=True, text=True, timeout=timeout)
        result["commands"].append({"label": label, "exit_code": response.returncode,
            "elapsed_seconds": time.monotonic() - started, "stdout": response.stdout[-4000:], "stderr": response.stderr[-4000:]})
        save()
        if response.returncode:
            raise RuntimeError(label + " failed; inspect saved package evidence")
        return response.stdout

    def cli(config, action, *args):
        return json.loads(execute("installed_cli_" + action,
             [python, "-m", "companion", "--config", config, "--json", action, *args], installed=True, timeout=30))

    try:
        files = source_files(package)
        hashes = {name: digest(path.read_bytes()) for name, path in sorted(files.items())}
        result["source"]["files"] = hashes
        result["source"]["python_files"] = sum(name.endswith(".py") for name in hashes)
        result["source"]["swift_files"] = [name for name in hashes if name.endswith(".swift")]
        dependencies = execute("existing_dependencies", [python, "-c", "import importlib.metadata,json,sys; print(json.dumps({'python':sys.version,'packages':{n:importlib.metadata.version(n) for n in ('pip','setuptools','wheel','watchdog','pypdf','psutil')}}))"])
        result["dependencies"] = json.loads(dependencies)
        execute("build_wheel_offline", [python, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
             "--no-index", "--no-cache-dir", "--wheel-dir", wheels, package], cwd=package, timeout=120)
        built = list(wheels.glob("*.whl"))
        if len(built) != 1:
            raise RuntimeError("Expected one new wheel")
        wheel = built[0]
        result["wheel"] = {"path": str(wheel), "sha256": digest(wheel.read_bytes()), "bytes": wheel.stat().st_size}
        with zipfile.ZipFile(wheel) as archive:
            members = set(archive.namelist())
            missing = sorted(set(hashes) - members)
            mismatched = [name for name in hashes if name in members and digest(archive.read(name)) != hashes[name]]
            metadata = archive.read(next(name for name in members if name.endswith(".dist-info/METADATA"))).decode()
            result["wheel"].update(missing=missing, mismatched=mismatched,
                                  metadata_version=next((line[9:] for line in metadata.splitlines() if line.startswith("Version: ")), "UNKNOWN"))
        result["acceptance"]["all_python_and_package_data_in_wheel"] = not missing and not mismatched
        result["acceptance"]["wheel_version_0_5_3"] = result["wheel"]["metadata_version"] == "0.5.3"
        if not all(result["acceptance"].values()):
            raise RuntimeError("Wheel content/version mismatch")
        execute("install_new_target_offline", [python, "-m", "pip", "install", "--no-deps", "--no-index", "--no-cache-dir",
             "--no-compile", "--target", target, wheel], timeout=60)
        installed_mismatch = [name for name, expected in hashes.items()
                              if not (target / name).is_file() or digest((target / name).read_bytes()) != expected]
        result["installed_mismatch"] = installed_mismatch
        result["acceptance"]["installed_source_bytes_match"] = not installed_mismatch
        modules = []
        for name in hashes:
            if not name.endswith(".py") or name.endswith("/__main__.py"):
                continue
            module = name[:-3].replace("/", ".")
            if module.endswith(".__init__"):
                module = module[:-9]
            modules.append(module)
        script = """import importlib,json,pathlib,sys,companion
target=pathlib.Path(sys.argv[1]).resolve()
mods=json.loads(sys.argv[2]); failures={}; paths={}
for name in mods:
 try:
  mod=importlib.import_module(name); paths[name]=str(pathlib.Path(mod.__file__).resolve())
 except Exception as error: failures[name]=type(error).__name__+': '+str(error)
print(json.dumps({'version':companion.__version__,'module_path':companion.__file__,'modules':paths,'failures':failures,'all_under_target':all(target in pathlib.Path(p).parents for p in paths.values())}))
"""
        imported = json.loads(execute("outside_cwd_imports", [python, "-c", script, target, json.dumps(modules)], installed=True))
        result["imports"] = imported
        result["acceptance"]["all_modules_import_from_installed_target"] = not imported["failures"] and imported["all_under_target"]
        result["acceptance"]["installed_version_0_5_3"] = imported["version"] == "0.5.3"
        execute("installed_console_entrypoint", [target / "bin" / "companion", "--help"], installed=True)
        result["acceptance"]["console_entrypoint_outside_source"] = True

        (docs / "budget.txt").write_text("项目：星河\n预算：17万\n")
        for mode in ("cli_start", "direct_run"):
            config = base / (mode + ".json")
            state = base / (mode + "-state")
            config.write_text(json.dumps({"data_dir": str(state), "watch_dirs": [str(docs)], "backend": "disabled",
                    "dnd": True, "notifications": False, "quiet_start_hour": 0, "quiet_end_hour": 0,
                    "native_observation_enabled": False}, ensure_ascii=False))
            # Initialize the new private owner marker before concurrent daemon
            # and client startup; this is only our newly-created test state.
            cli(config, "status")
            daemon = None
            try:
                if mode == "cli_start":
                    started = cli(config, "start")
                else:
                    with open(base / "direct-run.log", "w") as logfile:
                        daemon = subprocess.Popen([str(python), "-m", "companion", "--config", str(config), "run"],
                            stdout=logfile, stderr=logfile, cwd=outside, env=environment(target))
                    started = {"status": "starting"}
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        started = cli(config, "status")
                        if started.get("status") == "running":
                            break
                        if daemon.poll() is not None:
                            raise RuntimeError("Installed daemon exited")
                        time.sleep(0.1)
                answer = cli(config, "ask", "星河现在预算多少？")
                status = cli(config, "status")
                import psutil
                record = json.loads((state / "runtime.json").read_text())
                process = psutil.Process(record["pid"])
                daemon_cwd = process.cwd()
                result[mode] = {"start": started, "answer": answer, "status": status, "daemon_cwd": daemon_cwd}
                result["acceptance"][mode + "_started_and_indexed"] = (started.get("status") == "running"
                    and status.get("version") == "Companion V0.4.3" and "17万" in answer.get("text", "")
                    and status.get("native_observer", {}).get("state") == "disabled")
                if mode == "direct_run":
                    result["acceptance"]["daemon_itself_outside_workspace"] = Path(daemon_cwd) == outside
            finally:
                if daemon is not None:
                    # Reap only this verifier's own direct child while the
                    # sibling CLI waits for its process to disappear.
                    threading.Thread(target=daemon.wait, daemon=True).start()
                try:
                    stopped = cli(config, "stop")
                except Exception as error:
                    stopped = {"status": "error", "error": type(error).__name__ + ": " + str(error)}
                result.setdefault(mode, {})["stop"] = stopped
                if daemon is not None:
                    try:
                        daemon.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        daemon.terminate(); daemon.wait(timeout=3)
                result["acceptance"][mode + "_stopped_cleanly"] = stopped.get("status") == "stopped" and not (state / "runtime.json").exists()
                save()
                if stopped.get("status") != "stopped":
                    raise RuntimeError("Installed daemon stop did not complete")

        # Compile only the wheel's fixed native source, then use invisible
        # synthetic controls. No listen/status/real user app observation occurs.
        build_script = "import pathlib,sys; from companion.observers.native import build_native_helper; print(build_native_helper(pathlib.Path(sys.argv[1])))"
        binary = execute("installed_swift_source_build", [python, "-c", build_script, base / "installed-native"], installed=True, timeout=120).strip()
        fixture = {"config": {"allowlist": ["org.localpilot.synthetic"], "ax_enabled": True,
                "content_allowlist": ["org.localpilot.synthetic"]}}
        probe = subprocess.run([binary, "--fixture-snapshot"], input=json.dumps(fixture).encode(),
                               capture_output=True, timeout=10, cwd=outside, env=environment())
        result["installed_native_fixture"] = {"exit_code": probe.returncode,
            "events": [json.loads(line) for line in probe.stdout.splitlines()], "stderr_bytes": len(probe.stderr)}
        fixture_text = probe.stdout.decode()
        result["acceptance"]["packaged_swift_compiles_and_fixture_filters"] = (probe.returncode == 0
            and "Synthetic project status ready" in fixture_text and "MUST NOT EMIT" not in fixture_text)
        current = {name: digest(path.read_bytes()) for name, path in source_files(package).items()}
        result["acceptance"]["frozen_sources_unchanged_during_package_run"] = current == hashes
        result["status"] = "TESTED" if all(result["acceptance"].values()) else "FAILED"
        save()
        if result["status"] != "TESTED":
            raise AssertionError(result["acceptance"])
        return result
    except Exception as error:
        result["status"], result["error"] = "FAILED", type(error).__name__ + ": " + str(error)
        save()
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--python", required=True, help="existing interpreter with build and runtime dependencies")
    args = parser.parse_args()
    result = run(args.output, args.python)
    print(json.dumps({"status": result["status"], "acceptance": result["acceptance"], "base_dir": result["base_dir"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
