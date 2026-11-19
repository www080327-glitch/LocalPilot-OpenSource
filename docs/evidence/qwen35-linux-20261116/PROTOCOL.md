# Qwen3.5-2B Linux integration protocol

Declared before the first inference run on 2026-11-16. This is a real local model integration check with synthetic input files, not a public benchmark, AA score, or a comparison with mainstream agents.

## Model and runtime identity

- Source: [Qwen/Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B/tree/15852e8c16360a2fea060d615a32b45270f8a8fc), revision `15852e8c16360a2fea060d615a32b45270f8a8fc`.
- Original safetensors: 4,548,221,488 bytes, SHA256 `aa33250c4fc64891ddfaba3a314fd9542ea371843c387178b425fbcc5ed680b1`.
- Conversion: unmodified official llama.cpp source at `b1b770d90d94cad9e9ea5b993bdbc383a522fb28`; text-only BF16 GGUF, followed by its matching official `llama-quantize` binary to Q8_0. Vision projector and speculative MTP are outside this test.
- The resulting GGUF is a local controlled conversion of official weights. It is not an official Qwen GGUF release.
- Runtime: official llama.cpp build `b12359`, CPU only, 2 generation threads, 2 prefill threads, 1 slot, 8,192 context tokens. Source files and converted files must be hashed before running.

## Sampling and budgets

Main Agent and direct provider probes use the model card's [non-thinking text settings](https://huggingface.co/Qwen/Qwen3.5-2B/blob/15852e8c16360a2fea060d615a32b45270f8a8fc/README.md): temperature 1.0, top-p 1.0, top-k 20, min-p 0, presence penalty 2.0, repeat penalty 1.0. Seed 42 fixes the local test's sampling seed; it is a reproducibility choice rather than a Qwen recommendation. The embedded official Jinja template is enabled with reasoning off.

The lightweight Companion uses its unchanged production HTTP adapter, which sends temperature 0. Other sampler settings inherit the same owned server's defaults. Companion-to-Core delegation uses the Core route's sampling profile. These three paths do not have identical effective sampling parameters.

Existing integration budgets stay at 6 main steps, 8 tool proposals, 512 output tokens per model request, 2 children per turn, and child ceilings of 3 steps and 4 tools. Model HTTP timeout is 90 seconds; task timeout is 150 seconds. This deliberately short integration protocol does not use Qwen's much larger benchmark output budgets and cannot measure the model's full problem-solving ability.

## Cases and evidence

The existing nine task prompts remain unchanged: fixed real prompt/Skill prefix cache; integer arithmetic; file reading; Shell write plus readback; a real delegated child reading a file; streaming cancellation and HTTP 409 for an invalid cursor; interrupted Shell receipt persistence across Core restart; lightweight Companion; and Companion-to-Core file delegation.

File-related cases require completed read receipts for the requested file and the exact synthetic marker in the final answer. The child case requires a completed child with its own completed read receipt. A claimed read without a receipt fails. The Shell case additionally checks the real output file. Cancellation must reach a quiescent cancelled task, and invalid SSE cursors must return HTTP 409. The interrupted Shell case checks UNKNOWN effects, retained receipts, idempotent resubmission, and no second file append.

KV evidence distinguishes cold, hot, and explicitly saved/restored llama.cpp slot state after a provider restart. A passing result applies only to this owned server and prompt. It does not establish automatic persistent KV for generic HTTP providers, arbitrary prompts, power loss, or other models.

Raw provider responses, tasks, receipts, SSE frames, logs, command arguments, hashes, provider-reported usage/timings, and final process cleanup are retained. The first visible SSE text timing includes Core admission and queue time; it is not provider-only TTFT. Process high-water RSS is read from Linux `/proc` before exit. API spend is $0 because the owned CPU server makes no cloud requests; energy is unmeasured.

The earlier Qwen2.5-0.5B outcome remains 5 PASS and 4 FAIL in its original evidence directory. Different weights, model-specific sampling, and stricter receipt checks prevent treating the two runs as a controlled model leaderboard comparison. Any failed or aborted Qwen3.5 run must remain separately named and visible. A rerun requires a concrete implementation or environment issue, recorded before rerunning.
