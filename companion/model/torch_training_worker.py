"""CPU/CUDA worker for the explicit portable trainer, using local safetensors only."""
import argparse
import json
import math
from pathlib import Path
import time

from companion.model.reviewed_data import load_dataset


def train(config):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, TaskType, get_peft_model

    torch.manual_seed(config['seed'])
    torch.set_num_threads(config['threads'])
    if config['device'] == 'cuda' and not torch.cuda.is_available():
        raise ValueError('The selected CUDA device is unavailable; no device fallback was performed')
    tokenizer = AutoTokenizer.from_pretrained(config['model'], local_files_only=True, trust_remote_code=False)
    _, splits, _ = load_dataset(config['data'], batch_size=config['batch_size'])
    samples = {name: [_tokens(row['messages'], tokenizer, config['max_seq_length']) for row in splits[name]]
               for name in ('train', 'valid')}
    model = AutoModelForCausalLM.from_pretrained(config['model'], local_files_only=True,
        trust_remote_code=False, use_safetensors=True, dtype=torch.float32).to(config['device'])
    model.config.use_cache = False
    if config['method'] == 'lora':
        count = model.config.num_hidden_layers
        layers = list(range(count - config['layers'], count)) if config['layers'] != -1 else None
        targets = 'all-linear'
        if layers is not None:
            from transformers.pytorch_utils import Conv1D
            output_embedding = model.get_output_embeddings()
            # PEFT requires module suffixes, not all-linear or exact paths, to apply its layer filter.
            targets = sorted({name.rsplit('.', 1)[-1] for name, module in model.named_modules()
                              if isinstance(module, (torch.nn.Linear, Conv1D)) and module is not output_embedding})
        model = get_peft_model(model, LoraConfig(task_type=TaskType.CAUSAL_LM, r=config['rank'],
            lora_alpha=config['rank'] * 2, lora_dropout=0, bias='none', target_modules=targets,
            layers_to_transform=layers))
    else:
        model.requires_grad_(True)
    parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
    trainable = sum(parameter.numel() for parameter in parameters)
    total = sum(parameter.numel() for parameter in model.parameters())
    optimizer = torch.optim.AdamW(parameters, lr=config['learning_rate'])
    pad = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id
    if pad is None:
        raise ValueError('The tokenizer needs an existing pad or end-of-sequence token')
    collate = lambda rows: _batch(rows, pad, config['device'])
    loader = torch.utils.data.DataLoader(samples['train'], batch_size=config['batch_size'], shuffle=True,
                                        drop_last=True, collate_fn=collate, num_workers=0)
    metrics = {'trainable_parameters': trainable, 'total_parameters': total,
               'all_parameters_trainable': trainable == total, 'steps': [],
               'device': config['device'], 'dtype': 'float32', 'held_out_test_used': False,
               'validation_loss_before': _loss(model, samples['valid'], collate),
               'quality': 'NOT_EVALUATED', 'started_at': time.time()}
    model.train()
    iterator = iter(loader)
    for step in range(config['iterations']):
        try:
            batch = next(iterator)
        except StopIteration:
            iterator = iter(loader)
            batch = next(iterator)
        optimizer.zero_grad(set_to_none=True)
        loss = model(**batch).loss
        if not torch.isfinite(loss):
            raise ValueError('Nonfinite training loss; candidate was not published')
        loss.backward()
        torch.nn.utils.clip_grad_norm_(parameters, 1.0)
        optimizer.step()
        row = {'step': step + 1, 'loss': float(loss.detach().cpu())}
        metrics['steps'].append(row)
        print(json.dumps(row), flush=True)
    metrics.update(validation_loss_after=_loss(model, samples['valid'], collate), finished_at=time.time())
    destination = Path(config['output'])
    destination.mkdir(mode=0o700)
    model.save_pretrained(destination, safe_serialization=True)
    tokenizer.save_pretrained(destination)
    (destination / 'metrics.json').write_text(json.dumps(metrics, indent=2) + '\n')
    for path in destination.iterdir():
        if path.is_file():
            path.chmod(0o600)
    return metrics


def _tokens(messages, tokenizer, maximum):
    full = tokenizer.apply_chat_template(messages, tokenize=True)
    prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True)
    if len(full) > maximum or len(prompt) >= len(full) or full[:len(prompt)] != prompt:
        raise ValueError('Reviewed answer does not fit the context or chat template does not preserve the prompt prefix')
    return {'input_ids': full, 'labels': [-100] * len(prompt) + full[len(prompt):]}


def _batch(rows, pad, device):
    import torch
    width = max(len(row['input_ids']) for row in rows)
    return {key: torch.tensor(values, dtype=torch.long, device=device) for key, values in {
        'input_ids': [row['input_ids'] + [pad] * (width - len(row['input_ids'])) for row in rows],
        'attention_mask': [[1] * len(row['input_ids']) + [0] * (width - len(row['input_ids'])) for row in rows],
        'labels': [row['labels'] + [-100] * (width - len(row['labels'])) for row in rows],
    }.items()}


def _loss(model, samples, collate):
    import torch
    model.eval()
    total, count = 0.0, 0
    with torch.no_grad():
        for sample in samples:
            batch = collate([sample])
            scored = int((batch['labels'][:, 1:] != -100).sum())
            loss = float(model(**batch).loss.detach().cpu())
            if not math.isfinite(loss):
                raise ValueError('Nonfinite validation loss')
            total += loss * scored
            count += scored
    return total / count


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    train(json.loads(Path(args.config).read_text()))
