"""Text-only local inference process. Never accepts tools, paths to edit, or commands."""
import contextlib
import hashlib
import json
from pathlib import Path
import sys
import time
import os
import threading


def validate_request(data):
    """Reject malformed/non-text requests before loading any model weights."""
    if not isinstance(data, dict) or set(data) - {"messages", "max_tokens", "schema", "stream"}:
        raise ValueError("Unsupported model request fields")
    if "stream" in data and type(data["stream"]) is not bool:
        raise ValueError("Stream must be boolean")
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages or len(messages) > 128:
        raise ValueError("Messages must be a nonempty bounded list")
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise ValueError("Only role/content text messages are supported")
        if message["role"] not in {"system", "user", "assistant"} or not isinstance(message["content"], str):
            raise ValueError("Only system/user/assistant text messages are supported")
        if message["role"] == "system" and index != 0:
            raise ValueError("System message must be first")
    if not any(message["role"] == "user" for message in messages):
        raise ValueError("A user message is required")
    if type(data.get("max_tokens")) is not int or not 1 <= data["max_tokens"] <= 8192:
        raise ValueError("Invalid output token budget")
    if data.get("schema") not in {None, "active", "route", "support"}:
        raise ValueError("Unsupported output schema")
    return data


def watch_parent(parent_pid, interval=1):
    def monitor():
        while True:
            if os.getppid() != parent_pid:
                # Includes a parent killed during a long generation, not only EOF.
                os._exit(0)
            time.sleep(interval)
    threading.Thread(target=monitor, daemon=True, name="companion-parent-monitor").start()


def main():
    model = tokenizer = None
    watch_parent(int(sys.argv[3]) if len(sys.argv) > 3 else os.getppid())
    model_path, context_tokens = Path(sys.argv[1]), int(sys.argv[2])
    config = json.loads((model_path / "config.json").read_text())
    if config.get("model_file") or config.get("auto_map"):
        raise ValueError("Custom model code is not permitted")
    request_number = 0
    for line in sys.stdin:
        request_number += 1
        stage = "request_validation"
        try:
            data = validate_request(json.loads(line))
            cold = model is None
            with contextlib.redirect_stdout(sys.stderr):
                stage = "model_load"
                import mlx.core as mx
                from mlx_lm import load, stream_generate
                from mlx_lm.models.cache import make_prompt_cache
                from mlx_lm.sample_utils import make_sampler
                load_start = time.perf_counter()
                if model is None:
                    model, tokenizer = load(str(model_path), tokenizer_config={"trust_remote_code": False})
                load_seconds = time.perf_counter() - load_start if cold else 0
                stage = "chat_template"
                prompt = tokenizer.apply_chat_template(data["messages"], tokenize=False, add_generation_prompt=True, enable_thinking=False)
                tokens = len(tokenizer.encode(prompt))
                stage = "token_budget"
                if tokens + data["max_tokens"] > context_tokens:
                    raise ValueError("Prompt exceeds configured token budget")
                mx.reset_peak_memory()
                start = time.perf_counter()
                parts, last = [], None
                # No KV or recurrent-state reuse across sessions, including the
                # first request after reload. Make the existing MLX default explicit.
                options = {"prompt_cache": make_prompt_cache(model)}
                stage = "output_constraint"
                if data.get("schema"):
                    from companion.model.structured import mlx_processor
                    options["logits_processors"] = [mlx_processor(tokenizer, data["schema"], data["max_tokens"])]
                stage = "generation"
                for response in stream_generate(model, tokenizer, prompt, max_tokens=data["max_tokens"], sampler=make_sampler(temp=0), **options):
                    if data.get("stream") and not data.get("schema") and response.text:
                        sys.__stdout__.write(json.dumps({"event":"delta", "text":response.text}, ensure_ascii=False) + "\n")
                        sys.__stdout__.flush()
                    parts.append(response.text)
                    last = response
                result = {"status": "ok" if last and last.finish_reason == "stop" else "truncated", "text": "".join(parts).strip(), "finish_reason": last.finish_reason if last else None, "prompt_tokens": tokens, "generation_tokens": last.generation_tokens if last else 0, "generation_seconds": time.perf_counter() - start, "load_seconds": load_seconds, "mlx_active_bytes": mx.get_active_memory(), "mlx_peak_bytes": mx.get_peak_memory()}
                result["constraint"] = "finite_token_language" if data.get("schema") else "none"
                result.update(prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                              chat_template_sha256=hashlib.sha256(str(tokenizer.chat_template).encode()).hexdigest(),
                              sampling_temperature=0, enable_thinking=False, cache_policy="fresh_per_request")
        except Exception as exc:
            result = {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}", "error_stage": stage}
        result.update(worker_pid=os.getpid(), worker_request_number=request_number)
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
