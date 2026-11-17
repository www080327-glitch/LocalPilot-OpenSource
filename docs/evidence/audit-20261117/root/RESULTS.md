# Actual model integration results — 2026-11-17

## Status and scope

The completed integration receipts demonstrate actual GPT-6 Luna Responses requests, function-result round trips, streamed text, Core tools and children, cancellation, restart lookup, ordinary Companion clients, and both directions of local/cloud delegation. Those small synthetic checks do not establish general task quality or an autonomous-work success rate. The completed public forty-case scores, finite engineering attempts and package checks are recorded separately below, with their own source identities and limits.

The initial integration assessment was prepared independently from archived receipts and their hashes. Later status updates are appended by the root owner from the named run records; they do not change the original receipts or merge results from different sources.

Current production source is Core `5.0.0b31` / Desktop `5.0.1-rc.14`: remote commit [`c5439659a579b2ee9e74fd53e6d3232fe12fb855`](https://github.com/www080327-glitch/LocalPilot-OpenSource/commit/c5439659a579b2ee9e74fd53e6d3232fe12fb855) and local `7fe7c57c531bd44b966717502b44901582418cc4` share tree `d0b0b33b036587ef0f0a802ca728419e9a444587`. R6 engineering passed all four layers; RC14 passed build, native short qualification and its one complete animation sample. R5 remains overall FAIL with semantic PASS, and RC13 retains its failed native version gate. The independent b28 two-hour soak also completed PASS, under its own source identity. The grader stays frozen at b29 commit `8e92deb8b6a0acbba1d139851b1d805246304c61`, SHA256 `4cd3f405f7a4d1c05edb6bf5d5530657c69de6b934bf59c2cdf01df7e2f20b76`; later product fixes do not change or repeat the scores.

| Work item | Status at this report's preparation | Claim supported here |
| --- | --- | --- |
| [b31 restored-source continuation](continuation-b31/RESULTS.md) | **Core 1,545 PASS / 99 SKIP; installed components 12/12 PASS** | Full Core discovery on the final b31 source; separately rebuilt and installed current wheels for actual channel HTTP/process lifecycle. No production changes, live model calls, system installation, or new benchmark result. Seven existing archives / 743 payloads rechecked without changing their historical results. |
| Luna HTTP, function round trip, and streaming | PASS | The actual configured provider path returned usable responses and tool results. |
| Core smoke checks | 3/3 PASS | Shell/read, a genuine child read, and restart lookup of the same completed task. |
| Parallel child Shells | PASS | Two completed child processes overlapped for 4.663 seconds. |
| Child and stream cancellation | R1 ERROR; R2 PASS | First-run rate-limit errors are retained; cancellation was measured in the second run. |
| Companion reasoning and execution clients | 2/2 PASS | Ordinary client submission/retrieval completed, with a read receipt on the execution path. |
| Heterogeneous delegation | 2/2 PASS within the stated scope | Actual local and cloud child reads; the local-parent run later switched its parent to cloud. |
| [Finite engineering acceptance](engineering-luna-r1/RESULTS.md) | PASS | Frozen `91dd87c` Core; two genuine async children; original external 17 tests and four CLI cases passed. |
| [b28 engineering R2](engineering-luna-r2-b28/RESULTS.md) | INCOMPLETE: executor continuity lost | Last saved progress 105.61 seconds; no terminal result or observed Core-stop receipt. |
| [b28 native engineering R3](engineering-luna-r3-b28-native/RESULTS.md) | Overall FAIL; semantic PASS | External 17 tests and four CLI cases passed; repeated-file patch rejection left parser child and parent incomplete. |
| [b29 native engineering R4](engineering-luna-r4-b29-native/RESULTS.md) | **Overall FAIL; semantic PASS** | External 17 tests and four CLI cases passed; a failed read-only directory observation remained an unfinished child obligation. |
| [b30 engineering R5](engineering-luna-r5-b30-native/RESULTS.md) | **Overall FAIL; semantic PASS** | External 17 tests / 4 CLI passed. Both child interpreter attempts failed; parser later passed its tests, but aggregate never ran the required successful child tests. |
| [b31 engineering R6](engineering-luna-r6-b31-native/RESULTS.md) | **Protocol, orchestration, semantic and overall PASS** | Two completed async children, required 9 / 3 child tests, parent integration and external 17 tests / 4 CLI passed; 121.5947 seconds, owned Core stopped. |
| Original two-hour soak R1 | **INCOMPLETE: execution-session continuity lost** | 210 heartbeats, last observed 6,270.103 seconds; no terminal receipt or finished marker. |
| [Two-hour soak R3](cloud-soak-2h-r3-interrupted/RESULTS.md) | **INCOMPLETE: second execution-session loss** | `91dd87c`; 97 heartbeats, last 2,880.051 seconds; no terminal result or readback. |
| [b28 two-hour soak R4](cloud-soak-2h-r4-b28-native/RESULTS.md) | **PASS** | `03535fe`, Python 3.12.14: task 7207.384406 seconds, 240 heartbeats, actual completed Shell and fresh marker readback; completed/quiescent, owned Core stopped, outer exit 0. |
| [Original forty-case ITBench R2 score](itbench-aa-r2-original-score/RESULTS.md) | **21.4583333%; denominator 40** | 26 graded, 14 candidate_zero, 0 judge_error; all 34 unchanged-case caches reused, with 0 new judge requests. |
| [ITBench transport-continuation score](itbench-aa-r2-transport-completed/RESULTS.md) | **22.2916667%; denominator 40** | 30 graded, 10 candidate_zero, 0 judge_error; 30 completed / 32 format-valid candidates, with interruptions retained. |
| RC10 native package | **PASS for build and extracted-package UI verification** | Separate [RC10 evidence](../../../../desktop/docs/evidence/audit-20261117-desktop/final-package/RESULTS.md); these earlier model runs remain source-based. |
| [RC11 / Core b28 package](../../../../desktop/docs/evidence/audit-20261117-desktop/final-package-rc11/RESULTS.md) | **PASS for build and native short checks** | Source `03535fe`; 40 wheels / 286 source files verified; no system installation, new animation measurement, or binary Release upload claim. |
| [RC12 / Core b29 package](../../../../desktop/docs/evidence/audit-20261117-desktop/final-package-rc12/RESULTS.md) | **BUILD PASS; native PARTIAL_DEFERRED** | Components prepared in actual WebKit; stopped before setup completion, main-page version and live capability checks. Owned instance stopped normally. |
| [RC13 / Core b30 package](../../../../desktop/docs/evidence/audit-20261117-desktop/final-package-rc13/RESULTS.md) | **BUILD PASS; native version gate FAIL; native NOT_PASSED** | Package metadata b30 but actual service b28. The final setup button was enabled; no permanent UI blockage or version-rejection cause was established. |
| [RC14 / Core b31 package](../../../../desktop/docs/evidence/audit-20261117-desktop/final-package-rc14/RESULTS.md) | **BUILD PASS; native short qualification PASS; one animation sample PASS** | Actual service, metadata, source and GUI all b31; setup completed, 24-hour option selected without submission, K/L stopped. One 6007 ms sample; no system installation or binary upload. |
| [Shell timeout and Full child repair](shell-timeout-repair/RESULTS.md) | **72 PASS / 1 existing macOS SKIP** | Additional implementation checks, scripted model replies with real Shell and parent/child execution; no benchmark reclassification. |
| [b29 same-file multi-update](multihunk-patch/RESULTS.md) | **73 PASS / 1 existing macOS SKIP** | Actual Registry / Full parent-child / filesystem checks; same-file updates commit once after whole-batch preflight. Old R3 remains FAIL. |
| [b30 missing-directory observation](async-missing-directory/RESULTS.md) | **28/28 PASS; independent read-only review complete** | Only built-in `list_directory` + `FileNotFoundError` + `not_completed` is excluded from unfinished obligations; failed receipts remain. Denied, UNKNOWN, writes and cancellation keep their rules. |
| [b31 settled child Shell](async-settled-shell/RESULTS.md) | **36 PASS / 1 existing macOS SKIP** | Aligns child settlement with the existing root failed-process contract; original nonzero-exit receipt and independent missing-test requirements remain. |
| [b31 runtime version gate](version-gate/RESULTS.md) | **2 PASS** | Actual subprocess matching/mismatching inputs; old checker false PASS on b30/b28 retained, fixed checker rejects the same mismatch and accepts b31. |
| [Reference schema adapter](itbench-reference-adapter/RESULTS.md) | **22 PASS; all 40 reference scenarios parsed** | Input-only adaptation before any real judge call, with unchanged prompt, model, budgets and scoring rules. |

The two completed score archives remain separate from the completed b28 soak and the later b31 engineering/package qualifications. [Benchmark R1](itbench-aa-r1/ABORTED.json) was aborted after four terminal `CloudEgressDenied` failures at the hidden 131,072-byte ceiling; a fifth started case was interrupted. That historical runtime defect and its receipts are distinct from R2's timeout-unit error and remain preserved. No score is assigned to the aborted R1 run.

The frozen ITBench study's phrase `packaged Core HTTP` is historical wording: the candidate service actually loads Core from the frozen `qualification-source-r2` through `PYTHONPATH`. Its source manifest identifies that snapshot. It is not a model run from the installed RC10 DEB; the frozen study is retained unchanged.

The initial long-run executor handles later disappeared together and their progress files stopped updating. [The independently reviewed interrupted-soak archive](cloud-soak-2h-r1-interrupted/RESULTS.md) preserves the 210 heartbeats and missing completion evidence; the cause is unknown and no application-permission cause has been established. R3 later lost its execution session as well; its independent archive preserves the 48-minute partial trace. R4 completed from an existing native desktop Terminal, pinned to `03535fe` / b28. Its independent two-hour result stands on its own; neither interrupted duration is added.

ITBench R2 encountered dataset-download `URLError` / tunnel 403 failures before six candidates started, plus two started candidates whose execution sessions lost continuity. The original run has 40 immutable terminal receipts. The predeclared continuation selects only those six never-started download failures. A second executor loss interrupted case 025 after it started; the runner retained that interruption without another candidate attempt. The final four never-started cases completed from native Terminal with unchanged source, Python, prompt, budgets and input URLs. The changed PID/network namespace is recorded separately; proxy/TLS policy was unchanged. The combined cohort has 30 completed / 32 format-valid results. Initial grading failed at reference parsing before any judge request; the [input-only adapter](itbench-reference-adapter/RESULTS.md) then enabled the unchanged scoring protocol.

### Completed forty-case scoring

The [combined scoring archive](itbench-aa-r2-transport-completed/RESULTS.md) records 30 normalization attempts, 0 judge errors and **8.916666666666666 / 40 = 22.291666666666664%**. The distribution is 7 full scores, 5 partial scores, 18 graded zeros and 10 candidate zeros. Graded zeros mean that the existing normalization/scoring rules did not match the reference root causes; they do not by themselves prove an absolutely wrong diagnosis. Prompt, model, budgets and scoring rules were not changed in response to the scores.

The [original R2 cache-only scoring archive](itbench-aa-r2-original-score/RESULTS.md) records **8.583333333333334 / 40 = 21.458333333333336%**: 26 graded and 14 candidate zeros. All 34 unchanged cases were reused, including failures and low scores; the six original download failures stayed zero. The actual `backend_factory` guard recorded 0 calls, 0 new judge requests and 0 candidate reruns. Receipt/prediction/study bytes matched, all 61 copied cache files stayed unchanged, and only index 029's one-third point differs between cohort scores. These are two distinct cohorts using one set of normalization receipts, not independent repeated judging or score selection. Neither score is an official AA leaderboard result.

## Evidence integrity and source identity

All **49 entries** in [MANIFEST-initial.json](MANIFEST-initial.json) matched both their recorded byte counts and SHA-256 values. That initial manifest excludes later soak and ITBench archives, which have their own manifests. Its `credential_value_found: false` is the exporting process's recorded scan result, rather than a new credential audit by this report.

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

The RC10/b27 source publication was later than those initial integrations. [SOURCE_PUBLICATION.json](SOURCE_PUBLICATION.json) records remote commit `91dd87c6fd4678c103d6383dec1c1385deb38f9a` and local commit `e34532c1969b6494d0eba8918d84695d14fe12c6` with identical Git tree `c19b18071de42ed42feb25519671a559f38dec18`. The local commit/tree relationship was also checked directly. The root owner ran the 38-test frozen-source check from that clean remote checkout. It does not change earlier API-run identities, establish packaged RC10 execution, or become a test of the later b31 source named at the top of this report.

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
| [b28 Shell timeout / Full child repair](shell-timeout-repair/RESULTS.md) | 73 tests = 72 PASS + 1 existing macOS SKIP; 9.450 seconds. |
| [b29 same-file multi-update](multihunk-patch/RESULTS.md) | 74 tests = 73 PASS + 1 existing macOS SKIP; 4.584 seconds. |
| [b30 missing-directory observation](async-missing-directory/RESULTS.md) | **28 PASS, no skips, 5.988 seconds**; before-change root control PASS and async case FAIL. |
| [b31 settled child Shell](async-settled-shell/RESULTS.md) | **37 tests = 36 PASS + 1 existing macOS SKIP; 6.622 seconds**; actual root control PASS / async FAIL before the correction. |
| [b31 runtime version gate](version-gate/RESULTS.md) | **2 PASS, 0.077 seconds**; real subprocess checks plus retained actual mismatch and corrected-version receipts. |
| [Reference schema adapter](itbench-reference-adapter/RESULTS.md) | 22 PASS, 2.145 seconds; fixed official 40-scenario input parsed without changing scoring rules. |

The original Core R1 failures remain available. The fixture corrections aligned the affected tests with Full cloud preauthorization and earlier argument-boundary rejection while preserving their child-effect, interruption, accounting, and no-replay assertions; that work is described in [the runtime audit](../../../development/AUDIT_20261117_RUNTIME.md). The different R1/R2 test totals are recorded as separate runs, not presented as an unchanged test set.

A separate earlier command, `python -m unittest tests.test_openai_responses tests.test_itbench_scoring -q`, reported **28 tests in 8.315 seconds, OK**, only in the execution tool output. Its stdout/stderr was **not saved to a file**, so there is no original log path to cite. The new 38-test file is a separately executed frozen-source check, not a reconstructed or renamed copy of that earlier output.

## Finite engineering attempts by source

[The independent engineering review](engineering-luna-r1/RESULTS.md) verifies the actual model task, source identity, original acceptance files, saved tool receipts and artifact hashes. Core loaded clean source `91dd87c`; the newly added runner has its own frozen SHA-256. In 336.94 seconds, two async children implemented CSV parsing and Decimal aggregation, and the parent implemented the CLI, collected their work and ran the complete test suite. After Core stopped, the runner used the original, unchanged acceptance files in a separate directory: **17 tests and four CLI cases passed**. Protocol, orchestration and semantic criteria all passed.

The archive retains the first unconfigured-tier delegation failure, a status-query argument error and a child implementation error that the child repaired before acceptance. The initial `STRONG` enum was schema-valid, but the fixture had no tier mapping; explicit `route:worker` subsequently resolved. This does not qualify a configured STRONG tier. The 97.07-second child-lifecycle overlap includes model waits and tools, and the aggregate 36 model calls already include both children. Core's internal `verification_status=not_run` remains unchanged: the engineering PASS belongs to the external acceptance, not a rewritten internal status. The result is a bounded synthetic engineering check, distinct from a two-hour Shell, public benchmark and native-package test.

The later [b29 R4 attempt](engineering-luna-r4-b29-native/RESULTS.md), pinned to `8e92deb8`, passed the original external **17 tests / 4 CLI cases** and exercised the multi-update fix. It remained **overall FAIL** because a failed, read-only missing-directory observation kept parser child and parent incomplete. The [b30 correction](async-missing-directory/RESULTS.md) passed 28 actual runtime tests with scripted model replies; independent review verified receipt preservation and unchanged denied/UNKNOWN/write/cancel rules. That local regression does not reinterpret R4.

[R5 on b30](engineering-luna-r5-b30-native/RESULTS.md) also retained **overall FAIL / semantic PASS**. The parent supplied an abbreviated interpreter path; both children guessed a nonexistent workspace interpreter and received exit 127. Parser subsequently ran its nine tests successfully but the settled failed process remained an unfinished obligation. Aggregate did not run its three required successful tests, an independent reason that the frozen orchestration cannot pass. The [b31 two-line settlement correction](async-settled-shell/RESULTS.md) aligns children with the existing root contract; its local regression cannot supply the missing model action or reclassify R5.

[R6 on b31](engineering-luna-r6-b31-native/RESULTS.md) used the unchanged runner, prompt, 12 original fixtures and budgets. **Protocol, orchestration, semantic acceptance and overall engineering all PASS**, in **121.5947 seconds**. Both async children completed, were collected and changed only their assigned module; ParserTests ran nine tests and AggregateTests three. The parent integrated the CLI; independent immutable acceptance passed 17 tests and all four CLI cases. The 23 aggregate model calls already include both children; their lifecycles overlap by **58.072972 seconds**. Source and original acceptance files were unchanged and owned Core stopped. Independent read-only review verified all 45 payload hashes, original/delivered file hashes and exact recomputation by the frozen `orchestration()` function.

The R6 parent's auxiliary `git diff` exit 129 remains a failed-process receipt. Neither new child failed-process nor missing-directory exception branch occurred in R6; the separate local regressions provide that branch coverage. This is one bounded standard-library project qualification, not an autonomous success-rate estimate.

## Independent two-hour b28 soak

[The final R4 archive](cloud-soak-2h-r4-b28-native/RESULTS.md) records **PASS**, with task elapsed **7207.3844064939985 seconds**, outer elapsed **7208.490151643753 seconds** and **240** monotonic heartbeat rows. The actual foreground Shell ran the unchanged frozen-runner script, returned exit 0 and `process_completed=true`, then a fresh `read_file` retrieved the complete 24-byte marker. The model's final answer matches it exactly. The task completed quiescent with no pending approval or UNKNOWN receipt; the runner recorded owned Core stopped and the outer supervisor returned 0.

There is no standalone Shell-duration field. The lower bound of 7200 seconds is established by the unchanged script's monotonic loop reaching its threshold before writing the marker and exiting successfully; task elapsed is not presented as exact Shell duration. Three real Luna calls reported **8,276 input / 243 output tokens**, with no failed attempt. Internal `verification_status=not_run` and `task_outcome=unverified` remain unchanged; the PASS belongs to the fixed external soak criteria.

The 110-file Runtime manifest `9fe18b9f97a527b9357af2406d4a8530eef244eaf2a2d00d0f2db53108d0b35d` matches both the clean b28 checkout and its Git blobs. The [limited source-continuity comparison](long-run-source-continuity.json) verifies 47 relevant Shell, Full/Extended, deadline, cancellation, transport and qualifier files unchanged through b31 and separately lists four changed Core files. It does not claim identical overall model requests, turn this into a b31/RC14 measured run, or establish two hours of continuous model inference. R1/R3 interruptions and the final periodic `running` checkpoint remain unmodified; terminal task/RESULTS/exit receipts establish R4 completion.

## Remaining limits

The completed integrations, b31 R6 engineering, b28 two-hour soak, public forty-case scores and RC14 native checks retain separate execution identities and limited scopes. Raw reference labels and judge inputs were not archived. No official leaderboard placement, general autonomous success rate, completed 24-hour task or monetary cost total is asserted.

The 38-test frozen-source receipt belongs to `91dd87c`; b28, b29, b30 and b31 fixes have the separate targeted checks listed above. Earlier paid-model results remain attached to their actual source hashes. Prefix-preserved reasoning still has the limitation documented in the runtime audit when request history is rewritten; this report does not turn that known limit into a fixed issue.

[RC10 animation and package checks](../../../../desktop/docs/evidence/audit-20261117-desktop/final-package/RESULTS.md) and [RC11 short native checks](../../../../desktop/docs/evidence/audit-20261117-desktop/final-package-rc11/RESULTS.md) retain their own successful identities. [RC12](../../../../desktop/docs/evidence/audit-20261117-desktop/final-package-rc12/RESULTS.md) remains BUILD PASS / native PARTIAL_DEFERRED. [RC13](../../../../desktop/docs/evidence/audit-20261117-desktop/final-package-rc13/RESULTS.md) retains BUILD PASS / native version gate FAIL: metadata b30 differed from actual service b28. Its final setup button was enabled, no explicit version rejection was observed and final completion was not attempted; permanent UI blockage is not established.

[RC14](../../../../desktop/docs/evidence/audit-20261117-desktop/final-package-rc14/RESULTS.md), source `c5439659`, passed build and fresh native K/L short qualification. The actual service, source constant, metadata and GUI all report b31. First setup completed; live capability exposes the 86400-second limit, and the 24-hour UI option was selected without task submission. The first bubble was 320 × 221 pixels; a focused draft was typed and cleared without sending. Its sole 6007 ms animation sample has conservative full-phase rates **29.3073 / 28.9532 visible changes/s** for retraction/peeking, independently recomputed from original timestamps. This is layout-visible change at DPR 1 with eight source frames, not physical display photometry or 24 independent drawings. Both owned profiles stopped with no owned process remaining.

The RC14 DEB is **114,637,332 bytes**, SHA-256 `66aed474856ffa958ec07d383dd8f31840bbbdabbd0613e229ce342f9b78ce61`. Independent review matched the actual artifact and all 69 archive payloads, with byte-identical before/after 286-source verification. These are extracted-package checks. System-wide installation, physical Apple Silicon/Intel macOS qualification, other DPI/multiple-display qualification and a GitHub Release/binary upload remain uncompleted.
