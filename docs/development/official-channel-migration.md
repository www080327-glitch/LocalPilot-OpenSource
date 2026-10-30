# QQ / 微信共享官方 Agent 服务适配层

基线：官方 main `36b6b72ba286c6a0c13b89f8f40b7b71bf0bc8aa`。
隔离分支：`feature/official-channel-adapter`。源渠道代码与原测试从
`feature/localpilot-2-api@c12c96d2693c9108ac10ebba7b1552998401ffd2` 按文件引入。
未引入旧 `agent/api_server.py`、旧消息适配器或旧 JSONL；未迁移历史任务。

## 链路和范围

QQ / 微信各自的 Node 桥接 → 本机 `localpilot_channels` → 官方 `localpilot_service`
→ 现有 TaskService / AgentSession / Registry / 权限网关。

共享层仅有渠道 `/messages`、`/tasks/query`、`/tasks/decision`，不是第二套模型或 Agent API。
两个渠道保留平台接收、白名单、私聊回复、消息 ID / 回复上下文和去重机制。
新增 `processing`、`requires_human`、`timed_out` 展示；长任务通过 `/lp status <渠道任务ID>` 查询结果，
本版没有后台最终结果推送或 SSE 订阅器。QQ 回复仍受平台被动回复窗口限制。

## 身份和配置

`configs/message-channels.example.json` 只保存环境变量名与合成占位身份，不含凭据。
每个经过人工确认的 `(channel, sender_id)` 映射到一个独立官方普通 subject 和 token；
subject 最长 64 字符，不能直接使用 66 字符的渠道发送者哈希。
每个渠道的入站消息密钥不同，入站认证后强制绑定该 channel，不能靠修改 JSON 相互冒充。
所有配置凭据必须互不相同。消息正文不能指定 subject、token、session、workspace 或权限。

官方服务配置中的普通客户端示例（route 名须按宿主配置）：

```json
[
  {"subject":"qq_user","token_env":"LP_QQ_SERVICE_TOKEN","scopes":["submit","read"],"routes":{"localpilot":"local"}},
  {"subject":"wechat_user","token_env":"LP_WECHAT_SERVICE_TOKEN","scopes":["submit","read"],"routes":{"localpilot":"local"}},
  {"subject":"wechat_operator","token_env":"LP_WECHAT_OPERATOR_TOKEN","operator":true,"scopes":["read","control"],"approval_for":["wechat_user"],"routes":{"localpilot":"local"}}
]
```

普通消息永远使用普通 token。微信 `/tasks/decision` 必须同时通过独立入站审批密钥、
该渠道审批者白名单以及官方 operator / approval_for 检查。QQ 不能配置 operator，且没有审批命令。
服务 `/healthz` 在提交 / 决定前核对实际 subject、API 1.0 和 SQLite 持久化启用状态；
实际 scope 仍由官方配置强制实施，health 不提供完整 scope 枚举，不能据它推断权限资格。
示例字段不能从联系人或历史消息自动生成。需要人工核对后建立全新隔离配置。

## 状态和恢复合同

- 首次任务：POST `/localpilot/v1/tasks`，固定模型别名、新 user input、已有 session（如有），
  `Idempotency-Key = SHA256(instance_id, channel, sender_id, message_id)`。先落盘再发请求。
- 渠道任务 ID 保持原 `q_m_…` / `m_…`；独立存储官方 `resp_…`、`sess_…`，
  返回 `official_task_id`，不把两个 ID 当成同一个。查询只按持久映射进行 GET。
- 重复消息只返回记录 / GET 同一官方任务；内容变更返回 409，不重新 POST。
- queued/running/cancelling 或未 quiescent 返回 processing；requires_approval 返回 pending_approval。
  requires_human 保留；UNKNOWN_BLOCKED 返回 unknown，不继续、不审批、不自动重放。
- completed、failed、incomplete、cancelled、timed_out 分别处理。HTTP 200 不等于任务成功。
- 微信决定绑定最新 required_action.id，保存独立 decision_id 与请求指纹后才调用官方 approve/reject。
  重复决定不再次 POST；旧 action_id / 改动决定内容为 409。服务重启生成的新票据需要重新查询和人工确认。
  官方没有统一 rejected 顶层状态；确定接受的拒绝决定与最终状态一起映射为渠道 rejected，保留 upstream_status。
- 401/403 原样显示认证/权限类别；409、429、503 保留 HTTP 类别，不静默更换身份、模型或上游。
  不转发任意服务错误正文。连接超时、断线或协议不一致为 unknown。
- 已知官方 ID 的任务可通过 GET 在网络 / 服务恢复后重新核实。提交响应丢失且未取得 ID 时保持 unknown；
  不能仅靠请求指纹恢复原始正文，因此本版不会为找回 ID 自动重新 POST，需宿主人工对账。
- 审批响应丢失时决定保留 unknown；查询可核实任务，但不能把任务已完成当成该决定已被确认的证据。
- 同一发送者的活动/unknown 任务未解决时不能提交下一任务。桥接的 UNKNOWN 隔离也保持，
  不因一次查询而自动解除原有发送者暂停策略。

输入遵守官方 4096 字节 JSON UTF-8 限制，超限明确拒绝，不截断后提交。
配置模型、身份、实例或服务地址改变时，现有映射目录拒绝加载，需要明确的新环境或人工迁移。

## 私有映射和审计

新 `--state-dir` 必须在仓库和任务工作区之外。`channels.sqlite3` 只管理渠道关联 / 回执 / 决定；
官方任务真相仍保存在官方 runtime.sqlite3。辅助 owner.sqlite3 的独占事务保证单实例，
进程退出后由 SQLite / OS 释放锁，没有自动删除失效文件的逻辑。
使用 FULL 同步和 WAL；消息与发送者活动映射在同一事务提交。
数据库不保存 token 或原始输入文本，保留输入指纹。返回文本和审批预览可能含私人内容，
属于私有回执而非公开日志；Unix 要求私有目录，Windows 实机使用前还需人工核实目录 ACL。

`audit` 表记录有唯一 ID / 时间戳的 `official_tool_receipt_observed` 与 `official_task_state_observed`，
关联官方任务、session 与收据短内容无关的 SHA-256 标识。重复查询不产生重复收据记录。
只输出名称、成功证据与复用标记；不复制参数、payload、文件内容、模型文本或认证头。
`successful_non_reused_receipts` 统计成功且非历史/读取缓存复用的宿主收据，不是物理 I/O 次数，
也不伪造 `tool_execution_started`。失败、拒绝、审批等待与模型口头完成不计入。
审计/映射写入失败返回 unknown，不能报告已审计成功。
原分支的 JSONL 与 verify-audit 属于旧合同，保持原样；本版不声称新审计与旧 JSONL 格式完全相同。

## 运行方式（本轮未启动真实服务或渠道）

先由宿主在独立环境配置官方服务、独立 workspace / SQLite、`approve-mutations` 和上述客户端，
模型提供方凭据仅由宿主管理。用隐藏输入在本机设置示例引用的环境变量，不能在聊天提供或写入配置。
源代码调试入口如下，无需额外 Python 依赖。候选 Suite 可在独立可选环境中安装同一 facade，
普通 GUI 不需要 Node；本节原有 Windows/WSL 结果属于队友既有证据，本轮未重跑：

```text
python -m localpilot_channels --config /new/private/message-channels.json --state-dir /new/private/channel-state --port 8003
```

仅监听 127.0.0.1，上游只允许数字 loopback HTTP origin；忽略环境代理，拒绝重定向，不自动重试。
原 PR 的源码检出入口未纳入 wheel。本集成候选已补充 Core 包发现与独立可选渠道 wheel，
但本轮构建/安装仍为 NOT_RUN；使用方法和验收边界见 [集成说明](channels-pr2-integration-20261027.md)。
每个桥接的运行终端设置其自己的 LOCALPILOT_MESSAGE_KEY，分别对应 Q / WX 入站密钥。
微信额外配置 LOCALPILOT_APPROVAL_KEY 和 LOCALPILOT_WECHAT_APPROVERS，不能与普通密钥共用。
`LOCALPILOT_MESSAGE_ADAPTER_URL` 显式指向新共享入口。
两个 CLI 均要求显式 LOCALPILOT_QQ_STATE_DIR / LOCALPILOT_WECHAT_STATE_DIR；不得复用任何旧真实状态目录。
完整真实渠道切换仍需确认机器人独占连接与重新验收，本轮没有执行。

## 模拟测试与平台边界

```text
python -B -m unittest tests.test_channel_adapter tests.test_channel_official_integration -v
node --test tests/test_qq_bridge.mjs tests/test_wechat_ilink_bridge.mjs
```

WSL2 Ubuntu 在迁移仓库中运行：

```text
python3 -B -m unittest tests.test_channel_adapter tests.test_channel_official_integration tests.test_agent_service tests.test_runtime_api -q
node --test tests/test_qq_bridge.mjs tests/test_wechat_ilink_bridge.mjs
```

Windows：共享层 23 通过，4 项官方 Core 集成明确跳过（fcntl / POSIX 文件句柄）；Node 65 通过，均无失败。
WSL2：共享层＋真实官方 HTTP / SQLite 集成＋原官方 API 回归 82 通过，Node 65 通过，均无跳过或失败。模型响应为脚本，
QQ / 微信仅访问模拟 HTTP 服务，Node 场景从不连接真实网关、扫码或轮询真实 iLink。
官方集成确实调用隔离工作区工具：4 次 list_directory，批准后创建一次 approved.txt，
拒绝后 rejected.txt 不存在；普通身份 403、跨 owner 查询 404、过期审批和幂等冲突 409，
官方服务和适配层重启后保持相同任务关联。
这些结果不能说明真实手机、真实模型、原生 Windows 官方 Core 或 macOS 本轮已验收。

原生 Windows 官方 Core 仍因 agent/persistence.py、file_locks.py 的 fcntl，
以及 O_NOFOLLOW / dir_fd / 私有 owner 检查等受阻。共享层本身未引入 Windows 专有模块。
WSL 提示宿主 localhost 代理未镜像；测试直接访问 WSL loopback、无代理，全部测试服务均独立创建并退出。
Windows Node 跨 WSL 访问正式服务的网络路径、长时运行、投递窗口与人工对账尚需真实验收。

## 本轮文件清单和后续验收

相对官方基线均为新增文件；渠道代码来自原功能分支，仅在新工作区适配：

- `localpilot_channels/__init__.py`、`__main__.py`、`client.py`、`adapter.py`、`store.py`、`server.py`。
- `configs/message-channels.example.json` 与本文档。
- `integrations/qq-bridge/bridge.mjs`、`cli.mjs`、`gateway.mjs`、`package.json`。
- `integrations/wechat-ilink-bridge/bridge.mjs`、`cli.mjs`、`package.json`、`THIRD_PARTY_NOTICES.md`。
- `tests/channel_fixtures.py`、`channel_bridge_scenario.mjs`、`test_channel_adapter.py`、
  `test_channel_official_integration.py`、`test_qq_bridge.mjs`、`test_wechat_ilink_bridge.mjs`。

Core、MLP、GUI、原功能分支及真实渠道状态文件未修改。没有自动创建 Git 提交。
后续真实验收前，应在新的受保护服务目录完成官方 CLI 配置检查、模型连接与权限核对，
人工确认两个渠道身份及微信审批者，设置互异凭据并验证实际网络命名空间的 loopback 可达性。
真实桥接必须确认独占连接，并经用户同意才启动；使用全新平台状态目录，不导入或重放历史任务。
先做两个渠道各一条只读任务，再单独验证微信批准/拒绝和官方任务关联；不得沿用本轮模拟 PASS 声明手机接入成功。
