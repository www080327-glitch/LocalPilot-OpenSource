# DSH execution-path audit and reuse matrix

Upstream pinned in LOCALPILOT_V5_ARCHITECTURE.md. Upstream paths below are under
`packages/`; LocalPilot paths are repository relative. Existing detailed
wire/extension research is retained in DEEPSEEK_HARNESS_CAPABILITY_MATRIX.md.

| Mechanism / upstream execution path | Intent and LocalPilot gap | Choice / interfaces and reliability constraints | Expected metric and experiment |
|---|---|---|---|
| core/agent-loop/src/agent.ts | pre-step → request → stream assembly → tools → next step; LP _advance has equivalent ownership but heavy snapshots | Adapt step policy in AgentSession; retain _dispatch, _record_call and commit-before-effect | requests, latency; independent real tasks |
| core/session/src/surface.ts | derive model history from append-only events; LP canonical messages mixed with working snapshots | View-only projection over existing SQLite; preserve receipts and canonical messages | input/miss tokens; restart and projection invariance |
| core/system-prompt/src/index.ts | ordered stable sections and name-sorted tools; LP embeds changing state and model | Stable V5 instruction prefix, sorted schema; current controls in trailing host state | real cache usage and total input cost |
| core/tools/src/index.ts, schema.ts | parse/validate before execution, error feedback; LP Gateway already owns execution | Reuse LP validators, bounded repair budgets; never repair to executable empty arguments | validity/recovery, fault injection |
| core/agent-loop/src/tool-calls.ts | bounded pools, exclusive barriers, ordered result commit | Keep LP sequential mutation; parallelization lacks a receipt/UNKNOWN benefit case | no speculative concurrency claims; replay controls |
| core/session/src/tool-history.ts | tool baseline/delta and fresh series on schema changes | Sorted full current tool catalog; no unsupported tool delta beta | schema stability, switch tests |
| llm/llm-deepseek/src/serialize.ts | real Messages text/thinking/tool_use/tool_result; LP Chat-only | Python protocol port over Message; endpoint/auth adapted, no executor | real same-model Messages tool task |
| llm/llm-deepseek/src/replay.ts | index/model-bound native replay; LP has reasoning string only | Optional source-bound replay envelope in existing Message/checkpoint and Hybrid egress hash | signature continuity, tamper/cross-model/restore controls |
| llm/llm-deepseek/src/translate.ts, sse.ts | block lifecycle and terminal message_stop, cumulative usage | Strict streaming assembler; full response before dispatch; no partial tool release | truncation and malformed stream faults |
| llm/llm-deepseek-api-key/src/index.ts | public key route distinct from account eligibility | Existing protected key resolver, safe redirects, x-api-key; no DSH identity | public API protocol probe |
| llm/llm-retry/src/index.ts | persistent routed retries and cancellable wait | Keep bounded LP retry charged to same budget; no retry after visible partial output | pre-output failure versus cut-stream tests |
| compaction/compaction-basic/src/region.ts, summarizer.ts | balanced region, asynchronous summary checked against current surface | Deterministic protected view first; no model summary discarding authority | real compaction + restart, canonical hash invariant |
| core/agent/src/model-selection.ts | explicit route capabilities / context notices | V5 policy provider-neutral; signatures invalid across model or egress scope | local/OpenAI/DeepSeek switch controls; real qualification separately |
| session/session-persistence-* | durable events and recoverable model view | Preserve LP SQLite identity/idempotency/owner lock, no second store | process death, UNKNOWN and no replay |
| tool/subagent-* | scoped child orchestration and result collection | Existing LP children, ledger and budgets; avoid unsolicited delegation | unfinished-child finalization fault |
| llm/deepseek-llm-api-extensions, session/session-log-deepseek | logs/plugin inventory beyond ordinary messages; server benefit unknown | Exclude; would require explicit extra Cloud Egress grant | absence asserted at transport; no benefit claim |
| core/agent-loop final turn + LP finalization.py | upstream finish is not LP verification; LP can lose body during final-only view | Retain trusted four dimensions, bounded repair and recent evidence within output reserve | execution vs delivery vs verification vs engineering, real finalization |
| plugin loader / presets | configurable service composition; LP already modular API | Reference build only; no Node runtime dependency, Companion/GUI untouched | wheel smoke, service compatibility regression |

Direct use: pinned upstream benchmark executable and its tests. Adapted MIT
code: Messages serialization/replay/stream lifecycle (Python). Independent
implementation: V5 policy/context/feedback over LP authority. Session format,
plugin runtime and official identity are deliberately not transplanted.
