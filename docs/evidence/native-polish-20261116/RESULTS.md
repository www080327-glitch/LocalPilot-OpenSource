# Native polish and real Qwen qualification — 2026-11-16

> This report preserves the preceding b25/b30/b6 batch. The later b26/b31/b7 code, native profile continuation, new model diagnostic and final delivery are recorded separately in [continuation results](../native-continuation-20261116/RESULTS.md). The package SHA and frozen model counts below are historical identities, not the latest candidate.

## Identity and scope

Baseline: `d846fef0f4b442d57e6e37f856a59c5a1a1337de` (PR #14). The final commit containing this report identifies the reviewed integrated tree; the baseline SHA does not identify the edits described below.

Candidate versions: Desktop **5.0.1-rc.9**, Core **5.0.0b25**, Suite **0.2.0b30**, Companion **0.5.7b6**, Channels **0.1.0a3**. No Release, contest form, landing form or leaderboard submission was made. The user's Mac working tree and older Test application were not accessible from this cloud workspace and were not changed.

This report separates deterministic implementation tests, real model outcomes, native GUI observations, package checks, and unavailable target-device work. A synthetic model or IPC fixture does not establish model quality or native application acceptance. Historical failures remain in their original runs.

## Changes backed by observed defects

1. **Session restoration:** only a confirmed authenticated `404 + session_not_found` replaces a stale selection with a new draft. Connection failures, 403, 503 and non-JSON 404 preserve the selection. Attachment requests wait for a confirmed Session. Suite home is part of the connection scope. Existing drafts, service history and UNKNOWN receipts are not replayed.
2. **Test WebView identity:** the canonical Test root and application identity determine the persistent WebView store. macOS uses a named WKWebsiteDataStore; Linux uses the Test root's data directory. All five window builders share the selected scope. Daily application identity retains its normal configuration.
3. **Linux accessibility text:** preserve the selected AT-SPI bus and invoke `Atspi.Text.get_text()` through the correct GI interface. The original implementation swallowed a real TypeError and returned metadata without the static body text. The fixture now owns its D-Bus activation/Xvfb environment.
4. **Worker admission:** a real child initially entered finalization before receiving tools because the former 32,768-unit default could not accommodate prompt, schema and output reserves. New Sessions receive a 131,072-unit worker ceiling, still capped by the parent's remaining budget. Explicit ceilings remain unchanged. Existing omitted-default Sessions keep 32,768, with a full configuration match and the existing declared migration rules.
5. **Model tool descriptions:** the compact model-facing schema retains parameter semantics such as relative file paths and timeout units. Its stored canonical schema remains unchanged, preserving historical Session/worker contracts. Local-only worker routes no longer advertise a cloud-only tier field.
6. **OpenAI and routing:** add an explicit cloud OpenAI adapter with `max_completion_tokens`, streaming usage and existing private credential injection. Source classification is shared by Core, Suite, Channels and Desktop. Pure-cloud selection no longer treats a local primary with permitted cloud egress as a cloud primary.
7. **Harbor process identity:** compare resolved cwd paths so an existing controller is recognized through a symlink or macOS `/var` alias. Existing PID/UID/argv/daemon checks remain. The old 534-run study was not opened, resumed or overwritten.

See the [development explanation](../../development/NATIVE_POLISH_20261116.md), [Desktop source and regression evidence](../../../desktop/docs/evidence/polish-20261116/RECOVERY.md), [Linux accessibility evidence](linux-atspi/RESULTS.md), [OpenAI evidence](../openai-public-eval-20261116/RESULTS.md) and [requirements audit](../../development/REQUIREMENTS_AUDIT_20261116.md).

## Automated and native validation

Final integration results and the immutable package identity are recorded below. Earlier runs are retained under [validation](validation/README.md); they are not silently relabelled as covering later production edits. The [final log manifest](validation/FINAL_LOG_MANIFEST.json) contains the new regression/build logs and preserves the earlier manifest unchanged.

| Area | Result and scope |
| --- | --- |
| Desktop TypeScript / Vite | PASS on the current Desktop source. |
| Vitest | 74 PASS. |
| Chromium Playwright | 47 PASS; actual Chromium, synthetic native IPC. RC.8 stale-Session reproduction fails as expected. Early fixture/server failures remain in the logs. |
| Rust | 50 PASS, 3 ignored by test definition; resource-independent unit run. A separate real Core HTTP integration test passed with scripted model replies. |
| Companion full run | 720 discovered: 687 PASS, 33 SKIP. |
| Actual Linux GTK | 8 PASS; seven overlap the full run and one fills a skipped case. Real text, password/input exclusion and pause behavior are included. |
| Optional Linux training/ASR | 7 PASS: five real CPU tiny-model training/reload tests and two actual whisper.cpp public-sample/cancellation tests. |
| Companion unique coverage | **695 PASS, 25 remaining SKIP**, all requiring macOS native facilities. These counts do not establish training on personal data or real meeting capture. |
| Final Core | **1,563 discovered: 1,473 PASS, 90 SKIP, 0 FAIL, 0 ERROR**, 156.109 seconds; no ResourceWarning. Includes real old-build SQLite/UNKNOWN/default-budget migration. |
| Final Suite | **115 discovered: 114 PASS, 1 SKIP, 0 FAIL, 0 ERROR**, 25.044 seconds. |
| Final Linux DEB | PASS: build, 40 verified wheels, bundle self-check, extracted module imports/pip check and Node. `installed:false`. |
| System install / upgrade / rollback | NOT_RUN in this unprivileged cloud environment. |
| Physical Intel Mac | BLOCKED: no physical Intel Mac. No Rosetta/M1 substitute was used. |
| macOS native rc9 | NOT_RUN here. Existing Mac rc8 reports remain historical evidence. |
| Wayland, actual Pulse audio, logind sleep | NOT_RUN; the required live facilities are unavailable. |

The Companion [source list](linux-atspi/SOURCE_SHA256.json) and [29 compressed evidence files](linux-atspi/LOG_MANIFEST.json) identify the final b6 implementation and original logs. The final source list is compared by original path set; wheel build copies do not count as additional source edits.

Final DEB: `LocalPilot-Test-5.0.1-rc.9-linux-x86_64.deb`, **114,590,740 bytes**, SHA-256 **`dfbc657042759cbe07f9f510885cc431b32f92342c80025e94242288a6f347aa`**. Its [package report](package/RESULTS.json) records b25/b30/b6/a3 and the exact dependencies. The existing [resource check](package/VERIFIED_MODULES.json) compares 285 Python/Swift source files with the wheels and installed resources; a separate [Python-only check](package/COMPONENT_SOURCE_CHECK.json) verifies all 268 importable Python files. The pre-normalization Tauri artifact is retained separately; the delivered candidate is the normalized DEB above. The earlier b24/b29/b5 rc9 artifact has SHA `f9808ebf021d032623b9995fdcfbebd09e4add2c927a540bf14611166c1fad3a` and is not this candidate.

## Real model and public sample

The cloud qualification uses official `Qwen/Qwen3.5-2B`, pinned revision `15852e8c16360a2fea060d615a32b45270f8a8fc`. All 12 source files were verified. A controlled official llama.cpp conversion produced text-only Q8_0; the GGUF SHA-256 is `a7b660a8c7a4de32753adbebf4815119995738f1426f4ec07e84763a1255d718`. The original BF16 weight SHA-256 is `aa33250c4fc64891ddfaba3a314fd9542ea371843c387178b425fbcc5ed680b1`.

Runs use two CPU threads, 8,192 context tokens, 512 output tokens and a declared nonthinking sampling profile. The first provider process peaked at about 2.56 GiB RSS; this is not total application memory. Local API charges are $0; energy cost is UNKNOWN. No OpenAI or DeepSeek inference request was sent from this workspace.

| Frozen run | Outcome | Interpretation |
| --- | --- | --- |
| Original nine product cases | **7 PASS, 2 FAIL, 0 ERROR** | Includes real file receipts, Shell write/read, SSE cancellation/409, UNKNOWN restart/no replay, lightweight Companion and explicit cache save/restart/restore. Autonomous child delegation and Companion-to-Core completion failed. |
| Original three prescribed diagnostics | **0 PASS, 3 FAIL, 0 ERROR** | Exposed the worker admission defect; another child case selected an illegal cloud tier; Companion obtained a real read receipt but did not finish within its wall-clock limit. |
| Fixed MMLU-Pro sample | **10 PASS, 22 FAIL, 0 ERROR; 32/32 complete** | 31.25% on this sample only. Sixteen failed answers reached the 512-token output limit; six completed with an incorrect answer. |
| Corrected-default four-case diagnostic | **2 PASS, 2 FAIL, 0 ERROR; 4/4 complete** | Autonomous and prescribed child reads passed. Child Shell cancel/restart and Companion completion did not meet the frozen oracle. Parent/worker budgets differ from the original run; no original outcome is replaced. |

The original runtime is Core b24 / Suite b29 / Companion b5. Its 448-file source manifest SHA-256 is `e6f6bf16864dff9c3f7e9dfc6691129cbbbdc2d4c5693357ce023db089a14316`. The newer b25/b30/b6 run uses [SOURCE_FREEZE_CORRECTED.json](../qwen35-linux-20261116/SOURCE_FREEZE_CORRECTED.json), SHA-256 `d3d866d67ad9cf6f819d8e6786656e4f62265983c15caa3e0a7a8cc4e2333917`; all 448 files matched before and after execution. Neither model name nor the shared rc9 application filename makes evidence transferable between these snapshots.

The two corrected child reads completed in **228.92 and 212.00 seconds** with their own physical read receipts and complete parent answers. The original autonomous prompt was unchanged. The Shell case created a real child and reached a quiescent cancellation, but no Shell marker/receipt existed at the predeclared 180-second boundary, so the Shell/UNKNOWN/restart branch was not exercised. The Companion case read the file and returned the complete marker with a real source citation; three additional cached reads exhausted the step reserve, leaving task status `incomplete`. Its **282.03-second** result is still FAIL under the declared `completed` rule; it was not another 300-second timeout or output truncation. See [corrected diagnostic results](../qwen35-linux-20261116/CORRECTED_RESULTS.md).

MMLU-Pro is an independent public dataset, but this run is zero-shot and only 32 preselected questions. It is **not** a full MMLU-Pro evaluation, an Artificial Analysis Intelligence Index reproduction, a leaderboard position, or evidence that LocalPilot matches mainstream Agents. No questions or answers were removed from the denominator, and no gold answers or dataset rationales were sent to the model. The current AA index includes other/private evaluations; a fair tool-using Agent comparison still needs a separately frozen task study.

Full model provenance, protocol, request accounting and source identities are in [Qwen qualification](../qwen35-linux-20261116/RESULTS.md). Raw benchmark questions/responses, temporary databases and model artifacts are excluded from Git; the reusable raw run archive is retained separately.

## Preserved failures and limitations

- The user's uploaded Mac report and manifest were checked against the supplied checksum list. The raw local Mac logs and uncommitted source diff were not uploaded; their reported results were not independently rerun here. The report's declared file count differs from the actual supplied manifest count and is not used as a coverage denominator.
- The first rc9 Linux native launch failed because the compiled WebKit helper path was absent on the host. The DEB already declares the matching WebKit runtime. Extracting dependencies into a sysroot is not a system installation. Any later read-only namespace test is reported separately.
- Earlier Core/Suite, UI and native fixture failures are retained. A corrected invocation or fixture does not erase its original ERROR/FAIL.
- No live Docker daemon is available. The old 534 queue remains **1 PASS / 3 FAIL / 13 ERROR / 517 without final results**. No new formal Harbor study was claimed.
- No account key or claimed API-credit balance was available. Contract tests do not prove cloud model quality, actual usage or billing. Eligible Pro $100 API benefits are documented in the [OpenAI instructions](../../development/OPENAI_AND_PUBLIC_EVALUATION_20261116.md); an actual linked API organization still has to be verified privately.
- Managed oMLX prefix storage and explicit llama.cpp disk-slot restoration are distinct from generic external-HTTP automatic persistent KV, which is not implemented. Cache identity and eviction prevent a literal forever guarantee.
- Reviewed LoRA/full-parameter training code and tiny-model gradient tests are present. Personal sample approval, an independent held-out set and demonstrated PA benefit are still missing. An RL execution pipeline is not implemented.
- Full permission removes normal per-action approval and sandbox restrictions within current-user capabilities; it does not remove built-in credential protection, budgets, OS permissions, TCC or provider limits.

## Handoff

The [Work prompt](../../development/WORK_NATIVE_POLISH_20261116.md) lists only remaining actual device, account, data and formal-study actions. It preserves the Mac dirty tree, older Test profile, original failed studies and UNKNOWN receipts. The [requirements audit](../../development/REQUIREMENTS_AUDIT_20261116.md) distinguishes implemented capabilities from missing implementation and missing acceptance; it does not declare all prior requests complete.
