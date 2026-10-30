"""Reproducible schema/prompt size report; never download or load a model."""

import argparse
import hashlib
import json
import math
from pathlib import Path

from .profiles import PROMPT_PROFILES, TOOL_PROFILES


def measure_tool_budget(schemas, prompt, tokenizer=None):
    serialized = json.dumps(schemas, ensure_ascii=False, separators=(",", ":"))
    schema_bytes, prompt_bytes = len(serialized.encode("utf-8")), len((prompt or "").encode("utf-8"))
    result = {
        "tool_count": len(schemas), "schema_utf8_bytes": schema_bytes,
        "prompt_utf8_bytes": prompt_bytes,
        "schema_tokens": None, "prompt_tokens": None,
        "estimated_schema_tokens_bytes_div_4": math.ceil(schema_bytes / 4),
        "estimated_prompt_tokens_bytes_div_4": math.ceil(prompt_bytes / 4),
        "token_count_status": "estimate_only_without_tokenizer",
        "scope": "Compact JSON schemas and raw prompt; excludes provider framing, chat template, task and history.",
    }
    if tokenizer is not None:
        result.update(schema_tokens=len(tokenizer.encode(serialized, add_special_tokens=False).ids),
                      prompt_tokens=len(tokenizer.encode(prompt or "", add_special_tokens=False).ids),
                      token_count_status="exact_raw_text_with_supplied_tokenizer")
    return result


def main(argv=None):
    from .registry import create_default_registry

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--tokenizer-json", help="Existing local tokenizer.json; optional tokenizers library, no network.")
    parser.add_argument("--output", help="Optional JSON report path.")
    args = parser.parse_args(argv)
    tokenizer = None
    if args.tokenizer_json:
        from tokenizers import Tokenizer
        tokenizer = Tokenizer.from_file(args.tokenizer_json)
    report = {"version": "v0.1-independent-profiles", "tokenizer": None, "profiles": {}}
    if args.tokenizer_json:
        path = Path(args.tokenizer_json)
        report["tokenizer"] = {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                               "cache_model": path.parents[2].name, "revision": path.parent.name}
    for profile, prompt in PROMPT_PROFILES.items():
        for tools in TOOL_PROFILES:
            registry = create_default_registry(args.workspace, tool_profile=tools)
            report["profiles"][f"{profile}/{tools}"] = measure_tool_budget(registry.schemas(), prompt, tokenizer)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
