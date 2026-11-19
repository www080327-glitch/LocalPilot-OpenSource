# Qwen3.5-2B — fixed-source r2 diagnostic

## Result

The separately declared four-case diagnostic finished **2 PASS, 2 FAIL, 0 ERROR**. The real autonomous and prescribed child file-read cases passed after the worker admission and model-facing schema fixes. The complete child Shell cancellation/restart case and the Companion completed-task case did not pass. This batch was run once; no prompt or parameter was changed after inference began, and no additional attempt replaced a failure.

The tested source was Core **5.0.0b25** and Companion **0.5.7b6**. All 448 files in [SOURCE_FREEZE_CORRECTED.json](SOURCE_FREEZE_CORRECTED.json) matched before and after the run; manifest SHA256 is `d3d866d67ad9cf6f819d8e6786656e4f62265983c15caa3e0a7a8cc4e2333917`. The protocol was saved before inference at `2026-11-16T10:46:06Z`. Both owned Core and model processes stopped; the provider exited with code 0. The diagnostic process exited with code 1 to preserve the two failed cases.

[CORRECTED_PROTOCOL.json](CORRECTED_PROTOCOL.json) contains the complete fixed questions and conditions. [CORRECTED_SUMMARY.json](CORRECTED_SUMMARY.json) retains the task statuses, receipts, model usage, timings and failure interpretations. The runner is [corrected_defaults_diagnostic.py](corrected_defaults_diagnostic.py), SHA256 `58dd17b1336d13231a50f26a8a08551d56836812b79e3bcb03bfec4d09ed2581`.

## What changed between the source freezes

This was a product-fix check, not a controlled same-parameter model comparison. The earlier **7/9 integration**, **0/3 prescribed diagnostic**, and **10/32 public model subset** remain unchanged in [RESULTS.md](RESULTS.md).

The product now provides a 131,072-unit default worker admission ceiling. This diagnostic used production default parent/worker ceilings of **262,144 / 131,072**, compared with **100,000 / 32,768** in the original protocol. The prescribed prompts omitted `budget.tokens` so that the new default applied. Explicit old-budget behavior and configuration migration are separate code regressions, not additional real-model attempts in this batch. These conservative admission units are distinct from model context-token capacity.

The corrected wire schemas retain essential relative-path descriptions. When no cloud route is eligible, they no longer offer the cloud-only delegate `tier` field. Host validation still enforces the permission and route boundaries. Companion b6's native Linux helper change is in the source snapshot, but these HTTP model tasks do not exercise its native observation path.

The model, converted weights, embedded template, server binary and sampling were unchanged. The same controlled Q8_0 conversion of official [Qwen3.5-2B revision 15852e8c16360a2fea060d615a32b45270f8a8fc](https://huggingface.co/Qwen/Qwen3.5-2B/tree/15852e8c16360a2fea060d615a32b45270f8a8fc) ran on the CPU with two threads, one slot, an 8,192-token context and a 512-token request output limit. The declared non-thinking Main Agent profile remained temperature 1, top-p 1, top-k 20, min-p 0, presence penalty 2, repeat penalty 1 and seed 42. This batch tests Companion-to-Core delegation; it does not rerun the lightweight Companion adapter's temperature-0 task.

Main/worker step limits stayed at six/three and tool limits at eight/four. Each task had a 300-second limit; the Shell marker had to appear within 180 seconds of submission. The configured HTTP timeout remained 90 seconds, which is a transport setting rather than a proven total streaming deadline. One completed streamed request lasted 110.93 seconds.

## Four fixed cases

| Case | Result | Elapsed seconds | Actual observation |
|---|---:|---:|---|
| Original autonomous child prompt | PASS | 228.92 | A real local, read-only child performed its own complete `fact.txt` read. The child and parent completed, and the parent answer contained the full marker |
| Prescribed valid child file read | PASS | 212.00 | A real child performed the complete read and the parent completed with the marker; no marker truth was supplied in the prompt |
| Prescribed child Shell cancellation/restart | FAIL | 195.68 | A real child was created and its in-flight model request was cancelled, but no Shell marker or Shell receipt existed by the declared boundary. The restart branch was therefore not exercised |
| Prescribed Companion relative file read | FAIL | 282.03 | The physical read succeeded and the final answer contained the correct complete marker and evidence citation, but the host task ended `incomplete` after its step reserve was reached |

### Real child execution now proceeds past admission

The original budget defect entered final-only mode before a child's first tool opportunity. In both passing r2 cases, the actual child had a 131,072-unit ceiling and began in `exploring` phase. It produced a completed `read_file` receipt with `physical_read=true`, full-file coverage, and the correct file hash. This confirms the observed admission defect no longer blocked those real requests. It establishes a bounded single-local-model delegation path; it does not establish unrestricted task competence, multiple-model cooperation or cloud routing.

### Cancellation was real but did not cover the full Shell scenario

In the third case, the parent spent three model calls on `list_directory`, `file_info`, and then a valid local delegation with no cloud tier. The child began its first model request. At the 180-second marker boundary, the expected Shell file was still absent. The harness requested cancellation; parent and child became quiescent and cancelled. The child's interrupted model request had about 34.3 seconds of adapter wall time and no tool proposal or receipt. Provider token usage for that interrupted request remains unknown.

There was no executed child Shell, no UNKNOWN Shell effect and no second-append/no-replay check after a Core restart. The prescribed case therefore remains FAIL. The observed child model-request cancellation is a narrower result and must not be reported as passing child Shell cancellation and recovery.

### Correct Companion content does not change the declared completed-task oracle

Companion-to-Core made one physical `read_file` call and then reused its cached evidence three times. The final response contained the complete synthetic marker and its real source call identity; the final provider finish reason was `stop`, with 121 output tokens. It was not a length-truncated answer or a 300-second timeout.

However, the repeated calls consumed the exploration step allowance. The host entered finalization with `step_reserve`, and the task ended `incomplete`. The predeclared oracle requires `status=completed` as well as a complete read receipt and marker. The result remains FAIL; accepting the final text alone after seeing it would change the evaluation rule. This identifies a remaining completion/efficiency limitation even though the transport, physical read and final content worked.

## Measurement and retention limits

The provider ran for 920.97 seconds and its largest observed high-water RSS was 2,623,244 KiB, about 2.50 GiB. This is provider-only RSS. Timings include the shared cloud host environment, where lightweight desktop inspection could continue; no dedicated-hardware throughput claim is made. All model requests used the owned local server: cloud calls were zero, API spend was $0, and energy was unmeasured. Product telemetry that lacks provider usage or a configured monetary rate remains UNKNOWN.

Raw task, receipt, provider, runtime-event, protocol and source evidence is retained in a separate r2 archive, identified by [CORRECTED_PRIVATE_ARCHIVE_IDENTITY.json](CORRECTED_PRIVATE_ARCHIVE_IDENTITY.json). It excludes weights, KV binary cache, dependency environments, client credential files and complete service configuration. It does not overwrite the original private archive. No MMLU-Pro question was rerun; the 32-question result describes unchanged model settings and remains separate from these four product tasks.

This run does not complete physical Intel Mac qualification, Mac Qwen3.6-35B tasks, native Linux or Mac audio, native desktop SSE recovery, sleep/wake, multiple-model/cloud delegation, LoRA evaluation, or automatic persistent KV for generic external HTTP providers. Those require their own evidence.
