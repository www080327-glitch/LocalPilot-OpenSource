# LocalPilot Suite API contract and compatibility

Core **4.9.2rc2**, Companion **0.5.5rc2**, Suite **0.1.0rc2**. Agent Service API and Companion Client Contract are **1.0**, supported `>=1.0,<2.0` with required capabilities. Minimum negotiated Companion is 0.5.5rc1. Qualification: macOS arm64, Python 3.14.6; other platforms NOT_RUN.

Core and Companion remain independent distributions/processes. Companion uses authenticated HTTP and imports no Core Runtime. Suite contains no Agent loop. The original directories share one Git common directory and authorized private remote; independent package/source branches in that repository are the release units. They are not silently treated as independent remotes.

`GET /healthz` authenticates the caller and exposes release/version compatibility, persistent service state, client generation, task input limit and required capabilities. Model health is NOT_PROBED until actual execution. Missing/malformed negotiation, a new incompatible API major or missing capabilities stops before question/context submission. An audited legacy handshake accepts Core 4.9.1/4.9.1rc2 only with existing operation-specific host/route checks. Unknown legacy versions fail closed.

| Contract | Frozen behavior |
| --- | --- |
| Agent Service API | `/localpilot/v1`, API 1.0; OpenAPI generated from owning source |
| Companion Client | 1.0; subject/owner binding, host route map, no implicit approval |
| Session/Task | Existing Runtime IDs and lifecycle; queued/running/waiting/quiescent/terminal separate; one active task per Session |
| Idempotency | Persist key/body before POST. Same owner/key/body returns same task across restart. Changed body gives 409. UNKNOWN never authorizes a replacement mutation |
| SSE | Native sequence / Last-Event-ID. Reconcile cursor 409 with snapshot. Reconnect and terminal detach never resubmit a task |
| Approval/cancel/resume | Ordinary token gets 403 on approval. Trusted operator plus current action ID; stale action 409. Cancel is cooperative and does not certify rollback |
| Verification/UNKNOWN | Runtime, delivery, verification and engineering remain independent. NOT_RUN/unverified is not passed. UNKNOWN quarantines unsafe replay |
| Models/modes | Minimal reasoning_only route has no tools; standard Agent requires help confirmation and original Gateway. Route/backend affinity persists. Existing Hybrid switches require separate authorization |
| Cloud egress | Default explicit confirmation; fresh Session per question-only consultation. Original question only; no observations/files/memory/old answers/tool results/local metadata or client-instruction wrapper. No automatic conversion to tool execution |
| Errors/timeout/retry | 401/403 auth; 409 owner/route/action/idempotency conflict; 413 oversized original input; 429 bounded rate/capacity; 503 unavailable. Bounded reconnect and original-key recovery; no unbounded model retry |
| Capability negotiation | durable_tasks, durable_idempotency, sse_cursor, operator_approval, cancel, safe_resume, unknown_quarantine, verification_dimensions, model_registry, explicit_cloud_egress, resource_control_v1 |
| Health/version | Authenticated and inference-free. `limits.task_input_json_utf8_bytes=4096`; optional context omissions explicit, original question never silently truncated |
| Resource controls | Owner-bound resource ticket/generation. Scoped resource operator cannot approve tools. Managed model lease releases after task. Original local manager remains addressable after Hybrid switches to cloud |

## Consumer-driven matrix

Actual versioned source in separate interpreters; **real HTTP and SQLite, scripted model**. Each verifies refusal creates no task, submit, read receipt, verifier, same-key retry and SSE. These are API compatibility results, not real model quality evidence.

| Consumer | Provider | Result |
| --- | --- | --- |
| Companion 0.5.5rc2 | Core 4.9.2rc2 | PASS |
| Companion 0.5.5rc2 | Core 4.9.2rc1 source ca288239 | PASS |
| Companion 0.5.5rc1 source 19ebc7d5 | Core 4.9.2rc2 | PASS |
| Historical Companion 0.5.4 source 1b8783c9 | Core 4.9.2rc1 | Historical FAIL_SAFE_REJECTION: legacy consumer hardcodes release strings |

Initial old-0.5.4 migration therefore upgrades Companion first. Newly negotiated compatible module upgrades do not require rebuilding the other module. This is not an assurance for arbitrary future versions; run the consumer contract when releasing them. The previous compatible versions were available locally; no version was invented or falsely marked passed.

See `docs/evidence/suite-release-20261021/qualification-summary.json`, `evidence-hashes.json` and the joint release report. Raw tests/credentials/databases are retained locally, excluded from Git publication.
