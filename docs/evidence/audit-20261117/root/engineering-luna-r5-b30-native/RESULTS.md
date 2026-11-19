# Engineering R5 on the b30 source — FAIL, semantic acceptance PASS

**Overall result: FAIL, exit code 1.** The original external acceptance passed **17 unit tests and four CLI cases**. Both asynchronous children implemented their assigned modules, and the parent integrated and tested the project. Both children nevertheless ended `incomplete`. The parser child recovered from an invalid interpreter path and passed its tests, but an earlier settled failed process remained an unfinished child obligation. The aggregation child did not successfully run its required test class, which independently fails the frozen orchestration contract.

This is the sole authorized R5 attempt for this source. There was no task retry or verifier change. [R4 b29](../engineering-luna-r4-b29-native/RESULTS.md) and [R3 b28](../engineering-luna-r3-b28-native/RESULTS.md) remain FAIL; [R2](../engineering-luna-r2-b28/RESULTS.md) remains interrupted.

## Source and execution

| Item | Recorded value |
| --- | --- |
| Exact source commit | `1dca93c5a6a2d0c557a9507ca020c07458dd92d1` |
| Clean source tree | `1457ce75f9134196c0c489f69bc4ee5b03467d4b` |
| Runtime source manifest | `4fd87c5e367cb20ea9e7ce99e4f1a56bed1625758e76ac31031da79ea990ef94` |
| Frozen runner SHA-256 | `108f948c1b32fa9de95e48a1a84ede4b4b78a3d3ecfabe1c9977e4b7e21cc0fb` |
| Native job original SHA-256 | `2d85d2605331ae41d12e0d5ac5ffbd28b6a0490a57c2cdbf1e6aecc2fd7e6669` |
| Model / protocol | `gpt-6-luna`, OpenAI Responses, medium reasoning |
| Entry point / interpreter | Native Terminal foreground; Python `3.12.14`, Clang `22.1.3` |
| Start / finish | `2026-11-16T21:33:42.361815+00:00` / `2026-11-16T21:36:19.690188+00:00` |
| Model/Core / outer duration | 156.7709 / 157.3284 seconds |
| Shutdown and integrity | Owned Core stopped, source unchanged, clean tree afterward |

The exact source identity matters: this is the checkout published as b30, while its service `VERSION` still advertised `5.0.0b28`, as retained in [core.log](core.log). That metadata inconsistency does not imply a different runtime checkout. This report follows the recorded commit, tree and source-file manifest.

[PROTOCOL.json](PROTOCOL.json), [EXECUTION_START.json](EXECUTION_START.json), [EXECUTION_END.json](EXECUTION_END.json) and [JOB_MANIFEST.json](JOB_MANIFEST.json) preserve the run contract. Apart from source identity, the entire protocol matches R4: Full + standard, 1,200-second deadline, parent 100 steps / 200 tools, requested children 20 steps / 40 tools each, host ceilings 30 steps / 60 tools, maximum two children, one-second polling. The prompt SHA is `9c2e3300ef2bff76b38b2c1c645f1bb9d1e112cff853a40779f4aeb8f69e693a`; prompt and all 12 fixture hashes are identical. Only the fixed Python directory was prepended to inherited PATH; proxy/TLS settings were unchanged.

## Result layers

| Layer | Result | Recorded evidence |
| --- | --- | --- |
| Protocol | **FAIL** | Parent `incomplete`, quiescent; null task error and required action; two unresolved workers. |
| Orchestration | **FAIL** | Both async and collected, each changed only its assigned module, but neither reached completed. Aggregation lacks a successful AggregateTests receipt. |
| Semantic acceptance | **PASS** | [17 external tests](external-unittest.json), exit 0; [four CLI cases](external-cli.json), basic/precision/empty exit 0 and invalid input exit 2; parent CLI artifact matches. |
| Engineering | **FAIL** | The unchanged criterion requires all three preceding layers to pass. |

| Child | Calls / receipts | Assigned module | Child test | Terminal state |
| --- | --- | --- | --- | --- |
| `1.1` | 7 / 10 | `logstats/parser.py` only | Nine ParserTests passed after interpreter correction | incomplete, unresolved, collected |
| `1.2` | 7 / 12 | `logstats/aggregate.py` only | Initial invocation failed; no successful subsequent test invocation | incomplete, unresolved, collected |

Aggregate accounting is **28 model calls, 56 tool receipts, 383,365 input tokens and 18,471 output tokens**, including both children. Failed model attempts and UNKNOWN-effect receipts are zero. Actual monetary cost is not reported. The parent changed the CLI, ran all 17 tests successfully and ran the CLI to produce `result.json`. Original acceptance files and all four delivered-module hashes were verified against the saved receipts.

Actual start-to-terminal child lifecycles overlap by **47.894476 seconds**. The frozen verifier's start-to-`completed` overlap is **0**, because both terminal events are `incomplete`; this does not mean they executed sequentially. Recomputing the frozen `orchestration()` function from the saved task reproduced its result exactly, without running models or tests again.

## Failure chain and classification

The fixed parent prompt contains the real interpreter path. The parent instead delegated a shortened `.../.venv/bin/python` command and told its children to adjust the absolute root. Both children attempted `<workspace>/.venv/bin/python`, which did not exist.

- Parser receipt `worker:1.1/turn:1/call:call_uqn2P92ViPohiVekXBXTGwJS/entry:5` returned Shell exit **127**. Later receipt `turn:1/call:call_ZPuxEiSGeFJgp39krqpwFuBD/entry:9` used `python3`, ran nine ParserTests and exited 0. The earlier failure nevertheless remained the child's sole `unfinished_calls` entry.
- Aggregation receipt `worker:1.2/turn:1/call:call_eM08Ug3AzyEXWIjeCylYocTQ/entry:6` returned the same exit **127**. Subsequent receipts inspect the directory/module and update/read the aggregation file, but do not run Shell again. The required successful child test therefore genuinely did not occur.

Both failed receipts have `error.type=nonzero_exit`, `side_effect_status=failed_process`, `process_completed=true`, `action_may_have_applied=false` and `replay_allowed=false`. They are observed, terminated process failures, not UNKNOWN effects. The source's root `_finish` explicitly treats `failed_process` as a settled failed attempt; `_sync_child` still includes it in child unfinished calls. The parser sequence demonstrates that completion-accounting inconsistency after successful recovery. The aggregation test omission is a separate model failure to satisfy the requested workflow. Even if the accounting inconsistency were later corrected, that omission prevents reclassifying this attempt as PASS.

The first parent delegate proposal also omitted required `backend_preference` and received `schema_validation` / `not_dispatched`; the later valid proposals created the two real children. That rejected proposal is preserved. No failed `list_directory`/`FileNotFoundError` receipt occurred in R5, so this run did not directly exercise the new b30 missing-directory branch.

## Evidence boundary

[ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) records an explicit public allowlist, original and published hashes, and deterministic gzip storage of [the complete task](engineering-task.json.gz). Fixed absolute path prefixes are replaced by named placeholders. Original run files are unchanged. No private Core configuration, database, live workspace, credential file or unrelated reference labels were copied.

This is one source-based synthetic engineering integration attempt, not a general model-quality score, a benchmark rerun or packaged-native/macOS qualification. The old failures remain separate, and any later fixes or release versions do not change this R5 verdict.
