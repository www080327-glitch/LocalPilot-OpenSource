# Desktop file permissions and exact-action escalation

Date: 2026-10-24 (Asia/Shanghai). Baseline `13acd3ae69a8841379467a43082cee08fada9cf5`, installed dev.11/Core b12/Suite b9; 96 Core and 9 Suite Python sources matched installed wheels byte-for-byte. Existing grants, file tools, cloud projection and external MCP integration are retained.

## Authority

| New UI mode | Gateway risk policy | File boundary |
| --- | --- | --- |
| 严格隔离 / isolated | approve-all | Existing workspace only; outside proposals denied before intent |
| 请求批准 / request | approve-mutations | Reads inside workspace automatic; mutations approved; outside exact file action requests one-operation approval |
| 工作区自动 / workspace | workspace-auto | Ordinary workspace file tools automatic; outside exact file action requests approval; other tools keep independent approval |
| 完全权限 / full | full-permission | Automatic within already allowed resources; outside file scope still requires exact approval |

Full does not widen capabilities, directory grant scope, system access, network, cloud egress, protected data or UNKNOWN. This is deliberately narrower than DSH full host file access; it does not meet complete DSH parity. Shell is still bounded experimental argv execution, not an arbitrary OS-sandboxed shell. This remaining interface gap is a release blocker, not a cosmetic difference.

Legacy `ask`, `safe`, `uncertain`, `full` sessions retain their original gateway meaning. Existing stored preferences are preserved; only fresh installations default to workspace. New sessions include `scope_revision=1`; historical full sessions without this revision restore without introducing a changed prompt/configuration fingerprint. The old three risk settings remain under advanced permissions.

## One-operation lifecycle

1. Validate advertised schema, capability, read-only plan, current grant/revocation and private-root restrictions before recording mutation intent.
2. For outside built-in file tools, derive the exact absolute target set and normalized descriptor-relative arguments. Bind operation, complete original arguments, workspace/mode, existing ancestor device/inode, target inode/size/mtime/ctime/link count or absence. Reject symlink traversal, private service data and protected paths.
3. Persist the pending original ToolCall; expose its request through the existing TaskService required_action. No model-supplied approved flag, persistent grant or reusable token is introduced.
4. The native host refetches the current task/action and checks UNKNOWN. An NSAlert shows server-owned operation, targets, parameters and effects. Cancel/close returns without sending approval. Operator credentials stay out of the webview. The existing service checks ownership, Action ID, active task and generation again when approval arrives.
5. Recompute the proposal/version binding. Expired approval ends incomplete without dispatch or an alternate model path. Execute the same immutable original ToolCall using a single-call registry; original capabilities, grant guard and data policy remain in force. No shell or extension can use this file scope path.
6. Existing durable intent, receipt and inline physical checks record the effect. Scope receipt records the binding and actual root. It does not grant cloud disclosure or later reads. Fresh outside verification requires another approval; inline verification and current-state verification remain distinct.
7. Refusal ends this task and clears queued alternative execution. Restore rotates required_action through the existing recovery epoch; no approval bearer authority is persisted. UNKNOWN never takes this path to replay a mutation.

These guards do not prove an OS-atomic approved snapshot against arbitrary hostile concurrent directory reparenting. Existing no-follow descriptor tools and source hashes remain in use. Broader adversarial concurrency qualification is NOT_RUN.

## UI and authoritative state

The same Tauri/React application retains its navigation, themes and resizable three columns. New chat has one heading/subtitle and Composer, with idle inspector closed. Directory setup resets per chat. Route diagnostics appear with session preferences. The permission popover has four concise choices, selection, advanced legacy choices, Escape/arrow navigation and outside-click dismissal. Full access has an explicit explanation/confirmation.

The approval card beside Composer reads the current server required_action; inspector is an alternate view of that same object. No optimistic completed status is added. Existing runtime/delivery/verification dimensions and UNKNOWN rendering remain distinct. Native approval uses server data and the action ID displayed by the current card; service conflicts require refresh.

Reference sources: [DSH pinned source](https://github.com/deepseek-ai/deepseek-harness/tree/22ddee3792402c3e70ec5f86a63c3e3e895a2f60), [Apple macOS HIG](https://developer.apple.com/design/human-interface-guidelines/designing-for-macos), [Apple Popovers](https://developer.apple.com/design/human-interface-guidelines/popovers). Current installed Codex is a visual reference only; its windows and settings are not changed.
