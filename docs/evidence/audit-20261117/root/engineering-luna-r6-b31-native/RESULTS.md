# Engineering R6 on Core b31 — PASS

**Protocol, orchestration, semantic acceptance and overall engineering qualification all PASS; exit code 0.** Two actual asynchronous cloud children implemented separate parser and aggregation modules and ran their required test classes. The parent integrated the CLI, ran the full tests and produced the requested output. The independent immutable acceptance subsequently passed **17 unit tests and all four CLI cases**.

This is the sole authorized R6 attempt against this frozen b31 source. The same runner, prompt, fixtures, budgets and criteria were used. [R5](../engineering-luna-r5-b30-native/RESULTS.md), [R4](../engineering-luna-r4-b29-native/RESULTS.md) and [R3](../engineering-luna-r3-b28-native/RESULTS.md) remain archived as FAIL; [R2](../engineering-luna-r2-b28/RESULTS.md) remains interrupted. This result is a version-specific integration qualification, not a success-rate estimate over interchangeable attempts.

## Source and execution identity

| Item | Recorded value |
| --- | --- |
| Frozen source commit | `c5439659a579b2ee9e74fd53e6d3232fe12fb855` |
| Clean source tree | `d0b0b33b036587ef0f0a802ca728419e9a444587` |
| Runtime source manifest | `0d81995004ae32f41c635f00e114d572f81733545ce8420537a9c41a5f92e789` |
| Package / actual service version | Both `5.0.0b31`; checked before launch and retained in the service log |
| Frozen engineering runner SHA-256 | `108f948c1b32fa9de95e48a1a84ede4b4b78a3d3ecfabe1c9977e4b7e21cc0fb` |
| Native job original SHA-256 | `0e76e73506a297b642a932d229328b481a9118684f303eb2f1d5a3c77ff5d765` |
| Model / protocol | `gpt-6-luna`, OpenAI Responses, medium reasoning |
| Entry point / interpreter | Native Terminal foreground; Python `3.12.14`, Clang `22.1.3` |
| Start / finish | `2026-11-16T21:49:34.627425+00:00` / `2026-11-16T21:51:36.737741+00:00` |
| Model/Core / outer duration | **121.5947 / 122.1103 seconds** |
| Shutdown and integrity | Owned Core stopped, source unchanged, clean tree afterward |

The [protocol](PROTOCOL.json), [execution start](EXECUTION_START.json), [execution end](EXECUTION_END.json), [job preparation](JOB_MANIFEST.json), [native job](native-job.sh), [runner](runner.py) and [service log](core.log) are retained. Apart from source identity, the full protocol matches R5: Full + standard, a 1,200-second deadline, parent 100 steps / 200 tools, requested children 20 steps / 40 tools each, host ceilings 30 steps / 60 tools, maximum two children and one-second polling. The prompt SHA is `9c2e3300ef2bff76b38b2c1c645f1bb9d1e112cff853a40779f4aeb8f69e693a`; prompt and all 12 original fixture hashes match. The only environment change remains prepending the fixed task Python directory to inherited PATH; proxy/TLS settings were unchanged.

## Independent result checks

| Layer | Result | Actual evidence |
| --- | --- | --- |
| Protocol | **PASS** | Parent completed and quiescent, execution settled, delivery delivered; no pending approval, queued work, unfinished goal/worker, UNKNOWN receipt or mutation intent. Source remained unchanged and Core stopped. |
| Orchestration | **PASS** | Two completed, collected async children; each changed only its assigned module, ran the required test class and had a recorded model-call history. Their completed lifecycles overlap. The parent changed the CLI and ran real tests and CLI. |
| Semantic acceptance | **PASS** | [External unittest receipt](external-unittest.json): 17 tests, exit 0. [External CLI receipts](external-cli.json): basic/precision/empty pass with exit 0; invalid-input case passes with exit 2. Parent CLI output matches. |
| Engineering | **PASS** | All three unchanged preceding criteria pass. |

| Child | Model calls / tool receipts | Assigned changes | Successful child test | Terminal state |
| --- | --- | --- | --- | --- |
| `1.1` | 6 / 17 | `logstats/parser.py` only | Nine ParserTests, exit 0 | completed, resolved, collected |
| `1.2` | 6 / 16 | `logstats/aggregate.py` only | Three AggregateTests, exit 0 | completed, resolved, collected |

The recorded start-to-completed lifecycles overlap by **58.072972 seconds**. This measures concurrent child lifecycles, including inference and tools, rather than simultaneous CPU execution. Recomputing the frozen `orchestration()` function from the saved task produced exactly the saved result, without rerunning models or tests.

Aggregate accounting is **23 model calls, 56 tool receipts, 296,537 input tokens and 14,983 output tokens**, including both children. Failed model attempts and UNKNOWN-effect receipts are zero. Actual monetary cost is not reported. Completion used one bounded final-delivery attempt.

## Delivered code and preserved failure

A read-only inspection of the saved code confirms a general implementation rather than fixture-output lookup: the [parser](final-project/logstats/parser.py) uses CSV parsing, record validation, timezone normalization and Decimal values; the [aggregator](final-project/logstats/aggregate.py) groups by category, uses exact decimal summation and stable sorting; the [CLI](final-project/logstats/__main__.py) reads input, emits JSON and reports invalid input. The original SPEC/tests/fixtures were preserved. The four delivered-module hashes were verified against the acceptance receipt and the saved [file manifest](file-manifest.json).

One auxiliary parent inspection command failed and remains visible: `git diff -- logstats/parser.py logstats/aggregate.py logstats/__main__.py result.json` returned exit **129** with Git usage output. Receipt `turn:1/call:call_2fuE1MEQ6qOZb9OwrPqWXoig/entry:54` records `nonzero_exit`, `side_effect_status=failed_process`, `process_completed=true` and `action_may_have_applied=false`. This completed failed inspection did not invalidate the successful required tests or CLI. It was neither hidden nor rewritten as a successful command.

No child failed-process receipt or missing-directory failure occurred in R6. Therefore this successful integration does not by itself demonstrate execution of those two new exception branches. The separate real local regressions cover them: [settled child Shell recovery](../async-settled-shell/RESULTS.md) and [missing-directory observation](../async-missing-directory/RESULTS.md).

## Evidence boundary

[ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) lists the public artifacts, original/published hashes and deterministic gzip encoding of [the complete task](engineering-task.json.gz). Fixed absolute path prefixes are replaced with named placeholders. Original artifacts remain unchanged. Private Core configuration, databases, live workspace, credentials and unrelated reference labels are excluded.

The output is one small standard-library Python project's engineering integration result. It provides no general model-quality score or public benchmark ranking, and source-based Core execution is separate from RC14 packaged-application and macOS qualification. The earlier attempts retain their original outcomes.
