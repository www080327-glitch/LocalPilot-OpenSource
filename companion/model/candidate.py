"""Inspect an explicit local training candidate without loading or promoting it."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import stat

from companion.observers.events import redact_text
from companion.observers.files import read_regular_file

INTERFACE_SOURCE = 'https://github.com/ml-explore/mlx-lm/blob/ed1fca4cef15a824c5f1702c80f70b4cffc8e4dd/mlx_lm/utils.py'


def inspect_candidate(model, adapter, *, require_runtime=False):
    model, adapter = (Path(os.path.abspath(os.path.expanduser(value))) for value in (model, adapter))
    run_bytes, _ = read_regular_file(adapter.parent / 'run.json', 1024*1024)
    config_bytes, _ = read_regular_file(adapter / 'adapter_config.json', 1024*1024)
    run, configuration = json.loads(run_bytes), json.loads(config_bytes)
    if (not isinstance(run, dict) or run.get('schema') != 'companion-training-run-v1'
            or run.get('status') != 'completed' or run.get('training') != 'COMPLETED'
            or not isinstance(run.get('config'), dict) or not isinstance(configuration, dict)
            or not isinstance(run.get('base_config_sha256'), dict) or not isinstance(run.get('trained_weights'), dict)):
        raise ValueError('Use a completed Companion training run with its adapter configuration')
    if run.get('model') != str(model) or run['config'].get('adapter_path') != str(adapter):
        raise ValueError('Candidate and base model must match the recorded training paths')
    bindings = run.get('base_config_sha256', {})
    for filename in ('config.json', 'tokenizer_config.json'):
        content, _ = read_regular_file(model / filename, 1024*1024)
        if hashlib.sha256(content).hexdigest() != bindings.get(filename):
            raise ValueError('Base model configuration changed or lacks a recorded identity: ' + filename)
    for key in ('fine_tune_type', 'num_layers', 'lora_parameters'):
        if configuration.get(key) != run['config'].get(key):
            raise ValueError('Adapter configuration differs from the completed training run: ' + key)
    if configuration.get('fine_tune_type') not in {'lora', 'full'}:
        raise ValueError('This candidate loader supports the existing lora/full training output only')
    if hashlib.sha256(config_bytes).hexdigest() != run.get('adapter_config_sha256'):
        raise ValueError('Adapter configuration hash differs from the completed run')
    recorded = run.get('trained_weights', {})
    weights = adapter / 'adapters.safetensors'
    with os.fdopen(os.open(weights, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        observed = os.fstat(stream.fileno())
        if not stat.S_ISREG(observed.st_mode) or observed.st_size <= 0 or observed.st_size != recorded.get('bytes'):
            raise ValueError('Candidate weights are missing or differ from the completed run')
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != recorded.get('sha256'):
        raise ValueError('Candidate weight hash differs from the completed run')
    try:
        version = importlib.metadata.version('mlx-lm')
    except importlib.metadata.PackageNotFoundError:
        version = None
    if require_runtime and version != '0.31.3':
        raise ValueError('Explicit candidate loading requires mlx-lm==0.31.3')
    return {'status':'validated', 'directory':str(adapter), 'sha256':digest,
            'fine_tune_type':configuration['fine_tune_type'], 'mlx_lm_version':version,
            'runtime_version_ready':version == '0.31.3', 'inference':'NOT_RUN',
            'quality':run.get('quality', 'NOT_EVALUATED'), 'model_promoted':False,
            'base_weights_verified':False, 'base_identity':'recorded_path_and_configuration_hashes',
            'interface_source':INTERFACE_SOURCE,
            'config_fragment':{'backend':'mlx', 'model_path':str(model), 'model_adapter_path':str(adapter)}}


def main():
    parser = argparse.ArgumentParser(description='Validate a local training candidate; no inference, download or promotion')
    parser.add_argument('--model', required=True)
    parser.add_argument('--adapter', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(inspect_candidate(args.model, args.adapter), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({'status':'unavailable', 'error':redact_text(str(error))[:800], 'inference':'NOT_RUN'}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
