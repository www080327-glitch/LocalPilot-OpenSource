# LocalPilot 中断任务续作与交付 — 2026-11-16

## 交付结论与身份

本轮从保留的未提交工作树接续，完成上轮中断的 Linux 原生 Profile 验收，修复 compact Skills 目录、Companion 显式 OpenAI 准入/提供方身份，以及真实同步子 Shell 取消传播缺陷；重新构建全部组件和 Linux Test 包。真实 2B 模型的两项补充任务仍失败，原失败没有覆盖。

- 上轮 GitHub main 基线：`d846fef0f4b442d57e6e37f856a59c5a1a1337de`。
- **最终运行/构建/测试源码提交：`59fad12de6f57006fc7510805af2dfd1718c16ea`**。本报告及随后证据提交不修改该运行源码。
- 交付分支：`codex/native-polish-final-20261116`，面向 `www080327-glitch/LocalPilot-OpenSource`。完整文档由承载本报告的提交识别。
- GitHub 状态：两个提交目前仅保存在本地，尚未推送、未创建 PR。自动审批拒绝了本次推送，要求用户明确授权向该外部仓库发布源码、测试日志和截图；远端 main 仍为上述基线。
- Desktop **5.0.1-rc.9**；Core **5.0.0b26**；Suite **0.2.0b31**；Companion **0.5.7b7**；Channels **0.1.0a3**。
- 本轮交付为源码和独立 Test 候选；没有发布 Release、比赛/榜单表单，没有修改用户 Mac 的旧 APP 或未提交工作树。

[SOURCE_SHA256.json](SOURCE_SHA256.json) 对 917 个非证据源文件逐项绑定上述源码提交。新包在独立暂存工作树构建，生产源码与该提交一致，构建前后都与原工作树做源码比较；旧包、旧资源和旧模型结果保留。

## 本轮实际补完的代码

| 问题 | 修复及依据 |
| --- | --- |
| compact 工具视图删掉 Skills 用途目录 | 仅在模型请求中保留 `load_skill` 目录，正文仍按需加载，持久化 schema 合同不变。真实注册/加载、模型请求和快照恢复的 7 项测试通过，修复前缺失描述的失败保留。见 [Skills 证据](skills/RESULTS.md)。 |
| Companion 仍拒绝显式 OpenAI | 两处 DeepSeek 专用判断加入明确 `openai`，控制窗显示实际提供方；本地专用仍拒绝云端，确认和问题范围规则保留。 |
| 新 OpenAI 子任务提供方显示 unknown | 给新专用 backend 明确设置 `provider="openai"`，保留真实持久身份；没有改变旧兼容 provider 身份。 |
| 同步 child Shell 收不到父取消 | 真实执行 `printf; sleep 60` 后取消，旧代码仍继续等待且拖住 Core 停机。修复只向当前未结束 children 传播已有取消意图，沿用工具停止/UNKNOWN/恢复逻辑。同一真实 Shell→取消→SQLite 重启→同键不重放测试完整通过。 |

OpenAI 合同 62 项、取消/异步/可移植性 65 项均通过，详细复现和初始失败见 [模型与取消续验](../model-continuation-20261116/RESULTS.md)。这些用例与最终全量有重叠，不能相加成新的独立测试总数。

本次提交也纳入上轮尚未提交的 Session 认证恢复、Test WebView 独立存储、Linux AT-SPI 正文读取、子预算与旧 Session 兼容、OpenAI 后端、Harbor 路径别名和公开模型评测脚本。原阶段细节保留在[前阶段报告](../native-polish-20261116/RESULTS.md)，没有把那些先前工作说成这轮重新执行。

## 最终源码回归

| 范围 | 发现数量 | PASS | SKIP | FAIL / ERROR | 测试用时 |
| --- | ---: | ---: | ---: | --- | ---: |
| Core | 1565 | **1475** | 90 | 0 / 0 | 163.146 秒 |
| Companion | 722 | **689** | 33 | 0 / 0 | 31.929 秒 |
| Suite，正确仓库入口 r2 | 115 | **114** | 1 | 0 / 0 | 24.873 秒 |

[结构化回归摘要](REGRESSION_SUMMARY.json) 和 [日志清单](LOG_MANIFEST.json) 包含完整命令与来源。首次 Suite 调用误加 `-t suite`，在收集前出现 `Start directory is not importable`，没有执行测试；保留原 ERROR，改用原项目命令 `python -m unittest discover -s suite/tests -v` 后通过，没有修改产品或测试判据。

Core 的 90 项包含既有缺失历史基准/可选 SDK/原生平台等条件跳过；Companion 的 33 项包含 macOS 与可选原生/训练/ASR 环境。跳过不计作通过。前阶段独立 GTK、tiny CPU 训练及 whisper.cpp 测量仍作为各自源码证据保留，不自动叠加成这次全量的新总数。

Desktop 生产代码在本轮续作中未修改。既有 RC.9 Vitest 74、Chromium+合成 IPC 47、Rust 50 PASS/3 ignored 的来源见[原阶段日志](../native-polish-20261116/validation/README.md)；本轮重新通过 TypeScript/Vite、Rust release 编译及整包自检，不把编译重复算作又一轮全部单测。

## Linux 实际原生验收

上轮最后的 r4 包（Core b25 / Suite b30 / Companion b6）已完成 **7 项实际 X11/WebKit 场景**：A 状态恢复、B 独立首次设置、B 独立组件安装、A/B 分别重开、A 符号链接路径别名及全部自有进程停止。

A 保存唯一未发送草稿、深色主题、完全本地偏好；B 保存另一草稿、系统主题、平衡偏好。两组 WebKit store 不同；切换和重开没有串用。两个数据库的 journal/checkpoints 都为零，没有模型任务。别名验证 wrapper 的首次挂载/临时运行目录错误均保留。详见 [7 项原生场景及截图](../../../desktop/docs/evidence/native-continuation-20261116/RESULTS.md)。复核发现旧 r19 两张截图的标签错位，已追加[截图引用更正](../../../desktop/docs/evidence/native-continuation-20261116/final-package-smoke/PRIOR_SCREENSHOT_LABEL_NOTE.md)；原图与原清单保持不变。

最终 b26/b31/b7 包的短原生启动也已 **PASS**：在新建 C 根目录完成真实首次设置，主界面显示 Core 5.0.0b26；未配置模型或提交任务，核对归属后正常停止。详见[最终包 smoke](../../../desktop/docs/evidence/native-continuation-20261116/final-package-smoke/RESULTS.md)。两个包的实际 Desktop ELF 字节一致（SHA-256 `6cb3172ca81b9a8eeedf22f69d091585d19d1a157682f5ada8ce7bba43d1e11a`）；新后端资源身份以新包报告和短启动结果为准，不用旧 b25 的连接画面冒充 b26。

原生运行仍是提取 DEB 后，以已核验的只读 helper 映射补足宿主依赖路径，并保持 WebKit sandbox。它不等于系统级 DEB 安装、升级或故障回滚，也不替代 Wayland、音轨、登录/睡眠、Mac 或 Intel 真机。

## 最终 Linux Test 包

| 项目 | 结果 |
| --- | --- |
| 文件 | `LocalPilot-Test-5.0.1-rc.9-linux-x86_64.deb` |
| 大小 | **114,590,266 bytes** |
| SHA-256 | **`4faf7b91de548355aa717800d2f38fc65cccc8a7e87d501f36c1e3312b29a587`** |
| 包身份 | `local-pilot-test` / `io.localpilot.desktop.test` / amd64 |
| 目标环境 | Debian 13 x86_64，发行版 Python 3.13，声明的 GTK/WebKit 运行依赖 |
| 内置组件 | Core b26 / Suite b31 / Companion b7 / Channels a3 |
| 完整性 | 40 wheel；285 Python/Swift 源文件与最终源码逐字节一致；构建前后均复核 |
| 提取运行 | 模块导入、pip check、Node v22.23.4、native bundle self-check 均 PASS |
| 系统安装 | **NOT_RUN** |

自动生成的 [RESULTS.json](package/RESULTS.json)、[VERIFIED_MODULES.json](package/VERIFIED_MODULES.json) 和 [SHA256SUMS](package/SHA256SUMS) 保留原始内容。构建报告的 `source_dirty:true` 来自暂未提交的文档/证据；隔离树的生产文件与源码提交完全一致，没有把 generated report 手改为 clean。没有把此前同名 RC.9 的旧包 SHA 当成本包。

## 真实模型结果：全部分开保留

| 冻结批次 | 结果 | 可支持的结论 |
| --- | --- | --- |
| 官方 Qwen3.5-2B 首轮产品任务 | 7 PASS / 2 FAIL | 原始九项，不由后续重试替换。 |
| 原规定参数三项诊断 | 0 PASS / 3 FAIL | 暴露旧子预算准入问题，失败保留。 |
| b25/b30/b6 四项修复后诊断 | 2 PASS / 2 FAIL | 自主和规定参数 child 读取通过；另两项未满足完整任务判据。 |
| 本次更明确步骤、较长 wall-clock 的两项诊断 | **0 PASS / 2 FAIL / 0 ERROR** | child 查目录而没有 Shell；Companion 重复读取后错误解释独立 verification 状态，最终 incomplete。 |
| 固定 MMLU-Pro 32 题 | 10 PASS / 22 FAIL，31.25% | 仅固定的小样本基础能力测量；不是 AA 排名、完整基准或 Agent 能力对照。 |

新两项使用同一官方 Qwen3.5-2B 受控 Q8_0、2 个 CPU 线程、8192 上下文、每次 512 输出 token。父任务 6 步/8 工具，worker 上限 3 步/4 工具，Shell 提示明确请求 child 3 步/2 工具。每项执行一次，没有根据输出继续调提示重跑。原协议和预算、实际 provider usage、全部 task/child 收据见[新诊断](../model-continuation-20261116/RESULTS.md)。

该模型快照早于后来发现的取消传播修复，449 文件清单在执行前后完全一致。真实模型没有走到 Shell，不能据此验证或否定修复后的 Shell 执行链路；真实 Shell 的集成验证与模型自主任务质量分别报告。本轮外部云端请求为零，本地 API 支出为 $0，能耗未测；没有读取或核实用户 API 账单。

## 尚未完成的事项与明确边界

| 项目 | 当前状态 | 还缺什么 |
| --- | --- | --- |
| Mac Qwen3.6-35B、四权限、真实 child/Companion 完成交付 | NOT_RUN 本机新版本 | 已有 Mac、准确模型身份与当前候选的原生任务验证。不能将云端 2B 或脚本响应替代。 |
| Intel Mac 原生整包 | BLOCKED | 物理 Intel Mac，原生 x86_64 构建、模型任务、安装/回滚。 |
| Debian 系统安装/升级/回滚、Wayland、Pulse、登录/睡眠 | NOT_RUN | 已准备依赖及管理权限的真实桌面/VM与相应设备。 |
| OpenAI/DeepSeek 实际推理、多模型和五档质量/费用 | BLOCKED | 当前环境没有可用 provider key，用户组织、赠送额度余额与模型权限未核实。适配合同通过不等于真实模型通过。 |
| 新 Terminal-Bench/Harbor 正式对照 | BLOCKED | Docker CLI/daemon/socket 都不可用；旧 534 队列未打开或修改，不虚报 AA 成绩。 |
| 个人模型后训练 | BLOCKED | 用户确认样本、独立评估集与真实增益评估。已有 LoRA/full 与 tiny CPU 测试，不造个人标签。 |
| Mac oMLX KV 生命周期 | NOT_RUN 本机 | 当前模型的冷/热/卸载/重启测量；现有显式 llama.cpp slot 恢复不是通用 HTTP 永久 KV。 |
| 通用 Linux GUI 操作、任意 HTTP 自动持久 KV、RL 执行器 | 未实现或不属于当前已选实现路线 | 不能交给 Work 仅补一次测试就算完成；只读 AT-SPI不是 GUI 操作，HTTP KV需要提供方能力，当前后训练选择的是审阅后 LoRA/full。 |

[WORK_NATIVE_POLISH_20261116.md](../../development/WORK_NATIVE_POLISH_20261116.md) 已更新为可直接接续的具体设备/账户/数据步骤。它要求保存本机 dirty tree、旧失败与 UNKNOWN，并使用本轮交付分支。没有把未完成的功能或缺失环境改成 PASS。
