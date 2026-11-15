# 同一 Session 的主模型切换

基线：PR #1 `94e0e6f`。本轮是 Issue #6 的一部分：显式选模型在兼容的持久会话内完成迁移。它不证明所有模型/工作区/子代理组合都已兼容，也不是原生 macOS 或真实模型验收。

## 产品行为

当前会话空闲时，在模型选择菜单中选择另一个已注册的 Agent 模型，Desktop 调用 host operator 的模型切换操作。成功后保留 Session ID、可见聊天、未发送草稿、历史任务、canonical 消息、工具收据和完成过的 call ID；下一条任务提交到这个 Session。历史任务的 `model` 仍表示当时使用的路由，新增 `session_model` 表示现在继续会话时使用的路由。

选择本地 oMLX 模型仍使用既有的显式加载流程。加载或迁移失败时，不清空聊天，不清空输入框，不更换当前选择。若 Core 未声明 `desktop_model_switch_v1`，界面说明需更新 Core，不再静默创建一个没有历史的新会话。

“Core 自动选择 · 新会话选路”保留其原来的明确语义：它是新建会话时的首轮选路按钮，不是已有会话自动迁移到任意后端。用户也仍可显式新建会话。

## 实现与持久化

- API：`POST /localpilot/v1/desktop-sessions/{session_id}/model`。
- Native Suite 操作：`product_control / desktop_model`；Rust 只增加既有操作白名单。
- 所需主体：独立 operator，具有 `control`，且 `client_subject` 在其 `approval_for` 范围内。普通模型客户端不能自行改变会话的主机路由或数据边界。
- 请求字段：`client_subject`、`model`、`expected_model`、`source`；可选 `reasoning_effort`。`expected_model` 防止旧选择覆盖另一个已完成的选择；相同目标的重试返回当前 Session。
- `source` 使用现有五档来源策略核对目标。`reasoning_effort` 为字符串时要求目标支持；显式 `null` 使用目标主机默认值；省略则尝试保留旧会话的显式 override，不支持就返回 409。

迁移以既有目标 route factory 构造候选 `AgentSession`，应用原 Desktop 权限、Agent profile 和文件夹授权，并以原 Session ID 重新绑定已存在的文档工具。比较工作区、工具 schema、权限、文件作用域、预算、验证契约、引擎和异步策略。只允许模型相关的配置不同，不把一个不同工作区或工具集合伪装成同一契约。

然后通过现有 `snapshot_runtime()` / `restore_runtime()` 迁移整个 canonical runtime checkpoint。修改的是主机系统指令、目标后端、目标思考参数与 Hybrid 当前目标；所有非 system 消息、工具 ledger、UNKNOWN 记录、completed-call 去重状态、任务历史和工作状态都来自原 checkpoint。没有额外模型调用，没有重新执行工具，也没有把旧聊天拼成一条新的用户提示词来冒充会话恢复。

Hybrid 的历史 attempts 保留当时的 provider、configured model 和 kind。provider 专属的缓存/推理重放 provenance、旧 egress grant 不转移到另一个模型。canonical 中的原生推理记录继续保存在本机，但新 provider 的消息投影不会把它们当成自己的推理缓存重放。旧模型的 context_length 不沿用；目标若有 oMLX 实时 context_budget，使用该值，否则用目标 route 配置。

候选验证完才替换 SessionRecord 的 runtime/model，写入同一 SQLite Session 的 checkpoint；写入失败恢复内存中的原对象，保留服务原有的存储故障隔离。若检查点提交结果未确认，返回 503，要求重启核对持久状态，不声称一次未确认提交一定没有发生。确认持久化后才关闭原 runtime。

## 当前明确限制

| 情况 | 行为 |
|---|---|
| 任务执行中、等待审批/人工处理、队列或 durable intent 未结束 | 409 `session_busy`；不变更会话 |
| 会话关闭 | 409 `model_switch_unavailable` |
| 保留 UNKNOWN/partial 收据的可迁移边界 | 409 `model_switch_unknown_blocked`；模型切换不能清除未知效果 |
| 已保留任何 child Agent runtime，即使 child 已完成 | 409 `model_switch_children_incompatible`；尚未实现跨后端 child tree 迁移 |
| Native Computer 或 calibrated adaptive runtime | 明确拒绝；这些契约未资格验证 |
| 工作区、工具 schema、预算、验证或引擎/AsyncPolicy 不同 | 409 `model_switch_contract_incompatible`，列出不同字段 |
| Hybrid 协同策略、路径或请求大小上限不同 | 409；不改变原契约 |
| 旧 scope_revision 的 local/cloud 硬数据边界发生变化 | 409；仅现有 Desktop v3 明确选 provider 的语义支持这种迁移 |
| 无可用/已注册 Agent 目标、来源限制不满足或思考档位不支持 | 返回对应错误，保留旧选择 |

这意味着“多子代理任务之后再任意换模型”仍未交付；目前是同工作区、同工具和主机契约、无保留 child tree 的空闲 Session。目标模型能否真正使用完整历史、是否足够强、context 容量与实际延迟，需要用真实模型任务验证。

## 本轮验证

`tests/test_pa_model_switch.py`：8 PASS，0 FAIL，0 ERROR。测试使用真实 loopback HTTP、真实 SQLite、真实临时文件工具和 ScriptedBackend；没有模型权重或云端推理。

覆盖完整消息/收据/去重状态和 Session ID、local → cloud 路由及公开别名、历史 task.model 冻结、同目标重试、旧 expected_model 冲突、重启后继续、同原 idempotency key 返回原任务、V5 稳定指令与 AsyncPolicy、不同工作区回滚、权限/来源/模型状态/思考档位拒绝、真实 UNKNOWN 收据、已完成子代理不误改绑、native reasoning 保留但不跨 provider 重放，以及 SQLite before_commit 失败后从旧路由重启。

组合命令：

```bash
.venv/bin/python -m unittest \
  tests.test_pa_model_switch tests.test_desktop_product \
  tests.test_desktop_permission_v3 tests.test_pa_macos_install \
  tests.test_pa_macos_hardware tests.test_recommender -q
```

75 项：73 PASS、0 FAIL、0 ERROR、2 SKIP。两项 SKIP 明确要求 macOS Shell/Seatbelt。

`npm run build`：TypeScript 与 Vite PASS。

GUI 用例位于 `desktop/tests/ui/pa-model-switch.spec.ts`，使用明确标注的合成 native bridge，检查原聊天/草稿保留、下次提交沿用 Session、重开显示当前 session_model，以及不兼容路由失败时保留原选择。当前 2 项均为 NOT_RUN/BLOCKED：默认 Playwright 指定的 Chromium build 未安装；系统 `/usr/bin/chromium` 也因容器 `socket() failed: Operation not permitted` 在启动阶段退出。没有进入产品断言，不能把它记成 GUI 产品测试失败或成功。用例保留给本机 Work。

## 本机 Work 接续验收

在独立 `LocalPilot Test` APP 和独立 Core 数据目录内使用已获准的真实端点/已存在权重；不要复用或改动日常 APP/未授权的外部 oMLX 配置，不要因为磁盘不足自动下载大模型。

1. 选择两个工具契约和工作区相同的真实 Agent 路由。先执行带随机标记的文件创建/读取，记录 Session ID、任务 ID、工具收据和文件摘要。
2. 输入未发送草稿，再切换另一个模型。检查界面聊天/草稿保留、Session ID 不变、旧 task.model 不变、session_model 更新、权限/profile/文件夹授权不变。
3. 让新模型回答旧标记并实际读取原文件；确认从同一 Session 继续且旧 mutation 没有重放。记录 provider/model、thinking、上下文预算和实际调用。
4. 完全退出测试 GUI/Core，再用原隔离目录重开；检查 Session、历史、模型选择、思考档位和任务去重恢复后再继续一轮。
5. 对不支持 thinking、目标不可用、不同工作区、活动任务/审批和 UNKNOWN 分别验证拒绝。保留失败日志与原聊天，不用新 idempotency key 重放未知操作。
6. 子代理树迁移目前应得到明确不支持；记录为限制，不能写成“任意模型会话迁移通过”。

原生 SSE、真实模型加载/质量、macOS 权限与外部服务资源占用均不由上述 Linux 测试证明。


## Mac 续测

真实本地→云端→本地、同 Session 历史模型/收据保留和 child tree 拒绝已验证。原生重开发现既有 Session 草稿未持久化，已补保存/恢复并在最后 APP 再次重开验证；详见 [Mac 验收](../evidence/nationals-20261114-pa-mac/RESULTS.md)。
