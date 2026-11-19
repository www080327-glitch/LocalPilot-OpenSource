# ITBench-AA R1 — aborted runtime-defect run

**Status: `ABORTED_FOR_RUNTIME_DEFECT`; no benchmark score.** This archive preserves the initial interrupted run separately from R2. Four scenarios reached failed terminal states at the same host cloud-egress size ceiling. A fifth candidate had started when execution was interrupted. The planned 40-case cohort was not completed.

## Planned study and actual stopping point

[study.json](study.json) declares the public `ArtificialAnalysis/ITBench-AA` scenarios at revision `76df38a82288f75ba9e41dc8c515033332497473`: 40 cases, one attempt per case, four concurrent cases, LocalPilot Core V5 with `gpt-6-luna` Responses and medium reasoning. Each task had 100 model steps, 200 tool calls, an 8,192-token output ceiling, and a 1,200-second task deadline, using Full permissions and the standard profile.

[ABORTED.json](ABORTED.json) records exit code **130** and the following stopping state:

| Bookkeeping item | Recorded count |
| --- | ---: |
| Planned scenarios | 40 |
| Candidates with a recorded start | 5: `case-001` through `case-005` |
| Final case-result receipts | 4: `case-001` through `case-004` |
| Started candidate interrupted without a final case-result receipt | 1: `case-005` |
| Planned cases without a recorded candidate start | 35 |

Setup files in other case directories do not establish that a candidate started. No final task status, answer validity, or complete usage is inferred for case 005 from the absence of its result receipt.

## Preserved failure receipts

The abort record identifies **`CloudEgressDenied` / `denied_size` at a hidden 131,072-byte (128 KiB) per-request ceiling**. The public task API exposes this as `error.code="runtime_error"`, `error.message="denied_size"`. The ceiling concerns the serialized outbound request, which grew as the model worked with evidence and tool results.

For all four cases, the case-result and compressed final-task receipts agree: `task_status/status="failed"`, `quiescent=true`, `output_valid=false`, `runtime_status="error"`, `engineering_status="incomplete"`, and `task_succeeded=false`. Each case-result also records `owned_core_stopped=true`.

| Case / scenario | Terminal receipts | Task seconds | Recorded model calls | Input tokens | Output tokens | Tool receipts |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 001 / Scenario-1 | [Case result](case-001/case-result.json), [task](case-001/candidate-task.json.gz) | 146.044 | 11 | 160,844 | 5,723 | 23 |
| 002 / Scenario-2 | [Case result](case-002/case-result.json), [task](case-002/candidate-task.json.gz) | 160.990 | 15 | 251,960 | 5,791 | 17 |
| 003 / Scenario-3 | [Case result](case-003/case-result.json), [task](case-003/candidate-task.json.gz) | 147.753 | 13 | 231,660 | 6,668 | 15 |
| 004 / Scenario-4 | [Case result](case-004/case-result.json), [task](case-004/candidate-task.json.gz) | 244.490 | 20 | 401,076 | 8,873 | 22 |
| **Four terminal cases only** | | | **59** | **1,045,540** | **27,055** | **77** |

Every recorded model call reports `gpt-6-luna`. Task seconds exclude the separately recorded input-download time; concurrent case durations must not be summed into elapsed study time. The token totals sum the recorded calls without adding their cache counters again. Those counters total 88,028 cache-hit and 957,512 cache-miss input tokens. The monetary API-cost field remains `UNKNOWN`.

All four `runtime_metrics.failed_attempts` values are zero. That model-attempt counter does not negate the explicit task failure caused by the subsequent host-egress rejection. These usage totals cover only the four terminal receipts; case 005's incomplete usage is excluded, so this is **not the entire aborted run's consumption or bill**.

## Source identity and archive scope

[source.json](source.json) records 110 source-file hashes with manifest SHA-256:

`7fb18d68f0bf0ee8bbaa4fc3bab5b7712b906f1644110105697fa1444a6fb70f`

The recorded `localpilot_service/desktop_sessions.py` hash is `0b9118b8f6c07c314779c96ca391cc10918f8f2795e437003f8fd0aa163c5131`; `agent/hybrid.py` is `a6e8324c6a2d8fda6a9e8cbb13c0a227a7fe84ff1f1fa2e7bb44aed59b4bceab`. These identify the runtime used here, before the separately identified follow-up run. This evidence is not assigned retrospectively to final source commit `91dd87c…` or the RC10 native package. The original study's “packaged Core” wording is retained in that receipt; the actual runner used real Core HTTP processes loaded from source.

[ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) lists the published receipts and excludes private service configurations and downloaded case workspaces. Its credential-scan result belongs to the export process. This report reviewed only R1 bookkeeping, source identity, terminal statuses, and usage metadata; it did not inspect R2 candidates, reference labels, keys, or private Core configuration. The abort record states that no reference labels were used.

## Interpretation

The four failures remain part of this **one aborted run**, with their actual calls and errors preserved. They expose a shared runtime ceiling; they are not four independent model-quality verdicts and must not be added to R2's case count. Case 005 remains an interrupted candidate without a final result.

No grader score is produced here. The planned cohort remains 40; it is not narrowed to four or five cases, and missing cases are not assigned invented outcomes. A separately identified full R2 run must retain its own complete cohort and failures under its declared protocol. R1 and R2 are not pooled, and no per-case best-of-attempt selection is justified by this archive. This report makes no official Artificial Analysis leaderboard claim.
