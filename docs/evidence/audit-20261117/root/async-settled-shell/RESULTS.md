# Async settled Shell failure regression

## Result

The original source reproduced a root/child completion-accounting inconsistency with an actual host Shell: after a missing interpreter returned exit 127, the session delivered a real file and passed a real unittest. The root session completed, but the same sequence in an asynchronous child left both child and parent incomplete. The two-line production correction passed the targeted runtime and Shell regression suites: **37 tests, 36 PASS and one existing macOS-only SKIP, 6.622 seconds**.

This is a local scripted-model regression using real Full scope revision 3, `AgentSession`, `TaskService`, asynchronous scheduler threads, SQLite, filesystem patching and subprocess execution. It makes no external API call and does not reclassify [engineering R5](../engineering-luna-r5-b30-native/RESULTS.md), which remains FAIL.

## Existing contract and minimal correction

Root `AgentSession._finish` already excludes `side_effect_status=failed_process` from unresolved mutation failures: an observed, terminated process can be a failed attempt without an uncertain external effect. `SessionWorkers._sync_child` instead retained the same failed process as an unfinished child obligation, even after the child corrected its command and successfully tested the delivered file.

The production change is exactly two added lines in `_sync_child`, reusing that existing `failed_process` classification. The classification is produced by `_record_call` only for a qualified actual host Shell with `status=nonzero_exit` and `process_completed=true`; UNKNOWN classification has precedence. No repeated tool metadata validation or new classification is introduced. Root `_finish` is unchanged.

The failed receipt remains present with its original error, exit 127 and failed-process status. Settling its execution does not turn it into a successful process, assert that an unperformed test ran, replay the command or erase historical failure. UNKNOWN, partial, denied, pending and genuinely unfinished work retain their existing treatment.

## Actual reproduction and targeted verification

Both new tests create a fixed one-test unittest file in the temporary workspace. The model-response sequence invokes a nonexistent `.venv/bin/python`, creates `delivered.txt` through the actual `apply_patch` tool, invokes the real Python interpreter to run the unittest and finishes. The test asserts the file's exact delivered content. The root and async assertions also retain exit 127 and `process_completed=true`, then require the successful Shell exit 0 and actual `Ran 1 test` output. The async case requires collected child/parent completion, a resolved child obligation and no unfinished calls. Both run with the actual SQLite store.

| Stage | Command from repository root | Result |
| --- | --- | --- |
| Original implementation | `python -m unittest tests.test_async_runtime.AsyncRuntimeTests.test_root_settled_shell_failure_allows_actual_recovery tests.test_async_runtime.AsyncRuntimeTests.test_async_child_settled_shell_failure_allows_actual_recovery -v` | 2 tests / 0.280s: root PASS; async FAIL (`incomplete` versus `completed`) |
| Corrected implementation | `python -m unittest tests.test_async_runtime tests.test_shell_failure_repair -v` | 37 tests / 6.622s: 36 PASS, one existing native macOS/Seatbelt SKIP; zero failures |

Existing assertions cover denied children, model failure, UNKNOWN effects with/without persistence, restart, approvals, child/parent cancellation, queue/accounting, unexecuted schema rejections, different commands, reused successful receipts, repaired child receipt projection and an actual timed-out Shell. They were not relaxed. `git diff --check` passed. No broad optional regression or real-model retry was run here.

## Source and evidence

The isolated diff is **two production additions and 60 test additions across two files**. [SOURCE_BEFORE.json](SOURCE_BEFORE.json) identifies the old implementation with the same new tests; [SOURCE_AFTER.json](SOURCE_AFTER.json) identifies the corrected files, interpreter and unchanged root/classification contract sources. Core b31 / Desktop RC14 version assignment and release validation are handled separately; this evidence does not claim those packages or macOS execution.

[BEFORE.log](BEFORE.log) retains the actual failing reproduction. [AFTER.log](AFTER.log) retains the complete targeted result. [ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) records sizes and hashes, including original versus published logs; publication replaces only the exact repository absolute-path prefix.

R5's aggregation child did not run its required successful AggregateTests invocation. This correction cannot supply that missing model action, and the frozen R5 orchestration result remains FAIL. No engineering prompt, fixture, verifier, task budget, frozen source or original model receipt was changed.
