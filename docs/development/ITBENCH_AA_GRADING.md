# Public ITBench-AA grading

This evaluator covers the 40 public SRE cases in
[ArtificialAnalysis/ITBench-AA](https://huggingface.co/datasets/ArtificialAnalysis/ITBench-AA),
at revision `76df38a82288f75ba9e41dc8c515033332497473`. It implements entity
normalization and precision at full recall as described in the ITBench-AA section
of [Artificial Analysis's methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking).
Dataset license: CC-BY-4.0. The source scenarios originate in
[IBM ITBench](https://github.com/itbench-hub/ITBench).

## Scope

This is a separate LocalPilot evaluation, not an official Artificial Analysis
ranking. The official evaluation has 59 cases and three repeats; this run has the
40 public cases and one candidate attempt per case. The candidate uses LocalPilot
Core tools and its frozen prompt and budgets, rather than the official Stirrup
harness. Scores are therefore not directly comparable with the official ranking.

The candidate runner is `scripts/qualify_itbench_aa.py`. The independent grader is
`scripts/grade_itbench_aa.py`. The grader does not rerun or modify candidates.

## Execution

After the candidate runner has written `RUN_SUMMARY.json`, run:

```bash
python scripts/grade_itbench_aa.py --output /path/to/completed-run --key-file /path/to/private-key
```

The key file is resolved by the existing OpenAI credential implementation. It is
not copied into evaluation output. The grader uses the existing
`ServiceOpenAIResponsesBackend`, fixed to `gpt-5.5` with `medium` reasoning, no
tools, a 16,384 output-token limit, and a 180-second request timeout. There is one
normalization request per eligible nonempty candidate, with no retry or alternate
judge. Empty, missing, invalid, or failed candidate output scores zero directly.

Before fetching references, the grader verifies all 40 case receipts against the
completed summary and requires an affirmative stop receipt for each candidate
Core. It also checks for live `localpilot_service` processes whose `--config`
path belongs to the selected output directory. Other LocalPilot jobs are outside
this check. This is a lifecycle check for the documented runner, not an OS sandbox
or a claim about arbitrary background processes.

The reference `sre/data.jsonl` is downloaded into memory from the immutable
revision and checked against SHA-256
`6073f64edc4e011fbf4d4677ca04f5b4ff84d2041d1786c0f54b3e3e7392a745`.
Neither JSONL/YAML references nor judge request bodies are written to disk or to
a candidate workspace. The judge receives only entity metadata/aliases and the
candidate's submitted factors; root-cause flags, fault narratives, alerts,
propagation descriptions, runtime logs, candidate model identity, and candidate
prompts are excluded. Root-cause flags remain local to the deterministic scorer.

## Normalization and arithmetic

The normalization instructions are independently written. They ask the judge to
identify resources from names, namespaces, kinds, filters, and explicit aliases;
the judge does not determine which resources are root causes. The response must
contain one existing entity ID or `null` for each prediction, retaining its exact
name and order. The grader rejects malformed JSON, missing or additional entries,
changed names/order, invented IDs, tool calls, and incomplete responses.

The arithmetic is deterministic:

1. Merge alias links, including transitive links. A merged group is a target if
   any member has `root_cause: true`.
2. Count each matched target group once as a true positive (TP). Count each
   matched nontarget group once as a false positive. Each unmatched prediction
   contributes one additional false positive (FP).
3. If any target group is absent, assign zero. Otherwise assign `TP / (TP + FP)`.

Repeated predictions that map to one group do not add points or penalties.
Unmatched predictions have no established group and are counted individually.
The aggregate is the sum of all case scores divided by **40**, including every
candidate failure and grading error.

## Receipts and failures

`grading/manifest.json` freezes the dataset, judge settings, prompt hash, complete
candidate-study hash, and grader source hash. Each `grading/case-NNN.json` contains a candidate/input
fingerprint, score counts, available assistant output, provider response JSON,
usage, and any error. Generated judge outputs may identify entities; they are
retained for auditing, while the reference file and judge input are not persisted.
Transport errors retain the existing adapter's sanitized error details; provider
HTTP error bodies are deliberately unavailable through that adapter.

Completed grading receipts are reused only when their fingerprints still match.
A started request without a final receipt becomes an explicit interrupted-judge
error and is not silently repeated. Changed inputs or grading code are rejected
instead of replacing existing receipts. Judge failures remain zero in the
aggregate and set `grading_complete` to `false`; that provisional score must not
be presented as a fully graded estimate of candidate quality.

`grading/SUMMARY.json` contains all 40 case results and distinguishes graded
cases, direct candidate zeros, and judge errors. The command exits with `0` for
complete grading, `1` for retained judge failures, or `2` for a run/setup error.

## Verification and limits

```bash
python -m unittest tests.test_itbench_scoring -v
```

The synthetic tests exercise the real scorer, alias merging, all-case denominator,
input validation, reference-digest guard, process ownership check, output
immutability, interrupted-judge handling, and reference-free output files. Local
TLS tests use the actual Responses adapter and verify wire parameters, complete
provider output/usage retention, and failure handling. Only model responses are
scripted; these tests neither download benchmark labels nor use a real API key.

These tests verify the arithmetic and execution contract. They do not establish
that an LLM's entity matching is semantically correct. The saved judge outputs
permit a separate audit, and no claim of candidate performance follows from the
synthetic tests alone.
