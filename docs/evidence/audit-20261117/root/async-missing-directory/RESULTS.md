# Async child missing-directory observation regression

## Result

The original implementation reproduced a completion-status defect: the root-session control completed after an exploratory missing-directory observation, while the same actual tool sequence in an asynchronous child left the parent `incomplete`. The four-line correction passed all 28 tests in the existing asynchronous runtime suite in 5.988 seconds. Production and test edits were then frozen.

This is a local regression with scripted model responses and real `AgentSession`, `TaskService`, child scheduler threads, SQLite persistence, filesystem reads and `apply_patch` delivery. No external model/API was called. It is not a rerun or reclassification of the recorded R4 engineering attempt.

## Cause and correction

`SessionWorkers._sync_child` added an unsuccessful `list_directory` observation to `unfinished_calls` even when the error was `FileNotFoundError` and `side_effect_status` was `not_completed`. The child subsequently found the correct directory and delivered its file, but the historical observation kept its obligation unresolved. Root-session completion already allowed this read-only observation, so the two execution paths disagreed.

The only production change is four lines in `_sync_child`: skip adding precisely that three-condition observation to the child's unfinished obligations. The original failed receipt remains visible, with `ok=false`, the original error and the original side-effect status. The existing reserved builtin `list_directory` identity is used. `_finish`, tool schemas, all other errors, capability denials, mutations, partial/UNKNOWN effects and pending child work are unchanged.

## Reproduction and controls

Both new tests perform the same real sequence: attempt `tests/fixtures` (absent), successfully list `fixtures`, create `delivered.txt` through the actual patch tool, and finish. The async test additionally delegates through the real scheduler, waits and collects the child, and asserts child and parent completion, resolved obligation and empty `unfinished_calls`. Both tests assert the delivered file, retained failed receipt, successful directory observation and SQLite database existence.

| Stage | Command from repository root | Result |
| --- | --- | --- |
| Original source with new tests | `python -m unittest tests.test_async_runtime.AsyncRuntimeTests.test_root_missing_directory_observation_keeps_failed_receipt_and_completes tests.test_async_runtime.AsyncRuntimeTests.test_async_child_missing_directory_observation_does_not_block_delivery -v` | 2 tests / 0.145s: root PASS; async FAIL (`incomplete` versus `completed`) |
| Corrected source | `python -m unittest tests.test_async_runtime -v` | 28 tests / 5.988s: all PASS; no skip |

The existing suite includes capability-denied children, model/child failure, UNKNOWN effects with and without persistence, recovery/restart, cancellation of a child and parent, pending approvals, scheduler accounting and overlap. Their original assertions were retained. No broader optional regression was run here.

## Source and evidence identity

The before-stage baseline is commit `5a0a77b7486e412e2ed9f29c9fab8295e7a81d6a`. This isolated change is four production additions and 38 test additions across two files. The tested file hashes and interpreter identity are in [SOURCE_AFTER.json](SOURCE_AFTER.json); the original implementation and same new tests are identified in [SOURCE_BEFORE.json](SOURCE_BEFORE.json). The subsequent Core b30 / Desktop RC13 release identity is assigned separately by the release owner; these local tests do not claim packaged-native or macOS validation.

[BEFORE.log](BEFORE.log) preserves the original failure; [AFTER.log](AFTER.log) preserves the complete passing targeted run. [ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) records sizes, published hashes and original log hashes. Log publication changes only the exact local repository path prefix. The prior frozen b29 R4 engineering result remains **FAIL**; its failed missing-directory receipt and all original benchmark and engineering evidence remain untouched.
