"""oMLX transport over an existing service. Never owns its process or weights."""
import json
import threading
import re
import subprocess
import sys
import socket
from pathlib import Path
from .local_http import LocalHTTPBackend, LocalBackendError


class OMLXBackend(LocalHTTPBackend):
    def __init__(self, **kwargs):
        if kwargs.get('allow_remote') or kwargs.get('reasoning_replay'):
            raise ValueError('oMLX requires local transport without provider replay')
        kwargs.setdefault('include_stream_usage', True)
        kwargs.setdefault('engine', 'omlx')
        kwargs.setdefault('service_location', 'local')
        super().__init__(**kwargs)
        self._response_lock = threading.Lock()
        self._responses = set()

    def _payload(self, *args, **kwargs):
        payload = super()._payload(*args, **kwargs)
        for message in payload['messages']:
            # Native DeepSeek replay is never part of the local wire protocol.
            for name in ('reasoning_content', 'native_replay', 'signature'):
                message.pop(name, None)
        return payload

    def _admit(self):
        observed = self.inspect_service()
        model = next((m for m in observed['models'] if m['id']==self.model), None)
        if not model or not model['loaded'] or model['deployment_status']!='ready':
            raise LocalBackendError('oMLX model is not loaded; authorize loading in oMLX management', retryable=False)
        if sys.platform == 'darwin':
            try:
                # "custom" lists inactive battery/AC profiles as well. Only
                # the currently in-use settings can govern this admission.
                power=subprocess.run(['/usr/bin/pmset','-g'],capture_output=True,text=True,timeout=2,check=True).stdout
                setting=re.search(r'\blowpowermode\s+([01])\b',power)
                low=setting is None or setting.group(1)=='1'
            except (OSError,subprocess.SubprocessError):
                low=True
            size=model.get('size_bytes')
            from .power_consent import allowed
            if low and not allowed() and (type(size) is not int or size>1500000000):
                raise LocalBackendError('当前处于低电量模式，请在发送前选择“本次允许”以运行本地模型；本次未发送模型请求。',retryable=False)

    def request(self, *args, **kwargs):
        self._admit()
        return super().request(*args, **kwargs)

    def stream(self, *args, **kwargs):
        self._admit()
        yield from super().stream(*args, **kwargs)

    def inspect_service(self):
        """Read-only oMLX endpoints; no gateway, load, unload or download calls."""
        root = self.base_url.removesuffix('/v1')
        def get(path):
            # _open appends to /v1; use a separate validated transport for root paths.
            if path.startswith('/v1/'):
                with self._open(path[3:]) as response:
                    return json.load(response)
            from urllib.request import Request
            headers = {'Authorization': 'Bearer ' + self._api_key} if self._api_key else {}
            try:
                with self._opener.open(Request(root + path, headers=headers), timeout=min(self.timeout, 5)) as response:
                    return json.load(response)
            except Exception:
                raise LocalBackendError('oMLX status unavailable', retryable=True) from None
        models = get('/v1/models')['data']
        if not isinstance(models, list):
            raise LocalBackendError('Malformed oMLX discovery', retryable=False)
        status = get('/api/status')
        try:
            details = get('/v1/models/status').get('models', [])
        except LocalBackendError:
            details = []
        detail_by_id = {m['id']: m for m in details if isinstance(m, dict) and isinstance(m.get('id'), str)}
        entries = []
        for model in models:
            if not isinstance(model, dict) or not isinstance(model.get('id'), str):
                raise LocalBackendError('Malformed oMLX model entry', retryable=False)
            d = detail_by_id.get(model['id'], {})
            if d.get('is_helper') or d.get('engine_type') == 'markitdown' or model['id'].lower() == 'markitdown':
                continue
            quantization = None
            remote_code=None
            # oMLX returns trusted host paths. Only read metadata, never model code.
            try:
                c = json.loads((Path(d['model_path']) / 'config.json').read_text())
                remote_code=bool(c.get('auto_map'))
                q = c.get('quantization', c.get('quantization_config', {}))
                quantization = {k: q[k] for k in ('bits', 'group_size', 'mode') if k in q} or None
            except (OSError, ValueError, KeyError, TypeError):
                pass
            files_present = None
            if d.get('model_path'):
                directory=Path(d['model_path'])
                try:
                    index=directory/'model.safetensors.index.json'
                    if index.is_file():
                        names=set(json.loads(index.read_text())['weight_map'].values())
                        files_present=bool(names) and all((directory/name).is_file() and (directory/name).stat().st_size>0 for name in names if isinstance(name,str))
                    else:
                        files_present=any(p.stat().st_size>0 for p in directory.glob('*.safetensors') if p.is_file())
                except (OSError,ValueError,KeyError,TypeError):files_present=False
            entries.append({'id': model['id'], 'downloaded': files_present is not False, 'files_present':files_present,
                'loaded': d.get('loaded', model['id'] in status.get('loaded_models', [])),
                'deployment_status': 'not_deployed' if files_present is False else ('loading' if d.get('is_loading') else 'ready'),
                'context_budget': d.get('max_context_window') or model.get('max_model_len'),
                'size_bytes': d.get('estimated_size'), 'resident_bytes': d.get('actual_size'),
                'quantization': quantization, 'source': d.get('source_repo_id') or 'oMLX local discovery',
                'trust_remote_code':remote_code,
                'revision': Path(d.get('model_path','')).name if re.fullmatch(r'[0-9a-f]{40}',Path(d.get('model_path','')).name) else 'UNKNOWN', 'capability_qualification': 'NOT_RUN'})
        return {'status': 'ready', 'version': status.get('version', 'UNKNOWN'),
            'evidence_kind': 'LIVE_OMLX_READ_ONLY', 'models': entries,
            'memory_used_bytes': status.get('model_memory_used'),
            'memory_max_bytes': status.get('model_memory_max'),
            'active_requests': status.get('active_requests'),
            'management_url': root + '/admin', 'mutations_supported': False,
            'request_cleanup': 'client_disconnect; provider_release_not_verified'}

    def _open(self, path, payload=None):
        response = super()._open(path, payload)
        if payload is None:
            return response
        backend = self
        class TrackedResponse:
            def __enter__(self): return response
            def __exit__(self, *exc):
                try: response.close()
                finally:
                    with backend._response_lock: backend._responses.discard(response)
        with self._response_lock: self._responses.add(response)
        return TrackedResponse()

    def cancel_request(self):
        # Close only this Session's client responses; never unload the shared model.
        with self._response_lock:
            responses = tuple(self._responses)
        for response in responses:
            sock=getattr(getattr(getattr(response,'fp',None),'raw',None),'_sock',None)
            if sock is not None:
                try:sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            try: response.close()
            except OSError: pass
