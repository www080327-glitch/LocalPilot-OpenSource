# Engineering R3 on Core b28 — FAIL, semantic acceptance PASS

**Overall engineering qualification failed, with exit code 1.** The delivered project passed all **17 immutable external unit tests and four external CLI cases**, but one child retained an unresolved patch failure and finished `incomplete`. The frozen protocol requires two completed children and a completed parent; those requirements were not met. The failure is preserved without a retry or a change to the verifier.

## Source, environment and protocol

| Item | Recorded value |
| --- | --- |
| Source commit / clean tree | `03535fe943f64f49e9e3d79e7949aca6c9ec9b87` / `1792d58af7858208db5018a747d78a1c75848edf` |
| Runner SHA-256 | `108f948c1b32fa9de95e48a1a84ede4b4b78a3d3ecfabe1c9977e4b7e21cc0fb` |
| Native job original SHA-256 | `0a13a03353c9aec25b240d26a6abcf49ac6547439d3443fb563ddd251c6e2c55` |
| Model | `gpt-6-luna`, OpenAI Responses, medium reasoning |
| Host | Native Terminal foreground; Python `3.12.14`, Clang `22.1.3` |
| Environment adjustment | Only the designated task-tool Python directory prepended to inherited `PATH`; proxy and TLS variables unchanged |
| Permission / deadline | Full + standard; 1,200 seconds |
| Parent / requested children / worker ceilings | 100 steps / 200 tools; two children at 20 / 40 each; host worker ceiling 30 / 60 |
| Start / finish | `2026-11-16T20:24:24.550843+00:00` / `2026-11-16T20:27:08.530850+00:00` |
| Duration | Model/Core run **163.3123 seconds**; outer execution **163.9800 seconds** |
| Source and shutdown | Source unchanged, clean tree afterward; runner recorded owned Core stopped |

See [PROTOCOL.json](PROTOCOL.json), [EXECUTION_START.json](EXECUTION_START.json), [EXECUTION_END.json](EXECUTION_END.json), [runner.py](runner.py) and [native-job.sh](native-job.sh). The job was prepared after the separate [R2 executor interruption](../engineering-luna-r2-b28/RESULTS.md). R3 was one newly authorized version-validation attempt, not selection of a favorable response. R2 and the older-source R1 outcome remain separate.

## Independent result layers

| Layer | Result | Evidence |
| --- | --- | --- |
| Protocol | **FAIL** | Parent `incomplete`, quiescent; no runner exception, no task error or pending action. One unfinished worker obligation remains. |
| Orchestration | **FAIL** | Both children started async and were collected; each changed only its assigned module and ran its test class. Parser child remained `incomplete`; aggregate child completed. |
| Semantic acceptance | **PASS** | External unittest: 17 tests, exit 0. Basic, precision and empty CLI cases exited 0 with exact expected JSON; invalid-input CLI exited 2 with the expected error behavior. |
| Overall engineering | **FAIL** | Frozen criterion requires all three layers to pass. |

The [external unit receipt](external-unittest.json), [external CLI receipts](external-cli.json), [file manifest](file-manifest.json), [generated project](final-project/logstats/parser.py) and [project diff](project.diff) are retained. Original SPEC/tests/fixtures were unchanged. The parent ran the complete 17-test suite twice and the requested CLI twice during integration; the immutable external acceptance ran afterward using only the four delivered modules plus the original tests and fixtures. The parent CLI artifact matched the expected JSON.

| Child | Model calls / receipts | Assigned changes | Child test receipt | Terminal state |
| --- | --- | --- | --- | --- |
| `1.1` | 9 / 14 | `logstats/parser.py` only | 9 ParserTests, exit 0 | `incomplete`, obligation unresolved, collected |
| `1.2` | 6 / 14 | `logstats/aggregate.py` only | 3 AggregateTests, exit 0 | `completed`, obligation resolved, collected |

There were **33 aggregate model calls**, **57 aggregate tool receipts**, **507,351 provider-reported input tokens** and **17,794 output tokens**. These totals already include both children. Failed model attempts and UNKNOWN-effect receipts were both zero; actual monetary cost is not reported.

The verifier's completed-child overlap field is **0**, because it constructs intervals only from `completed` terminal events and parser has an `incomplete` event. The recorded start-to-terminal intervals overlap by **50.485645 seconds**. That observation describes concurrent child lifecycles, including inference and tools, and is not proof of simultaneous CPU execution.

## Exact failure chain

Parser child receipt `turn:1/call:call_IuuPHz5GvdfEyFxDJ6DWV5B1/entry:10` submitted two `update` changes for `logstats/parser.py` in one `apply_patch`. The second change was a no-op. `agent/patches.py::apply_patch` rejected the repeated resolved target during batch preflight, before authorization or writes, with:

```text
ValueError: Patch paths must be distinct files, not the workspace root
```

The receipt has `side_effect_status=not_completed`, but no structured `not_dispatched` / `action_sent=false` result. The next patch succeeded using different `old_text` / `new_text` arguments; the child then read its file and passed all nine ParserTests. No `repaired_proposals` association was created. The original failed mutation therefore remained in the child ledger, causing `incomplete` and one unresolved parent worker obligation.

This exposes the current same-file patch-batch restriction and a recovery limitation after replanning. It is not a failure to launch children or execute their tests, and it does not exercise the b28 Shell timeout-only repair path. The verifier's FAIL follows its declared completion requirement; recomputing the frozen `orchestration()` function over the saved receipt returned the identical result.

A read-only check of the file content observed immediately before the rejected patch found that both requested updates could match exactly once in sequence; the second is unchanged text. This is diagnostic evidence for evaluating the current restriction, not a production fix or a retroactive PASS. The successful later patch differs from the rejected proposal, so matching only the path would not establish exact proposal repair.

## Archive and scope

[ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) lists the explicit public allowlist, original/published hashes and deterministic gzip encoding of [the full task receipt](engineering-task.json.gz). Fixed absolute path prefixes are replaced with named placeholders. No private Core configuration, database, key file, live workspace or benchmark reference labels were copied. All four delivered module hashes matched the saved acceptance receipt, and source artifacts remained unchanged during archival.

This is one public synthetic engineering integration task. It is not a general model-quality score, a benchmark rerun, or an RC11 packaged-application test. The b28 source run's failure remains FAIL regardless of any later code changes.
