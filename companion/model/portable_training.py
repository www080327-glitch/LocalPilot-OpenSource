"""Explicit offline Linux CPU/CUDA LoRA or full-parameter training on reviewed data."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from companion.config import PrivateData
from companion.model.finetune import training_inputs
from companion.observers.events import redact_text

VERSIONS = {'torch': '2.9.1', 'transformers': '4.57.3', 'peft': '0.18.1', 'safetensors': '0.7.0'}


def readiness():
    installed = {}
    for name in VERSIONS:
        try:
            installed[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed[name] = None
    ready = sys.platform.startswith('linux') and all(
        installed[name] and installed[name].split('+')[0] == version for name, version in VERSIONS.items())
    return {'ready': bool(ready), 'platform': sys.platform, 'required': VERSIONS,
            'installed': installed, 'device': 'checked_on_explicit_execution'}


def prepare(model, dataset, output, *, method='lora', iterations=100, rank=8, layers=None,
            max_seq_length=2048, batch_size=1, seed=17, learning_rate=1e-5, device='cpu'):
    if device not in {'cpu', 'cuda'}:
        raise ValueError('Choose cpu or cuda; CPU does not require MPS')
    layers = (-1 if method == 'full' else 4) if layers is None else layers
    model, dataset, output, manifest, model_config, config_hashes = training_inputs(
        model, dataset, output, method, iterations, rank, layers, max_seq_length, batch_size, seed, learning_rate)
    if model_config.get('quantization') or model_config.get('quantization_config'):
        raise ValueError('The portable trainer requires unquantized Transformers safetensors; MLX/GGUF weights are not interchangeable')
    if method == 'full' and layers != -1:
        raise ValueError('Portable full training updates all parameters; use --layers -1')
    if method == 'lora' and (type(model_config.get('num_hidden_layers')) is not int
            or layers > model_config['num_hidden_layers']):
        raise ValueError('Choose existing Transformer layers for this LoRA model')
    private = PrivateData(output)
    weights = {}
    for path in sorted(model.glob('*.safetensors')):
        with path.open('rb') as stream:
            weights[path.name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    config = {'model': str(model), 'data': str(dataset), 'output': str(output / 'candidate'),
              'method': method, 'iterations': iterations, 'rank': rank, 'layers': layers,
              'max_seq_length': max_seq_length, 'batch_size': batch_size, 'seed': seed,
              'learning_rate': learning_rate, 'device': device, 'threads': 2}
    filename = private.write('training-config.json', json.dumps(config, indent=2) + '\n')
    plan = {'schema': 'companion-portable-training-v1', 'status': 'not_run', 'training': 'NOT_RUN',
            'quality': 'NOT_EVALUATED', 'model_promoted': False, 'created_at': time.time(),
            'output': str(output), 'config': config, 'base_weights_sha256': weights,
            'base_config_sha256': config_hashes, 'base_model_modified': False,
            'dataset_sha256': manifest['sha256'], 'counts': manifest['counts'],
            'held_out_test': 'reserved_not_used_by_trainer' if manifest['counts'].get('test') else 'NOT_PROVIDED',
            'readiness': readiness(), 'offline': True, 'device': device,
            'training_scope': 'lora_selected_linear_layers' if method == 'lora' else 'all_model_parameters_including_embeddings_and_head',
            'command': [sys.executable, '-m', 'companion.model.torch_training_worker', '--config', str(filename)],
            'model_source': 'operator_selected_local_files; hashes identify bytes, not upstream provenance'}
    private.write('run.json', json.dumps(plan, indent=2) + '\n')
    return plan


def execute(plan):
    private = PrivateData(plan['output'])
    if not plan['readiness']['ready']:
        return plan
    environment = os.environ | {'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
        'HF_DATASETS_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1', 'WANDB_DISABLED': 'true',
        'TOKENIZERS_PARALLELISM': 'false'}
    plan.update(status='running', training='RUNNING', started_at=time.time())
    private.write('run.json', json.dumps(plan, indent=2) + '\n')
    log_path = private.file('training.log')
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as log:
            process = subprocess.run(plan['command'], env=environment, stdout=log, stderr=subprocess.STDOUT, check=False)
        plan.update(exit_code=process.returncode, status='completed' if process.returncode == 0 else 'failed',
                    training='COMPLETED' if process.returncode == 0 else 'FAILED')
        if process.returncode == 0:
            _record_candidate(plan)
    except KeyboardInterrupt:
        plan.update(status='interrupted', training='INTERRUPTED', exit_code=130)
    except (OSError, ValueError) as error:
        plan.update(status='failed', training='FAILED', error=redact_text(str(error))[:800])
    plan.update(finished_at=time.time(), log=str(log_path))
    private.write('run.json', json.dumps(plan, indent=2) + '\n')
    return plan


def _record_candidate(plan):
    output = Path(plan['config']['output'])
    files = list(output.glob('*.safetensors'))
    if not files or not (output / 'metrics.json').is_file():
        raise ValueError('Trainer did not produce candidate weights and metrics')
    plan['candidate_files'] = {}
    for path in sorted(output.iterdir()):
        if path.is_file():
            with path.open('rb') as stream:
                plan['candidate_files'][path.name] = {'bytes': path.stat().st_size,
                    'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}
    for name, expected in plan['base_weights_sha256'].items():
        with (Path(plan['config']['model']) / name).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                plan['base_model_modified'] = True
                raise ValueError('Base weights changed during training')
    plan['metrics'] = json.loads((output / 'metrics.json').read_text())
    plan['candidate_format'] = 'peft_lora' if plan['config']['method'] == 'lora' else 'transformers_full'
    plan['candidate_directory'] = str(output)
    plan['activation'] = 'explicit_external_local_server; not an MLX adapter and not automatically selected'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('model', 'data', 'output'):
        parser.add_argument('--' + argument, required=True)
    parser.add_argument('--method', choices=['lora', 'full'], default='lora')
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    parser.add_argument('--iterations', type=int, default=100)
    parser.add_argument('--rank', type=int, default=8)
    parser.add_argument('--layers', type=int)
    parser.add_argument('--max-seq-length', type=int, default=2048)
    parser.add_argument('--batch-size', type=int, default=1)
    parser.add_argument('--seed', type=int, default=17)
    parser.add_argument('--learning-rate', type=float, default=1e-5)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        plan = prepare(args.model, args.data, args.output, method=args.method, iterations=args.iterations,
                       rank=args.rank, layers=args.layers, max_seq_length=args.max_seq_length,
                       batch_size=args.batch_size, seed=args.seed, learning_rate=args.learning_rate, device=args.device)
        if args.execute:
            plan = execute(plan)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0 if not args.execute or plan['status'] == 'completed' else 2
    except (OSError, ValueError) as error:
        print(json.dumps({'status': 'error', 'error': redact_text(str(error))[:800]}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
