# Model Backend API v1

南向推理接口与北向 Agent Service API 分开。Backend 收到 messages/tools，只发推理请求，返回文本、tool calls、usage/finish_reason 或异常。模型输出不执行工具、不批准操作；所有工具仍回到原 AgentSession/Permission Gateway。

## 复用的 owning interfaces

`agent.backends` 定义 Message、ToolCall、BackendResponse、BackendChunk、BackendCapabilities、ModelInfo。`agent.local_http.LocalHTTPBackend` 对接标准 OpenAI-compatible Chat Completions；`agent.deepseek.DeepSeekBackend` 对接 DeepSeek 的已支持协议。服务的 ServiceOpenAIBackend/ServiceDeepSeekBackend 仅增加 host generation options，保留原 HTTP/SSE parsing、context guards、tool argument reliability 和错误处理。

| 项目 | 契约 |
|---|---|
| 推理路径 | POST `{base_url}/chat/completions`；model 是 host 注册的实际 ID |
| messages | system/user/assistant/tool；system prompt 由 Runtime 控制；历史与 reasoning replay 使用既有 backend 规则 |
| tools | 标准 function schema；返回 function tool_calls 只作为 Runtime 提案 |
| streaming | BackendChunk text/reasoning/最后 response；中断不能执行不完整 tool call |
| context | model_info.effective_context 为配置的保守 admission estimate；非 provider 实测 context 能力证书 |
| 输出预算 | Runtime max_output_tokens → backend max_tokens；每次推理 cap，不冒充全树 token 总量 |
| generation | host generation_parameters 的 temperature/top_p/seed/presence_penalty/frequency_penalty/stop；类型/范围校验；Backend/provider 可拒绝未支持字段 |
| reasoning | BackendCapabilities 与 thinking_mapping 协商；未声明 effort 拒绝；不伪造各 provider 共同枚举 |
| usage | 原 provider 返回；未知 null；不从字节长度或 SSE 帧推算 token/billing |
| timeout/error | host timeout；连接/HTTP/malformed/truncated stream 按既有 adapter fail-closed；service 默认 retry max_attempts=1 |
| fallback | 服务 packaging 默认不自动 fallback；选择/失败日志可追踪；原 Hybrid 显式 handoff 仍保留原授权与 generation 规则 |

DeepSeek thinking 开启时 temperature 等采样参数可能被 provider 忽略；配置不是效果验证。此轮云端使用已有 deepseek-flash + none，token/费用只按 wire/provider evidence 解释。

## Host 配置

`backend.kind`：local-openai、remote-openai、deepseek、unavailable。模型 ID、URL、API token 环境引用/显式 key_file、context_budget、timeout、reasoning_efforts、capabilities、generation_parameters 和 include_stream_usage 只在 owner-only 服务配置中出现。未知字段拒绝。

local-openai 默认 numeric loopback。remote-openai 要求显式 HTTPS URL 和 API token；adapter 标记为 cloud，由 HybridController 执行 egress，不可伪装 local。DeepSeek 保留原 owner-only 文件 resolver，provider credential 不进入 Task/SQLite/审计/Skill。普通客户端不能让服务请求任意 URL。

每个 host route 使用单一已注册 Backend，避免 routing policy 的隐式 local-first fallback。服务选择器区分 explicit/preference/automatic、model_not_registered/model_not_deployed/model_unavailable/model_capability_insufficient；所有任务保留 route decision。catalog ready 是 operator declaration，health 默认 NOT_PROBED。网络失败由真实任务暴露，不用配置 ready 冒充连接成功。

local-openai/remote-openai 可显式设置 `include_stream_usage: true`，复用已有 Backend 的 `stream_options.include_usage` 请求与 SSE usage 解析。默认 false 保留原行为；缺失 token usage 始终 UNKNOWN/null。此选项必须为 boolean，启用状态进入恢复 fingerprint。

Generation/timeout/可信验收合同在 service_contract 中进入既有恢复 configuration hash；改变参数不沿旧 checkpoint 静默继续。正常旧 Backend 无该字段时历史 fingerprint 不变。

## vLLM / MLX 接入

### 2026-10-25：独立 vLLM Adapter（实验性，默认后端不变）

`agent.vllm.VLLMBackend` 复用 Message/BackendResponse/BackendChunk 和现有 HTTP/SSE 校验。
服务配置新增 `kind: vllm`（numeric loopback）和 `kind: remote-vllm`（显式 HTTPS + token，始终作为 cloud 经过 Egress）。
文本、多轮、Streaming、Usage、timeout、保守上下文准入和 tool proposals 仍进入原 AgentSession；不执行第二套 Agent Runtime。
工具能力默认关闭；只有 host 配置 parser 并明确声明 `capabilities.tool_calling: true` 才可使用。未声明的 reasoning effort 拒绝。

`cancel_request()` 仅关闭此 Adapter 的请求；共享服务不卸载。真实取消后恢复已测，provider 内部资源释放时延仍 UNKNOWN。
`localpilot_service.vllm_host.VLLMHost` 提供 trusted-host、已下载固定 snapshot 的进程级 load/unload、活跃 lease 拒绝卸载及失败启动清理。
它不下载权重、不替换日常 APP、不向普通 Agent 开放任意命令或生命周期入口。现有 Model Manager 的 HTTP job contract 没有被冒充为已实现的 vLLM 管理服务。

当前真实平台仅 Apple M1 Max / vLLM-Metal / Qwen3.6-35B-A3B-4bit。Linux CUDA/ROCm 只具有同一南向 Adapter 的远端接口，运行资格 NOT_RUN。
版本、能力矩阵、真实工具 E2E 与缓存限制见 `docs/experiments/vllm-hybrid-20261025/`。

### Cooperative Router（host 显式 opt-in）

本地 route 的 `cooperation` 可增加 `optimizer`（CooperativePolicy 字段）和 `profiles`。
五档 mode 仍受 routing policy、DataPolicy、CloudEgressPolicy、原 HybridController.switch、receipt、UNKNOWN 和 pending approval 检查约束。
模式不是审批：`CLOUD_ALLOWED` 必须由 host 单独授予；默认旧 cooperation 仍保持 REQUIRES_APPROVAL。
开发集校准必须绑定完整本地 backend identity；evaluation profile 拒绝。空 profile 不虚构质量分数。
现有 GUI 五档仍是 `deterministic_host_rank_v1` 静态排序，未自动升级为实验 Router，也未更改日常 APP。
host 可为已审计的公开模拟器，在 registry 声明精确 `public_tool_results` 名称；该名单进入恢复 fingerprint，默认扩展工具结果仍不出站，凭据扫描继续有效。

以下为历史接入设想和旧轮次资格说明，不能覆盖以上本轮真实证据。

未来 vLLM 只需提供受保护的 Chat Completions endpoint、真实 model ID 与明确 capability/context 声明，并填 local-openai route；MLX/现有本地 API 复用同一 adapter。必要时使用已有 backend_verification 工具生成带 provenance 的健康/基础chat/stream/tools/reasoning 报告。Model Manager 负责准备部署；Runtime 不安装依赖、下载模型或执行 trust_remote_code。

本轮真实 DeepSeek Cloud、缓存 Qwen3.6/oMLX 本地 E2E 与 scripted loopback Backend 合同测试分别记录。本地在21:00后串行执行：受保护 API、ready model、服务端一次只读工具、native SSE、provider token usage、trusted host verifier均有实测；本地/云端在各自 Session 中显式选择。跨 Backend 的运行中 handoff与真实vLLM仍 NOT_RUN。未扩展模型推荐器或 Computer Use。
