# LocalPilot V5 Agent Engine

Research date: 2026-10-22 Asia/Shanghai. Development branch starts at
`41e81141` (the preserved DSH optimization work), incorporating published Core
RC2 `1e3b3feb62a1cb5a9b8a049ab7953b75a4c45a3c`. The older main working
directory is `5e79fb2e`; neither checkout is modified. Legacy comparison uses
the published RC2 implementation, not the previous experimental adapter.

Upstream: https://github.com/deepseek-ai/deepseek-harness at
`687f282e8625c6b8d11ff58211a90524be2e4317`, verified against remote HEAD on
2026-10-22. Existing detached checkout is reused without modification.

Delivery update: 2026-10-23. Candidate package 5.0.0a1, engine policy revision=2.
Revision 2 bounds final-only history by the remaining delivery admission budget;
it does not alter canonical history or enlarge any host budget. Checkpoint
fingerprints reject silent adoption of development revision=1 sessions.

## Decisions and authority

V5 is a host-selected policy inside AgentSession, independent of provider.
TaskService, PermissionGateway, tool intent/receipt, verification and SQLite
remain the only authorities. No DSH daemon, Session database or executor enters
the product. Legacy remains the default, with configuration fingerprints
preventing recovery under a different engine. API 1.0 clients are unchanged.

The separate DeepSeek Native Provider implements the public Messages wire
protocol: thinking/text/tool blocks, streaming lifecycle, signed replay bound
to original message and model, usage/cache counters and explicit effort. It
does not implement Files, server tools, undocumented session logs, plugin
inventory or official-client identity. Unsupported capabilities fail closed.
No production dependencies are added.

Context is a request projection, never a replacement task authority. Stable
instructions and sorted tools precede history. Full historical working-state
snapshots are replaced *in the view only* by a compact current host snapshot;
current obligations, versioned evidence, goal, approval and UNKNOWN state are
retained. Balanced complete tool groups survive compaction. The original task
is protected even when the latest user entry is tool feedback. Finalization
retains bounded recent observations rather than relying on hashes as content.
Provider-reported usage is separate from conservative UTF-8 byte admission.

The loop uses bounded malformed-call feedback and bounded completion feedback;
it cannot retry uncertain mutations. All tool proposals still enter the
existing Gateway. Natural final answers cannot override unfinished children,
UNKNOWN, approvals or trusted verification. Four success dimensions remain
independent. Output truncation never dispatches a partial tool call.

## Evaluation and admission

Freeze distinct development and evaluation tasks before real calls; preserve
fixtures, oracle hashes, raw requests/SSE, retries, receipts and failures.
Three arms: native upstream headless, published RC2 Legacy, V5. Same requested
model/effort/output/request/tool limits where possible; disclose different
prompts, tools, permissions, CLI startup and host safety admission. Native DSH
is an independent benchmark reference only.

Only synthetic workspace data may leave the machine for these tests. Default
session-log/plugin extensions remain disabled in native and absent in V5.
Actual dollars billed remain UNKNOWN without billing evidence; costs computed
from provider usage and a dated tariff are labelled estimates, including
unpriced/unknown failed-request usage. A high hit ratio without reduced total
cost and preserved correctness is not a cache improvement.

Phase commits: A audit/design; B native protocol; C context; D loop; E/F real
evaluation and confirmed fixes; G regression/package/report. No push. Default
promotion requires API/persistence/safety regression plus scoped real benefit
or independently valuable protocol compatibility. Promotion is a separate
acceptance decision, never an automatic release or stable tag update.
