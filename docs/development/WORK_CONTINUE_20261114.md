# 给本机 Work 的完整交接提示词

以下可直接交给拥有用户 Mac 环境的 Work。它包含继续实现与实测，不只是阅读任务。

---

继续 LocalPilot 的 AIC 国赛验收与 PA 开发。请直接完成已授权工作，不要停在计划。先阅读真实 GitHub 状态与下列文档，以实际 HEAD 为准，不能把旧报告的 PASS 移植到新构建。

## 1. 接收源码并保护已有工作

- 公开仓库：`https://github.com/www080327-glitch/LocalPilot-OpenSource`。
- 本轮分支：`codex/pa-readiness-20261114`，基于 Draft PR #1 的 `94e0e6ff2c8da974d20530d7a0faa50844d052f4`，预期以独立 Draft PR 交付。先 fetch，核对最新分支 HEAD、PR 状态、远端后续改动，再建立独立 worktree。不要重置用户脏树、覆写他人提交或将依赖 PR 的内容重复当作本轮新改动。
- 用户上轮本机目录为桌面 `aic竞赛/LocalPilot-nationals-retest-20261114`；先核实当前存在的位置。旧的 `docs/evidence/nationals-20261114-head-retest/RESULTS.md`、失败日志和 `desktop/release/test-v5.0.1-rc.7/20261114-163712-17209` 均为保留的历史证据。
- 先读根/目录 AGENTS（尤其 `desktop/AGENTS.md`）、本轮 `PA_READINESS_20261114.md`、`COMPANION_PA_20261114.md`、`MAC_PORTABILITY_20261114.md`、`SESSION_MODEL_SWITCH_20261114.md`、`PUBLIC_AGENT_EVALUATION_20261114.md` 与验收记录。不要引入仓库未使用的新工作流。
- 上轮隔离 Core/Companion 可能仍运行，另有用户原本的 oMLX 服务。先只读识别 PID、启动路径、端口、拥有者、配置和磁盘。只管理本轮明确拥有的测试进程，不能按进程名批量杀掉 oMLX/Python/Node。
- 沿用 `io.localpilot.desktop.test` / `LocalPilot Test`，独立服务 HOME、数据库、日志、端口、工作目录。日常 APP、日常配置、外部 oMLX 不作为安装或故障注入目标。禁止为腾空间删除未核实归属的权重、历史 APP、回滚包或私人记录。
- 已授权：隔离目录内改代码、测试、构建/安装测试 APP、测试槽回滚、提交和推送 Draft PR。无需重复询问这些事项。合并、Release、正式发布、替换日常 APP、发送邮件/提交比赛或落地表单仍需单独明确指令。

## 2. 先确认这轮已改了什么

已完成源码：服务可配置共享异步子代理调度器；V5 分派提示；Skills 用途目录与按需正文；完全权限复用既有云端外发授权；Companion 确定性问候/活动摘录/accepted反馈/终态通知/真实HTTP409恢复；分层只读模型健康与模型库入口；兼容契约内同 Session 换模；独立测试安装身份及替换后失败回滚；Intel 硬件识别和 CPU HTTP 接入回退；公开基准冻结/Harbor 启动/全分母审计工具。

这些是工程实现。云端测试模型为脚本 fixture，没有真实模型质量结论。真实 macOS/Swift/Rust/安装器/Intel 与正式榜单分数仍须你完成。

**升级限制不得掩盖：**已选 Skill 的旧 Session schema 指纹与新目录不同；修改 async_policy 也会改变恢复契约，旧库可能拒绝启动。先保留旧库，使用新隔离服务跑新特性。若需要迁移，只实现精确、可审查、保持收据的迁移；禁止改历史哈希、删除数据库或全局放松恢复校验。GUI换模也明确拒绝忙碌、关闭、UNKNOWN、不同工作区/工具契约、仍保留子代理 runtime 的 Session。

## 3. 在最终代码快照上复测并修复

使用现有项目依赖和运行器；保存命令、退出码、Git SHA/dirty 状态、Python/Node/Rust/macOS/架构、所有 skip 理由。以 `scripts/run_core_qualification.py --report <新证据目录>/python.json` 跑 Core 全量；Companion 按其现有 unittest 发现入口独立跑。测试夹具依赖与生产依赖分开，不使用系统中碰巧存在的不兼容 MCP SDK。

前端跑已有 Vitest、TypeScript/Vite 和 Playwright。云端曾因浏览器缺失、系统 Chromium 套接字被环境禁止、headless-shell 下载损坏而失败启动；这些不等于产品 UI 通过。新测模型切换失败不丢草稿/消息、成功保持Session ID、当前模型与历史任务模型分别显示、Pet accepted 不污染答案、只读连接检查不显示“推理已验证”、Intel 无 MLX 安装引导。运行现有 Rust 测试与原生构建，记录是否使用真实后端资源；空资源目录通过不算完整打包资格。

上轮缺失公开 benchmarks 包导致的跳过必须继续明确列出；不得造同名空模块消除 skip。Companion BM25 原始诊断曾出现约0.111秒超出0.1秒门槛；单元测试已去掉负载相关断言，benchmark门槛未改。独立重测并报告，不把单测绿色称为性能过线。

## 4. 找到可用真实模型，避免盲目下载

上轮磁盘仅约7 GiB、推荐模型约15 GB。重新读取当前真实余量。优先查已安装/已加载模型和现有服务的只读发现接口，记录实际 model ID、架构、量化、revision、context、内存。只在不会重启、卸载或修改外部服务的条件下用公开测试夹具验证已有模型。不要用 `ready`、`/models` 列出或一次文本回答代替工具能力。

如果本地没有满足条件的模型，给出确切缺口、候选体积和所需空间。不要自动下载大权重或删除文件。已配置云端凭据只从原有私有机制读取，不输出/提交；未授权外发的私人活动不发云端。缺少必要凭据或磁盘时，先完成不受阻项目，再汇总需要用户提供的一项具体信息。

以实际可用的本地与云端模型分别验证：普通文本、工具调用、一个真实文件任务、取消、恢复、上下文接近限制时的行为。先做小而完整的闭环，再扩大样本。记录错误而非改结果标签。

## 5. 原生产品验收矩阵

1. **四档权限：**用隔离 fixture 工作区和一个独立外部 fixture 目录验证只读、请求批准、工作区写入、完全权限。验证真实文件状态、实际 Shell 退出/子进程。完全权限不重复请求同一应用层授权；系统 TCC/FDA/Accessibility、真实未授予云端外发、UNKNOWN 均按实际状态处理，不伪造权限。
2. **SuperAgent：**在新隔离配置设置 async_policy，参考 PA 文档先将本地并发模型请求限制1、云端2。本地主对两个独立本地子任务、云端主调本地子任务、本地主调已授权云子任务；观察真正请求重叠/串行、父任务保持响应、工具收据和资源预算。不能把脚本后端测试当模型规划成功。
3. **五档来源：**记录 local-only、local-first、balanced、cloud-first、cloud-only 下实际路由和外发。按调用/token/时间/费用统计实际比例，不制造五个固定百分比；本地不可用不能悄悄违反local-only。若UI偏好尚未传入任务中途策略，修复可复现断点并加测试。
4. **取消和UNKNOWN：**真实Shell和真实子代理运行时取消，核实进程/线程/请求已停止或明确未知；在隔离副作用中制造可控中断，确认UNKNOWN收据不自动重放、不被切模型洗白、不误报成功。
5. **任务/Session恢复：**新任务至少一个真实工具副作用后暂停/重启测试服务和GUI，原task/session/幂等键复用。已完成工具不重做，UNKNOWN不重做。界面重开能连Core只是连接恢复，不算这项通过。
6. **同Session换模：**空闲且契约兼容时本地↔云端，保持聊天/草稿/收据/Session ID；历史task.model不改，session_model反映当前选择；重启后保留。忙碌、无效目标、不兼容工具、过小上下文和持久化失败均保留原会话并给准确提示。对子代理历史暂拒绝是已知边界，若扩展须证明历史模型不被重绑定。
7. **原生SSE409：**真实APP桥连接真实Core，在同一任务流里造成保留窗口落后，实际收到409后取快照并续订；验证已生成前缀完整、后续文本不重、只创建一次任务。记录原生链路证据，不能拿浏览器合成桥或HTTP单测替代。
8. **Companion：**授权可读来源后验证晨/晚/唤醒问候、勿扰/静音/去重；连续做可追溯的Codex文件任务与可读取会议转录，再问今日/昨日、指定活动。答案给来源/时间/覆盖缺口；不因看见窗口就声称任务已完成。先accepted再结果/需人工/失败通知，委派默认本地，重启后保持游标。未采集音频、不可访问Codex历史必须明说。

## 6. 构建、独立安装与回滚

按 `desktop/AGENTS.md` 和现有 `build-macos.sh` 构建单一新候选，组件wheel逐项核对源码，Python/Node/wheel架构、锁与watchdog来源记录不遗漏。构建器只归档，接着用修复后的安装器：

```sh
python desktop/scripts/install-local-app.py --source "$CANDIDATE" --test-app --receipt "$RUN/install-plan.json"
python desktop/scripts/install-local-app.py --source "$CANDIDATE" --test-app --execute --plan "$RUN/install-plan.json" --receipt "$RUN/install-result.json"
```

`CANDIDATE`/`RUN`由实际新构建和新证据路径赋值，不照抄占位路径。确认目标是 `~/Applications/LocalPilot Test.app`，日常应用安装前后树摘要一致。验证签名、DMG、实际启动及首次设置、已有测试配置保留。升级第二个可区分测试构建并验证归档解压摘要/签名。

只在测试槽做故障注入：复制/验签/替换后验签/LaunchServices注册失败；核对旧测试APP恢复或首次安装目标恢复不存在，失败候选与回滚材料保留。同时验证Core/Suite/Companion组件升级失败回滚，避免GUI新、Core旧却声称升级成功。结束后留下明确运行状态，原始日志和恢复材料保留本机。

## 7. KV、Intel 与后续产品代码

KV：固定模型revision/量化/tokenizer/template/Skills与提示，记录冷/热/卸载重载/服务重启后的cached tokens、TTFT、总耗时。检查Companion逐请求fresh cache路径；如果它阻止所需持久复用，基于真实后端支持补受管前缀缓存。模型/模板/Skill改变需失效，不能加载过期KV。“永久”应改为可说明容量/失效/重启条件的持久缓存。

Issue #7 的50 GiB预算：先列出**本项目拥有且可重建**的缓存目录与实际后端控制接口。共享oMLX/HuggingFace目录、模型权重、活动记忆、任务/收据/UNKNOWN、发行/回滚归档不进入自动清理集合。用现有缓存/安装管理实现有上限、可解释淘汰与使用中条目保护；不要伪造不存在的Provider淘汰API。新增复杂机制前先指出实际冲突和代码范围。按用户已有授权做可审查plan；涉及删除用户材料时先给确切路径及理由。

Intel：CPU可通过local-openai接入；运行时验证设备能力，不假定Intel有MPS，也不要只改device='cpu'便声称兼容。若有Intel真机，逐一核验Python/扩展/Node/Tauri/helper和PKG的x86_64构建及原生行为，再测量化模型文本/工具/上下文/取消与吞吐。无真机就明确NOT_RUN，并完成可验证的源码适配，不能把arm64重命名为universal2。A3B表示激活参数不能据此推断仅需3B权重内存。

保留用户代码风格：入口校验一次、内部使用类型确定的值；不为臆想竞态堆复杂度；不抽一次性小函数；不手改生成文件；测试真实实现。对App.tsx等进一步拆分只围绕实际功能边界，避免比赛前无收益大重构。

## 8. 外部基准：先adapter再正式比较

阅读 `PUBLIC_AGENT_EVALUATION_20261114.md`。当前 `scripts/public_agent_eval.py` 已能冻结真实Git任务/哈希、生成arm×repeat的Harbor配置、调用固定版本runner、导入逐任务结果和审计；**还没有完整LocalPilot Harbor容器执行adapter，也没有模型分数**。

实现官方BaseAgent薄适配，让现有Runtime/Session通过真实任务容器执行工具；不能另写简化循环冒充产品，不能在Mac宿主执行命令却给容器判通过。注意当前生产HostShell偏macOS，容器执行边界需要明确实现与验证。用正式Docker/官方任务verifier跑一个预注册smoke，再冻结完整正式试验；Harbor固定 `ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4`，有升级理由再创建新试验而非改已跑配置。

用户要求参考旧AA榜：先准确选择Terminal-Bench Hard/对应公开版本或固定Terminal-Bench版本，并单独考虑τ²-Bench Telecom。AA模型分数不等于LocalPilot产品分数。比较分两组：同模型同预算比harness；另选实际可运行主流产品与各自明确模型版本做产品比较。任务/模型/seed(如支持)/超时/步骤/费用/token/重复次数提前冻结。至少报告全分母、失败/超时/错误/未跑、成本未知、延迟与不确定性；不能挑成功、以重试择优、把不显著当等价或拿少量任务证明“全面不弱”。

有合适训练设备/数据且基线指出具体可改进项时再考虑LoRA/全参或RL。问候不需要训练，未采集内容不能靠训练补全。用独立训练/验证/测试集和相同任务预算比较；权重/数据许可证另核实。没有条件则明确不做，不让训练阻塞核心产品闭环。

## 9. 比赛材料与交付

官方半决赛材料截止是 **2026-11-19 23:59，按中国本地时间执行**，不是落地表单的11月20日。腾讯会议全体报名队员全程出镜，PPT+演示合计≤6分钟，无剪辑/快进，按评分顺序，去掉学校/导师及暗示标识。以最新官方通知复核。

评分15/20/20/25/15/5，优先把真实闭环、可验证效果和自主开源改进讲清楚。原作Apache-2.0，第三方许可证原样保留；不要将模型权重/第三方材料强行改成Apache。准确披露AI辅助开发与团队复核。

完成后推送可审查Draft PR，给最终SHA、逐项PASS/FAIL/NOT_RUN、失败历史、原始日志的本机位置、脱敏证据、剩余阻塞、实际模型与成本，以及哪些服务仍运行。不要合并或发布。以当前新HEAD的证据结论收尾；如果还有做不了的项目，指出缺少的具体机器/权限/数据，不能仅写“以后测试”。

---
