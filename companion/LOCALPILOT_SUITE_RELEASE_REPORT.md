# LocalPilot + Companion 首次联合发行报告

发行候选：**LocalPilot Core 4.9.2rc2 · Companion 0.5.5rc2 · Suite 0.1.0rc2**。Agent Service API / Companion Client Contract 均为 **1.0**。

准入结论：**SCOPED_RC_GO，非完整生产正式版**。已取得真实模型、真实服务、真实安装和 CLI 操作证据；未因回归全绿宣称全部场景通过。0.8B 普通算术答错、全天候运行和真实压缩语义验收仍限制正式准入。本报告对应 2026-10-21 开始的发行工程，最终时长以证据清单为准。

## 模块与仓库审计

最初检查了真实路径、Git common directory、分支、HEAD、工作区和 remote。LocalPilot、Companion 与缓存修复目录实际为同一仓库的不同 worktree，不是两个独立 remote。原 LocalPilot 位于 v2-computer-use / 5e79fb2e；原 Companion 位于 companion-v0.4.4 / 1b8783c9；缓存修复在 companion-v0.4.4-service-cache / fed2409b。目录名没有被用作版本依据。

发行使用隔离的 Core/Companion/main 工作树，保留原目录及其未跟踪资料。发布前再次检查当前 Work，未发现其它活跃任务同时修改这些发行工作树。授权远端为 `https://github.com/www080327-glitch/LocalPilot.git`，实际验证其为当前账号所有、private 且具有 push 权限。

Core、Companion、Suite 是三个独立 Python distribution。Companion 不导入或复制 Core AgentSession/Runtime；Core 不依赖 Companion 内部实现；Suite 只协调安装、进程、配置、升级和 API。Suite 的有界心跳管理进程仅维护已有任务的普通 token 控制面，不调用模型、不执行工具、不审批。

发布采用经过白名单与敏感扫描的源码快照：Core 保留现有 Runtime，Companion 作为可独立安装的包，Suite 作为薄管理包。main 保留原合法历史及其它已有代码，更新当前发行源码；不合并整条包含私有运行证据的开发历史。模块源码分支独立提供，未创建或猜测新 remote。

## 契约冻结与升级兼容

详见 [API 兼容协议](SUITE_API_COMPATIBILITY.md) 与 `localpilot_service/openapi.json`。冻结了 Session/Task、幂等键、SSE 游标、Approval/Cancel/Resume、verification/UNKNOWN、模型模式、Cloud Egress、错误/超时/重试、capabilities、health/version 和 4096 字节任务输入上限。

启动/提交前协商拒绝未知 API major、缺失能力、错误身份与不符合策略的路由。模型未就绪不会被健康检查推断为可用。普通 token 无权批准工具；resource-only token 只能执行限定资源授权，不能批准标准 Agent 的工具。

消费者契约使用**真实 HTTP/SQLite＋脚本模型**，不冒充真实模型验收：

| 组合 | 结果 |
| --- | --- |
| Companion 0.5.5rc2 + Core 4.9.2rc2 | PASS |
| Companion 0.5.5rc2 + 上一兼容 Core 4.9.2rc1（ca288239） | PASS |
| 上一兼容 Companion 0.5.5rc1（19ebc7d5）+ Core 4.9.2rc2 | PASS |

实际旧源均可获得，没有伪造旧版本。更早的 Companion 0.5.4 写死 Core 版本，历史迁移测试会安全拒绝新 Core；首次迁移应先升级 Companion。兼容范围内独立升级不要求重建另一模块，任意未来版本仍须实测。

## 真实端到端验收 A–P

接通电源后按用户授权关闭了系统 AC/电池两套 lowpowermode，并验证均为 0。真实模型使用现有 Qwen3.5-0.8B、受管 Qwen3.6-35B-A3B-4bit 和 DeepSeek flash；未下载权重。测试只读写隔离的公开合成 fixture。

| 项目 | 结论与范围 |
| --- | --- |
| A 独立启动/问候 | PASS；规则问候不调用模型 |
| B 简单问题 | PASS_ROUTING；真实 0.8B 光合作用问答，无 Core Task；但英文 6+7 答成 7，质量 FAIL 保留 |
| C 拒绝帮助 | PASS；无明确帮助同意不提交标准 Agent，无写入 |
| D 同意后进入标准 Agent | PASS；真实 Companion → authenticated API → Qwen 标准 Runtime |
| E 真实工具/receipt/verification | PASS；真实读与一次 apply_patch 写入；可信 verifier passed，另核对文件精确内容 |
| F 进度/结果 | PASS_SCOPED；原生控制窗、真实 SSE、Companion 任务投影和最终结果；并非所有 OS 通知模式验收 |
| G 等待审批 | PASS；展示 action；普通 token 403，无提前写入 |
| H 可信授权继续 | PASS；独立 operator、当前 action；切换、出站、写入分别审批 |
| I 重启恢复 | PASS；真实 Core 重启/包替换后原 Task ID、SQLite 和结果可查询；旧审批 action 409 |
| J SSE 重连 | PASS；游标重连不重新提交；一次 mutation receipt；最终 CLI 重复 watch 不重放历史事件 |
| K 本地失败→云端确认 | PASS_FAULT_TRIGGERED；真实 Qwen 输出预算设为 1 token，真实安全失败后提示确认；非自然能力不足证明 |
| L 拒绝云端 | PASS；明确拒绝后云端请求数为 0 |
| M 同意后仅原问题 | PASS；实际 provider 请求只有一条原始 user 消息，无本地上下文或客户端包装；每次咨询新 Session |
| N 云端结果不自动执行 | PASS；DeepSeek 回答 42，零工具；verification NOT_RUN 保持明确 |
| O 标准 Agent 跨模型接管 | PASS_SCOPED；Qwen read → 独立切换审批 → 出站审批 → DeepSeek apply_patch → 写入审批 → 精确文件和 verifier；限明确 cloud thinking none 的测试主机配置 |
| P 云端不可用 | PASS_SAFE_FAILURE；真实高 thinking 接管收到 HTTP 400，未写文件；确定性离线/错误故障另列为 scripted，不伪造成功 |

关键任务：审批/重启 `resp_07f2fb2b27d440978d7fc0e2c69d7d13`；最终接管 `resp_4751eb93e5af4c2ca639d99a2b16172a`；新环境 Agent `resp_72820f22187248699f9c4dae9803282d`。完整计数、验证维度和 SHA256 在 `docs/evidence/suite-release-20261021/`。

原生 UI 实际运行并确认可见控制面，可信本地测试通道执行用户授权的确认动作，不是模型自授权。跨系统通知投递、专注模式与另一台机器的系统权限保留 MANUAL_REQUIRED；自然工作行为触发帮助的召回率仍未充分证明。本轮没有扩大 Native Computer Use 准入。

## 实际修复

修复 provider 嵌套缓存统计漏报；过大输入先于 Runtime/模型租约拒绝；可选上下文省略有计数，原问题不截断；前一轮 usage/verification 不再污染未开始的新任务；关闭 Session 只在权威状态证明后处理，不换键重放不明 POST。

Companion 恢复规则→0.8B→必要时大模型的路径，禁用后端不虚增调用计数；每次云端仅原问题并使用新 Session；没有提交成功时不再显示“已提交”；UI 实例标识与当前版本一致。

隔离模型解释器与安装环境的 cwd/PYTHONPATH，避免 Core Python 3.14 的 regex 被 vendor Python 3.11 误载。受管初始化共享一个模型池与普通用户命名空间；CLI 退出由有界 API 心跳维持已授权任务。Hybrid 切到云端后仍能查询和维护原本地资源。没有增加第二套 Runtime。

## CLI、安装与升级

[README](README.md) 已更新为当前安装与日常入口；[CLI 手册](SUITE_CLI.md)、[安装升级回滚](SUITE_INSTALL_UPGRADE_ROLLBACK.md) 列出命令、退出码、JSON、可信审批、幂等和安全退出。

真实全新隔离环境安装三个 wheel，配置既有权重，启动 Core/Companion，问候、0.8B 问答、交互 chat、Agent detach、真实 read_file、verification、24 秒客户端退出后重连、重复游标 watch、重启查询同一任务及 SQLite integrity_check 均通过。配置/凭据引用校验值未变。受管模式依赖已安装的 oMLX.app；包不捆绑模型、oMLX 或私人数据。doctor 仅检查配置引用，不通过推理探测冒充模型健康。

实际独立替换 Companion、Core，升级/回滚、卸载重装保持 5 个受保护配置/用户文件 SHA256。pip 安装不具备事务回滚保证；升级要求保留旧 wheel 并显式停止受影响服务。历史旧 Core 缺少新 CLI 时，Suite 清楚拒绝并可用薄升级路径恢复。

故障验收覆盖错误 token、端口被占、API 不兼容、429、同键重复、SSE 断开、SQLite 恢复和并发生命周期锁。确定性故障与重放安全使用 scripted model，实际真实模型失败另有记录。补测实际空闲 Core 被 SIGKILL 后重启，失败任务/结果恢复且 Companion 仍可响应；mutation 中 SIGKILL 与 schema 跨版本迁移未运行，不能以脚本 UNKNOWN 控制替代。

已用两个全新环境分别验证 Core（没有安装 Companion）和 Companion（没有安装 Core）的独立安装与启动/问候；Suite 可联合安装。数据目录与代码/工具工作区分离，升级不覆盖凭据/SQLite。主要平台验收为 macOS arm64/Python 3.14.6，vendor 模型 Python 3.11；其它平台 NOT_RUN。

## 外部 Agent、回归和缓存

当前 Codex → portable Skill/HTTP Adapter → Core → 实际 DeepSeek 工具任务通过；不是嵌套再启动一个 Codex。实际 DSH headless → Skill/MCP → Core → DeepSeek 工具任务通过；使用 DSH 已有 credential service 的临时配置，没有复制 Core provider key 到 DSH。普通宿主权限不自动升级，Skill 不获得审批。Codex 原生 MCP 工具权限未获授予部分保留 NOT_RUN。

最终全量回归：Core **995** 项、Companion **546** 项，均 source_unchanged、0 failure/error/skip；可选 SDK 检查已实际运行。脚本回归与真实模型验收分别计数，测试通过不等于模型回答正确。

缓存专项见 [实测报告](SUITE_CACHE_ACCEPTANCE.md)。真实审批任务 cached 12,288/input 37,406（32.85%）；真实接管 cached 3,072/input 24,232（12.68%）；全新 CLI Agent 0/8,962；极简原问题咨询 0/25。指标来自 provider，费用与 provider TTFT UNKNOWN。持续 99%、压缩前后真实语义和长会话稳态收益未证明。

## 长程运行与资源

服务监控持续记录 Core/Companion RSS、可用内存、swap、模型进程/租约、Task 和 SQLite。测试包含多次真实模型任务与有意重启，实际每段连续时长、重启边界和 RSS 差异见 service-soak.json；不把分段累计当成连续全天候证明。此前另有 916 秒纯空闲无模型 soak，单独列明。

受管模型并发 1、资源/超时有界、任务后进程释放，不无限重试或重复加载。测试曾在原服务无活动请求时临时卸载原 Qwen3.8-27B 以释放 RAM；已恢复并实际确认 loaded_models，原服务未停止、配置未改变。无关服务与原工作区保持原状。完整清理和最终资源结果在本地 publication/final audit。

## Git 与发行安全

当前账号拥有并授权的 private 远端已核验。发布只纳入安全源码、文档、清单、受控合成测试和脱敏证据投影；不纳入原始对话/观察、记忆/运行数据库、模型权重、缓存、provider payload 原始日志、凭据或本机私人路径。扫描 exact wheel/source archive 与待提交树，合成 PEM 头测试夹具有精确 hash 白名单；没有因此放行实际私钥。main 原有的过期原始实验日志移出最新树并保留本地副本；历史文档中的本机用户名路径脱敏，既有远端历史不重写。回归原先依赖一份未发行的原始模型日志，已改为保留 usage 数字、明确标注合成文本的独立安全夹具，复跑整树回归；它只证明离线解析，不冒充真实模型通过。

发行提交采用普通 fast-forward 更新 main，并发布三个独立模块源码分支；不 force push，不覆盖稳定 tag，不上传完整开发历史。推送结果、模块 commit/branch 和 artifact SHA256 保存于发行清单，main 的最终 SHA 由 Git 历史及远端复核给出。当前仅发布带清楚限制的 RC，不创建正式稳定 tag。

## 未通过与最终回答

- **FAIL**：普通 0.8B 算术回答；历史高 thinking Hybrid HTTP400、私有早期启动/会话/512-token 失败全部保留，后者有独立复验通过，不能删除失败史。
- **UNKNOWN**：实际账单、provider TTFT、普遍事实准确性、长期生产可靠性；缺失历史 cache usage 不回填。
- **NOT_RUN**：24 小时真实模型 soak、真实压缩语义对照、其它平台、真实 mutation 中 SIGKILL、自然能力不足触发的 Qwen→云端证明、未获宿主权限的原生 MCP 项。
- **PARTIAL / MANUAL_REQUIRED**：原生 UI 已运行和展示，但所有系统通知场景与真实用户长期主动帮助召回率未完成。

LocalPilot 与 Companion **仍完全模块化**；已测兼容范围可独立升级，非任意版本保证。**真实 Companion→Core 工具任务、故障触发的 Qwen→DeepSeek 咨询、明确配置的标准 Agent 接管均完成**。权限与 UNKNOWN 边界保持，未绕过审批。缓存存在真实复用，收益不稳定且没有 99% 承诺。CLI 已具备独立用户安装、配置、操作、诊断和恢复的实测闭环，按 **受限 RC** 交付；正式成熟度仍受模型质量及长期验收限制。安全模块化制品与授权 main 推送以发布清单和最终远端核验为准。

## 实际发布回执

首次原子推送已成功并通过远端 SHA 核验：main 发行提交 `5dc3661532ea0321664ad491e883f4318b3177d2`，三个模块发行分支同时创建。已从该远端 main 重新克隆并在全新环境安装，三包版本与 pip check 均通过。后续仅以普通快进修正帮助版本显示、补充观察主动开启说明及发布回执；最新 SHA 见远端 main / 本地 release-state.json，不改稳定 tag。

最后一段真实 Core＋Companion 连续监测 **1808.19 秒（30.14 分钟）**；含前两段的分段累计 2927.37 秒（48.79 分钟），不称作连续运行。Core/Companion SQLite integrity_check 均为 ok，稳态尾部及 RSS/日志数据见 service-soak.json。它不是全天候或无泄漏证明。所有本轮测试服务与受管模型已停止，原 Qwen3.8 模型已恢复；系统 AC/电池低电量模式保持关闭。
