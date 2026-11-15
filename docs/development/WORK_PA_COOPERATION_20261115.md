# Work：新候选的本机验收与真实能力对照

以下内容可整体交给本机 Work。代码实现已经在 `codex/pa-cooperation-20261115`，基线是 PR #10 `92ad9a30b9fda43bc185d96c99e5cb0a8ce8ec02`。实际受测代码 SHA、最终 PR 引用和源文件清单以 `docs/evidence/pa-cooperation-20261115/RESULTS.md` / `RESULTS.json` 为准。

---

请继续 LocalPilot 的最后一轮本机工作。先读取 GitHub 当前动态、新分支的验收记录与开发说明，再核对本机真实状态。完成已授权、可执行的工作；资源不足的一项单独记录 BLOCKED，继续其他项。提交实际修复与脱敏证据到独立 Draft PR，保留旧记录。

## 1. 固定代码、实例与材料

- 阅读仓库根与 `desktop/AGENTS.md`，读取本轮 `PA_COOPERATION_20261115.md`、`EVALUATION_CONTINUATION_20261115.md`、`COMPANION_CONTINUATION_20261115.md`、`desktop/docs/development/PA_CONTINUATION_20261115.md`。
- 从远端 `codex/pa-cooperation-20261115` 建新的独立 checkout/worktree，保存准确 HEAD、与记录中受测 SHA 的差异、清洁状态。PR #1、#9、#10 和已有工作树保持可恢复。
- 只读核对 `/Users/perry_guo/Desktop/aic竞赛/LocalPilot-pa-mac-20261114` 的测试 Core、Companion、观察服务、测试 oMLX、VM、Harbor 作业和实际监听端口。区分测试实例与已有外部服务，再选择本轮独立 home、bundle ID 和端口。
- 核实当前磁盘、VM 磁盘、内存、模型/缓存归属与活跃引用。此前约 6.5 GiB 可用、还差约 15 GiB 只是历史观察；重新实测。模型、原任务/UNKNOWN、备份和已开始的评测尝试均保留。目录清理需要既有逐路径授权，尚无授权的只列清单。

## 2. 构建与可审阅产品状态

- 按现有资源准备、构建、签名、归档流程重建四组件 wheel 和完整独立测试 APP，bundle ID 使用 `io.localpilot.desktop.test`。保存 wheel/源码逐文件一致性、39 个真实资源、Python/Node、签名/DMG、架构与资源搬移后的运行结果。
- 运行本机 Rust、Swift、TS/Vite、Vitest 以及适用的既有回归。浏览器合成桥测试单独记录为前端协议证据；APP 首次启动、重开、原生权限与真实任务单独记录。
- 检查拆分后的任务详情、工具收据、子 Agent、结果/diff、设置和模型选择。检查原 Pet 委派与主窗口云端确认。版本页应显示 Channels，架构信息来自实际制品。
- 从统一更新入口执行独立测试 APP 与四组件的成功/失败路径，观察 GUI 退出、助手换包、重开后的维护记录与服务恢复入口。制造可恢复的助手交接失败时，应显示本次错误及原安装收据；旧成功收据不代表本次交接成功。
- 核对原 Session、消息、幂等 key、工具收据、历史模型与 UNKNOWN；恢复过程中已执行操作不重放。日常 APP 的原摘要保存作对照。
- 继续执行 [上一轮 Work 提示词](WORK_PA_COMPLETION_20261115.md) 第 2、3 节的明确序列：已完成 child → 同一 Session 主模型切换 → 重启 → 切回，核对历史 child 的原模型、收据与调用数；旧 Core 仍包含 Channels 时的组合回滚；Test APP 拒绝执行 Daily APP 的历史替换计划。
- 单独复核渠道 SIGINT 后重开与原生 framework Python 身份确认：云端已捕获初始命令行暂时为空导致 `CHANNEL_PROCESS_RECORD_FAILED`，现仅将初次空观测延后到既有就绪检查后确认，参数实际改变仍拒绝。新版本沿用私有 `adapter.error.log` 保存固定阶段/异常类名/errno；本机失败时保留该诊断及脱敏系统证据，不把 Linux 结果或一次复跑通过代称 macOS 已验收。

## 3. 真模型与 PA 链路

- 优先复用已核实归属的现有 Qwen 权重与独立测试服务，记录真实模型路径/revision/量化、服务版本和健康结果。恢复加载前确认内存和磁盘条件。
- 验证 Companion 的即时确认 → 本地主 Agent → 多个子 Agent → 结果通知；验证五档策略、真实本地/云端来源、子任务取消、Shell 取消、UNKNOWN、任务/Session 恢复与原生 SSE 409。API usage 或费用缺项保持 UNKNOWN。
- 另建四档权限任务矩阵：只读、请求批准、工作区写入、完全权限，逐档验证文件、Shell 与子任务。完全权限下不重复同义审批；操作系统/TCC 授权及既有云端出站范围仍按实际配置核对。五档模型来源测试不替代四档权限测试。
- 用专门授权的 Codex 可见历史与会议转录测试来源问答；检查模型旧回答仍是未核验文本。撤销/停用其中一个来源后，该来源及派生任务摘要停止参与检索；原任务与收据仍在，新提问不复用含失效来源的自动 Session。
- 真实会议分别验证 mic、system、both。检查最终分段、时间、原生权限、静音/无语音、helper 异常退出与停止回执。连续多段后，先前观察 ID 和已审阅样本仍有效，新增片段按实际增量入库。
- 关闭 Core、保留 Companion 时，GUI 仍能查询并停止会议；关闭设置后停止入口仍可见。结构化错误显示状态待确认，starting 只显示正在启动。
- 用真实早晚、勿扰、静音、完全退出重开、系统睡眠唤醒检验问候时机与去重。未测试的时段不从晨间结果推断。

## 4. 人工样本和候选 adapter

- 在主界面和 Pet 入口打开实际回答的审阅视图，检查原问题/回答/来源；人工编辑并保存样本，验证再次打开、删除与导出。来源撤销、过期或被保留策略清理后，原样本不再进入导出。
- 按 `companion/model/finetune.py` 与 Companion 续作说明，先生成可审阅训练计划，使用已固定 `mlx-lm==0.31.3` 和本地权重执行小规模 LoRA。记录数据来源、按来源分组划分的 train/valid、数据与配置摘要、命令、stdout/stderr、失败与产物。
- 使用独立候选配置中的 `model_adapter_path` 显式加载该次完成产物；核对 run.json、base 模型、adapter 文件与实际模型身份。默认产品配置保持原样，独立比较基础模型和候选模型。
- 比较事实正确性、来源引用、拒答/无依据回答、延迟和内存。训练完成不代表能力提高；真实推理未完成时记录 NOT_RUN。本轮选择 LoRA；现有 `full` 入口仅支持固定 MLX-LM 的 Transformer 层 dense 训练，不包含 embedding/head，不得称为全模型所有参数训练。强化学习执行器仍为 NOT_IMPLEMENTED，不属于已经写好、只待本机测试的功能；不能用 LoRA 结果代称。

## 5. KV 与 Intel

- 同一真实固定提示、工具 schema 和 Skills 集，测冷/热首 token、模型卸载重载、服务重启、Skill 摘要变化后的计数与失效。记录后端真实缓存证据。受管 50 GiB 是上限，不是本机已经具备的空间或永不失效承诺。
- 有 Intel Mac 时，用真实 x86_64 Python、Node、wheel 与审阅后的目标锁构建独立 APP，并连接本机 CPU OpenAI 兼容服务完成实际任务。记录无 MPS/MLX 的功能与性能；没有机器或合格资源时保留明确 NOT_RUN。

## 6. 公共对照

- 旧 534 项队列保留原源码 `1c06e97`、已开始尝试、1 PASS / 3 FAIL / 13 ERROR 和其余未完成分母。仅在资源条件成立且原配置不变时按既有 resume 协议恢复。
- 新候选用新的 study ID 和固定源码。按照 `EVALUATION_CONTINUATION_20261115.md` 配置 `orchestration="multi-agent"`、子任务限额及同模型总预算，先完成真实 tokenizer/model 资格与独立 smoke，再冻结正式任务集。
- 使用固定 Harbor `ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4`、原始公开任务/verifier 和同总预算参考适配器。每个 trial 保留父子事件、`model-budget.jsonl`、`localpilot-orchestration.json`、实际容器命令与产物。推理只有一个共享槽，工具执行可以并行。
- 报告 PASS/FAIL/ERROR/NOT_RUN、完整分母、真实委派数、用量与资格审计。预算耗尽仍是实际失败；tokenizer、内存、未结算取消或缺失 usage 不能取得对照资格。完整结果出来前不发布排名或“不弱于主流 Agent”。

## 7. 最终交付

输出准确 SHA、受测 APP 与 wheel 哈希、逐项状态、命令/版本/时间、原始日志位置、脱敏公开证据与剩余阻塞。任何新发现先最小修复，再跑相关真实回归；保留首次失败。保持 Draft，不合并、不发布 Release、不替换日常 APP、不提交比赛表单或对外消息。

---

这份提示词要求完成实际原生/模型验收，不要求重写已有架构。云端证据和 Mac 证据分别注明平台与执行对象。
