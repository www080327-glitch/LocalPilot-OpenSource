# 新候选本机验收与剩余材料交接（2026-11-15）

以下提示词用于本机 Work。新候选分支为 `codex/pa-completion-20261115`，叠加在 Draft PR #9 的 `0a7fdff36f45a471130293b508b5d008f40cecf9` 上。不要用 PR #9 的旧 APP `d2b2fae` 的通过结果替代新源码的结果，也不要把新的 Agent 代码放进旧的冻结评测队列。

完整实现说明：[PA 产品补齐](PA_COMPLETION_20261115.md)、[Desktop / Suite 新入口](../../desktop/docs/development/PA_PRODUCT_COMPLETION_20261115.md)、[Companion 来源、会议与后训练](COMPANION_PA_COMPLETION_20261115.md)、[外部评估协议](EVALUATION_COMPLETION_20261115.md)。精确测试结果以本轮 evidence 为准。

## 可直接交给 Work 的提示词

你负责继续 LocalPilot 的本机验收，直接执行已获授权的工作，不停留在方案。先读取 GitHub 最新 PR #1、PR #9 与 `codex/pa-completion-20261115` 对应 Draft PR，以及本文件、仓库 AGENTS.md、desktop/AGENTS.md 和本轮 evidence。记录实际 Git SHA、dirty 状态、现有服务和所有制品身份；如果远端后来又推进了，先理解差异，不能覆盖正在进行的工作。

旧本机工作树为 `/Users/perry_guo/Desktop/aic竞赛/LocalPilot-pa-mac-20261114`，旧验收文件是 `docs/evidence/nationals-20261115-completion/PROGRESS_20261115_065014.md`。保留该工作树、旧 APP、模型、原始日志、20 个历史 Session、179 条消息、56 份收据和全部失败。为新候选创建独立 checkout 和新的 evidence 目录。只使用 `io.localpilot.desktop.test` 与独立测试数据。没有合并、发布 Release、替换日常 APP、提交 AIC 表单或向外发送消息的任务。

### 1. 先完成本机才能完成的编译与新 APP

按现有流程执行前端构建、Rust 编译/有意义的测试和格式检查。编译新增的 `companion/observers/MeetingTranscriber.swift`：使用 Companion 提供的 `meeting-build` 入口及其实际 `--help`，不要另造未受管 helper。这轮云端没有 cargo、Swift/macOS SDK，不能把代码审查当作编译通过。如出现真实编译或入口问题，在原有结构内修复并记录。

在新的版本化构建目录，从新源码重新构建四个 wheel。Core 不再拥有 `localpilot_channels` 包、其 console entry point 或渠道资源；Channels 独立 wheel 是唯一拥有者。确认 Companion 的 Swift 源文件、四个 wheel 的源码与许可证都入包；沿用已核验的 Python / Node / watchdog / 依赖材料，不复用同版本但旧源码的组件 wheel。运行 `check-bundled-backends.py`，再走 `build-macos.sh` 的测试身份构建和归档。记录 wheel、APP、签名、ZIP 解压摘要与 DMG 的实际结果。

### 2. 验收新维护事务及历史保持

从新 GUI 的“统一升级与回滚”入口，审阅 GUI + Core + Companion + Suite + Channels 的具体计划。保留每个当前组件的准确回滚 wheel；旧 Core 的 RECORD 同时拥有 Channels 时，必须同时提供 Channels 的目标和回滚 wheel。不要省略这个兼容条件。

先观察活动任务与进程，明确停止测试服务后执行。检查 GUI 退出、独立 Suite helper 等待、换包、重开、显示回执；维护重开后不应自动恢复 Core 或重连消息平台。然后通过现有按钮显式恢复。比较升级前后 Session、messages、children、工具收据、UNKNOWN、幂等键与历史 journal 前缀，禁止重放任务。

新组合事务至少覆盖：Channels 独立运行目录安装失败、组件导入失败、旧 Core 仍含 Channels 的回滚、GUI 提前退出时 helper 失败回执、Test APP 不能执行 Daily APP 的历史替换计划。失败注入使用临时受控材料，不损坏日常安装。旧三组件 pip 回滚和四种 APP 失败无需为了增加数量再完整重跑；检查新组合带来的具体风险即可。

### 3. 真实多模型协作、换模、取消与恢复

使用已经存在、明确允许使用的模型和端点。可用 Qwen revision 及 endpoint 以本机实际探测为准，不自动改动外部 oMLX。新增协作 Agent 选择主模型与多个已配置伙伴，验证新 route 的 async 策略、旧 route 保持原同步契约、服务重启后旧 Session 仍可恢复。不要通过清空数据库修复指纹不匹配。

在真实任务中观察即时确认、子 Agent 状态及最终回报；覆盖五档来源策略，记录真实本地/云请求和 token 占比，usage 不全就保留 UNKNOWN。五档不是固定比例。用实际文件成果验证任务；仅收到“完成”文字不算成功。

重点检查已完成 child 后主模型切换、再重启、再切回；历史 child 必须仍标识原模型，收据和调用数不能增长。保留历史 route 配置。只在兼容的空闲边界换模；忙碌、待批准、UNKNOWN 和不同工具/工作区契约明确拒绝是预期行为。需要迁移 async 配置或私有路径时，使用文档中的精确旧指纹与 Session 清单，不能直接忽略 hash。

对新增真实协作流程验收 Shell 与子 Agent 取消、UNKNOWN 不重放、任务和 Session 恢复、原生 SSE 409 修复全链路。可复用旧合格材料，仅补新候选受影响部分。真实模型或账号不可用的项单列 NOT_RUN，不改成脚本模型来获得能力 PASS。

### 4. PA 来源和实时会议

用明确允许观察的 Codex 可见用户/助手记录与会议文本，通过原生选择入口注册来源。验证持续同步、时间范围、覆盖不足、文件修改/删除、停用、撤销和重开；提问时不重复提供答案内容，看模型能否根据实际来源回答并给出来源、时间和限制。助手自己的旧回答属于未独立核验的报告，不能变成外部事实；隐藏推理不是可见对话记录。私人原文和导出的训练数据只保留本机，公开记录脱敏。

对实时会议分别检查 microphone / system / both。确认 Speech、麦克风和系统音轨授权归属，包括直接启动 helper bundle 内二进制时 macOS 实际把权限授给谁；不绕过 TCC。设备上识别不可用时应明确失败，不能自动转云端。

至少持续 110 秒跨两次片段轮换；在 49–55 秒间停止一次；长静音后停止一次。核对最终文字、mic/system 来源、捕获结束时间与 ASR 排空时间，停止后不再采集。检查关闭设置仍有全局状态/停止条；暂停观察、停用或撤销当前会议来源、清空记忆、退出服务都会结束拥有的采集；重启状态应为 interrupted，不能自动恢复录音。拒绝授权、音轨失败、断联未知和 final 超时要保留真实失败，不能降成单路后声称两路成功。不要保存原始音视频或屏幕帧。

晨间勿扰、静音和去重已经有旧原生证据；补新候选的晚间与真实系统睡眠/唤醒，不靠改时钟伪装。检查轻量问候无需加载大模型，复杂请求默认交给本地 Super Agent。

### 5. 缓存、Intel 和后训练

固定同一模型 revision、模板、系统提示和 Skills 摘要，测冷/热 TTFT、提供方缓存 token、模型卸载再加载、服务重启后的结果。区别磁盘持久前缀与进程内缓存；50 GiB 是受管目录准入，不是凭空可用空间或“永不失效”。需要释放空间时先列归属明确的候选及影响，不能删模型、未完成评测容器、用户数据或失败日志。

如有真实 Intel Mac，使用原生 x86_64 Python、实际 x86_64/universal2 wheel 生成目标锁，走原生构建、安装、重开及本机 CPU OpenAI 兼容服务推理。不要把 arm64 wheel 改名，也不要假造 SHA256。没有 Intel 或合格依赖时保留 NOT_RUN，列出具体缺少项；Intel 兼容代码不等于 MLX 训练可在 Intel 上执行。

后训练只使用用户显式审阅的样本，通过来源分组划分训练/验证集合，保存 manifest。先运行 Companion 的 training-* 帮助与计划入口；如本机有合适基座、足够存储和预算，再显式运行固定 `mlx-lm==0.31.3` 的 LoRA。不要自动下载权重、调用云训练或替换产品模型；`full` 模式不等于所有参数均解冻。不具备数据和资源就记 BLOCKED，不能宣称训练增益。新模型需要独立验证集及同任务基准的实际改善，活动观察不能直接充当正确标签。

### 6. 旧 534 队列与新候选的公开评估

先读 `EVALUATION_COMPLETION_20261115.md`，实际检查磁盘、专用 VM、Docker daemon 与停止中的 Harbor 进程。旧记录约 6.5 GiB 空闲、尚缺约 15 GiB 只是上次观测，重新检查，不能当成现在的资源保证。

旧正式 study 冻结在 `1c06e97`，当前已发生的 1 PASS / 3 FAIL / 13 ERROR 必须保留，517 项没有最终结果。若原进程仍安全暂停且资源充足，使用文档中的原进程继续机制；原进程已不存在而有未结算尝试时，保留 BLOCKED，不能删 trial 后自动重做。不要直接调用会删未完成目录的上游 resume，不选择性重试失败。

本轮新代码必须另建 study ID，冻结实际源码、官方题库/Harbor revision、模型/模板、共享请求及 token 预算、超时、机器/容器资源。相同公开题目、相同资源限制和参考 Agent 完整运行后，再看所有分母及比较资格；预算不足、usage 缺失或配置不等价就不下非劣结论。现有 Harbor LocalPilot adapter 测容器 Shell 主 Agent，禁用子 Agent；这只能作为该能力子集的公开测试，不是完整 Companion、Super Agent 或 Computer Use 的排名。不要称作 AA 官方成绩。

### 7. 交付记录

每项输出 PASS / FAIL / ERROR / BLOCKED / NOT_RUN、准确命令、源码/模型/依赖版本、实际材料路径、失败日志和摘要。区分受测代码 SHA 与后续仅追加文档的 HEAD。原始私有证据保留本机，公开部分脱敏推到当前新 Draft PR；不覆盖 PR #1/#9 的记录，不合并、不发布。

历史 benchmark 还有 12 个门控测试文件引用未公开的实现及夹具，另有旧 Release 资产来源待核验。搜索本机已授权材料和公开历史；找不到就列出缺失的原件、对应 commit/哈希和授权，不从测试断言反造实现、不删测试来消除 SKIP。比赛评分表和落地表单保留为独立交付事项，提交前需要完整具体材料与明确授权。
