# Desktop permissions v3

This change follows the locally installed DeepSeek Harness `@deepseek-ai/dsh-permission-presets` 0.2.1-rc.2 and `dsh-sandbox-local`. DSH's default presets are `workspace-write / ask` and `danger-full-access / never`; read-only and explicit-review are the corresponding file-policy/approval combinations.

| LocalPilot choice | File policy | Approval behavior |
| --- | --- | --- |
| 只读 | Read files, confine Shell against file writes | Writes require choosing another mode |
| 请求批准 | Read normal files; approved modifications and commands use OS user rights | Ask before modifications / Shell |
| 工作区写入 | Write workspace and permitted system temporary directories; read elsewhere | Automatic normal workspace operations; ask for wider writes or unconfined Shell |
| 完全权限 | Current OS user, no LocalPilot file/process sandbox | No application approval prompts |

Choosing a cloud provider authorizes that provider to receive the conversation and results of permitted tools. Readable tool results must not be replaced by `body_withheld`, and each model round must not require a separate egress approval. This is Desktop-session authority established by the local operator, not authority granted by model text or generic external API clients. Local-only model routes remain local-only.

Full access includes available file/Shell/network tools and local inference while macOS low-power mode is active. It does not change macOS security settings, remove OS permissions, or acquire administrator privileges. Tool argument validation, execution/output limits and truthful receipt/UNKNOWN handling remain. Unknown effects are never automatically replayed.

Permission changes at idle boundaries update the existing owned session, preserving history and the original task. Active and old pending operations are not silently approved. No DSH application, profile or global settings are changed.

Focused validation uses real temporary files and Shell, with a scripted model for cloud-context and loopback API tests. It is not a general model-quality or DSH end-to-end benchmark.
