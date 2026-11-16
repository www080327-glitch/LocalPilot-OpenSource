# Actual model integration results — 2026-11-17

## Status and scope

The completed receipts demonstrate actual GPT-6 Luna Responses requests, function-result round trips, streamed text, Core tool execution, child execution, cancellation, restart lookup, ordinary Companion clients, and both directions of local/cloud delegation. These are bounded integration checks with small synthetic tasks. They do not establish general task quality, an autonomous-work success rate, a public benchmark score, or final native-package qualification.

This report was prepared by independently reading the archived receipts and verifying their hashes. It did not launch another model request, inspect an API key, read benchmark reference answers, or inspect the active soak or benchmark output.

| Work item | Status at this report's preparation | Claim supported here |
| --- | --- | --- |
| Luna HTTP, function round trip, and streaming | PASS | The actual configured provider path returned usable responses and tool results. |
| Core smoke checks | 3/3 PASS | Shell/read, a genuine child read, and restart lookup of the same completed task. |
| Parallel child Shells | PASS | Two completed child processes overlapped for 4.663 seconds. |
| Child and stream cancellation | R1 ERROR; R2 PASS | First-run rate-limit errors are retained; cancellation was measured in the second run. |
| Companion reasoning and execution clients | 2/2 PASS | Ordinary client submission/retrieval completed, with a read receipt on the execution path. |
| Heterogeneous delegation | 2/2 PASS within the stated scope | Actual local and cloud child reads; the local-parent run later switched its parent to cloud. |
| [Finite engineering acceptance](engineering-luna-r1/RESULTS.md) | PASS | Frozen `91dd87c` Core; two genuine async children; original external 17 tests and four CLI cases passed. |
| Original two-hour soak R1 | **INCOMPLETE: execution-session continuity lost** | 210 heartbeats, last observed 6,270.103 seconds; no terminal receipt or finished marker. |
| Final-source two-hour soak R3 | **RUNNING** | Fresh 7,200-second run from `91dd87c`; its time is not added to R1. |
| Forty public ITBench-AA cases | **RUNNING** | No score, grading result, or completion claim yet. |
| Final native package | **PASS for build and extracted-package UI verification** | Separate [final-package evidence](../../../../desktop/docs/evidence/audit-20261117-desktop/final-package/RESULTS.md); these earlier model runs remain source-based. |

The root owner will append the completed long-run and benchmark evidence separately. [Benchmark R1](itbench-aa-r1/ABORTED.json) was aborted after four terminal `CloudEgressDenied` failures at the hidden 131,072-byte ceiling; a fifth started case was interrupted. That historical runtime defect and its receipts are distinct from R2's timeout-unit error and remain preserved. No score is assigned to the aborted R1 run.

The frozen ITBench study's phrase `packaged Core HTTP` is historical wording: the candidate service actually loads Core from the frozen `qualification-source-r2` through `PYTHONPATH`. Its source manifest identifies that snapshot. It is not a model run from the installed RC10 DEB; the frozen study is retained unchanged.

The initial long-run executor handles later disappeared together and their progress files stopped updating. [The independently reviewed interrupted-soak archive](cloud-soak-2h-r1-interrupted/RESULTS.md) preserves the 210 heartbeats and missing completion evidence; the cause is unknown and no application-permission cause has been established. A fresh, full 7,200-second soak now uses the final frozen source. Its future result must stand on its own.

ITBench R2 also encountered dataset-download `URLError` / tunnel 403 failures before some candidates started, plus two candidates whose executing sessions lost continuity. The unmodified original runner is being resumed: existing terminal receipts are reused, previously started unfinished candidates are retained as interrupted without another model attempt, and only never-started remaining candidates begin. A separately declared transport continuation will address only the original download failures that never started a model. No grading has begun, and these pending steps carry no score claim.

## Evidence integrity and source identity

All **49 entries** in [MANIFEST-initial.json](MANIFEST-initial.json) matched both their recorded byte counts and SHA-256 values. The manifest deliberately excludes the running soak and ITBench work. Its `credential_value_found: false` is the exporting process's recorded scan result, rather than a new credential audit by this report.

The manifest's own SHA-256 is `8b4cbf3957a8f2dd6e582623a7d2a16b94046e348513944dba4214cd5ea9746b`. These later additions were read separately and are not retroactively represented as members of that initial manifest:

| Additional receipt | SHA-256 |
| --- | --- |
| [suite-regression-r2.log](suite-regression-r2.log) | `710cb76cd230bcb72c581256dcfe6bcc67361f95d72068631af42ac465b482c1` |
| [SOURCE_PUBLICATION.json](SOURCE_PUBLICATION.json) | `64f254299705feed29ff30148e3a6906ba4fa0916c36e1aa66cfdd5b3b237098` |
| [frozen-openai-grading-r1.log](frozen-openai-grading-r1.log) | `56fc9078696ab4a24fd10fb228a3e41149a94bcba37d1ff1d40373f666ce073e` |

### Source snapshots used by the actual model runs

The Core runners use real service processes loaded from source through `PYTHONPATH`. A service version banner does not make these packaged-binary tests. Each run's `RESULTS.json` includes a 110-file source manifest; the recorded aggregate hashes distinguish the tested snapshots:

| Actual run | Recorded source manifest SHA-256 |
| --- | --- |
| [Core smoke R1](cloud-smoke-r1/RESULTS.json) | `1feb0270264c716c7e1fef13908bfa0f6331b4a0531538e377645e9bb1cc77f1` |
| [SuperAgent R1](cloud-superagent-r1/RESULTS.json) | `7fb18d68f0bf0ee8bbaa4fc3bab5b7712b906f1644110105697fa1444a6fb70f` |
| [SuperAgent R2](cloud-superagent-r2/RESULTS.json) | `7fb18d68f0bf0ee8bbaa4fc3bab5b7712b906f1644110105697fa1444a6fb70f` |
| [Cloud parent / local child](heterogeneous-cloud-parent-r1/RESULTS.json) | `7fb18d68f0bf0ee8bbaa4fc3bab5b7712b906f1644110105697fa1444a6fb70f` |
| [Local parent / cloud child](heterogeneous-local-parent-r1/RESULTS.json) | `7fb18d68f0bf0ee8bbaa4fc3bab5b7712b906f1644110105697fa1444a6fb70f` |

Only `localpilot_service/desktop_sessions.py` differs between those two recorded file maps: smoke used `b28fffe5bc3388a786d57aaba344a0686821b5286b3a37c72bf3b18d48415154`; the later runs used `0b9118b8f6c07c314779c96ca391cc10918f8f2795e437003f8fd0aa163c5131`. All five manifests record the following shared implementation hashes:

| File | SHA-256 at those runs |
| --- | --- |
| `agent/openai_responses.py` | `10a07af342ebed9e7041d5d21062e30a67ed45a220ca8b0dfe24a73f4d353d4b` |
| `agent/session.py` | `21d063687674e0cd69b1918c7eea60ca081d9a536768ab89f8db972a1bf6d6a3` |
| `agent/child_sessions.py` | `738ba86bbc33e525232db5779bf7394c23efe57b39df41ea96c5b89824cf416f` |
| `scripts/qualify_openai_agent.py` | `633d2d9019caf7065dae46396b6b5e619cb15ce293f9f59c56648cd256da895a` |

The final source publication is a later identity. [SOURCE_PUBLICATION.json](SOURCE_PUBLICATION.json) records remote commit `91dd87c6fd4678c103d6383dec1c1385deb38f9a` and local commit `e34532c1969b6494d0eba8918d84695d14fe12c6` with identical Git tree `c19b18071de42ed42feb25519671a559f38dec18`. The local commit/tree relationship was also checked directly for this report. The root owner subsequently ran the 38-test frozen-source check from a clean checkout of that remote commit. That check is additional evidence; it does not change the source identities of the earlier actual API runs or establish that they ran the final RC10 native package.

[Generated Runtime reconstruction patches](runtime-source-reconstruction/README.md) now preserve the exact R1 and R2 bytes that differ from `91dd87c` within each recorded 110-file subset. Actual `git apply` followed by all-file hash checks reproduced both manifests, 110/110. This restores the recorded Runtime subset, not a complete historical Desktop tree or dependencies; the missing intermediate smoke bytes are not invented.

## Actual provider protocol checks

The preflight in [openai-preflight.json](openai-preflight.json) returned HTTP 200, `completed`, and reported model `gpt-6-luna`. The provider reported 15 input and 11 output tokens.

The previous Chat Completions path did **not** pass the requested Luna medium-reasoning/function case. [openai-chat-before.json](openai-chat-before.json) records `LocalBackendError`, HTTP 400, and the earlier adapter hash `54bb01b3bb32919513d63de2888ebe5ce03e641b1e8ecf6c19430d0451573846`. This historical protocol failure remains in the archive.

[openai-responses-live-r1.json](openai-responses-live-r1.json) records the actual Responses replacement check:

- Configured model `gpt-6-luna`, reasoning effort `medium`, with the Responses adapter hash recorded above.
- The first request returned a real `public_fixture_echo` function call: 68 input / 24 output tokens.
- After the fixture tool result was returned, the second request completed: 110 input / 10 output tokens, with **six text chunks** observed.
- The two-request check passed in **21.713 seconds**. Both responses reported the requested model.

These tiny requests reported zero reasoning tokens. Setting `medium` and completing this round trip establishes protocol compatibility for this case; it does not measure reasoning depth or quality. The fixture function is deliberately small; real Core Shell/file and child tools are covered separately below.

## Three Core smoke checks

[cloud-smoke-r1/RESULTS.json](cloud-smoke-r1/RESULTS.json) records `passed: true`, all three checks passing, and the owned Core stopped after the run.

| Check | Observed execution | Result and limit |
| --- | --- | --- |
| Shell and file reads | Three actual Luna calls; tool receipts for one `shell` and two `read_file` calls. | Completed and quiescent; three receipts, zero unknown effects. A small synthetic filesystem task. |
| Child read | Four actual Luna calls across parent/child; one completed, read-only OpenAI child with a real `read_file` receipt. | `completed_child_read_observed: true`; completed and quiescent, zero unknown effects. Parent text alone was not used as proof of child execution. |
| Restart idempotency | The runner restarted Core and looked up/submitted the existing operation using its idempotency contract. | `same_task: true`, the same task ID, and status still `completed`. This is the bounded restart/idempotency check recorded by the runner. |

The detailed [Shell task](cloud-smoke-r1/shell-read-task.json), [Shell progress](cloud-smoke-r1/shell-read-progress.json), [child task](cloud-smoke-r1/delegate-task.json), and [child progress](cloud-smoke-r1/delegate-progress.json) remain alongside the summary.

The [resolved runtime budgets](cloud-smoke-r1/resolved-runtime-budgets.json) record parent ceilings of 100 steps, 200 tool calls, and 8,192 output tokens; worker ceilings are 30 steps, 60 tool calls, and 4,096 output tokens, with at most two subagents per turn. Those are configured ceilings, not the number of steps consumed or a claim of unlimited execution. Token-unit accounting in that receipt is separate from provider-reported tokens.

## SuperAgent: retained first run and targeted rerun

### First run

[cloud-superagent-r1/RESULTS.json](cloud-superagent-r1/RESULTS.json) and its [top-level log](cloud-superagent-r1.log) retain all four case outcomes:

| R1 case | Status | Recorded outcome |
| --- | --- | --- |
| Parallel children | PASS | Two completed child Shells; 4.663271903991699 seconds of actual overlap. |
| Child Shell cancellation | ERROR | HTTP 429, `rate_limited`, `Client request/connection limit reached`. |
| Stream cancellation | ERROR | The same HTTP 429 client-limit response. |
| Companion | PASS | Both ordinary-client paths completed. |

The test operator identified **5 Hz status polling** as the cause of the two R1 client-limit errors and changed the targeted R2 harness to **1 Hz polling**. The archived summaries directly preserve the 429 responses and later outcomes; the polling-frequency attribution comes from that run configuration, not a timestamped request trace in these archived Core logs. These are Core client-limit errors, not evidence of an OpenAI provider quota error.

R2 reran only the two affected cancellation cases. It did not erase R1, rerun the entire matrix, or turn those first errors into passes. The recorded 110-file source manifests for SuperAgent R1 and R2 are identical. The poll-rate adjustment is a test-harness correction, **not a product fix**.

### Actual overlap of two child Shells

Both R1 workers were asynchronous OpenAI children. Each executed its own Shell and read its output, completed, was collected, and had no unresolved obligation. The parent finished quiescent. Across the run there were nine reported Luna calls, seven tool receipts, and zero unknown effects.

The [timing evidence](cloud-superagent-r1/RESULTS.json) contains child-process timestamps. The first process ran for approximately 12.000 seconds and the second for approximately 12.001 seconds. The overlap is calculated from the process intervals:

`min(child end times) - max(child start times) = 4.663271903991699 seconds`

The overall case took 64.285 seconds. Thus the evidence demonstrates concurrent child work, rather than merely two delegation requests or two queued children. One pair of small Shell tasks does not establish scheduling fairness, sustained throughput, or an arbitrary number of parallel workers.

### R2 child cancellation, restart, and unknown effects

[cloud-superagent-r2/RESULTS.json](cloud-superagent-r2/RESULTS.json) records a **1.034881644998677-second** cancellation interval, a stopped child process, a cancelled/quiescent task, and `same_task_after_restart: true`.

The [child task receipt](cloud-superagent-r2/cancel-child-task.json) preserves the interrupted Shell's result: `status: cancelled`, exit code `-9`, `action_sent: true`, `process_completed: false`, `action_may_have_applied: true`, and `replay_allowed: false`. Its effect status remains `unknown`; the summary reports **one unknown effect**, and the child's obligation remains unresolved. That uncertainty is retained through cancellation instead of being relabeled successful. Restart/idempotency returns the same cancelled task; the evidence does not authorize replay of the interrupted operation.

The real child had already entered Shell execution. This check therefore goes beyond cancelling a queued task or cancelling only a model request. The single recorded interval is not a latency percentile or a bound for every platform/process tree.

### R2 stream cancellation

The archived [SSE receipt](cloud-superagent-r2/cancel-stream-sse.json) includes task creation/running events, `ModelResponseStarted`, and a real `TextDelta`. Cancellation followed observed text, rather than being sent before model output began.

The [R2 result](cloud-superagent-r2/RESULTS.json) records **0.014650534001702908 seconds** from cancel to quiescence, with task status `cancelled`, no tool receipts, and zero unknown effects. The interrupted request appears as one model attempt and one failed attempt, with no completed model-call record. That is an interrupted-stream outcome, not a completed answer or zero-cost assertion. The timing measures local cancellation/settlement observed by the runner; it does not prove when remote generation or provider billing stopped.

## Companion through ordinary clients

The R1 [Companion summary](cloud-superagent-r1/RESULTS.json), [reasoning view](cloud-superagent-r1/companion-reasoning-view.json), and [execution view](cloud-superagent-r1/companion-execution-view.json) show two completed, quiescent paths using client identity `companion`:

| Path | Observed result |
| --- | --- |
| Reasoning | Submitted and retrieved a completed response; no file-read receipt was expected or claimed. |
| Execution | Submitted a file task and retrieved the completed result with a real read receipt. |

The runner records both `operator_credential_given_to_companion: false` and `provider_credential_given_to_companion: false`. Provider access remained behind Core's client boundary in these checks.

Both views also retain `semantic_status: UNVERIFIED`, `goal_verified: false`, and `verification_status: not_run`. The integration assertions passed, but the application did not claim an independently verified user goal. These checks do not cover native Companion UI interactions, speech, arbitrary documents, or general reasoning quality.

## Genuine local/cloud child reads

Both directions used a real local model server and the actual cloud provider. The local model was **Qwen2.5-0.5B**, reported through alias `qwen2.5-0.5b-qualified-worker`; it was not the earlier Qwen3.5-2B diagnostic.

| Local dependency | Recorded SHA-256 |
| --- | --- |
| Local model file | `041474553fcabfc2a2d67903f9d2c2e50bd92528e670da4f33b5d0ce6e59fd55` |
| Local server binary | `cf07a7d6b6d2c61064105cc0a81360cb5830aacd3d1a949b80eaea3a96fa409f` |

| Direction | Actual call/receipt evidence | Qualification |
| --- | --- | --- |
| [Cloud parent → local child](heterogeneous-cloud-parent-r1/RESULTS.json) | Luna parent calls bracket two local-model calls. A completed local child has a fresh `read_file` receipt. Four model calls total. | The local child's `provider` metadata is `unknown`; its configured/reported model alias, model-file/server hashes, actual local calls, and read receipt identify this as the local path. Do not silently relabel that provider field. |
| [Local parent → cloud child](heterogeneous-local-parent-r1/RESULTS.json) | The local parent starts the task, a Luna child actually reads the file, and a second local call follows. Five calls total: two local and three cloud. | The parent later switches to the cloud route: final backend `route:worker`, generation `1`. This is successful local-initiated cloud delegation, not a fully local parent run through the final answer. |

Both children read the complete **19-byte** synthetic file. Each receipt records whole-file coverage, no truncation, `reused: false`, and `new_coverage: true`, with file SHA-256 `aedb13edc7bce268025dde5b96bfc2708138312df4b0164f03b013eb736229c5`. Both tasks completed quiescent with zero unknown effects, and both runners recorded their owned processes stopped. The local-parent run has one child and two `delegate` receipts; those receipts must not be counted as two independent children.

One small file-read task per direction establishes the exercised routing and child-execution paths. It does not establish the 0.5B model's reliability on general autonomous work or compare model quality.

## Regression context and frozen-source checks

These deterministic/local-fixture tests support the implementation but are distinct from the actual provider runs above. Skips remain visible and are not counted as passes.

| Archived check | Recorded result |
| --- | --- |
| [OpenAI protocol R1](openai-protocol-r1.log) | 14 tests, 11.890 seconds, OK. |
| [Core regression R1](core-regression-r1.log) | 1,594 tests, 174.521 seconds; **2 failures, 8 errors, 91 skips**. |
| [Core regression R2](core-regression-r2.log) | 1,616 tests, 168.062 seconds, OK; 91 skips. |
| [Suite regression R2](suite-regression-r2.log) | 123 tests, 49.778 seconds, OK; one skip. |
| [Companion regression R2](companion-regression-r2.log) | 727 tests, 41.326 seconds, OK; 33 skips. |
| [Cloud budgets R1](cloud-budget-r1.log) / [R2](cloud-budget-r2.log) | 41 / 32 tests, respectively; both OK. |
| [Companion long-task check](companion-long-task-r1.log) | 45 tests, 0.452 seconds, OK. |
| [Frozen source: Responses, credential sources, Chat compatibility, and grading](frozen-openai-grading-r1.log) | **38 tests, 14.712 seconds, OK**, run by the root owner from the clean remote-source checkout identified above. |

The original Core R1 failures remain available. The fixture corrections aligned the affected tests with Full cloud preauthorization and earlier argument-boundary rejection while preserving their child-effect, interruption, accounting, and no-replay assertions; that work is described in [the runtime audit](../../../development/AUDIT_20261117_RUNTIME.md). The different R1/R2 test totals are recorded as separate runs, not presented as an unchanged test set.

A separate earlier command, `python -m unittest tests.test_openai_responses tests.test_itbench_scoring -q`, reported **28 tests in 8.315 seconds, OK**, only in the execution tool output. Its stdout/stderr was **not saved to a file**, so there is no original log path to cite. The new 38-test file is a separately executed frozen-source check, not a reconstructed or renamed copy of that earlier output.

## Final-source finite engineering task

[The independent engineering review](engineering-luna-r1/RESULTS.md) verifies the actual model task, source identity, original acceptance files, saved tool receipts and artifact hashes. Core loaded clean source `91dd87c`; the newly added runner has its own frozen SHA-256. In 336.94 seconds, two async children implemented CSV parsing and Decimal aggregation, and the parent implemented the CLI, collected their work and ran the complete test suite. After Core stopped, the runner used the original, unchanged acceptance files in a separate directory: **17 tests and four CLI cases passed**. Protocol, orchestration and semantic criteria all passed.

The archive retains the first unconfigured-tier delegation failure, a status-query argument error and a child implementation error that the child repaired before acceptance. The initial `STRONG` enum was schema-valid, but the fixture had no tier mapping; explicit `route:worker` subsequently resolved. This does not qualify a configured STRONG tier. The 97.07-second child-lifecycle overlap includes model waits and tools, and the aggregate 36 model calls already include both children. Core's internal `verification_status=not_run` remains unchanged: the engineering PASS belongs to the external acceptance, not a rewritten internal status. The result is a bounded synthetic engineering check, distinct from a two-hour Shell, public benchmark and native-package test.

## Remaining limits

The archived integration cases exercise concrete paths successfully, with the two R1 polling errors retained. They do not replace the still-running two-hour soak or the full public benchmark. No benchmark label, candidate answer, cost total, leaderboard comparison, or quality score is asserted here.

The final source has later compatibility and credential-source fixes, including GPT-5.5 reasoning-effort defaults. Its frozen-source test receipt is linked above; earlier paid-model results remain attached to their original source hashes. Prefix-preserved reasoning still has the limitation documented in the runtime audit when request history is rewritten; this report does not turn that known limit into a fixed issue.

Final native packaging and package-specific execution now have their own [completed receipts](../../../../desktop/docs/evidence/audit-20261117-desktop/final-package/RESULTS.md), including the final source identity and measured motion. That separate success does not change the explicitly identified source snapshots used for the earlier paid-model runs. System-wide installation, macOS devices and a GitHub binary upload are not claimed.
