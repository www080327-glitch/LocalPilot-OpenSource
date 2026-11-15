"""Plan or explicitly run existing MLX-LM training on reviewed local examples."""
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from companion.config import PrivateData
from companion.observers.events import redact_text
from companion.observers.files import read_regular_file

MLX_REQUIREMENT = "mlx-lm[train]==0.31.3"
MLX_SOURCE = "https://github.com/ml-explore/mlx-lm/blob/ed1fca4cef15a824c5f1702c80f70b4cffc8e4dd/mlx_lm/lora.py"


def prepare(model, dataset, output, *, method="lora", iterations=100, rank=8, layers=None,
            max_seq_length=2048, batch_size=1, seed=17, learning_rate=1e-5):
    layers = (-1 if method == "full" else 4) if layers is None else layers
    model, dataset, output, manifest, model_config, base_config_sha256 = _inputs(
        model, dataset, output, method, iterations, rank, layers, max_seq_length, batch_size, seed, learning_rate)
    private = PrivateData(output)
    config = {"model":str(model), "data":str(dataset), "train":True, "test":False,
              "fine_tune_type":method, "adapter_path":str(output / "adapters"), "seed":seed,
              "num_layers":layers, "batch_size":batch_size, "iters":iterations,
              "learning_rate":learning_rate, "max_seq_length":max_seq_length, "val_batches":-1,
              "steps_per_report":min(10, iterations), "steps_per_eval":min(50, iterations),
              "save_every":min(50, iterations), "grad_checkpoint":True, "mask_prompt":True,
              "lora_parameters":{"rank":rank, "scale":rank*2, "dropout":0.0},
              "report_to":None}
    # JSON is valid YAML, and keeps planning independent of the optional trainer.
    config_path = private.write("training-config.json", json.dumps(config, indent=2) + "\n")
    checks = readiness()
    plan = {"schema":"companion-training-run-v1", "status":"not_run", "training":"NOT_RUN",
            "quality":"NOT_EVALUATED", "model_promoted":False, "created_at":time.time(),
            "model":str(model), "model_type":model_config.get("model_type", "UNKNOWN"),
            "model_weights_verified":False, "dataset":str(dataset), "output":str(output),
            "base_config_sha256":base_config_sha256,
            "dataset_sha256":manifest["sha256"], "counts":manifest["counts"],
            "manifest_sha256":hashlib.sha256((dataset / "manifest.json").read_bytes()).hexdigest(),
            "config":config, "command":[sys.executable, "-m", "mlx_lm", "lora", "--config", str(config_path)],
            "offline":True, "requirements":MLX_REQUIREMENT, "readiness":checks,
            "token_budget":"NOT_RUN", "base_model_modification":False,
            "trainer_interface_source":MLX_SOURCE, "custom_tokenizer_code":"not_supported"}
    plan["training_scope"] = "lora_selected_transformer_layers" if method == "lora" else "dense_selected_transformer_layers_not_embedding_or_head"
    private.write("run.json", json.dumps(plan, indent=2) + "\n")
    return plan


def readiness():
    try:
        version = importlib.metadata.version("mlx-lm")
    except importlib.metadata.PackageNotFoundError:
        version = None
    missing = [name for name in ("mlx", "transformers", "yaml", "tqdm") if importlib.util.find_spec(name) is None]
    supported_host = sys.platform == "darwin" and platform.machine() == "arm64"
    ready = supported_host and version == "0.31.3" and not missing
    return {"ready":ready, "apple_silicon_macos":supported_host, "mlx_lm_version":version,
            "version_in_supported_range":version == "0.31.3", "missing_modules":missing,
            "reason":"ready_for_explicit_training" if ready else "local_training_prerequisites_missing"}


def execute(plan):
    private = PrivateData(plan["output"])
    if not plan["readiness"]["ready"]:
        return plan
    try:
        plan["token_budget"] = _token_budget(plan)
    except (ValueError, OSError, ImportError) as error:
        plan.update(status="not_run", reason="tokenizer_preflight_failed", error=redact_text(str(error))[:800])
        private.write("run.json", json.dumps(plan, indent=2) + "\n")
        return plan
    if not plan["token_budget"]["fits"]:
        plan.update(status="not_run", reason="training_examples_exceed_context_budget")
        private.write("run.json", json.dumps(plan, indent=2) + "\n")
        return plan
    environment = os.environ | {"HF_HUB_OFFLINE":"1", "TRANSFORMERS_OFFLINE":"1", "HF_DATASETS_OFFLINE":"1",
        "HF_HUB_DISABLE_TELEMETRY":"1", "WANDB_MODE":"disabled", "WANDB_DISABLED":"true"}
    plan.update(status="running", training="RUNNING", started_at=time.time())
    private.write("run.json", json.dumps(plan, indent=2) + "\n")
    logfile = private.file("training.log")
    fd = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as log:
            result = subprocess.run(plan["command"], env=environment, stdout=log, stderr=subprocess.STDOUT, check=False)
        plan.update(exit_code=result.returncode, status="completed" if result.returncode == 0 else "failed",
                    training="COMPLETED" if result.returncode == 0 else "FAILED")
    except KeyboardInterrupt:
        plan.update(status="interrupted", training="INTERRUPTED", exit_code=130)
    except OSError as error:
        plan.update(status="failed", training="FAILED", error=redact_text(str(error))[:800])
    plan.update(finished_at=time.time(), log=str(logfile))
    weights = private.root / "adapters" / "adapters.safetensors"
    if plan["status"] == "completed":
        if not weights.is_file() or not weights.stat().st_size:
            plan.update(status="failed", training="FAILED", reason="trainer_did_not_produce_weights")
        else:
            with weights.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            plan["trained_weights"] = {"path":str(weights), "bytes":weights.stat().st_size, "sha256":digest}
            adapter_config = weights.parent / 'adapter_config.json'
            if not adapter_config.is_file():
                plan.update(status='failed', training='FAILED', reason='trainer_did_not_produce_adapter_config')
            else:
                plan['adapter_config_sha256'] = hashlib.sha256(adapter_config.read_bytes()).hexdigest()
                plan['candidate_config'] = {'backend':'mlx', 'model_path':plan['model'],
                                            'model_adapter_path':str(weights.parent)}
    private.write("run.json", json.dumps(plan, indent=2) + "\n")
    return plan


def _inputs(model, dataset, output, method, iterations, rank, layers, max_seq_length, batch_size, seed, rate):
    if method not in {"lora", "full"}:
        raise ValueError("Use lora or full; reinforcement learning is not implemented by this launcher")
    for name, value, minimum, maximum in (("iterations", iterations, 1, 1000000), ("rank", rank, 1, 128),
        ("layers", layers, -1, 512), ("max_seq_length", max_seq_length, 128, 131072),
        ("batch_size", batch_size, 1, 128), ("seed", seed, 0, 2**32-1)):
        if type(value) is not int or not minimum <= value <= maximum or (name == "layers" and value == 0):
            raise ValueError("Invalid training " + name)
    if type(rate) not in (int, float) or not math.isfinite(rate) or not 0 < rate <= .01:
        raise ValueError("Invalid learning rate")
    model, dataset, output = (Path(os.path.abspath(os.path.expanduser(value))) for value in (model, dataset, output))
    if not model.is_dir() or not dataset.is_dir():
        raise ValueError("Use existing local model and reviewed dataset directories; downloads are not started")
    if output.exists() or output.is_relative_to(model) or model.is_relative_to(output) or output.is_relative_to(dataset) or dataset.is_relative_to(output):
        raise ValueError("Choose a new output directory separate from the base model and dataset")
    model_bytes, _ = read_regular_file(model / "config.json", 1024*1024)
    model_config = json.loads(model_bytes)
    if not isinstance(model_config, dict) or not any(model.glob("*.safetensors")):
        raise ValueError("The local model requires config.json and safetensors weights")
    tokenizer_bytes, _ = read_regular_file(model / "tokenizer_config.json", 1024*1024)
    tokenizer_config = json.loads(tokenizer_bytes)
    # 0.31.3 hard-codes tokenizer trust_remote_code=True; no config flag overrides it.
    if not isinstance(tokenizer_config, dict) or model_config.get("auto_map") or tokenizer_config.get("auto_map"):
        raise ValueError("This MLX version requires a standard local tokenizer without custom auto_map code")
    if method == "full" and (model_config.get("quantization") or model_config.get("quantization_config")):
        raise ValueError("Full training requires unquantized base weights; use lora for a quantized model")
    manifest_bytes, _ = read_regular_file(dataset / "manifest.json", 8*1024*1024)
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict) or manifest.get("schema") != "companion-reviewed-training-v1" or not isinstance(manifest.get("sha256"), dict) or not isinstance(manifest.get("counts"), dict):
        raise ValueError("Use a Companion reviewed training export")
    for split in ("train", "valid"):
        filename = split + ".jsonl"
        content, _ = read_regular_file(dataset / filename, 64*1024*1024)
        if hashlib.sha256(content).hexdigest() != manifest["sha256"].get(filename):
            raise ValueError("Dataset hash no longer matches the reviewed export: " + filename)
        rows = [json.loads(line) for line in content.decode("utf-8").splitlines() if line.strip()]
        if not rows or len(rows) != manifest["counts"].get(split) or len(rows) < batch_size:
            raise ValueError("Each reviewed split must contain at least one complete batch")
        for row in rows:
            messages = row.get("messages") if isinstance(row, dict) else None
            if (not isinstance(messages, list) or len(messages) != 3 or
                    [message.get("role") for message in messages if isinstance(message, dict)] != ["system", "user", "assistant"] or
                    any(not isinstance(message.get("content"), str) or not message["content"].strip() for message in messages)):
                raise ValueError("Training rows require complete system/user/reviewed-answer messages")
    return model, dataset, output, manifest, model_config, {
        'config.json':hashlib.sha256(model_bytes).hexdigest(),
        'tokenizer_config.json':hashlib.sha256(tokenizer_bytes).hexdigest()}


def _token_budget(plan):
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(plan["model"], local_files_only=True, trust_remote_code=False)
    longest, overflow, unscored = 0, 0, 0
    for split in ("train", "valid"):
        for line in (Path(plan["dataset"]) / (split + ".jsonl")).read_text().splitlines():
            messages = json.loads(line)["messages"]
            tokens = tokenizer.apply_chat_template(messages, return_dict=False)
            prompt = tokenizer.apply_chat_template(messages[:-1], add_generation_prompt=True, return_dict=False)
            longest = max(longest, len(tokens))
            overflow += len(tokens) > plan["config"]["max_seq_length"]
            unscored += len(prompt) >= len(tokens)
    return {"fits":not overflow and not unscored, "max_tokens":longest,
            "overlong_examples":overflow, "examples_without_target_tokens":unscored}


def main():
    parser = argparse.ArgumentParser(description="Prepare or explicitly execute local Companion LoRA/full training")
    parser.add_argument("--model", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--method", choices=["lora", "full"], default="lora")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--layers", type=int, help="Default: 4 for LoRA, all Transformer layers for full")
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--execute", action="store_true", help="Start training using the existing local MLX installation")
    args = parser.parse_args()
    try:
        plan = prepare(args.model, args.data, args.output, method=args.method, iterations=args.iterations,
                       rank=args.rank, layers=args.layers, max_seq_length=args.max_seq_length,
                       batch_size=args.batch_size, seed=args.seed, learning_rate=args.learning_rate)
        if args.execute:
            plan = execute(plan)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        if args.execute and plan["status"] != "completed":
            return 2
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"status":"error", "error":redact_text(str(error))[:800]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
