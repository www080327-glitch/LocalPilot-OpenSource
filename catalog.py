"""Curated MLX model metadata. Context limits come from upstream configs."""

MODELS = [
    {
        "id": "qwen3.5-4b", "name": "Qwen3.5 4B", "parameters_b": 4,
        "repo_id": "mlx-community/Qwen3.5-4B-4bit", "quantization": "4-bit",
        "revision": "0e7ffd5c629ef7719d4cbc04069232580bfa9d9c",
        "bits": 4, "backend": "mlx-vlm", "max_context_tokens": 262144,
        "architecture": "Qwen3_5ForConditionalGeneration", "context_source": "upstream config.json + tokenizer_config.json",
        "artifact_gb": 2.85, "active_parameters_b": 4, "capability_rank": 1, "capability_basis": "subjective product ordering",
    },
    {
        "id": "qwen3.5-9b", "name": "Qwen3.5 9B", "parameters_b": 9,
        "repo_id": "mlx-community/Qwen3.5-9B-4bit", "quantization": "4-bit",
        "revision": "8b2b98c00a6b4d291155e4890773ca8f769aee53",
        "bits": 4, "backend": "mlx-vlm", "max_context_tokens": 262144,
        "architecture": "Qwen3_5ForConditionalGeneration", "context_source": "upstream config.json + tokenizer_config.json",
        "artifact_gb": 5.57, "active_parameters_b": 9, "capability_rank": 2, "capability_basis": "subjective product ordering",
    },
    {
        "id": "qwen3.6-35b-a3b", "name": "Qwen3.6 35B-A3B", "parameters_b": 35,
        "repo_id": "mlx-community/Qwen3.6-35B-A3B-4bit", "quantization": "4-bit",
        "revision": "38740b847e4cb78f352aba30aa41c76e08e6eb46",
        "bits": 4, "backend": "mlx-lm", "max_context_tokens": 262144,
        "architecture": "Qwen3_5MoeForConditionalGeneration", "context_source": "upstream config.json + tokenizer_config.json",
        "artifact_gb": 19.03, "active_parameters_b": 3, "capability_rank": 3, "capability_basis": "subjective product ordering",
    },
    {
        "id": "qwen3.8-27b", "name": "Qwen3.8 27B", "parameters_b": 27,
        "repo_id": "mlx-community/Qwen3.8-27B-4bit", "quantization": "4-bit",
        "revision": "10c35caafbb80f7dc6a7a432cdd11af10a6d4818",
        "bits": 4, "backend": "mlx-vlm", "max_context_tokens": 262144,
        "architecture": "Qwen3_5ForConditionalGeneration", "context_source": "upstream config.json + tokenizer_config.json",
        "artifact_gb": 14.98, "active_parameters_b": 27, "capability_rank": 4, "capability_basis": "subjective product ordering",
    },
]

BITS = [4]
CONTEXT_LENGTHS = [16, 32, 48, 64, 96, 128, 192, 256]  # thousands of tokens
CONTEXT_LENGTHS_TOKENS = [value * 1024 for value in CONTEXT_LENGTHS]
