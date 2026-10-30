> 2026-10-18 独立Companion补丁：可选稳定前缀/minimal纯推理、缓存35B的宿主生命周期、owner-only推理停止/心跳、resource-only例外票据。默认旧部署不自动启用managed模型。见[本轮合同/限制/证据](COMPANION_V044_CACHE_RESOURCE_REPORT.md)，OpenAPI已同步。原版下文保留历史语义。

# LocalPilot Agent Service API v1

服务包 `4.9.1rc1`，基于 V4.9 `ad886b59`。正式入口为 `python -m localpilot_service --config /private/service.json`。底层仍是现有 TaskService → AgentSession → Registry → Permission Gateway；没有第二套 Agent Runtime。默认 numeric loopback，所有路径，包括健康与文档，均需独立客户端 Bearer token。

## 客户端与任务身份

服务端从受保护的配置与环境变量解析 `client_subject`，从不接受请求或模型指定身份、workspace、权限、Backend URL、审批主体。配置的公开模型名映射到 host route；不同客户端可配置不同 workspace、读写/执行能力、模型和 egress。Session owner 在原 SQLite checkpoint 内与 Session 一起提交，重启后保持。历史未绑定 owner 的 Session 不会自动分配给新客户端。

每次 HTTP 请求返回 `X-Request-ID`。任务第一次提交的 ID 保留在 `task.service.request_id`；重试有新的传输 Request ID，但不改变任务、Session 和原提交身份。Task ID、Session ID 原样沿用 Runtime 的 resp_/sess_ ID。

所有任务提交需要 `Idempotency-Key`，原生任务也可使用 body 的 `idempotency_key`。两处同时填写必须相同。键为 1–128 个可见 ASCII 字符，按客户端命名空间隔离。相同键与完整相同请求返回原 Task，包括 failed、等待审批和 UNKNOWN；改变参数返回 409。服务复用 Runtime 的提交 fingerprint、checkpoint 与 dispatch 前持久化，不另外维护一个非原子的外部幂等数据库。

客户端应在发送前持久化键和公共请求内容。接收 Task 后持久化其 IDs。不要通过替换键重新执行副作用任务。这里没有外部分布式 exactly-once 或自动回滚承诺。

## 两套北向协议

| 接口 | 合同 |
|---|---|
| POST `/v1/responses` | 既有文本子集；短任务同步，background=true 异步，stream=true SSE |
| POST `/v1/chat/completions` | 既有文本多轮/单 choice/文本 SSE；长任务建议使用原生 API |
| GET `/v1/responses/{id}`；POST `…/cancel` | 查询/协作取消同一个 Runtime Task |
| POST `/localpilot/v1/sessions` | 可选 `{model}`；服务绑定客户端 owner，返回 201 |
| GET/DELETE `/localpilot/v1/sessions/{id}` | 客户端隔离的查询/关闭；活动任务必须先解决 |
| POST `/localpilot/v1/tasks` | 原生异步提交，202；长任务与断连恢复的推荐入口 |
| GET `/localpilot/v1/tasks/{id}` | 完整状态、结果、工具进度、收据、Verification 摘要 |
| GET `/localpilot/v1/tasks/{id}/events` | 原生 SSE；after=N 或 Last-Event-ID=N，断线可续读 |
| POST `…/cancel` | 普通客户端 cancel scope 可协作取消 |
| POST `…/approve`、`…/reject` | 绑定到任务 owner 的 operator control scope，当前 action_id |
| POST `…/continue` | operator 继续 SAFE_TO_RESUME；保留同 Task ID |
| POST `…/computer/takeover`、`…/computer/resume` | 复用原有人工接管/重观测控制；本服务配置不新增 Computer capability |
| POST `…/finalize`；GET `…/children` | 复用已有终结和 Child 查询；不扩展调度算法 |
| GET `/localpilot/v1/model-registry` | 客户端可见的配置模型、能力、部署状态与 provenance |
| GET `/healthz`、`/openapi.json` | 受认证的服务状态/OpenAPI；健康默认不发模型推理 |

原生提交字段：`input` 必填，`model`、`session_id`、`instructions`、`timeout_seconds`、`max_output_tokens` 可选。省略 Session 时新建。同 Session 一次只能有一个活动 Task，审批等待仍占用它。

服务额外接受 top-level `model_preferences: [id,…]` 和 `required_capabilities: [tool_calling,streaming,…]`，两者是 LocalPilot 扩展。显式 model 不可用时明确拒绝；偏好模式按可用能力候选选择，省略时自动选择已配置 route。native `task.service.route_decision` 与 OpenAI `localpilot.service.route_decision` 保留选择来源、被跳过原因、实际配置 Backend model 和 fallback=false。Backend 连接失败仍是原 Task 的失败，不会静默换模型。已存在的 persistent Session 不能换 route；需要换 Backend 的 Runtime handoff 使用原 Hybrid 合同，或新建一个选择其他 route 的 Session。

## 多轮、进度与最终结果

Responses 可以沿最新 `previous_response_id` 线性续接，或 conversation=Session ID；旧 head/分叉拒绝。Chat 的持久模式用 `localpilot.session_id`，只发送新增 user turn，不能重放历史。原生方式对下一次 submit 填同 session_id 与新键即可。已选非默认 route 的 Session 在省略 model 时沿用该 route，记录 selection=session_affinity；显式改成其它 route 仍为409。

SSE 的 task/native/runtime 事件展示工具提案、审批、派发和结果；连接断开仅 detach。过期/超前 cursor 为 409，需要 GET Task 重新同步。不能靠流 EOF、自然语言“完成”或 Chat finish_reason 判定任务成功。

原生 status 包括 queued/running/cancelling/completed/incomplete/failed/requires_approval/requires_human/cancelled/timed_out；quiescent 表示 worker 已 yield。`result` 的 runtime_status、deliverable_status、verification_status、engineering_status 分开解释。`receipt_summary` 列出收据数和 UNKNOWN effects；`verification_summary` 保留四维结果。未配置可信验收回调时 verification=not_run，engineering=unverified。

Host 可配置受限 `verification: {id, files: {relative_path: expected_sha256}, required_text}`，复用已有 HostVerification callback。只验当前文件版本和最终文本中的合同标记，文件数≤32，不执行命令，不是通用需求认证。合同纳入恢复 fingerprint；改变它需要显式迁移。客户端不能注入或替换 verifier。

## 审批、接管、恢复与 UNKNOWN

ordinary Agent token 不含 control。Operator 配置 `operator=true`、control scope 和具体 `approval_for` subjects；服务在动作前验证任务 owner，审计 operator subject/action/ticket。模型生成“批准”文本不能授予权限。控制动作必须读最新 required_action.id；旧 epoch、重复票据、忙碌任务均 409。

UNKNOWN_BLOCKED 只能查询或取消，不能 approve、continue、resume 或自动重放。取消仍保留已发生但未知的副作用义务。Human Takeover 不复用过期 GUI handles；恢复仍经原 Computer resync。Deadline 包含审批与停机时间，取消不强杀已派发的操作。

## 兼容边界与错误

OpenAI endpoints 复用已有部分兼容的文本 adapter。支持普通文本、限定多轮、background/poll 与 SSE；不支持客户端注册/执行 function tools、图像音频、完整 Conversations CRUD、分叉、完整严格 SDK schema。审批/human/UNKNOWN 为显式扩展状态，不会映射 completed。未知 usage 为 null，不伪造 0。OpenAI retrieve 的标准 stream reconnect 未实现；使用 native events。

401 缺失/错误 token；403 scope、Origin 或非 operator 控制；404 未注册模型或无访问权的 Task/Session；409 参数幂等冲突、stale ticket/session head、UNKNOWN、部署/能力不足；429 客户端速率/活动任务/连接上限；503 无可选 route。Runtime/provider 执行失败沿既有 failed Task/Response 返回，客户端还需查实际状态。

原文档中的“无持久幂等/无跨用户隔离”是旧 Alpha 范围；新服务入口补齐这里声明的合同。旧 `python -m localpilot_api` 仍作为 legacy 单身份入口保留，不能用它替代新服务的多客户端安全合同。

OpenAPI：[localpilot_service/openapi.json](localpilot_service/openapi.json)。启动与示例：[SERVICE_DEPLOYMENT.md](SERVICE_DEPLOYMENT.md)。
