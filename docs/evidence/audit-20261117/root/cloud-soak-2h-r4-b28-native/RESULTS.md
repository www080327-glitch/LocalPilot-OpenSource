# Full + Extended two-hour soak R4 on Core b28 — PASS

**The independent R4 run completed the authorized 7,200-second foreground Shell, read the resulting marker through the real `read_file` tool, returned that exact marker in the model's final answer, settled quiescent and stopped its owned Core. The runner and outer native supervisor both completed successfully.** This is a fresh b28 run; no elapsed time from either interrupted predecessor is added.

## Source and execution identity

| Field | Observed value |
| --- | --- |
| Frozen source commit | `03535fe943f64f49e9e3d79e7949aca6c9ec9b87` |
| Frozen source tree | `1792d58af7858208db5018a747d78a1c75848edf` |
| Runtime source manifest | `9fe18b9f97a527b9357af2406d4a8530eef244eaf2a2d00d0f2db53108d0b35d`; 110 files |
| Actual service version | `5.0.0b28`, retained in [core.log](core.log) |
| Frozen runner SHA-256 | `a860afd95c17ec86bdd1b738ae7a4223fd3985eadd262c84259e4f396acf3238` |
| Model / protocol / reasoning | `gpt-6-luna` / OpenAI Responses / medium |
| Actual task options | Full, scope revision 3, Standard agent profile, **Extended execution budget** |
| Execution surface | Existing native desktop Terminal foreground; Python `3.12.14` |
| Native supervisor start / finish | `2026-11-16T20:04:16.350356+00:00` / `2026-11-16T22:04:24.840508+00:00` |
| Task elapsed / outer elapsed | **7207.3844064939985 / 7208.490151643753 seconds** |
| Task deadline / Shell timeout | 7,800 / 7,320 seconds |

The [native surface receipt](native-surface.json), [job](job.json), [launcher](launcher.sh), [supervisor](supervisor.py), [runner](runner.py), [Core harness](core-harness.py) and [outer exit](exit.json) preserve that identity. No proxy, TLS or network setting was changed for the native run. The service loaded the b28 source through `PYTHONPATH`; this was not execution from the current b31 / RC14 package.

After the terminal receipts appeared, independent review recomputed the manifest digest and checked every one of the 110 source-file SHA-256 values against both the frozen checkout and the corresponding b28 Git blob: **110/110 match**, with the expected HEAD/tree and a clean checkout. The review did not rerun any model, Shell, business test or task.

## Actual execution and independent checks

| Check | Raw evidence and conclusion |
| --- | --- |
| Real foreground Shell | [Complete task](soak-task.json.gz): the requested Python interpreter ran `heartbeat.py` with timeout 7320 and Full access. Its fresh receipt is `completed`, exit 0, `process_completed=true`, untruncated marker stdout and empty stderr. |
| At least two hours in the Shell | The actual [heartbeat script](heartbeat.py) matches the exact initializer in the frozen runner. It writes the marker only after `time.monotonic() - start` reaches 7200, then exits normally. There is **no separate Shell-duration field** in its receipt; the measured task duration above is not relabelled as an exact Shell duration. |
| Heartbeat continuity | [heartbeat.jsonl](heartbeat.jsonl) contains **240** strictly increasing samples, from `0.00007033699512248859` to `7170.148518402995` seconds. Sampling occurs before each 30-second wait, so the last sample precedes the final wait and marker write. |
| Completion marker | [soak-finished.txt](soak-finished.txt) is exactly the 24-byte `LOCALPILOT_SOAK_COMPLETE`, SHA-256 `4a780a56e5db021c969dc0e2f379d9b61c062ff436247ac92e920507a8a29a24`. |
| Real file readback | The next actual `read_file` receipt reads `soak-finished.txt`, matches that hash and size, covers the whole file, is not truncated or reused, and records new coverage. |
| Actual model readback | The subsequent model response is exactly `LOCALPILOT_SOAK_COMPLETE`; it is supported by the preceding tool receipt. |
| Terminal state | The task is **completed and quiescent**, with execution settled, delivery delivered, no required action, no pending approval, no unfinished goal/worker and zero UNKNOWN receipts. |
| Owned shutdown | [RESULTS.json](RESULTS.json) records `owned_core_stopped=true`; the frozen Core harness terminates and waits for the owned process. The following native [exit receipt](exit.json) records return code 0. This is not a new system-wide process inventory. |

The independent [VERIFICATION.json](VERIFICATION.json) retains the exact source comparisons, tool IDs, read coverage, task obligations and time basis. The [last periodic progress file](soak-progress.json) still says `running`: it is the unmodified checkpoint from the runner's 15-second reporting interval, not a terminal receipt. The later saved task, RESULTS and supervisor exit establish completion; no progress record was rewritten to make it appear final.

The run records **three actual model calls**, **8,276 input tokens** and **243 output tokens**, with no failed model attempt and no unknown usage call. There are two tool receipts and no subagents. The runner records zero approval interventions, and the terminal task has no pending approval. No extra approval or manual continuation was performed. Actual monetary cost remains unknown. The [resolved budgets](resolved-runtime-budgets.json) are preserved as configured ceilings, not claimed consumption.

## What this result establishes

The fixed external soak criterion passed. Internal `verification_status=not_run`, `engineering_status=unverified` and `task_outcome=unverified` remain unchanged; external soak PASS does not rewrite those internal classifications.

This exercises one real, long foreground Shell while Core retains the task and later processes fresh tool results and model requests. It does not establish two hours of continuous model inference, a 24-hour completed task, sustained multi-agent workload or a general autonomous-success rate. The task used the native run's Python 3.12.14, distinct from the packaged application's Python 3.13.

The [source-continuity comparison](../long-run-source-continuity.json) independently found 47 relevant Shell, Full/Extended budget, deadline, cancellation, transport and qualifier files byte-identical between b28 and b31. It also lists the four changed Core Runtime files, including changed model-facing patch-tool text. That limited continuity evidence does not make entire requests identical and does not turn this measured b28 run into a b31 or RC14 two-hour run.

[Interrupted R1](../cloud-soak-2h-r1-interrupted/RESULTS.md) retains 210 heartbeats and no terminal completion; [interrupted R3](../cloud-soak-2h-r3-interrupted/RESULTS.md) retains 97 heartbeats and no completion. Their unknown execution-session interruptions remain unclassified as application-permission failures. Their outcomes and elapsed times are not overwritten or accumulated into R4.

## Public archive boundary

[ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) records each allowlisted source path, original bytes/SHA-256 and archived bytes/SHA-256. The complete task is stored with deterministic gzip (`mtime=0`) and decompresses to the exact original bytes. Only the known private key **filepath** in the job is replaced with `<private_key_file>`; no credential file was opened or copied. Other source receipts and scripts remain byte-preserving, with transformations stated individually.

Private Core configuration, client/provider credential material, raw SQLite/WAL, unrelated workspace files, model weights, candidate diagnoses and reference labels are excluded. The original run is untouched. This review and archive made no API call, did not operate Terminal tab 8, and did not interrupt or restart any process.
