# LocalPilot V5 Agent Engine — 工程交付与验收

2026-10-23，Asia/Shanghai。**交付 `5.0.0a1` 候选实现；保持 Legacy 默认。**
建议进入 DeepSeek 文本/工具范围的下一阶段默认引擎验收，目前不切换生产默认。
本轮实现、真实 API 对照、故障测试和封装均已完成；长期可靠性和总体任务质量
不因本报告或普通回归通过而获得生产级资格。

## 1. 来源、分支与边界

- 项目原目录仍在 `LocalPilot`，其 HEAD 为 `5e79fb2e`，未覆盖未提交/未跟踪内容。
- 实际发布 Core RC2 基线为 `1e3b3feb62a1cb5a9b8a049ab7953b75a4c45a3c`。
  前轮 DSH 优化提交 `41e81141` 已包含该发布基线，本轮从其建立独立 worktree。
- 分支：`codex/localpilot-v5-agent-engine-20261022`；worktree：
  `$HOME/Desktop/aic竞赛/LocalPilot-v5-agent-engine`。
- DSH 在获取时核对官方远端 HEAD 并固定为
  `687f282e8625c6b8d11ff58211a90524be2e4317`，版本 0.2.1-rc.2。
  后续实验继续使用此固定源码，没有在实验途中更新上游。
- 完整引擎修复提交：`e54fdb64`，内部策略 revision=2。
  最终证据/封装提交单独保存，交付时的 Git HEAD 是其精确标识。
- 没有 push、更新稳定 tag、安装到现有服务、修改 Companion/GUI 产品代码或扩大
  Native Computer Use。本轮及低电量续行没有启动本地模型或下载权重。

官方参考：[固定源码](https://github.com/deepseek-ai/deepseek-harness/tree/687f282e8625c6b8d11ff58211a90524be2e4317)。
模块级分析见 [DSH → LocalPilot 矩阵](LOCALPILOT_V5_DSH_MATRIX.md)，设计见
[V5 架构](LOCALPILOT_V5_ARCHITECTURE.md)，接入与回滚见
[迁移说明](LOCALPILOT_V5_MIGRATION.md)。

## 2. 实际实现

`agent/engine_v5.py` 是独立于供应商的内部执行策略，接入原 AgentSession。
它提供稳定指令、直接执行优先、受限完成反馈和无效调用预算。TaskService、
SQLite、Registry、Permission Gateway、审批、持久意图、收据和 Verification
仍拥有原有权威。生产包没有增加 DSH Runtime、Session store 或 Node 依赖。

DSH 的 pre-step → request → stream assembler → tool execution → next-step
路径，以及无工具输出后继续接纳新上下文的机制，是本轮的主要执行路径参考。
LocalPilot 将受限的 trusted completion feedback 接回自己的状态机；Child 收集、
预算、取消、错误后已完成收据的保留和跨进程围栏继续使用已有实现。

`agent/deepseek_native.py` 实现公开 `/anthropic/v1/messages` 文本/工具协议：
thinking/text/tool_use/tool_result、output_config.effort、流式参数片段、block
生命周期、message_stop、usage 合并、非流式请求，以及源模型/完整消息绑定的
Thinking 签名续传。签名来自服务商响应；不生成官方身份、资格或 DSH 身份头。
历史坏参数只在 wire 投影中按上游规则表示为对象；原参数和拒绝记录保留，
没有把它们修成新的可执行调用。

Messages input_tokens 与 cache-read/cache-write 分开报告；生产适配器将总输入
正规化为三者之和，并保留原始 usage。缺失计数保持 UNKNOWN。Thinking 的数值
budget_tokens 在当前公开兼容协议中被忽略，本轮使用明确的 none/low/high/max
effort，不虚构数值 reasoning budget。普通 OpenAI-compatible 和本地 Provider
不会收到 native_replay 或私有 reasoning 字段。

协议范围限于当前 LocalPilot 的文本/工具 Message 契约。Files、图像、server
tools、tool_addition/tool_removal beta 和插件/Session-log 扩展未实现；不宣称
完整 Anthropic/DSH 所有能力兼容。依据：
[公开 Messages 兼容协议](https://api-docs.deepseek.com/guides/anthropic_api/)。

`agent/context_v5.py` 构造模型请求投影：稳定 system/schema → canonical 历史 →
当前 Host 状态。它不累积每轮全量状态快照，不改写持久历史。原任务、修订、
审批、UNKNOWN、未完成副作用、Child/Goal、版本证据及预算继续保留；历史省略
明确记录数量和哈希。压缩保持完整调用/结果组。最终请求可保留近期观察正文，
并按剩余交付预算分配历史空间，避免第一次交付耗尽第二次交付的预算。

工具错误仅在未投递时允许有界纠正，要求 fresh call ID。相同无效参数两次即
停止该修复循环；整体无效调用上限三次。经 Gateway 授权、由默认 read_file
观察到的“不存在”单独记录为失败的无正文/无版本观察；它不再混入副作用 UNKNOWN。
扩展工具不能凭 FileNotFoundError 获得该资格，已有不确定 mutation 不会被清除。

Execution、Delivery、Verification、Engineering 保持独立。没有验收器时 API
仍可结束普通对话，但 execution=settled、verification=not_run、engineering=
unverified；不能据 API completed 推导严格成功。有验收器时，文件就绪与最终
交付分别检查，模型文字不清除失败、审批、UNKNOWN 或未收集 Child。

## 3. 三路真实对照及方法限制

开发集 4 项、冻结评估集 8 项，均在开发实测前保存 fixture/oracle 哈希。
评估覆盖普通工具、三文件修改、边界 Bug、七步有序读取、错误恢复、跨文件
鉴权/缓存审查、双文件重构和最终交付。输出截断、真实进程恢复、压缩另外测试。
8 类任务分别运行 none/high，属于两组重复设置，不能说成 16 类独立任务。

A 为官方原生 DSH headless + 官方 API-key adapter；B 从发布 RC2 commit 单独
导出并在独立 PYTHONPATH 进程运行；C 为 LocalPilot V5。模型请求均为
deepseek-flash，输出上限 2048、模型请求上限 12、外层任务期限 180 秒。
每个任务轮换三路先后次序。gold 文件/哈希不进入模型提示。严格验收要求文件
全集、规定读取轨迹、独立 DELIVERED 行、终止状态同时通过。

条件仍有区别：DSH 使用自己的 prompt/fs 工具、沙箱和 CLI 启动；LP 使用
Gateway/收据/Host 验收器，并保留 UTF-8 byte 准入和最终交付预留。LP 有 24 次
工具预算，原生没有完全等价的工具计数门；原生禁用 shell/web/delegation，LP
仍暴露部分已有协调工具但任务禁止委派。V5 的执行检查可给予不含答案的失败
反馈，原生验收在外部执行。DSH e2e 包含进程启动，LP 从已启动服务提交计时。
这些结果不能作为严格因果归因或总体模型排名。

### 冻结评估：none

| 路径 | Strict | 请求/工具 | Input / Output | 缓存命中 | e2e 合计(s) | 估计费用上界 USD | 每严格成功任务费用上界 | False completed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 原生 DSH | 7/8 | 35/47 | 95,881 / 3,705 | 89.04% | 49.51 | 0.008110 | 0.001159 | 1 |
| RC2 Legacy | 8/8 | 42/48 | 204,461 / 3,172 | 56.59% | 42.68 | 0.031125 | 0.003891 | 0 |
| V5 policy rev1 | 8/8 | 41/54 | 166,482 / 4,604 | 51.44% | 46.36 | 0.030294 | 0.003787 | 0 |

### 冻结评估：high

| 路径 | Strict | 请求/工具 | Input / Output | 缓存命中 | e2e 合计(s) | 估计费用上界 USD | 每严格成功任务费用上界 | False completed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 原生 DSH | 8/8 | 41/55 | 119,700 / 6,038 | 91.11% | 67.78 | 0.011093 | 0.001387 | 0 |
| RC2 Legacy | 7/8 | 41/48 | 200,337 / 4,947 | 56.35% | 49.79 | 0.032846 | 0.004692 | 0 |
| V5 policy rev1 | 8/8 | 40/55 | 169,076 / 7,351 | 52.99% | 61.72 | 0.033202 | 0.004150 | 0 |

正常评估所有上述工具调用均通过实际声明 Schema 的 JSON Schema 校验。
high 的 RC2 服务商报告 reasoning_tokens=1,595；Messages 未报告可分离的
reasoning token 明细，保持 UNKNOWN，而非填零。详细 TTFT、逐请求 usage、
工具数、失败与费用区间见 `FINAL_METRICS.json`。

普通设置下 V5 总输入比 RC2 少 18.6%，估计总费用约少 2.7%，e2e 慢约 8.6%；
high 总输入少约 15.6%，总费用约高 1.1%，e2e 慢约 24.0%。high 每成功任务
费用较低与其 8/8、RC2 7/8 有关。样本不足以证明稳定或显著的总体成功率提升。
原生 DSH 在这些任务的总输入与估计费用仍明显更低。

之后独立的大历史交付控制发现预留预算问题，修为 policy revision=2。最终候选
在同一评估集 none 确认轮为 8/8：170,428 input、3,796 output、43 请求、51 工具、
48.38s、费用上界约 $0.027685。它是确认轮，不能充当新增独立样本或与原轮作
缓存/随机性无关的因果比较。rev2 的 high 全集未重跑；原 high 的八条 V5 路径
均未进入 final-only 分支。交付预算变更另有前后故障控制及最终全量回归。

## 4. Prompt Cache 与压缩

同一公开合成文件，每轮更换 marker，要求重新用工具读取；每路 8 轮、输出 cap
512、每轮请求上限 6。原生每轮从持久 Session 重启进程；LP 第 5 轮重建服务。
三路使用相同正文，没有为 V5 增加缓存专用静态前缀。以下为 context v1/policy
rev1 的实测；rev2 只调整 final-only 的预算分配。

| 普通多轮 | Strict | 总输入 | Hit / Miss | 命中率 | 请求 | 费用上界 USD |
|---|---:|---:|---:|---:|---:|---:|
| 原生 DSH | 8/8 | 93,463 | 87,424 / 6,039 | 93.54% | 16 | 0.003507 |
| RC2 | 7/8 | 190,674 | 41,984 / 148,690 | 22.02% | 16 | 0.045327 |
| V5 | 8/8 | 178,391 | 144,128 / 34,263 | 80.79% | 16 | 0.011614 |

V5 总输入比 RC2 少约 6.4%，估计费用少约 74.4%，并保持本组 8/8；它还没有
达到原生 DSH 在普通多轮测试的输入规模与成本。

| 压缩压力测试 | Strict | 总输入 | 缓存命中 | 请求 | LP ContextCompacted | 费用上界 USD |
|---|---:|---:|---:|---:|---:|---:|
| 原生 DSH | 8/8 | 110,221 | 91.86% | 23 | 不适用/该轮 canonical 计数未知 | 0.008648 |
| RC2 | 7/8 | 156,595 | 26.81% | 16 | 7 | 0.035119 |
| V5 | 8/8 | 147,130 | 92.30% | 16 | 6 | 0.004691 |

LP context admission 为 65,536 bytes；DSH 是独立 token meter，压力轮将
thresholdRatio 设为 0.005、retainTokens=1200、summary cap=512。两种阈值不能
当作同一 token 窗口。所有额外摘要调用计入输入、输出和费用，不只报命中率。

另做 4 轮、thresholdRatio=0.003 的 canonical 诊断并保存 `.jsonl.zstd` 日志：
原生 4/4，观察到 1 次工具结果 prune、7 次摘要尝试、0 次摘要提交；失败包括
摘要没有变小和触及 cap。上游保留原历史并继续任务。该阈值远低于默认 0.8，
不能推广为默认 DSH 的失败率。早期分析把 marker 中的单词 compaction 误计为
原生压缩事件；最终指标不使用该计数，原始派生文件仍保留。

费用使用服务商真实 usage × [2026-10-22 核对的公开费率](https://api-docs.deepseek.com/quick_start/pricing/)
估计：Flash 每百万 hit/miss/output tokens 的离峰价为 $0.003/$0.15/$0.6，
高峰价为其两倍。表中为高峰估计上界，JSON 同时保存两端区间。实际账单、
余额抵扣和特定客户端可能的待遇为 UNKNOWN。Reasoning 已包含在 output 中，
不重复计费；未取得 usage 的尝试不能被当成免费请求。

## 5. 故障与可靠性证据

- 最终 rev2 真实进程故障控制 19/19：进程 SIGKILL/退出、意图与收据提交边界、
  审批等待、Parent/Child、终止前后恢复。模型为脚本，接收端、线程、SQLite 和
  进程故障是真实的；未观察到 receiver mutation replay。
- 真实 DeepSeek 的 Legacy/V5 分别验证收据提交后 SIGKILL 恢复：均完成两个
  独立写入，各一次；效果发生但收据未提交的 UNKNOWN 均隔离并拒绝继续/重放。
  此恢复 Legacy 使用候选源码中关闭 V5 的路径；主任务比较才是隔离发布 RC2。
- 原生 DSH 在一个工具结果后 SIGKILL，恢复同一持久 Session 并用显式继续 turn
  完成任务；观测到 a/b 各一次写入提案。它没有等价的 LP 副作用收据，不能据此
  宣称相同的 UNKNOWN 或 exactly-once 保证。
- 三路真实输出 cap=64、请求 cap=3 的截断故障均没有执行不完整写入，工作区只
  保留原文件；任务未被标为成功。原始 partial JSON、usage、退出与错误保留。
- 另有 API/Gateway/SQLite/SSE、native 签名来源和跨模型/跨出站范围控制。
  V5 本地/云端 Child、审批、私有 reasoning 隔离与新 ID 防重放为脚本模型控制；
  不能把这些表述为本轮 MLX/vLLM 真实协同验收。

## 6. 回归、许可证与封装

最终全量 **1,062 tests，0 failures / 0 errors，42 optional skips**。
strict **11/11**；stabilization **51/51 controls、36 ablations**。
这些是工程契约控制，不是 Agent 模型能力提高的证明。固定 DSH 源码的 Adapter、
stream 和 tool-order 选定上游测试 **97/97**；没有运行完整上游测试集。

Python 原生协议适配保留 DeepSeek MIT 版权、LICENSE/NOTICE，见
`third_party/deepseek-harness/`。没有新增生产依赖；既有 psutil 依赖保留。上游
Node 依赖闭包含非 MIT/未知条目，只有独立参考运行使用它们，未装入产品包。
候选 wheel 带上述许可证和 V5 文档；包检查与 smoke 结果见证据目录的
`package-validation.json`。没有覆盖稳定发行包或安装到当前服务。

## 7. FAIL / UNKNOWN / NOT_RUN

**保留的失败**：开发普通轮 V5 的已知缺失读取被 UNKNOWN 阻塞，已修复；确认轮
另一次跳过指定 missing read 而仅做 file_info，按轨迹判为失败；DSH 普通评估
错误恢复也漏指定读取；RC2 high 长任务文件正确，但 token_reserve 后未回读与
交付。没有把这些变成成功。V5 的无验收器 API 状态回归、absence evidence 字段
缺失和大历史交付预算控制的开发失败均保留，最终已修复并重测。

第一次缓存驱动在重启前后注入不同 verifier 配置，被正确的持久配置围栏拒绝；
修正测试 scaffold 后重跑，失败目录不覆盖。原生压力摘要失败和所有诊断额外
调用也保留。完整逐任务失败索引见 `FINAL_METRICS.json`，原始资料见归档。

**UNKNOWN**：实际账单/未报告 usage 成本、Messages reasoning token 明细、不可变
模型权重 revision、原生与 LP 等价的副作用收据保证、未运行的专属扩展服务器
行为和收益。

**NOT_RUN / 未资格化**：24h 运行、生产负载/多平台、复杂真实用户仓库泛化、
新引擎真实 MLX/vLLM 协同、V5 Computer Use、rev2 high 全集与 high 多轮缓存专项、
完整上游测试。Files/视觉/服务器工具/动态工具 beta 不在本轮 Provider 能力声明。
没有上传额外原始用户会话、Companion 观察、用户记忆或插件清单。

## 8. 准入、提交与合并建议

`SCOPED_ENGINE_CANDIDATE = YES`：真实公开 Messages 文本/工具协议已有独立价值，
API/安全/持久化控制和范围内真实任务通过，支持进入下一阶段默认引擎验收。
`DEFAULT_PROMOTION_GO = NO`：样本、任务规模、本地协同与长期资格尚不足，且
部分真实场景延迟/总费用没有改善。继续保留 Legacy 默认和完整回滚路径。

阶段提交：A `53773a99`；B `e2389cb6`；C `12aab0a5`；D `312af8e1`；冻结基准
`77a5d347`；开发修复 `a63e1106`、`ecfbb50f`、`36de9235`；恢复诊断 `fd457426`；
最终执行预算修复 `e54fdb64`。后续证据/包封存提交见 Git log。

建议向**以发布 Core RC2 `1e3b3feb` 为祖先的集成分支**合入完整候选，先审阅
从该发布基线起的差异。原项目目录 `5e79fb2e` 与该发布源码线没有 Git merge-base；
不要直接对旧目录使用 allow-unrelated-histories、reset 或覆盖式复制。先保留其
工作树和稳定发行，再独立进行版本整合。本轮不自动合并、不 push。

复现入口：`benchmarks.v5_campaign`、`v5_cache`、`v5_faults`、`v5_real_faults`、
`v5_truncation` 与 `v5_summary`。模型基准会产生新 API 用量，输出目录必须全新。
基准环境为 Python 3.14/jsonschema 和已锁定的原生 DSH Node 依赖；这些不是产品
依赖。最终证据入口为 `docs/evidence/v5-agent-engine-20261022/README.md`。
