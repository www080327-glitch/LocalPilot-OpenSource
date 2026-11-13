# LocalPilot 国赛前整改：Work 接力任务（2026-11-13）

> 本文是未完成工作及验收操作单，不是已通过测试的结果。以 GitHub 实时 HEAD 与真实运行环境为准，不能将任何 `NOT_RUN` 写成 `PASS`。

## 仓库与保护边界

- 产品主线：`www080327-glitch/LocalPilot-OpenSource`，目标 PR **#1**，head `fix/nationals-runtime-ux-20261113`，base `main`。
- 开始前核实 PR、实际 HEAD、main、未推送/未提交工作树、运行中 APP/Core/Channels/wheel 版本、当前已有 Work 任务，避免覆盖或交叉修改。
- 私有 `www080327-glitch/LocalPilot` 的 `codex/desktop-rc7-oneclick-20261029` 为历史产品源码来源；`LocalPilot-AIC-20261030-Frozen` 为不可回写的初赛存档。仓库审阅可以跨仓库，修改只进授权的 PR 工作树。
- **不合并 main、不替换 Latest、不覆盖日常 APP、不删除缓存/模型/任务收据/凭据**。仅在 macOS 独立测试槽安装候选。严格执行 `desktop/AGENTS.md` 与现有发布、备份、回滚流程。
- 不创建第二套 Runtime/Router/权限或状态管理框架，不复制已经完成的工具动作，不为了很小概率的竞态引入额外状态机；外部输入只在入口验证一次。

## 已写入 PR #1 的内容（需实际回归）

1. 上下文 token 准入：`agent/context_budget.py`、`context.py`、`context_v5.py`、`session.py`、`hybrid.py`、`vllm.py` 等；旧 turn 字节账本保持独立。中文回退估算已比 UTF-8 每字节一 token 更积极。核对具体本地 tokenizer 支持率及过窗边界。
2. Cooperative 有界本地试用，云端主模型可配本地伙伴，云端/本地双向委派复用已有 HybridController。已新增 cloud-primary route 的返回切换预算逻辑。
3. 偏好保存失败恢复、UNKNOWN 只阻塞原 Session、符号链接与 Full 授权、Shell 长时限/Schema（**Shell 取消尚未完成**）。
4. 显式跨模型切换仍采用明确的新会话，不虚构 canonical history 已迁移；本地模型加载失败不再先丢失当前会话；从显式路由选择 Core Auto 也会新开会话而非继续绑定旧模型。
5. 项目组织/置顶、模型列表只展示 ready+tool_calling+来源允许的注册路由；注意 `ready` 并不是在线健康证明。
6. 底部本地/云端**请求次数**占比与子代理侧栏，运行中统计包含 `SubagentEvent` 嵌套调用，完成后采用服务端持久汇总，不假装是 token/费用占比。
7. SSE 重开 GUI 后支持 `after=0` 重放、事件序号去重；服务端任务快照在运行中暴露 `streamed_text`，过保留窗口的 `reconciled` 快照用于重建全文并续接新事件；工具不重放。

## 第一阶段：先完成静态/构建与测试验收

在**完整 Git 检出**、现有仓库工具链与可明确证明的独立执行环境中，先执行：

```bash
python3 -m unittest tests.test_nationals_runtime tests.test_context_v5 tests.test_harness_context tests.test_v49_context_cache tests.test_vllm_cooperative tests.test_cloud_local_partners tests.test_runtime_api
cd desktop
npm ci
npm test
npm run build
cargo test --manifest-path src-tauri/Cargo.toml
```

如环境可用，再按仓库 Playwright / macOS 测试槽流程执行 `npm run test:ui` 和现有全量测试。任何失败都应定位真实实现最小根因，修修复并重新跑；记录 Python、Vitest、Rust、TypeScript、UI、真实模型的独立结果与日志。尤其检查新加入的 `StreamBackend` 运行快照测试、`replyText` 回退、SSE 409 重建、实时子代理统计与 Auto route 会话边界。若缺环境，标记 `NOT_RUN`，不要推断通过。

## 第二阶段：独立 macOS 测试槽与真实用户路径

遵守 `desktop/AGENTS.md`，先检查当前安装路径/进程/数据/备份，**不覆盖正式 Bundle ID 的日常应用**。重点按以下顺序做端到端：

1. 首装→模型下载/加载→标准 Agent 读取/修改文件；对未装 Core、未加载模型、云 API 不可用分别显示真实状态。
2. 偏好保存失败一次后继续修改与发送；加载本地模型失败时不丢原对话草稿；显式模型↔自动路由切换时历史边界清楚。
3. 一个 UNKNOWN 原提交不会冻结其他 Session 的安全只读任务；旧 UNKNOWN 收据和幂等身份保留。
4. 四档权限、合法软链接、macOS 临时目录别名、工作区外授权、Full 文件工具与 Shell 行为一致。
5. 长 Shell 的正常完成/超时/手动取消，核对部分副作用收据、不自动重试。
6. SSE 正常重连、GUI 完全关闭重开、事件保留窗口溢出后的任务全文、已完成子代理及收据恢复。
7. 同一局部/云端模型组合运行：Local 主→Cloud 子、Cloud 主→Local 子、Local 有界升级到 Cloud；每个真实请求在任务事件和占比里有可核验来源、模型/任务/成本记录。
8. 真实组件升级候选的版本一致性与失败回滚；用户可完成的一次升级流程。

## 第三阶段：尚需实现的关键产品整改

按用户影响与可验证性排序；**不要把此部分全部硬塞进一次高风险 PR**。先在 PR #1 修回归问题，其余拆成可审核的聚焦 PR（或明确说明为何同 PR 更合理）：

- **同会话无损模型迁移**：已有 Session 的 canonical 消息、工具收据、未决任务和工作状态通过既有 Hybrid 交接路径转给新模型，不重演写操作；不能做到之前继续显式新建会话。
- **真实可用模型列表**：配置 ready/文件已下载/进程已加载/Endpoint 活跃/支持工具调用/云端鉴权有效分别展示。在线健康不能假造，避免向用户承诺未探测的云 API；精简不是真正可执行的选项。
- **Shell 手动取消**：沿现有 task cancellation + subprocess/process group 接线；区分已完成的非零退出、超时、UNKNOWN 写效果，不引入新的权限弹窗。
- **单次组件升级**：GUI/Core/wheels/Channels 各自版本独立，用户只做一次“升级”，更新/兼容检查/失败回滚可见且原有数据安全。
- **50GiB 受管可重建缓存预算**：先在用户 Mac 只读盘点每个目录的归属与可重建性；预算只覆盖 LocalPilot 自己拥有的缓存。优先复用现有淘汰机制，禁止误删模型、收据、备份或外部进程缓存。
- **减法式重构**：App.tsx 的会话提交恢复、服务连接、消息任务事实逐步拆分；Session 初始化多代策略和 desktop_sessions 手工回滚按现有正常路径减法整理，不引入万能配置对象。权限、模型来源与低功耗选择解耦，保持四档体验。
- **独立配对评估**：冻结任务集，DSH 全云/LP 全云/LP 本地优先/同本地模型框架配对，统计成功率、质量、真实主子模型、请求次数、token、成本未知项、重试与耗时；先修工程准入再谈节费。

## 交付格式

每个问题提交：实际根因、最小复现/对应源码、改动范围、删除/合并的重复逻辑、真实跑过的测试命令与结果、仍未解决的具体条件。证据归 `docs/evidence` 新运行目录，修复报告归 `docs/development`，更新 PR 描述；**不合并 main、不发布候选为 Latest、不宣称尚未运行的验收已经 PASS**。
