# LocalPilot external child Agent contract, API 1.0

LocalPilot remains the sole persistent Agent Runtime. HTTP `/localpilot/v1/tasks` submits a new task or a new turn into an owned Session. Required idempotency key is scoped by authenticated client. Identical accepted requests return the same Task ID, including after disconnect, restart, approval, cancellation and UNKNOWN. Changed request bodies under the same key return 409. No caller owns server threads or their lifetime.

| Operation | HTTP | Stable MCP tool |
|---|---|---|
| submit | POST /localpilot/v1/tasks | localpilot_submit |
| status | GET /localpilot/v1/tasks/{id} | localpilot_status |
| events | GET /localpilot/v1/tasks/{id}/events; Last-Event-ID | localpilot_events (bounded SSE batch) |
| result | same authoritative task snapshot | localpilot_result |
| cancel | POST /localpilot/v1/tasks/{id}/cancel | localpilot_cancel |
| continue | existing POST /localpilot/v1/tasks/{id}/continue | localpilot_continue; operator only |
| capabilities | /healthz and /localpilot/v1/model-registry | localpilot_capabilities |

Snapshots include Task ID, Session ID, authenticated client subject, `service.origin_agent`, optional untrusted correlation label `service.parent_task_id`, route decision, receipts, final result, quiescence, required_action ticket, recovery class, execution/delivery/verification/engineering states and fresh physical file verification. Submit supports timeout_seconds and max_output_tokens below the existing server ceilings. Route configuration supplies bounded step/tool/token/child-depth budgets; clients cannot expand them. Provenance fields do not grant control or allow reading a named parent task.

Ordinary per-host credentials can submit/read/cancel only their own tasks. Only an explicitly configured operator bound through approval_for can approve, continue or perform human takeover. Models do not receive operator/provider credentials. Task ownership does not transfer on disconnect. Cancellation is cooperative and cannot certify rollback; inspect receipts and quiescence. Timeout of an adapter/MCP call is a transport result, not proof that a submitted task stopped. Query the same ID/key; use explicit task cancellation when appropriate.

Internal children retain existing depth/count/budget ceilings and inherit folder guards, including after persistence restoration. There is no external redelegation tool; selected-folder sessions disable shell execution. Skill instructions forbid recursive parent/child delegation. Host denial must be reported as Host Denied, without alternate transport or identity attempts to bypass it.

UNKNOWN_BLOCKED is neither completed nor permission to resume/replay. A current action ticket and server SAFE_TO_RESUME decision are required for continue; human approval cannot clear unknown side effects. Retain failed/unknown receipts and surface the required human reconciliation.

MCP stdio uses JSON-RPC 2.0 initialize/ping/tools/list/tools/call and tool-level isError for HTTP rejections. Exact argument schemas reject unknown fields, invalid types and limits. The SDK retains the existing HTTP Agent API and live SSE transport. This release does not claim a Streamable HTTP MCP listener; HTTP integration is the authenticated Agent API.

For MCP event batches, the cursor is `event.data.sequence`; pass the last observed sequence as `after`. The SDK also accepts the task snapshot last_event_id. The adapter advisory mentions data.id, but this server emits sequence: follow the actual event schema, not that advisory string. This wording defect does not change SSE delivery or receipt persistence.
