# Qwen3.5-2B real Linux qualification — original frozen source

## Outcome and scope

The first real-model integration batch finished **7 PASS, 2 FAIL, 0 ERROR**. A separately declared prescribed-argument diagnostic finished **0 PASS, 3 FAIL, 0 ERROR**. Both used Core **5.0.0b24** and Companion **0.5.7b5**, with the same frozen runtime source, official Qwen3.5-2B weights, and locally converted Q8_0 text model. All owned model and Core processes stopped after each batch. None of the original failures was replaced by a later attempt.

A separate fixed **32-question MMLU-Pro** model study finished **10 PASS, 22 FAIL, 0 ERROR**: 16 responses exhausted the 512-token output limit and 6 completed with an incorrect answer. The observed 31.25% applies only to that preselected, zero-shot subset. It is not the full benchmark, an Artificial Analysis score, an Agent ranking, or evidence of parity with a mainstream Agent.

The first batch ran from `2026-11-16T09:51:44Z` to `2026-11-16T10:16:58Z`; the prescribed diagnostic ran from `2026-11-16T10:18:19Z` to `2026-11-16T10:30:17Z`. All 448 files in [SOURCE_FREEZE.json](SOURCE_FREEZE.json) remained unchanged during both runs. Its SHA256 is `e6f6bf16864dff9c3f7e9dfc6691129cbbbdc2d4c5693357ce023db089a14316`.

These are real CPU model requests through the product Core/Companion backend code, with actual tool receipts, filesystem effects, SSE frames and controlled service restarts. The task inputs are synthetic. This is not acceptance of a packaged native application, native screen observation, system audio, or a physical Intel Mac. Companion b6 changes and later Core fixes are outside this frozen result.

## Model provenance and conditions

The source is [Qwen/Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B/tree/15852e8c16360a2fea060d615a32b45270f8a8fc), revision `15852e8c16360a2fea060d615a32b45270f8a8fc`, under Apache-2.0. Twelve source files were downloaded and checked against the repository's LFS SHA256 or Git blob identities. The 4,548,221,488-byte safetensors file has SHA256 `aa33250c4fc64891ddfaba3a314fd9542ea371843c387178b425fbcc5ed680b1`.

An unchanged official llama.cpp checkout at `b1b770d90d94cad9e9ea5b993bdbc383a522fb28` converted the text model to BF16 with MTP excluded. The matching official quantizer then produced Q8_0. The resulting 2,012,010,624-byte GGUF has SHA256 `a7b660a8c7a4de32753adbebf4815119995738f1426f4ec07e84763a1255d718`. This is a controlled local conversion of official weights, not an official Qwen GGUF release. Vision and speculative MTP were not tested. Full file and tool identities are in [MODEL_IDENTITY.json](MODEL_IDENTITY.json).

The shared Linux x86_64 host exposed about 9.73 GiB RAM and no swap. The server used CPU only, two decode threads, two prefill threads, one slot and an 8,192-token context. A smaller-model fallback was unnecessary. The embedded official Jinja template ran with reasoning off. Main Agent and direct model probes used the model card's non-thinking recipe: temperature 1, top-p 1, top-k 20, min-p 0, presence penalty 2, repeat penalty 1; seed 42 was a local reproducibility choice. Lightweight Companion retained its production temperature 0. Its sampling is therefore different from the Main Agent's.

The original integration allowed six main steps, eight main tool proposals and 512 output tokens per request. Admission accounting ceilings were 100,000 for the parent and 32,768 for a worker; these are the product's conservative admission units, not a claim of that many model context tokens. Worker limits were three steps and four tools. The original task wall limit was 150 seconds. The separately declared diagnostic used 300 seconds and a 180-second Shell-marker wait, without increasing the worker admission ceiling. The configured model HTTP timeout was 90 seconds; a streamed request exceeding 90 seconds was observed, so this value must not be described as a strict total streaming wall deadline. See [PROTOCOL.md](PROTOCOL.md).

## Original nine integration cases

| Case | Result | Elapsed seconds | Observed result |
|---|---:|---:|---|
| Fixed prompt/Skill KV cold, hot, restart | PASS | 19.87 | Explicit owned llama.cpp slot save and restore; cache reuse after a changed provider PID |
| Direct arithmetic | PASS | 0.79 | Answer `56`; provider usage present |
| Main Agent file read | PASS | 142.70 | Actual completed `read_file` receipt for `fact.txt`, full marker returned |
| Main Agent Shell write/readback | PASS | 96.33 | Actual `printf 7319` file effect, completed readback receipt and answer `7319` |
| Autonomous delegated child | FAIL | 150.78 | Model proposed local + `LIGHT`; host rejected it. No child was created; parent fallback calls did not satisfy the child oracle |
| Streaming cancellation and invalid cursor | PASS | 13.15 | Visible SSE text, then quiescent cancellation; invalid cursor returned real HTTP 409 |
| Interrupted Shell and Core restart | PASS | 55.70 | Partial append persisted with UNKNOWN effect; same idempotency key resolved to the same task after restart, without a second append |
| Lightweight Companion | PASS | 2.77 | Actual production local-HTTP backend answered `56`, with provider usage |
| Companion-to-Core file task | FAIL | 150.61 | Absolute path rejected, then a misspelled path and empty search; no complete delivered fact, task timed out |

The file-read oracle requires the completed physical read and the complete marker in the answer. It does not require bare-file output: the passing Main Agent answer added prose and a code block. The cancellation case tests the Core HTTP/SSE route, not the native desktop bridge's entire 409 recovery flow. Provider usage for an interrupted request can remain unknown; the report does not invent token usage for it. [INTEGRATION_SUMMARY.json](INTEGRATION_SUMMARY.json) contains the safe task, receipt, model-call and aggregate timing details.

### Cache, latency and resource observations

The cache probe used an actual fixed product prompt and Skill prefix with SHA256 `aff097d8a1a07d05ed4c5e2dee5e35ee590c68556f00e9e8c81ccbf3058648b4`. Of 1,280 prompt tokens, provider-reported cached tokens were **0 / 1,276 / 1,276** for cold / hot / after restart. The server saved and restored 1,281 slot tokens. Provider prefill time was **17,561.590 / 180.542 / 346.969 ms**, respectively. These measurements establish explicit persistence for this owned llama.cpp slot and fixed prefix; they do not implement automatic permanent KV for arbitrary external HTTP providers, all Skills, or a power-loss scenario.

The first visible SSE text arrived 12.133 seconds after Core submission. That measurement includes admission and queue time and is not provider-only TTFT. The largest sampled server high-water RSS was 2,683,416 KiB, approximately 2.56 GiB, excluding Core, Companion and the desktop. Provider-reported decode rates and timings remain in raw evidence; these shared CPU measurements are not dedicated-hardware throughput claims. All requests used the owned local server, so cloud API spend was $0. Energy was not measured.

## Separately prescribed diagnostic and corrected failure attribution

The three diagnostic prompts were declared before this second batch. They provide valid tool argument shapes without revealing the file marker. They are not autonomous-task successes and are not included in the nine-case total. [PRESCRIBED_SUMMARY.json](PRESCRIBED_SUMMARY.json) preserves all three failures.

| Case | Result | Elapsed seconds | Observation |
|---|---:|---:|---|
| Prescribed child file read | FAIL | 266.88 | A real local, read-only child was created, but the host entered final-only mode before its first model/tool attempt. No child read receipt existed |
| Prescribed child Shell cancel/restart | FAIL | 143.47 | Model again emitted local + `LIGHT` despite an instruction to omit tier. No child or Shell marker existed, so child cancellation/restart was not exercised |
| Prescribed Companion relative file read | FAIL | 300.92 | `read_file {"path":"fact.txt"}` succeeded. Two subsequent reads reused the evidence. Final delivery exhausted its bound and the task timed out |

The evidence exposed product issues; a blanket explanation that the model was too weak would be incorrect:

1. **The old worker admission default prevented exploration.** In the prescribed read case, child `1.1` had a 32,768-unit ceiling and a 20,924-unit delivery reserve. `FinalizingStarted` occurred with zero model attempts and zero admission charged. The first child request was already final-only, without tools. It generated 512 tokens but had no opportunity to read the file. This is a host-budget defect, not proof that the model refused or was unable to call a tool. [CHILD_ADMISSION_FINDING.json](CHILD_ADMISSION_FINDING.json) records the persisted budgets and event sequence.
2. **The compact model-facing file schema omitted the relative-path hint.** Initial triage inspected the full tool schema and attributed the absolute path to model noncompliance. Checking the actual compact schemas showed that parameter descriptions, including that hint, had been removed before the request. The original Companion failure therefore cannot be attributed solely to disregarding a visible instruction. This correction is retained here alongside the original failed outcome. The permission boundary should remain enforced.
3. **The local-only delegate schema offered a cloud-only tier.** Both the autonomous and prescribed cancel cases produced local + `LIGHT`, which the host correctly rejected. The protocol did not bypass this validation. A later product change can omit this unavailable field when no cloud route is eligible, while retaining host rejection for invalid input.

The relative-path diagnostic proves that Companion delegation reached a real Core tool and read the file. It does not prove successful end-to-end answer delivery. The two later evidence-cache reads are not additional independent file reads.

## Public model study

The MMLU-Pro subset was selected and frozen before inference from official revision `b189ec765aa7ed75c8acfea42df31fdae71f97be`: two questions from each of fourteen subjects plus four deterministic hash-selected questions, selection seed 20261116. Each question received exactly one request with a 512-token output limit and the declared non-thinking sampling profile. The thin runner reused the product `ServiceOpenAIBackend`; it did not replace the Agent implementation with another loop.

The protocol file SHA256 is `4ff714d10aff543d318699bd67bbc88b5c08c7496922ce25b024c17044331e07`. Raw provider responses, usage, finish reasons and elapsed times are retained privately. Questions, answer keys and raw model answers are excluded from this public evidence directory. **10/32** is the complete observed result; unfinished-by-token-limit answers remain failures. The small sample and short output budget cannot establish mainstream-model or mainstream-Agent parity. Model-only questions also do not test delegation, permissions, cancellation or desktop operation.

## Retention and subsequent work

The original raw archive contains 586 verified files: task/receipt/SSE/provider evidence, the two completed batch results, source and conversion identities, the frozen source snapshot, and the private public-study questions and responses. It excludes weights, dependency environments, KV binary caches, service credential files and full runtime databases. Archive SHA256 is `0cc5e04f5e6c597281ff0864d1bafe03986a0e876ec4b907208491073241c254`; size is 1,555,088 bytes. [PRIVATE_ARCHIVE_IDENTITY.json](PRIVATE_ARCHIVE_IDENTITY.json) records its identity. It must not be added to the public Git repository.

The earlier Qwen2.5-0.5B result remains 5 PASS / 4 FAIL in its separate original evidence. Different models, sampling and strengthened receipt checks do not constitute a controlled leaderboard comparison.

Later fixes and a separately declared four-case diagnostic use a different source freeze and revised production admission defaults. Their results must be published separately; they cannot change the original **7/9**, **0/3**, or **10/32** outcomes in this report. Physical Intel Mac, Mac Qwen3.6-35B, cloud/multiple-model delegation, native audio/TCC, sleep/wake, LoRA quality and automatic generic HTTP persistent KV are not established by these runs.
