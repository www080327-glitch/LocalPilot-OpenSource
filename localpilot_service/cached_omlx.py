"""Trusted-host lifecycle for one explicitly granted cached MLX model.

No download, arbitrary command, user-model mutation or ordinary-client control
endpoint. The existing Model Manager grant validator owns admission.
"""
from contextlib import contextmanager
from dataclasses import asdict
import atexit
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time

from .model_manager import ControlledModelManager, ResourceGrant, ManagerError
from .sdk import Client

MODEL = "Qwen3.6-35B-A3B-4bit"
REVISION = "38740b847e4cb78f352aba30aa41c76e08e6eb46"
SNAPSHOT = Path.home()/".cache/huggingface/hub/models--mlx-community--Qwen3.6-35B-A3B-4bit/snapshots"/REVISION
BINARY = "/Applications/oMLX.app/Contents/MacOS/omlx-cli"


def save(path, value):
    temporary=path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value,indent=2)+"\n");temporary.chmod(0o600)
    temporary.replace(path)


class CachedOmlxHost:
    """Host-only, one inference lease, bounded startup and idle release."""
    def __init__(self, spec, directory):
        if set(spec)-{"snapshot", "port", "idle_seconds", "memory_bytes", "min_available_bytes"}:
            raise ValueError("Unknown cached-model host option")
        self.snapshot=Path(spec["snapshot"]).expanduser().resolve(strict=True)
        if self.snapshot!=SNAPSHOT.resolve(strict=True) or self.snapshot.name!=REVISION or not (self.snapshot/"config.json").is_file():
            raise ManagerError("source_revision_not_approved")
        config=json.loads((self.snapshot/"config.json").read_text())
        if config.get("auto_map") or config.get("model_file"):
            raise ManagerError("untrusted_code_forbidden")
        self.port=spec.get("port",8048);self.idle=spec.get("idle_seconds",60)
        self.memory=spec.get("memory_bytes",26*1024**3)
        self.minimum=spec.get("min_available_bytes",28*1024**3)
        if (type(self.port) is not int or not 1024<=self.port<=65535 or
                type(self.idle) is not int or not 10<=self.idle<=600 or
                type(self.memory) is not int or not 24*1024**3<=self.memory<=28*1024**3 or
                type(self.minimum) is not int or self.minimum<self.memory):
            raise ValueError("Invalid bounded cached-model resource grant")
        weights=list(self.snapshot.glob("*.safetensors"))
        disk=sum(p.stat().st_size for p in weights)
        registry={MODEL:{"source":"mlx-community/Qwen3.6-35B-A3B-4bit", "revision":REVISION,
            "license":"apache-2.0", "trust_remote_code":False, "hardware":"apple-metal",
            "downloaded":bool(weights), "resource_estimate":{"memory_bytes":self.memory,"disk_bytes":disk}}}
        grant=ResourceGrant(allowed_models=(MODEL,),memory_bytes=self.memory,disk_bytes=disk,
            hardware="apple-metal",approved_sources=(registry[MODEL]["source"],),approved_licenses=("apache-2.0",))
        admission=ControlledModelManager(registry).ensure(MODEL,grant=grant,idempotency_key="cached-host-admission",operation="load")
        if admission["failure_reason"] or not weights:
            raise ManagerError(admission["failure_reason"] or "model_not_downloaded")
        if not Path(BINARY).is_file() or sys.platform!="darwin":
            raise ManagerError("hardware_incompatible_or_unknown")
        self.root=Path(directory)
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.root.is_symlink() or self.root.stat().st_mode&0o077:
            raise ValueError("Cached host directory must be private")
        self.token=secrets.token_urlsafe(32)
        self.client=Client(f"http://127.0.0.1:{self.port}",token=self.token,timeout=90)
        self.lock=threading.RLock();self.start_lock=threading.Lock();self.slot=threading.BoundedSemaphore(1)
        self.process=None;self.active=0;self.phase="unloaded";self.active_tasks=set();self.generation=0;self.gui_deadlines={};self.power_grants={};self.control_tickets={}
        self.grant=asdict(grant)
        atexit.register(self.close)

    def status(self):
        phase=self.phase;model_alive=False if self.process is None else None
        if self.process:
            try:
                import psutil
                record=json.loads((self.root/"owned-process.json").read_text())
                if record.get("guardian_pid")==self.process.pid:
                    try:
                        model=psutil.Process(record["model_pid"])
                        model_alive=abs(model.create_time()-record["model_created"])<.001
                    except psutil.NoSuchProcess:model_alive=False
            except (OSError,ValueError,KeyError):pass
            if self.process.poll() is not None:phase="orphaned_owned_model" if model_alive else "unloaded" if model_alive is False else "UNKNOWN"
        return {"status":phase,"active_leases":self.active,"model":MODEL,"downloaded":True,
                "revision":REVISION,"minimum_available_bytes":self.minimum,"memory_guard_bytes":self.memory,
                "release_after_task":True,"model_process_alive":model_alive,
                "control_surface_required":True,"evidence_kind":"HOST_LIFECYCLE_STATE_NOT_MODEL_BENCHMARK"}

    def _lease_record(self):
        save(self.root/"lease.json",{"active":self.active,"at":time.time(),"ui_deadline":min(self.gui_deadlines.values()) if self.gui_deadlines else 0,"battery_allowed":all(self.power_grants.values()) if self.power_grants else False})

    def _ensure(self, memory_override=False, cancelled=lambda:False):
        generation=self.generation
        if cancelled():raise ManagerError("model_start_cancelled")
        if self.process and self.process.poll() is None and self.phase=="ready":
            return
        if self.process and self.process.poll() is not None:self.process.wait(timeout=3)
        import psutil
        available=psutil.virtual_memory().available
        if available<4*1024**3 or available<self.minimum and not memory_override:
            raise ManagerError("resource_budget_exceeded")
        with socket.socket() as check:
            check.settimeout(.3)
            if check.connect_ex(("127.0.0.1",self.port))==0:
                raise ManagerError("existing_model_listener_preserved")
        models=self.root/"models";models.mkdir(exist_ok=True,mode=0o700)
        link=models/MODEL
        if link.is_symlink():
            if link.resolve()!=self.snapshot:raise ManagerError("source_revision_not_approved")
        elif link.exists():raise ManagerError("model_directory_conflict")
        else:link.symlink_to(self.snapshot,target_is_directory=True)
        model_state=self.root/"model-state";model_state.mkdir(exist_ok=True,mode=0o700)
        save(model_state/"model_settings.json",{"version":1,"models":{MODEL:{"enable_thinking":False}}})
        profile={"root":str(self.root),"parent":os.getpid(),"parent_created":psutil.Process().create_time(),
            "idle_seconds":self.idle,"port":self.port,"memory_guard_gb":self.memory/1024**3}
        save(self.root/"profile.json",profile)
        env={k:v for k,v in os.environ.items() if k in {"PATH","HOME","LANG","TMPDIR"}}
        env.update(OMLX_API_KEY=self.token,HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",HF_DATASETS_OFFLINE="1",PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        with (self.root/"lifecycle.log").open("a") as log:
            with self.lock:
                if generation!=self.generation or cancelled():raise ManagerError("model_start_cancelled")
                self.process=subprocess.Popen([sys.executable,"-m","localpilot_service.cached_omlx",str(self.root/"profile.json")],
                    env=env,cwd=str(self.root),stdout=log,stderr=log)
        self.phase="starting";deadline=time.monotonic()+100
        try:
            while time.monotonic()<deadline:
                if cancelled() or generation!=self.generation or self.process is None or self.process.poll() is not None:raise ManagerError("owned_model_startup_failed")
                try:
                    self.client.request("/v1/models")
                    break
                except Exception:time.sleep(.5)
            else:raise ManagerError("model_startup_timeout")
            self.phase="loading"
            self.client.request("/v1/models/"+MODEL+"/load",{})
            status=self.client.request("/api/status")
            if MODEL not in status.get("loaded_models",{}):raise ManagerError("model_not_ready")
            if generation!=self.generation:raise ManagerError("model_start_cancelled")
            self.phase="ready"
        except BaseException:
            self.close();raise

    @contextmanager
    def lease(self, task_id="host", consent=None, client_subject=None, cancelled=lambda:False, control_ticket=None):
        consent=consent or {}
        override=((consent.get("kind")=="memory_override" or consent.get("allow_memory_override") is True) and consent.get("client_subject")==client_subject
                  and consent.get("expires_at",0)>time.time())
        if not isinstance(control_ticket,str) or len(control_ticket)<16:raise ManagerError("control_surface_required")
        allowed_battery=consent.get("allow_on_battery") is True and consent.get("client_subject")==client_subject and consent.get("expires_at",0)>time.time()
        import psutil
        battery=psutil.sensors_battery()
        if (battery is None or battery.power_plugged is not True) and not allowed_battery:
            raise ManagerError("battery_confirmation_required")
        with self.lock:
            self.active_tasks.add(task_id);self.active=len(self.active_tasks)
            self.control_tickets[task_id]=control_ticket;self.gui_deadlines[task_id]=time.time()+20
            self.power_grants[task_id]=allowed_battery;self._lease_record()
        try:
            with self.start_lock:self._ensure(memory_override=override,cancelled=cancelled)
            yield
        finally:
            with self.lock:
                self.active_tasks.discard(task_id);self.active=len(self.active_tasks)
                self.gui_deadlines.pop(task_id,None);self.power_grants.pop(task_id,None);self.control_tickets.pop(task_id,None);self._lease_record()
                if not self.active:self.close()

    def heartbeat(self, task_id, ticket):
        with self.lock:
            if self.control_tickets.get(task_id)!=ticket:return
            self.gui_deadlines[task_id]=time.time()+20;self._lease_record()

    @contextmanager
    def inference(self):
        if not self.slot.acquire(timeout=100):raise ManagerError("model_concurrency_limited")
        try:yield
        finally:self.slot.release()

    def close(self, force=False):
        # Keep admission serialized until the previous model actually exits.
        # A dead guardian must not leave an owned orphan behind.
        import psutil
        with self.lock:
            self.generation+=1
            process=self.process
            self.phase="stopping"
            model=None
            try:
                value=json.loads((self.root/"owned-process.json").read_text())
                if process and value["guardian_pid"]==process.pid:
                    candidate=psutil.Process(value["model_pid"])
                    if abs(candidate.create_time()-value["model_created"])<.001:
                        model=candidate
            except (OSError,ValueError,KeyError,psutil.Error):pass
            if model and (force or process.poll() is not None):
                try:os.killpg(model.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=15)
                except subprocess.TimeoutExpired:raise ManagerError("owned_model_cleanup_pending")
            if model:
                try:
                    model.wait(timeout=2)
                except psutil.TimeoutExpired:
                    try:os.killpg(model.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    try:model.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        self.phase="cleanup_pending"
                        raise ManagerError("owned_model_cleanup_pending")
            self.phase="unloaded"



def model_environment(source):
    """The vendor model runtime must not import the Core interpreter's packages."""
    names={"PATH","HOME","LANG","TMPDIR","OMLX_API_KEY"}
    env={k:v for k,v in source.items() if k in names}
    env.update(HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",HF_DATASETS_OFFLINE="1",PYTHONNOUSERSITE="1")
    return env


def guardian(path):
    """Watch only this parent's private model process, including parent death."""
    import psutil
    profile=json.loads(Path(path).read_text());root=Path(profile["root"])
    stopping=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stopping.set())
    signal.signal(signal.SIGINT,lambda *_:stopping.set())
    command=[BINARY,"serve","--base-path",str(root/"model-state"),"--model-dir",str(root/"models"),
        "--host","127.0.0.1","--port",str(profile["port"]),"--max-concurrent-requests","1",
        "--memory-guard-gb",str(profile["memory_guard_gb"]),
        "--paged-ssd-cache-dir",str(root/"prefix-cache"),"--paged-ssd-cache-max-size","2GB",
        "--hot-cache-max-size","128MB","--no-hf-cache",
        "--initial-cache-blocks","8","--log-level","warning"]
    baseline=psutil.swap_memory().used
    process=subprocess.Popen(command,env=model_environment(os.environ),cwd=str(root),start_new_session=True)
    reason="normal_shutdown"
    try:
        save(root/"owned-process.json",{"guardian_pid":os.getpid(),"model_pid":process.pid,
             "model_created":psutil.Process(process.pid).create_time(),"parent_pid":profile["parent"],"baseline_swap_bytes":baseline})
        while not stopping.wait(2):
            try:
                parent=psutil.Process(profile["parent"])
                parent_live=abs(parent.create_time()-profile["parent_created"])<.001 and parent.status()!=psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:parent_live=False
            lease=json.loads((root/"lease.json").read_text())
            if not parent_live:reason="parent_exited";break
            if lease["active"] and time.time()>lease.get("ui_deadline",0):reason="control_surface_lost";break
            battery=psutil.sensors_battery()
            if lease["active"] and not lease.get("battery_allowed") and (battery is None or battery.power_plugged is not True):reason="battery_grant_required";break
            if psutil.swap_memory().used-baseline>1024**3:reason="swap_growth_guard";break
            if not lease["active"] and time.time()-lease["at"]>profile["idle_seconds"]:reason="idle_unload";break
            if process.poll() is not None:reason="model_exited";break
    finally:
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
        save(root/"lifecycle-final.json",{"reason":reason,"model_exited":process.poll() is not None,
            "model_pid":process.pid,"swap_used_bytes":psutil.swap_memory().used})


if __name__=="__main__":guardian(sys.argv[1])
