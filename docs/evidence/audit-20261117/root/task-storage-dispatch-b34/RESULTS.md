# RC17：任务逐条存储、Super Agent 分工与真实工程复验

2026-11-17。接续 PR #15，当前版本为 Desktop **5.0.1-rc.17**、Core **5.0.0b34**、Companion **0.5.7b11**、Suite **0.2.0b34**、Channels **0.1.0a4**。

**本轮完成任务存储热路径修复、可配置的探索／审阅角色，以及最终候选的 Sol medium 工程验收。发布状态仍为 `NOT_RELEASE_READY`：当前候选的 macOS 双架构及 Linux 原生界面、桌宠可见动画门禁未完成。** PR 保持 open；没有合并、创建 Tag 或发布新的原生 APP/DEB。

## 源码与证据入口

| 用途 | GitHub 源码提交 | 等价本地提交 | Git tree |
|---|---|---|---|
| RC16 基线、R9 | [c411dd1](https://github.com/www080327-glitch/LocalPilot-OpenSource/commit/c411dd1f92ad09e3b6e095acc96bc65c12107d5e) | 同左 | 见 [SOURCE.json](SOURCE.json) |
| RC17 初候选、R10、存储性能及迁移 | [ce9264b](https://github.com/www080327-glitch/LocalPilot-OpenSource/commit/ce9264b2e958c163debb0b350eeb32ce7c4e56e0) | `37570b9a7c6b64e0ac67ab2706c15eeebc714069` | `2272b6f3a975d26bcae1c020b94bb3e2ca4ef04f` |
| RC17 最终源、R11、Core 全量复验及最后安装组合 | [2fcf955](https://github.com/www080327-glitch/LocalPilot-OpenSource/commit/2fcf955f5d9a1d22c8edc5342de85cc0336eda83) | `3764fc054899d9fb3d13c545667e4ff0fc64d044` | `6923f502896ebc565be54532e49107fd1bbd21d9` |

GitHub 创建的提交与本地测试提交具有相同完整 tree；最终源已从 GitHub 重新 fetch，并比较全树无差异。最后一笔源修改只让无工具请求省略无关工具指导，保留原 4000-token 测试窗口并增加实际请求断言；Companion 156 份 Python 文件与性能测试源码逐字相同。

[逐组归档与清单](SUMMARY.md) · [原始归档清单](MANIFEST.json) · [完整交付文件散列](DELIVERY_MANIFEST.json) · [独立复核](INDEPENDENT_REVIEW.json) · [实现与配置说明](../../../../development/TASK_STORAGE_SCHEDULING_20261117.md)

## 1. 一万条历史任务不再反复解析和重写整份 JSON

Companion 在同一个 SQLite 数据库中按 task ID 保存一行完整 payload，另建时间、session、endpoint、活动状态索引。热路径已改用精确读取、单行更新和索引游标分页；没有保留会重新物化完整映射的兼容入口。

旧库首次打开时，先校验旧映射、创建权限为 0600 的任务迁移前备份，然后在同一事务内建表、导入全部记录、删除旧映射键。实际 SQLite 失败注入验证了 DELETE / COMMIT 失败后的迁移回滚。未知历史字段、原始请求、任务与会话 ID、provider、scope、幂等提交及事件游标保留。已接受任务恢复采用 `put_if_absent`，避免覆盖更完整的旧收据。

### 同机对照结果

同一 Python 3.12.14、Linux x86_64 环境、同一脚本，基线和候选顺序执行；没有其他构建、全量测试或模型任务并发争用。每个规模有一个经过真实认证 HTTP 的脚本化任务，其余记录为明确标注的合成历史，且真实任务被放到最旧位置。每项记录五个预热后的样本；SQL 追踪及 tracemalloc 分开执行。

| 保存任务数 | 旧 JSON：真实旧任务 HTTP 状态，中位 ms | 新逐行存储：同路径，中位 ms |
|---:|---:|---:|
| 1 | 1.916 | 1.928 |
| 100 | 13.460 | 1.933 |
| 1,000 | 120.502 | 2.088 |
| 10,000 | 1,493.586 | 1.970 |

| 一万条历史下的操作 | 旧 JSON，中位 ms | 新逐行存储，中位 ms |
|---|---:|---:|
| 按原 task ID 查 provider | 373.630 | 0.0337 |
| 接收任务终态更新 | 715.529 | 0.6108 |
| 历史首页，默认 30 条 | 467.151 | 1.5260 |
| 历史第二页 | 481.171 | 1.2439 |
| 对该真实旧任务的上下文检查 | 711.614 | 0.0661 |

一万条 HTTP 状态路径每次原有 **3 次整映射读取、1 次整映射写入**，候选均为 **0**。独立 Python 分配采样峰值 **368,284,764 → 62,906 bytes**；它不是进程 RSS。首次打开一万条旧历史、包含迁移、备份及 host 初始化的耗时为 **1,158.971 ms**，与后续稳态查询单独记录。

[可直接阅读的性能对照](PERF_COMPARISON.json) · [存储原始证据及脚本](storage.SUMMARY.md)

这些结果证明本次历史热路径不再随全库 JSON 解码和重写增长，不能推广成所有操作恒定成本。分页总数仍使用 `count(*)`；同一 session 的历史权限仍逐条核对，测试未覆盖单 session 中一万条前序请求。`stored_payload_bytes` 不含索引、SQLite 页开销或备份；数据库及原始历史仍占磁盘。该 host fixture 没有执行完整原生 Companion 启动循环，不是 UI 延迟或跨平台性能保证。

### 升级、降级及清空

真实旧实现读取恢复后的备份，任务与其他 memory 全部一致；迁移后的新增行可在重启后读取。旧 Companion 直接打开新库不会主动拒绝 schema，但读不到已经移除的旧映射，所以**降级必须停服务并恢复迁移前备份**。备份之后的新任务不在旧快照中。明确清空记忆会同时删除任务行和自动迁移备份，重开不会复活旧任务。原 MemoryStore 初始化可能先于任务备份运行，不把该备份称为整个数据库初始化之前的字节快照。

## 2. Super Agent 继续统筹，探索和审阅可单独配置模型

在现有模型合作配置入口中，可为已选择的伙伴指定“探索模型（只读）”和“审阅模型（只读）”，同一伙伴可兼任。取消伙伴或将其提升为主模型时，失效角色选择会清理。配置复用现有 route 和合作策略，没有加入第二套路由器。

主 Super Agent 决定任务分解、按需委派、收集收据并交付。命名角色绑定自己的注册 backend，保留明确配置的思考强度，并由现有 Gateway 限定只读；实际 Full host 中不再向只读子任务广告无法执行的 Shell。角色子任务不提供模型切换工具，自适应模型锁与其专属目录一致，父级既有模型锁继续生效。普通执行子任务仍可在已有权限内运行 Shell 和测试。

显式伙伴 `thinking` 优先于父任务继承，实际 localhost TLS Responses 检查确认了父 high、伙伴 medium 的请求；另一个真实 loopback 角色流程记录主 high、探索 low、审阅 medium 及重启后的身份。它们使用脚本化 provider，验证模型/effort/权限/恢复集成，不冒充真实多模型能力评测。

`worker_roles_v1` 仅在保存非空角色配置时作为兼容能力要求。旧的无角色配置和固定 V5 system 文本保持兼容。简单路径选择、来源、预算和队列判断仍由已有代码处理；没有固定三次顾问触发、每次 grep 必调模型或自动升级付费模型，也没有引入未明确来源的 JEV 服务。只读审阅没有实现 worktree 隔离，测试由父任务或普通执行子任务承担。

[配置、HTTP 与前端证据](scheduling.SUMMARY.md) · [核心定向、恢复和独立审阅](superagent.SUMMARY.md)

## 3. R8 原因修复，以及 R9 / R10 / R11 的真实结果

R8 原失败仍保留。错误解释器路径及 Parser 子任务未完成自身验收，是当轮任务规划与恢复问题；但广告了未注册的 LIGHT/STRONG 则是可复现的产品缺陷。当前只声明实际注册且符合来源策略的 tier，并给有工具的请求补充通用工作指导：保留解释器与验收命令、明确子任务所有权、回收真实收据和未完成检查。未写入特定验收答案或放宽规则。

无工具会话原本也追加了这段指导，导致 4k 窗口回归中第三轮输入的宿主估算由 3444 增至 3686 tokens，超过 3664 的输入预算 22，正常触发了压缩。最后修复省略此无关指导，原窗口和全部旧前缀断言保留；33 项定向回归通过。

工程 runner 只新增显式 `--model` 和 `--reasoning`，冻结 SHA-256 为 `1878a177ed32600e9d53490ad518a93ece8d729643f2e2681c7b10d11d4724c4`。原始 prompt 模板、夹具、验收函数、4096 子任务输出上限和两个子任务预算保持不变；运行环境生成的绝对 Python 路径不能称与更早 R8 字节相同。

| 轮次 | 源码 / 实际主与子模型 | 整体工程 | 模型调用 | 工具回执 / failed | 耗时 s |
|---|---|---|---:|---:|---:|
| R9 | RC16 / Luna high | **PASS** | 28 | 61 / 3 | 281.068 |
| R10 | RC17 初候选 / Luna high | **FAIL** | 20 | 40 / 4 | 184.082 |
| R11 | RC17 最终候选 / 6.1 Sol medium | **PASS** | 29 | 58 / 0 | 212.880 |

- **R9** 遇到两次旧版未注册 backend 错误和一次 subgoals schema 错误后恢复。提高思考强度的这次成功不能抹去已发生的产品错误。
- **R10** 的 Parser 子任务第二次响应输出恰好达到 4096 tokens，`finish_reason=length`。本次响应的工具提案未执行，Parser 保持 stub。此前该子任务已有四条只读回执，因此不能说整个子任务没有使用工具。父任务试图创建第三个子任务，被原预算拒绝；Aggregate 自测成功，但外部工程仍失败。现有截断响应缺少同一子任务内拆分补丁后继续的恢复路径，本轮没有追加预算或改变这项机制。
- **R11** 两个子任务都异步完成并被收集，各自只修改负责模块并完成自己的测试：Parser **9 项**、Aggregate **3 项**；父任务完成 CLI 与整体检查。两个成功子任务生命周期交叠 **78.762289 s**，不是同时占用 CPU 的证明。停止 Core 后，恢复原始验收文件进行的 **17 项 unittest + 4 个 CLI 场景全部通过**。全部 **29 条实际 ModelRequestStarted** 宿主事件均记录 `gpt-6.1-sol` / `medium`，provider 返回的模型字段也全部为 `gpt-6.1-sol`；provider 没有独立回显 effort。小型摘录公开，SQLite 本体排除。

[R9 摘要](ENGINEERING_R9.json) · [R10 摘要](ENGINEERING_R10.json) · [R10 失败分析](R10_FAILURE_ANALYSIS.json) · [R11 摘要](ENGINEERING_R11.json) · [三轮比较](ENGINEERING_COMPARISON.json)

R11 provider 用量为输入 **1,055,681**、输出 **5,975**、缓存输入 **871,073** tokens；这些是汇总一次的父子调用用量，不是计费账单。三轮都是单次合成工程集成，没有总体成功率或 Artificial Analysis 官方榜单排名含义。R10 到 R11 同时更换了模型／effort 并修复无工具指导开销，不能把结果差异只归因于模型。三轮父子各自使用同一个配置模型，不是异构探索／审阅角色的真实模型能力评测。R9/R11 的产品结果仍为 `unverified / not_run / task_succeeded=false`；这里的 PASS 是独立外部工程门禁，没有改写产品内的验证等级。

## 4. 回归和安装验收

| 范围 | 实际结果 | 范围说明 |
|---|---|---|
| 最终 Core 全量 | **1709 = 1617 PASS + 92 SKIP**，零失败/错误 | 最终源；607 文件前后不变 |
| Companion 全量 | **756 = 723 PASS + 33 SKIP**，零失败/错误 | 初候选；最终 Companion 156 文件一致 |
| Suite 全量 | **127 = 126 PASS + 1 SKIP**，零失败/错误 | Suite 代码与最终源一致 |
| 前端 | **75/75 PASS**，TypeScript/Vite build PASS | 不等于原生界面通过 |
| 角色集成定向 | **161/161 PASS** | 最后小窗口修复另有 33/33，最终 Core 全量覆盖 |
| 原四 wheel 组合 | 31 项首次通过，5 项修正测试临时目录后通过 | 同一批 wheel；首轮失败保留 |
| 最终 Core + 原其余三个 wheel | **36/36 安装态 Core 测试 PASS** | pip check、能力、导入来源通过；288 份安装源与最终源码、wheel 一致 |
| 浏览器配置交互 | **2 个 Chromium launch BLOCKED，0 页面断言** | `socket() failed: Operation not permitted` |
| macOS / 当前原生桌宠动画 | **NOT_RUN** | 未连接 Apple Silicon / Intel Mac；本轮无可见 ≥24 Hz 验收 |

最终 Core wheel SHA-256：`0914939f70dce9b4f88dc6c2a00f0e09d285b0bcdfee75c786ab8b3e9852c641`。其他三包保留原批次，实际安装来源、散列和两轮构建分别见 [最终组合](PACKAGING_FINAL.json)、[原组合](packaging-original.SUMMARY.md)、[最终组合原始证据](packaging-final-core.SUMMARY.md)。wheel 组件验证不代表原生系统安装、签名或发布合格。

Core 首轮真实记录为 5 FAIL / 18 ERROR：包含一处上述小窗口问题、缺少 `__main__` 保护的验收启动器，以及没有安装既有插件 extra 和 YAML 测试依赖。原日志完整保留。仅修启动器、补既有依赖并修正具体产品路径后复验；没有删除失败测试或改成 skip，import/setUpClass 恢复后发现的测试数自然增加。原四 wheel 的五个初始化错误来自测试设置的 TMPDIR 祖先可写；沿用原系统临时目录后仅复验这五项，未更改产品路径规则。

最终 Core 的 92 个 skip 包括 42 个可选官方 SDK 案例、未提供的固定历史基准及原生环境等；Companion 的 33 个 skip 包括 macOS Swift、Whisper、Torch/PEFT 和 Linux Xvfb/D-Bus 条件。逐项原因见 [回归原始记录](regressions.SUMMARY.md)。跳过不是通过。

## 5. 仍未宣称完成的发布门禁

当前候选的 Apple Silicon / Intel macOS 真机构建与交互、Linux 原生桌面交互、Companion 气泡焦点、缩放、多显示器、减少动态效果和可见动画更新率仍未完成原生验收。原 RC14 Ubuntu arm64 首装/升级/回滚、旧 Linux 动画和两小时 soak 只保留其原版本范围。本轮没有将这些历史证据改标成 RC17 通过。

Core 通用 archived-canonical 搜索工具、未覆盖路由的执行段轮换及单个运行中超长 turn 的块式持久化仍是既有后续范围。Full 的一次授权和显式长时预算准入保留，本轮没有新的数小时权限 soak，也不将一次 213 秒的工程验收写成数小时运行证明。

原“四类各十项”的审计清单保留，新增工作不重复凑入四十项。所有本轮失败、阻断、跳过和源码对应均随此 GitHub 证据交付。
