# Work 接力：只补真实设备、实际来源与完整对照

以下为可直接交给本机 Work 的提示词。本轮已完成的代码与云端回归见 [当前状态](LINUX_COMPLETION_20261116.md) 和 [evidence](../evidence/linux-completion-20261116/RESULTS.md)。无需重新搭建 Runtime、Router、权限系统或写另一套框架。

---

你在继续 LocalPilot-OpenSource 的 Linux/Intel/PA 验收。先阅读当前 `main` 的 README、AGENTS、`docs/development/LINUX_COMPLETION_20261116.md`、`LINUX_CORE_20261116.md`、`LINUX_COMPANION_20261116.md`、`REVIEWED_TRAINING_20261116.md` 和最新 evidence。已有 main 的 PR #13 基线为 `0cc99d57990e81302b941b6f5a160093dd298d4b`，新候选版本是 Desktop 5.0.1-rc.8 / Core 5.0.0b23 / Suite 0.2.0b28 / Companion 0.5.7b5 / Channels 0.1.0a3。开始时拉取并记录实际 Git SHA、工作树状态及版本；不要在另一个旧源码上补记 PASS。

我授权你完成下列独立测试和必要的小范围修复，保留日常 APP、既有模型服务、用户资料和所有失败历史。使用新证据目录；不要擅自清理模型/缓存/旧 APP，不提交比赛表单、不发布 Release。不因为代码来自任何模型就跳过审查，也不因为模型名称就否定真实证据。

## 1. 真实 Linux 图形和安装环境

优先有完整用户桌面会话的 Debian 13 x86_64 机器/VM。云端已能编译 Rust/准备真实资源，但 D-Bus/Chromium 的 Unix socket 创建遭宿主拒绝，不能通过测试夹具冒充真实桌面。

使用 `desktop/docs/development/LINUX_20261116.md` 的既有构建入口，以 `io.localpilot.desktop.test` 和独立 Test 配置构建。只使用当前源码四个 wheel，按脚本核对全部 Python 文件、依赖 SHA、架构、匹配的系统 Python minor、Node 和迁移后的入口。不要用 macOS APP 安装脚本处理 DEB，也不把 Debian 13 构建直接称为兼容所有 Ubuntu。

在专用桌面环境中执行：完整 Playwright、独立 DEB 首装/重开、Core/Companion 连接、一个真实模型文件和 Shell 任务、取消、Session/UNKNOWN 恢复。分别记录系统包管理和现有组件升级/失败回滚；故障只在专用测试安装与工作区注入。升级前后比较旧数据、模型路由、幂等键和 UNKNOWN；不能拿 `dpkg-deb -x` 当作真实安装事务通过。

检查 X11 和 Wayland 分别能提供哪些来源；使用 `companion.tests.test_linux_native` 的自有窗口先验证 AT-SPI 静态文字、排除输入框/密码、停用和撤销，再在我允许的真实窗口检查。Wayland 全局窗口无能力时写 UNSUPPORTED，不尝试绕过桌面策略。Core 原生 Computer Use 目前仍是 macOS 专用；只读 AT-SPI 不是操作工具。

核对 `systemd --user` 的显式注册、登录启动、停止/移除、通知可见性、实际睡眠唤醒及晨晚静音/勿扰/去重。不要自动启用 linger 或修改系统省电设置。

## 2. Linux 真实会议

使用本机 Pulse/PipeWire-Pulse、显式选择的麦克风与 monitor 来源、本地 whisper.cpp 和已核对 revision/SHA 的多语言模型。英语 tiny.en 的公开样本通过不能当作中文会议质量。

验证 microphone / system / both，正常停止、捕获中 SIGTERM、正在转写时取消、来源失效，以及转写跟不上时明确失败。记录实际文字段、声道来源、时间、子进程是否退出；确认应用没有写音频文件，停止后没有晚到文字，撤销后不再检索旧来源。实际录制仅使用已获准的内容和参与者；如果没有真实设备或授权内容，记录阻碍，不造会议。

## 3. 物理 Intel Mac

需要真正 Intel Mac，不能用 M1/arm64、Rosetta 或 universal2 文件清单代替。核对 macOS 15+、原生 x86_64 Python/Node、既有锁脚本要求的 CPython 3.14.6 与 watchdog/cryptography 源码构建材料。沿 `desktop/docs/development/INTEL_MAC_20261116.md` 构建、验证所有 Mach-O/动态库目标架构、签名和独立 Test APP。

先检查可用内存/磁盘，再选择确实能运行的已有 GGUF CPU 模型，记录上游 revision、权重 SHA、量化、模板、真实上下文、TTFT、速度、峰值内存和 provider usage。不把 MLX 权重直接当 GGUF，不以 LM Studio 支持 Intel 为前提。测试本机 HTTP 配置、文件/Shell、取消、重开和实际升级失败回滚。没有 Intel 机器就将这一整项保留 NOT_RUN，并准确说明所需设备。

## 4. Apple Silicon 当前候选

PR #13 的 arm64 结果只对应原源码；其 Test APP 未安装运行任务。本轮 RC.8 必须在新目录按当前源码重建，核对组件/资源后使用既有独立 APP 安装流程。先辨认运行中的旧 Test APP，按现有计划安全停止/安装；不覆盖日常 APP。

需要补真实模型任务、四档权限、主/子 Agent、Shell 取消、UNKNOWN、任务与 Session 重开、原生 SSE409、安装升级及故障/反向回滚。旧数据、日常 APP 摘要和历史失败保留。单纯 GUI 退出再打开不算任务恢复。

音轨/TCC 必须从真正获授权的 Test APP 责任链启动，核对 responsibility、entitlements 和实际 helper 来源；不要用宿主 ChatGPT 发起的 helper 去冒充 Test APP 已授权。系统授权被拒时记录实际原因，不重置或绕过 TCC。还需真实晚间/睡眠唤醒与已授权 Codex/会议来源问答。

## 5. 真实多模型与能力

云端本轮使用小型 Qwen2.5-0.5B 验证链路，9 项 5 PASS / 4 FAIL；四项任务质量失败必须保留。它证明实际父子调用，不证明主 Agent 能力合格。

优先已有、来源可核验且内存足够的主模型。分别测真实主/子模型组合、五档来源偏好、即时反馈、取消/恢复、最终结果、每次实际 provider usage/延迟/成本；无法确认计费就写 UNKNOWN。私有来源不能因 Full 文件权限自动获得云端外发许可。不要为了通过验收写死答案、替模型补事实或隐藏失败。

对主流能力结论，沿现有固定 Harbor/Terminal-Bench 工具先执行 preflight，必须确有 Docker daemon、足够磁盘/内存和匹配 tokenizer。旧 534 队列保持原 study、原源码 `1c06e97` 和原失败；新候选另立 study，冻结当前源码、模型、量化、模板、工具、预算与参考臂，完整运行并保存所有分母。没有完整合格结果，不报榜单排名或“不弱于”。不得直接用 Harbor 默认 resume 删除/重放旧无终态尝试。

## 6. 实际后训练与 KV

后训练实现已在 Linux CPU 微型模型跑通，不需要重写。用我实际审阅的样本导出至少 train/valid/test 三个独立来源组；评估规模和人工标准先明确，测试集不得用于挑参数。没有人工确认数据就先停止数据阶段，不能把观察文本自动变成“正确答案”。

按 `REVIEWED_TRAINING_20261116.md` 分别记录基座/候选 SHA、依赖版本、loss、实际更新范围和独立测试原始答案。Linux CPU/CUDA 用 portable trainer，Apple Silicon 用既有 MLX；格式不能混用。CUDA/MLX 真机未测部分如实记录。候选训练成功不自动替换当前产品模型，不由 loss 单独宣称能力提高。

KV 本轮已验证固定 llama.cpp + 提示/Skill 的 cold=0、hot=1256、显式进程重启恢复=1256 cached tokens；这是显式 slots API，不是产品自动管理任意外部服务的证明。oMLX 受管 SSD 路径需在当前候选上记录冷/热/卸载/重启的 provider token 与 TTFT、模型/模板变更失效和空间准入。不要承诺跨权重/模板永久有效，也不要改动不归本次测试拥有的外部模型服务配置。

## 交付

每项列出实现、实际 PASS/FAIL/ERROR/SKIP/BLOCKED、命令、当前 SHA、模型/资源身份、原始日志和哈希。修复实际缺陷时走仓库流程，在新日志中复验，首轮失败保留。提交可公开的代码和脱敏 evidence；凭据、SQLite、私人活动、模型权重不推送。最后明确哪些已经完成、哪些是质量失败、哪些缺设备/数据，不能用“基本完成”合并这些状态。

---

Linux 通用外部模型服务器的自动磁盘 KV 管理与 Linux Core 原生 Computer Use 仍属功能范围缺口，不应由本机测试擅自标成通过。若后续实施，应使用具体后端/桌面契约另行设计和验证，不要为消除 NOT_RUN 在本轮虚构替代实现。
