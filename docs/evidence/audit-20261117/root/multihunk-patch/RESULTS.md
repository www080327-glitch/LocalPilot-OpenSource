# Same-file multi-update patch regression

**Final targeted result: 74 tests, 73 PASS, one existing macOS-only SKIP, zero failures or errors, in 4.584 seconds.** This is local implementation validation with real Registry, Full parent/child Session and filesystem operations. Model responses are scripted; no external model API was called. Version and new remote commit assignment remain with the release owner.

## Concrete issue and implementation

The b28 engineering R3 task submitted two `update` changes for the same file in one `apply_patch`. The existing preflight rejected every repeated path, although both updates in that specific request matched exactly once in sequence and the second was a no-op. The child later changed the file successfully, but its prior failed mutation remained unresolved. The archived [R3 result remains FAIL](../engineering-luna-r3-b28-native/RESULTS.md).

The implementation change is confined to `agent/patches.py`: **15 added / 8 removed lines, net +7**, including a readability-only line wrap. Prepared entries are indexed by resolved target. Repeated targets are allowed only when every operation for that target is `update`; later exact-text matches use the prior in-memory result. Each file keeps its original `before` bytes, inspected identity and expected-hash comparison. After the complete batch passes preflight and authorization, the existing commit path writes each file once and returns one final before/after/diff receipt per file.

The `apply_patch` description in `agent/schemas.py` adds the public contract: same-file updates apply in input order, and `expected_sha256` always refers to the original inspected version. This changes one description line only. An AST comparison confirms all schema fields and other tools are identical. Production totals are **16 added / 9 removed lines** across those two files; tests add 92 lines.

Repeated `create` or `delete`, and mixed operations on one target, remain rejected. A later mismatch or wrong original hash prevents the whole prepared batch from being written. The existing lock, approval, conflict, partial-effect and UNKNOWN behavior is retained. `tool_protocol.py` and `Session._finish` were not changed; their source hashes still match the frozen b28 source.

## Recorded before and after

| Stage | Result | Meaning |
| --- | --- | --- |
| Before production change | Two new positive controls: **1 ERROR + 1 FAIL**, exit 1 | Real Registry rejected the repeated target; real Full parent/child ended `incomplete`. [BEFORE.log](BEFORE.log) |
| First focused run after production change | **4 PASS + 1 FAIL** | The remaining failure was a new test's audit filter: existing applied audit records expose operation `update`, while the test incorrectly filtered `apply_patch`. The real file, one physical replacement, final receipt and hashes had already passed their assertions. Only the test filter was corrected to use applied status and target path. [FOCUSED_FIRST.log](FOCUSED_FIRST.log) |
| Implementation targeted suite | **73 PASS + 1 SKIP**, exit 0, 4.734 seconds | All five new workflow tests and the selected existing reliability checks passed. [AFTER_IMPLEMENTATION.log](AFTER_IMPLEMENTATION.log) |
| Final suite after public description and line wrap | **73 PASS + 1 SKIP**, exit 0, 4.584 seconds | Same targeted suite against the final three source/test files. [AFTER.log](AFTER.log) |

Five new tests in the existing `tests/test_agent_coding.py` cover:

- Sequential same-file updates, including a later match that exists only after the first update, while both expected hashes refer to the original file. A wrapper around the real `os.replace` verifies one actual replacement; the real final file, one receipt, one applied audit entry and original/final identities are checked.
- A real Full parent/child Session completing a same-file update plus no-op without an initial rejection or a repair marker.
- A later exact-text mismatch leaving both the repeated target and an earlier prepared create unwritten.
- Repeated/mixed create, delete and update rejection with unchanged files.
- Rejection of an intermediate-content hash used where the original inspected hash is required.

Final command:

```sh
python -B -m unittest tests.test_agent_coding tests.test_v2_remaining_reliability.A03Tests tests.test_tool_protocol_reliability tests.test_shell_failure_repair -v
```

The selected existing checks include batch preflight, approval-time and post-approval conflicts, cross-process writers, lock failures, partial write receipts, argument repair, child accounting, UNKNOWN/no-replay and the b28 Shell timeout repair. The skip requires native macOS / Seatbelt; these tests ran on Linux. `git diff --check` passed for the three changed source/test files.

## Source and evidence boundary

[SOURCE_BEFORE.json](SOURCE_BEFORE.json) captures production before the change and the newly added controls. [SOURCE_AFTER_IMPLEMENTATION.json](SOURCE_AFTER_IMPLEMENTATION.json) retains the intermediate implementation snapshot; [SOURCE_AFTER.json](SOURCE_AFTER.json) captures the final three source/test hashes and unchanged completion/repair files. The baseline `patches.py` hash is the same as frozen b28 commit `03535fe943f64f49e9e3d79e7949aca6c9ec9b87`. The test-file hash changed once after the initial focused run for the audit-filter correction described above; that intermediate failure is retained.

[ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) records original and published log hashes. Original logs remain in scratch; public logs replace only the absolute source checkout prefix. This patch is later than the b28 source used by R3 and the ongoing b28 Shell-duration validation. No result from those runs is reassigned to this source, and no benchmark outcome or score was changed.
