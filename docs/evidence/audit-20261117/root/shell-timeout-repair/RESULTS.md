# Shell timeout repair and child receipt projection

**Result: 73 tests run; 72 passed, one existing macOS-only test skipped, zero failures.** These are local implementation tests with scripted model responses and real `AgentSession` / host Shell execution. No external model API was called for this repair validation.

**Release binding:** Core **5.0.0b28** and Desktop **5.0.1-rc.11** source were published at [`03535fe943f64f49e9e3d79e7949aca6c9ec9b87`](https://github.com/www080327-glitch/LocalPilot-OpenSource/commit/03535fe943f64f49e9e3d79e7949aca6c9ec9b87), tree `1792d58af7858208db5018a747d78a1c75848edf` (local source commit `2d44a73801d580da5ae10ae9437951435e59ce59` has the same tree). The four tested source files are identified by SHA-256 in [ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json). This report proves the implementation checks; package and native validation have their own receipts.

## Two reproduced defects

1. A Shell proposal rejected before dispatch for `timeout=120000` remained an unresolved mutating failure even after a fresh call executed the identical command successfully with `timeout=120`. A real append-and-read test wrote `proof.txt` exactly once but ended `incomplete`. The new association uses the existing `repaired_proposals` field and preserves the original failed receipt. It requires the actual host-installed Shell, an old `schema_validation` / `not_dispatched` receipt with no possible action, a fresh successful `process_completed=true` result, the same turn and worker, and identical arguments except `timeout`.
2. After that repair, a real Full parent/child test still ended `incomplete`: the child was `completed`, its obligation was `resolved`, and the parent read the file successfully. Child receipt IDs gained a worker prefix during projection, while their repair references remained local IDs. Projection now applies the same prefix to both. Unfinished-call accounting accepts projected IDs and the prior local-ID representation.

The general `Session._finish` completion rule, tool schema, prompts, budgets and UNKNOWN handling were not changed. Production changes are confined to `agent/tool_protocol.py`, `agent/session_tools.py` and `agent/session_workers.py`; five real workflow tests were added to the existing `tests/test_shell_failure_repair.py`.

## Recorded controls

| Check | Observed outcome |
| --- | --- |
| Initial three-test control, before production changes | Exact timeout-only retry failed its expected `completed` assertion; no-execution and different-command negatives passed. [BEFORE.log](BEFORE.log) |
| Full parent/child control, after Shell association but before projection repair | Child completed with its repair linked; parent still returned `incomplete`. [CHILD_BEFORE.log](CHILD_BEFORE.log) |
| Final timeout-only retry | `completed`; file contains one append; original rejection retains `action_sent=false` and `action_may_have_applied=false`. |
| Final Full parent/child | Both complete; projected repair references match projected receipt IDs. |
| No execution, different command, or reuse of an older success receipt | Remain `incomplete`; none gains a new repair association. |
| Existing uncertain Shell timeout | Remains `UNKNOWN_BLOCKED`. |

Final command, run from the primary source checkout:

```sh
python -B -m unittest tests.test_shell_failure_repair tests.test_tool_protocol_reliability tests.test_harness_reliability tests.test_async_runtime -v
```

[FINAL.log](FINAL.log) records **73 tests in 9.450 seconds**, including existing patch repair, repair-limit, UNKNOWN/no-replay, child accounting, SQLite recovery and async-runtime checks. The one skip is `test_invalid_macos_flag_can_be_inspected_and_corrected`, which requires native macOS / Seatbelt; this validation ran on Linux. `git diff --check` passed for the four changed files.

## Benchmark and compatibility boundary

The frozen R2 case-020 metadata demonstrated the exact-command, timeout-only successful-retry mechanism. This fix is validated separately; the candidate was not rerun and its archived status or score was not changed. Case-019 used different later commands, so this narrow association does not cover it and makes no inference about equivalent script intent. Other schema errors remain subject to the existing completion rules. Historical task snapshots and prior benchmark reports are not migrated or reclassified.

The original three logs remain in scratch. Public copies replace only the absolute source-checkout prefix with `<source_root>`; the manifest records both original and published sizes and SHA-256 values. No old benchmark evidence was modified.
