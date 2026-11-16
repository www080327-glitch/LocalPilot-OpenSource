# Engineering R2 on Core b28 — infrastructure interruption

**Outcome: no terminal result.** This attempt is neither a PASS nor a product-failure verdict. Its incomplete evidence is retained independently of the earlier R1 result and the later native-Terminal R3 attempt.

## Source and declared execution

- Source commit: `03535fe943f64f49e9e3d79e7949aca6c9ec9b87`.
- Clean source tree: `1792d58af7858208db5018a747d78a1c75848edf`.
- Frozen engineering runner SHA-256: `108f948c1b32fa9de95e48a1a84ede4b4b78a3d3ecfabe1c9977e4b7e21cc0fb`.
- Interpreter: Python `3.12.14`, Clang `22.1.3`, using the designated task-tool interpreter.
- Entry point: executor foreground TTY session `5638`.
- Model contract: `gpt-6-luna`, Responses, medium reasoning; Full permission with standard execution budget; 1,200-second task deadline. Parent limit: 100 steps / 200 tools. Two requested async children: 20 steps / 40 tools each, within host worker ceilings of 30 steps / 60 tools.

[EXECUTION_START.json](EXECUTION_START.json), [PROTOCOL.json](PROTOCOL.json), [runner.py](runner.py) and [prompt.txt](prompt.txt) preserve the declared execution. No fixture, prompt, budget or runner change was made for this attempt.

## Observed interruption

| Receipt | Observation |
| --- | --- |
| Start | `2026-11-16T20:10:46.420494+00:00` |
| Last saved progress | `2026-11-16T20:12:32.415665+00:00`; elapsed **105.606908799 seconds** |
| Saved task state | Task ID present; `running`, `quiescent=false` |
| Parent's executor observation | At approximately 20:19:50 UTC, session lookup returned `Unknown process id` and execution-session state had reset. |
| Runner stdout/stderr log | Present, **0 bytes**; no final result line |
| `RESULTS.json`, execution-end receipt, exit code | Unavailable |
| Owned Core termination | **Not established by an observed stop receipt** |

[EXECUTOR_INTERRUPTION.json](EXECUTOR_INTERRUPTION.json) records the interruption and preserved-file hashes; [engineering-progress.json](engineering-progress.json) is a stale checkpoint, not a live status query. Its empty tool list does not establish zero model calls or zero provider usage. No terminal tool ledger or external acceptance result is available, so there is no 17-test / four-CLI result to report for R2.

The original attempt was not resumed or automatically rerun. A separately authorized [R3 native-Terminal attempt](../engineering-luna-r3-b28-native/RESULTS.md) uses a new output directory; its outcome does not replace this interruption. The earlier R1 result remains attributed to its own older source snapshot.

## Archive boundary

The explicit allowlist contains public protocol, prompt, original acceptance files, startup/progress/interruption receipts, the frozen runner and logs. No live workspace, private Core configuration, database, credential file or unrelated benchmark material was copied. Fixed absolute path prefixes are replaced with named placeholders. [ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) records original and published sizes and SHA-256 values; the original files remain unchanged in scratch.
