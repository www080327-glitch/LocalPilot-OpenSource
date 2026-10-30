import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time
from typing import Protocol


class ModelBackend(Protocol):
    def complete(self, messages: list[dict], max_tokens: int) -> dict: ...
    def unload(self) -> None: ...


class ModelManager:
    """MLX is contained in a disposable child. Eco unload really releases its process."""
    def __init__(self, config, metrics_store=None, adapter: ModelBackend | None = None):
        self.config = config
        self.metrics_store = metrics_store
        self.adapter = adapter
        self.child = None
        self.last_used = 0.0
        self.wake_times = metrics_store.get("model_call_times", []) if metrics_store else []
        self.load_times = metrics_store.get("model_load_times", []) if metrics_store else []
        totals = metrics_store.get("model_totals", {}) if metrics_store else {}
        self.inferences = totals.get("invocations", 0)
        self.total_loads = totals.get("loads", 0)
        self.total_unloads = totals.get("unloads", 0)
        self.last_result = None
        self.stopping = False

    def complete(self, messages, max_tokens=None, schema=None):
        if self.stopping:
            return {"status":"unavailable", "error":"Companion is stopping"}
        if self.adapter is None and self.config.backend != "disabled":
            from companion.runtime.power import local_model_block_reason
            reason = local_model_block_reason(self.config)
            if reason:
                self.unload()
                return {"status":"unavailable", "error_stage":"power_policy", "error":reason}
        from companion.runtime.power import LowPowerPolicy
        if self.adapter is None and self.config.backend == 'omlx':
            try:
                from companion.model.omlx import loaded_model
                state = loaded_model(self.config)
                self.external_state={'model':state['id'],'loaded':state['loaded'],'observed_at':time.time(),'owns_process':False}
                if LowPowerPolicy(self.config).active() and (type(state.get('estimated_size')) is not int or state['estimated_size']>self.config.lightweight_max_weight_bytes):
                    raise ValueError('oMLX model exceeds the low-power lightweight budget')
            except Exception:
                return {'status':'unavailable','error_stage':'omlx_admission',
                        'error':'oMLX model unavailable, not loaded, or outside lightweight resource grant'}
        if LowPowerPolicy(self.config).active() and self.adapter is None and self.config.backend != "disabled":
            if self.config.backend == "local-http":
                return {"status":"unavailable", "error_stage":"power_policy", "error":"Unmanaged local backend is disabled in low-power mode"}
            if not self.config.lightweight_on_demand and (self.child is None or self.child.poll() is not None):
                return {"status":"unavailable", "error_stage":"power_policy", "error":"Lightweight model is idle; explicit on-demand configuration required"}
            root = Path(self.config.model_path).expanduser()
            weights = list(root.glob("*.safetensors")) if self.config.model_path else []
            if not weights or sum(p.stat().st_size for p in weights) > self.config.lightweight_max_weight_bytes:
                return {"status":"unavailable", "error_stage":"power_policy", "error":"Model size is unknown or exceeds lightweight budget"}
            try:
                metadata = json.loads((root/"config.json").read_text())
                text = metadata.get("text_config", {})
                qualified = (metadata.get("model_type") == "qwen3_5" and
                    (text.get("hidden_size"),text.get("num_hidden_layers"),text.get("intermediate_size")) == (1024,24,3584))
            except (OSError,ValueError,AttributeError):
                qualified = False
            if not qualified:
                return {"status":"unavailable", "error_stage":"power_policy", "error":"Only the qualified 0.8B profile is enabled in low-power mode"}
        deadline = getattr(self, "request_deadline", None)
        if deadline is not None and time.monotonic() >= deadline:
            return {"status":"unavailable", "error":"Shared answer deadline reached", "error_stage":"deadline", "latency_seconds":0}
        if self.adapter is None and self.config.backend == "disabled":
            return {"status":"unavailable","error_stage":"primary_unconfigured","error":"Model backend disabled","model_called":False}
        self.last_used = time.monotonic()
        cutoff = time.time()-3600
        self.wake_times[:] = [t for t in self.wake_times if t > cutoff]
        self.load_times[:] = [t for t in self.load_times if t > cutoff]
        self.wake_times.append(time.time())
        self.inferences += 1
        if self.metrics_store:
            self.metrics_store.set("model_call_times", self.wake_times)
            self.persist_totals()
        start = time.perf_counter()
        try:
            if self.adapter is not None:
                structured = getattr(self.adapter, "complete_structured", None)
                if schema and callable(structured):
                    result = structured(messages, max_tokens or self.config.max_output_tokens, schema)
                else:
                    result = self.adapter.complete(messages, max_tokens or self.config.max_output_tokens)
                    result["constraint"] = "unsupported_validator_required" if schema else "none"
            elif self.config.backend == "disabled":
                raise RuntimeError("Model backend disabled")
            elif self.config.backend in {"local-http", "omlx"}:
                if not self.config.http_model_host_local_only:
                    raise RuntimeError("Configured model endpoint policy UNKNOWN; declare a local-only host before sending context")
                from companion.escalation.provider import request_chat
                from companion.model.structured import json_schema
                response_format = {"type":"json_schema", "json_schema":{"name":schema,"strict":True,"schema":json_schema(schema)}} if schema and self.config.http_schema_supported else None
                http_seconds = max(.001, min(90, deadline-time.monotonic())) if deadline is not None else 90
                result = request_chat(self.config.http_model_endpoint, self.config.http_model_name, messages, max_tokens or self.config.max_output_tokens, api_key_env=self.config.http_model_api_key_env, response_format=response_format, timeout_seconds=http_seconds,
                    **({'chat_template_kwargs':{'enable_thinking':False}} if self.config.backend=='omlx' else {}))
                result["backend"] = self.config.backend
                result["constraint"] = "server_requested_unverified" if response_format else "unsupported_validator_required" if schema else "none"
            else:
                model_path = Path(self.config.model_path).expanduser()
                if not self.config.model_path or not model_path.is_dir():
                    raise RuntimeError("Local model not configured/downloaded; no automatic cloud fallback")
                cold = self.child is None or self.child.poll() is not None
                if cold:
                    if self.child:
                        self.unload()
                    self.load_times.append(time.time())
                    self.total_loads += 1
                    if self.metrics_store:
                        self.metrics_store.set("model_load_times", self.load_times)
                        self.persist_totals()
                    import re
                    credential_names = {self.config.localpilot_resource_key_env, self.config.localpilot_api_key_env, self.config.agent_api_key_env, self.config.http_model_api_key_env}
                    env = {k:v for k,v in os.environ.items() if k not in credential_names and not re.search(r"token|secret|password|credential|api.?key|localpilot|deepseek|authorization", k, re.I)}
                    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
                    self.child = subprocess.Popen([sys.executable, "-m", "companion.model.worker", str(model_path), str(self.config.model_context_tokens), str(os.getpid())], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0, env=env, close_fds=True)
                    self.worker_buffer = b""
                callback = getattr(self, "on_delta", None) if schema is None else None
                payload = {"messages": messages, "max_tokens": max_tokens or self.config.max_output_tokens, "schema":schema}
                if callback:
                    payload["stream"] = True
                self.child.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
                self.child.stdin.flush()
                worker_deadline = min(deadline, time.monotonic()+120) if deadline is not None else time.monotonic()+120
                while True:
                    while b"\n" not in self.worker_buffer:
                        wait_seconds = max(0, worker_deadline-time.monotonic())
                        ready, _, _ = select.select([self.child.stdout], [], [], wait_seconds)
                        if not ready:
                            self.unload()
                            raise TimeoutError("Local model timed out")
                        chunk = os.read(self.child.stdout.fileno(), 65536)
                        if not chunk:
                            self.unload()
                            raise RuntimeError("Local model worker exited")
                        self.worker_buffer += chunk
                        if len(self.worker_buffer) > 1024*1024:
                            self.unload()
                            raise ValueError("Model response exceeds limit")
                    line, self.worker_buffer = self.worker_buffer.split(b"\n", 1)
                    result = json.loads(line)
                    if result.get("event") != "delta":
                        break
                    if callback:
                        callback(result.get("text", ""))
                result.update(backend="mlx", cold=cold)
            result["latency_seconds"] = time.perf_counter() - start
        except Exception as exc:
            result = {"status": "unavailable", "error": str(exc), "latency_seconds": time.perf_counter() - start}
        self.last_used = time.monotonic()
        self.last_result = result
        if result.get("status") == "unavailable":
            self.unload()
        if self.metrics_store:
            cutoff = time.time()-3600
            self.metrics_store.set("model_call_times", [t for t in self.wake_times if t > cutoff])
            self.metrics_store.set("model_load_times", [t for t in self.load_times if t > cutoff])
            self.persist_totals()
        return result

    def tick(self):
        from companion.runtime.power import LowPowerPolicy
        low = LowPowerPolicy(self.config).active()
        if (low or self.config.mode == "eco") and (self.child or self.adapter) and time.monotonic() - self.last_used >= (min(15, self.config.eco_unload_seconds) if low else self.config.eco_unload_seconds):
            self.unload()

    def available(self):
        if self.adapter is not None:
            return True
        if self.config.backend in {"local-http", "omlx"}:
            return bool(self.config.http_model_endpoint and self.config.http_model_name and self.config.http_model_host_local_only)
        return self.config.backend == "mlx" and bool(self.config.model_path) and Path(self.config.model_path).expanduser().is_dir()

    def stats(self):
        loaded = bool(self.child and self.child.poll() is None)
        rss = None
        if loaded:
            import psutil
            try:
                rss = psutil.Process(self.child.pid).memory_info().rss
            except psutil.Error:
                pass
        self.wake_times[:] = [t for t in self.wake_times if time.time() - t < 3600]
        self.load_times[:] = [t for t in self.load_times if time.time() - t < 3600]
        return {"loaded": loaded, "worker_pid": self.child.pid if loaded else None, "worker_rss_bytes": rss, "inferences": self.inferences, "model_calls_last_hour": len(self.wake_times), "model_wakes_last_hour":len(self.load_times), "model_wakes_total":self.total_loads, "model_unloads_total":self.total_unloads, "last_result_metrics": {k:v for k,v in (self.last_result or {}).items() if k not in {"text", "error"}}}

    def persist_totals(self):
        if self.metrics_store:
            self.metrics_store.set("model_totals", {"invocations":self.inferences,"loads":self.total_loads,"unloads":self.total_unloads})

    def unload(self):
        if self.adapter is not None:
            self.adapter.unload()
        if self.child:
            if self.child.poll() is None:
                self.child.terminate()
            try:
                self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait()
            self.child.stdin.close()
            self.child.stdout.close()
            self.child = None
            self.total_unloads += 1
            self.persist_totals()

    def request_stop(self):
        # Signal handlers must not enter SQLite, wait, or invoke adapter callbacks.
        self.stopping = True
        if self.child and self.child.poll() is None:
            self.child.terminate()
