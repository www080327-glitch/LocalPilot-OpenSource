# Engineering R4 on Core b29 — FAIL, semantic acceptance PASS

**Overall result: FAIL, exit code 1.** The immutable external acceptance passed **17 unit tests and four CLI cases**. Both children implemented their assigned modules and passed their test classes, but the parser child retained an unsuccessful read-only directory probe as an unfinished obligation. That child and its parent therefore ended `incomplete`, failing the unchanged protocol and orchestration criteria.

This is the sole authorized R4 attempt against this frozen source. There was no task retry or verifier change. The [R3 b28 failure](../engineering-luna-r3-b28-native/RESULTS.md) and [R2 interruption](../engineering-luna-r2-b28/RESULTS.md) remain separately archived.

## Source and execution identity

| Item | Recorded value |
| --- | --- |
| Core source commit | `8e92deb8b6a0acbba1d139851b1d805246304c61` |
| Clean source tree | `813a2544f1553d9c6a5e8a01982f2f512eec5e5b` |
| Runtime source manifest | `faa4d838ccbcc1bb81f3e7c23642f3f1bd50066568f407fa6d9af32b8fae0ab9` |
| Frozen engineering runner SHA-256 | `108f948c1b32fa9de95e48a1a84ede4b4b78a3d3ecfabe1c9977e4b7e21cc0fb` |
| Native job original SHA-256 | `dbd0f194792244966c47c9dc6ab9f5315e450c1ce5d21c04b601d0f249ca56e4` |
| Model / protocol | `gpt-6-luna`, OpenAI Responses, medium reasoning |
| Entry point / interpreter | Native Terminal foreground, new tab; Python `3.12.14`, Clang `22.1.3` |
| Start / finish | `2026-11-16T20:58:35.296955+00:00` / `2026-11-16T21:03:04.657869+00:00` |
| Model/Core / outer execution duration | **268.7617 / 269.3609 seconds** |
| Source and shutdown | Source unchanged, clean tree afterward, owned Core stopped |

The [protocol](PROTOCOL.json), [start](EXECUTION_START.json), [end](EXECUTION_END.json), [job preparation](JOB_MANIFEST.json), [runner](runner.py) and [native job](native-job.sh) are preserved. Apart from the source identity, the protocol is identical to R3: Full + standard, 1,200-second deadline, parent 100 steps / 200 tools, two requested children at 20 steps / 40 tools each, host worker ceilings 30 steps / 60 tools, and one-second polling. The prompt SHA is `9c2e3300ef2bff76b38b2c1c645f1bb9d1e112cff853a40779f4aeb8f69e693a`; prompt and all 12 original fixture hashes match R3. The environment change remains only the designated Python directory prepended to inherited PATH; proxy/TLS settings were unchanged.

## Result layers and actual work

| Layer | Result | Evidence |
| --- | --- | --- |
| Protocol | **FAIL** | Parent `incomplete` and quiescent; task error and required action are null; one unfinished worker obligation remains. |
| Orchestration | **FAIL** | Both children were async and collected, edited only their assigned modules and ran their test classes. Parser child remained `incomplete`. |
| Semantic acceptance | **PASS** | [External unit receipt](external-unittest.json): 17 tests, exit 0. [External CLI receipts](external-cli.json): basic, precision and empty pass with exit 0; invalid-input case passes with exit 2. Parent CLI artifact matches. |
| Engineering | **FAIL** | The frozen criterion requires all three preceding layers to pass. |

| Child | Model calls / tool receipts | Assigned changes | Successful child test | Terminal state |
| --- | --- | --- | --- | --- |
| `1.1` | 6 / 9 | `logstats/parser.py` only | 9 ParserTests, exit 0 | `incomplete`, unresolved, collected |
| `1.2` | 5 / 7 | `logstats/aggregate.py` only | 3 AggregateTests, exit 0 | `completed`, resolved, collected |

Aggregate accounting is **35 model calls**, **60 tool receipts**, **732,942 input tokens** and **25,971 output tokens**, including both children. Failed model attempts and UNKNOWN-effect receipts are zero. Actual monetary cost is not reported. Original SPEC/tests/fixtures are unchanged, and the four delivered module hashes match the saved acceptance receipt and [final project](final-project/logstats/parser.py).

The verifier's completed-child lifecycle overlap is **0** because one child lacks a `completed` terminal event. Recorded start-to-terminal lifecycles overlap by **40.303256 seconds**. This describes concurrent child lifecycles, including inference and tools, rather than a CPU-concurrency measurement. Recomputing the frozen `orchestration()` function from the saved task produced the identical result.

## Failure diagnosis

Parser child receipt `turn:1/call:call_prJoHvxbEjzzjGu57fcQJgKl/entry:2` called:

```json
{"path":"tests/fixtures"}
```

The built-in `list_directory` returned `FileNotFoundError` and `side_effect_status=not_completed`. The child then read the acceptance tests, successfully listed `.` and the correct `fixtures` directory, implemented its parser, read it back and passed all nine ParserTests. The failed read-only probe nevertheless remained the child's sole `unfinished_calls` entry.

The source explains the discrepancy: the root Session completion scan checks unrepaired **mutating** failures, while `SessionWorkers._sync_child` adds any unsuccessful non-Computer child tool to unfinished calls. The subsequent child completion check sees that entry and returns `incomplete`; the parent retains one unfinished worker. This is a concrete child-accounting limitation for a missing-directory observation. The original failure receipt is retained in [the complete task](engineering-task.json.gz).

A parent CSV-behavior exploration command also exited 1 after a deliberate malformed-CSV sample reached the standard-library parser. Its receipt is correctly classified `failed_process`, with a completed process and no uncertain effects. Separately, the first finalization response hit `finish_reason=length`: its 1,024 output tokens were all reasoning. The second bounded finalization response returned `stop`; the unresolved child obligation still remained. Both finalization attempts are preserved and were part of the frozen runtime's existing procedure.

## Observed b29 multi-update behavior

Parent receipt `turn:1/call:call_PIPwLS7ytyG6FPA4unr46Rx6/entry:51` successfully applied **two update entries to `logstats/parser.py` in one call**, returning **one** final file receipt with `verification=passed`. Its final SHA-256 is `32ad1fe4d6ce605d4e79c6976bd806e842afd880d82e67be654719b25ec65e3a`, matching the delivered parser. Thus this run exercised the new multi-update path successfully; its overall qualification still fails for the separate child-directory accounting issue.

## Evidence boundary

[ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) records the public allowlist, original/published hashes and deterministic gzip task encoding. Fixed absolute paths are replaced with named placeholders. No live workspace, private Core configuration, database, credential file or unrelated reference labels were copied. Original artifacts were not modified.

This is one source-based Core b29 synthetic engineering integration run. RC12 packaged-application checks are separate. It is not a general model-quality score or a benchmark rerun, and later product changes do not reclassify this R4 failure.
