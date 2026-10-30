"""Trusted-host lifecycle for a pinned, already-downloaded vLLM model.

No agent-controlled commands, downloads, shared-process termination or weight
swapping. The process is the unit of load/unload on standard vLLM serving.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import threading
import time

from agent.vllm import VLLMBackend


class VLLMHost:
    def __init__(self, *, python, snapshot, revision, model, directory, port=8051,
                 context=8192, max_sequences=4, memory_bytes=32*1024**3,
                 prefix_cache=False, tool_parser='qwen3_coder', reasoning_parser='qwen3'):
        # Preserve a venv launcher: resolving its symlink selects base Python
        # and loses the isolated serving dependencies.
        self.python=Path(os.path.abspath(python))
        if not self.python.is_file():raise ValueError('Host Python executable missing')
        self.snapshot=Path(snapshot).resolve(strict=True)
        if not re.fullmatch(r'[0-9a-f]{40}',revision) or self.snapshot.name!=revision:
            raise ValueError('A matching immutable HF snapshot revision is required')
        config=json.loads((self.snapshot/'config.json').read_text())
        if config.get('auto_map') or not list(self.snapshot.glob('*.safetensors')):
            raise ValueError('Downloaded native checkpoint required; remote code forbidden')
        if (type(port) is not int or not 1024<=port<=65535 or type(context) is not int or context<1024
                or type(max_sequences) is not int or not 1<=max_sequences<=4
                or type(memory_bytes) is not int or memory_bytes<1024**3 or type(prefix_cache) is not bool):
            raise ValueError('Invalid bounded vLLM resource configuration')
        if not isinstance(model,str) or not model or tool_parser not in {None,'qwen3_coder'} or reasoning_parser not in {None,'qwen3'}:
            raise ValueError('Unsupported host model/parser declaration')
        self.root=Path(directory).resolve()
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.root.stat().st_mode&0o077:
            raise ValueError('vLLM process state must be owner-only')
        self.port,self.memory=port,memory_bytes
        self.token=secrets.token_urlsafe(32)
        self.command=[str(self.python),'-m','vllm.entrypoints.openai.api_server',
            '--model',str(self.snapshot),'--served-model-name',model,'--host','127.0.0.1','--port',str(port),
            '--max-model-len',str(context),'--max-num-seqs',str(max_sequences),
            '--max-num-batched-tokens','512','--generation-config','vllm',
            '--gpu-memory-utilization','0.42','--kv-cache-memory-bytes','1073741824',
            '--enable-prefix-caching' if prefix_cache else '--no-enable-prefix-caching']
        if tool_parser:self.command+=['--enable-auto-tool-choice','--tool-call-parser',tool_parser]
        if reasoning_parser:self.command+=['--reasoning-parser',reasoning_parser]
        self.backend=VLLMBackend(base_url=f'http://127.0.0.1:{port}/v1',model=model,
            effective_context=context,timeout=120,api_key=self.token,engine='vllm-metal',
            model_revision=revision,supports_tool_calling=bool(tool_parser),
            chat_template_kwargs={'enable_thinking':False},generation_parameters={'temperature':0,'seed':25})
        self.process=None
        self.lock=threading.RLock()
        self.active=0
        self.startup_seconds=None

    def load(self, timeout=240):
        import psutil
        with self.lock:
            if self.process and self.process.poll() is None:
                if self.backend.health_check():return self.status()
                raise RuntimeError('Owned process exists but inference is unhealthy')
            with socket.socket() as check:
                if check.connect_ex(('127.0.0.1',self.port))==0:
                    raise RuntimeError('Existing listener preserved')
            if psutil.virtual_memory().available<self.memory:
                raise RuntimeError('Insufficient available memory for host grant')
            env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','TMPDIR'}}
            env.update(VLLM_API_KEY=self.token,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
                       VLLM_METAL_BACKEND='mlx',VLLM_ENABLE_V1_MULTIPROCESSING='1',
                       PYTORCH_ENABLE_MPS_FALLBACK='0',TOKENIZERS_PARALLELISM='false')
            started=time.monotonic()
            with (self.root/'server.log').open('a') as log:
                self.process=subprocess.Popen(self.command,env=env,stdout=log,stderr=log,start_new_session=True)
            deadline=started+timeout
            try:
                while time.monotonic()<deadline:
                    if self.process.poll() is not None:raise RuntimeError('vLLM process failed; inspect owned server log')
                    processes=[psutil.Process(self.process.pid),*psutil.Process(self.process.pid).children(recursive=True)]
                    rss=sum(p.memory_info().rss for p in processes if p.is_running())
                    if rss>self.memory:raise RuntimeError('Owned process RSS exceeded memory grant')
                    if self.backend.health_check():
                        self.startup_seconds=time.monotonic()-started
                        return self.status()
                    time.sleep(.5)
                raise TimeoutError('vLLM load deadline exceeded')
            except BaseException:
                self.unload()
                raise

    @contextmanager
    def inference(self):
        with self.lock:
            if not self.process or self.process.poll() is not None:raise RuntimeError('Owned vLLM model is not loaded')
            self.active+=1
        try:yield self.backend
        finally:
            with self.lock:self.active-=1

    def unload(self):
        with self.lock:
            if self.active:raise RuntimeError('Cannot unload an active model lease')
            process=self.process
            if process is not None:
                # Kill only the process group created by this object, including
                # engine workers, even if the API parent has already exited.
                try:os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    process.wait(timeout=10)
            self.process=None
        return self.status()

    def status(self):
        return {'state':'running' if self.process and self.process.poll() is None else 'unloaded',
                'pid':self.process.pid if self.process else None,'active_leases':self.active,
                'startup_to_discovery_seconds':self.startup_seconds,'model':self.backend.model,
                'revision':self.snapshot.name,'command':self.command,
                'memory_guard_bytes':self.memory,'downloads':False}
