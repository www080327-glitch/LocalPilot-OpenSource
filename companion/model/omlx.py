"""Read-only admission to an existing shared oMLX service. No process control."""
import json
import os
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler
from companion.escalation.provider import validate_endpoint, NoRedirect


def loaded_model(config):
    base = validate_endpoint(config.http_model_endpoint)
    headers = {}
    if config.http_model_api_key_env:
        key = os.environ.get(config.http_model_api_key_env)
        if not key: raise ValueError('oMLX credential unavailable')
        headers['Authorization']='Bearer '+key
    url=base.removesuffix('/v1')+'/v1/models/status'
    with build_opener(ProxyHandler({}),NoRedirect()).open(Request(url,headers=headers),timeout=5) as response:
        state=json.load(response)
    model=next((m for m in state.get('models',[]) if m.get('id')==config.http_model_name),None)
    if not model or model.get('loaded') is not True or model.get('is_loading'):
        raise ValueError('oMLX model is not loaded; confirm loading in oMLX management')
    if Path(model.get('model_path','')).resolve()!=Path(config.model_path).expanduser().resolve():
        raise ValueError('oMLX model path differs from the granted local profile')
    return model
