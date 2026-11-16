# Linux 适配及原计划状态

本轮基线为 PR #13 已合入的 `0cc99d57990e81302b941b6f5a160093dd298d4b`，保留此前 PR #1、#9、#11、#12、#13 的原始记录。用户要求完成 Linux 适配、继续未完成需求，并同步完成的源码到 main。本说明区分源码、实际测试和仍缺少的产品证据。

当前版本：Desktop **5.0.1-rc.8**、Core **5.0.0b23**、Suite **0.2.0b28**、Companion **0.5.7b5**、Channels **0.1.0a3**。未发布新 Release，未提交比赛/落地表单。

## 本轮交付

| 范围 | 代码与实际执行 | 限制 |
| --- | --- | --- |
| Linux Core | Bubblewrap 只读/工作区 Shell，Full 当前用户执行，进程组取消、UNKNOWN、恢复；宿主断言网络隔离 | 依赖允许用户 namespace 的系统；Full 仍受 OS 用户权限约束 |
| Linux 服务与硬件 | Core detached 生命周期，Linux 电源/CPU/内存，Suite 能力报告，XDG 与显式 systemd 用户服务 | 登录、真实电池、物理睡眠需目标设备 |
| Linux 桌面 | macOS 原生模块按目标编译；Linux 文件打开、可移植桌宠、Tauri/DEB 构建，真实组件资源 | 图形会话、系统安装及升级回滚未在当前限制环境验证；Linux 没有 macOS Liquid Glass |
| Linux Companion | AT-SPI/X11 前台只读来源、logind、显式 Pulse/PipeWire-Pulse 设备和本地 whisper.cpp | Wayland 不保证通用全局窗口；不是 Core Computer Use 操作能力；实际声卡/中文会议待验 |
| 后训练与评估 | 人工审阅、按来源的 train/valid/test、CPU/CUDA LoRA/full、独立本地评估与比较 | CPU 微型模型已执行；真实个人数据增益、CUDA、MLX/Intel 训练未验 |
| Linux 渠道运行时 | 官方 Node 22.23.4 x86_64/aarch64 归档与哈希 | x86_64 安装/重开/执行通过；aarch64 本轮未运行 |
| 原生模型资格 | 已核验 Qwen GGUF/llama.cpp，真实父子调用、取消/SSE409/UNKNOWN、显式 KV 保存恢复 | 9 项为 5 PASS、4 FAIL；不是正式 Agent 能力榜单 |

具体实现与用法：[Core](LINUX_CORE_20261116.md)、[Companion](LINUX_COMPANION_20261116.md)、[桌面](../../desktop/docs/development/LINUX_20261116.md)、[后训练](REVIEWED_TRAINING_20261116.md)。原始命令、计数与保留失败见 [本轮 evidence](../evidence/linux-completion-20261116/RESULTS.md)。

## 原计划逐项对照

| 用户目标 | 当前状态 | 不能据此宣称的结论 |
| --- | --- | --- |
| 参考 DeepSeek SuperAgent，主 Agent 调多个本云子 Agent | 已有同一 Runtime 的异步调度、历史子树与五档来源偏好；本轮实际发生父子模型请求 | 未逐项复制研究原型；同一个 0.5B 模型调用不等于多模型合作质量通过 |
| Companion 轻交互 → 主 Agent → 子 Agent，及时反馈与最终结果 | 已有即时反馈、后台任务/SSE、来源与结果账本；本轮真实轻聊、委派通路执行 | 小模型的委派文件任务失败；不能把“任务进入终态”说成用户目标完成 |
| 四档权限、Full 不重复弹 APP 许可 | 同一 Gateway；Linux Shell 已接入；Full 直接使用当前用户 | 不能绕过 OS/TCC、root、Wayland 或外部服务自身限制 |
| 晨晚问候、用户活动、最高级只读权限 | 原有问候/静音/勿扰/去重；Linux 增加原生来源与会话/唤醒信号 | 不等于所有软件/历史/窗口均可读取；无法读取的来源必须报告范围不足 |
| 能回答已发生的 Codex/会议/活动 | 既有显式来源、可读静态文本、引用、撤销；新增本地 ASR | 隐藏推理不读取；没有真实完整历史或中文会议的本轮质量证据 |
| 通过 Skills 提供能力，按需加载 | 已有稳定目录、摘要与按需加载，继续共用原 Runtime | Skills 不是模型训练，也不保证弱模型必然正确调用工具 |
| 固定提示/Skills 的持久 KV | oMLX 既有受管 SSD 前缀/50 GiB 准入；llama.cpp 本轮 cold/hot/显式重启恢复实测 | 通用 unmanaged HTTP 后端尚无自动磁盘 KV 管理；换权重/模板不能保证缓存永久有效 |
| LoRA 或全参后训练 | 数据、离线训练、候选哈希和独立评估代码完成；真实 CPU 梯度路径通过 | 实际个人数据未训练，收益未证；没有 RL 或自动自学习 |
| Intel Mac 高优先级 | CPU/HTTP、原生 x86_64 资源和构建路径保留 | 物理 Intel、macOS 15+ 和真实 x86_64 材料仍 NOT_RUN；M1/Rosetta 不替代 |
| Linux 支持 | 服务、Shell、桌面构建和 PA 适配已写入；实际 Linux 测试开展 | 不能称所有发行版、GPU、图形会话和原生电脑操作均已合格 |
| 不弱于主流 Agent，用公开任务与榜单 | 既有固定 Harbor/Terminal-Bench、冻结模型预算、参考臂、审计与保留失败工具 | 当前没有完整公开对照或非劣统计结论；自定义 smoke 不补成榜单分数 |
| 安装、升级、失败回滚与历史保留 | Python 组件事务继续使用真实 pip/wheel 检验；Linux DEB/资源有实现 | Linux 原生包管理事务、Mac 新 RC.8 APP 实际安装任务仍需目标环境 |
| 开源、README 和简易安装 | 自有代码 Apache-2.0；保留 MIT 等第三方署名；更新根和各组件 README | 第三方模型、系统库和私有材料不被自动重新许可；没有新 Release |
| 国赛/落地材料 | 已有官方规则/评分核验文档和历史证据，当前功能主张可按本表引用 | 表单/比赛未提交；不能用源码测试代替实际录制、队员信息或提交回执 |

“全部此前要求已达到”仍不成立。关键缺口中有实际失败（小模型任务质量）、环境阻碍（图形/音轨/Docker/Intel）和功能范围（通用 HTTP 自动磁盘 KV、Linux 原生 Computer Use）。三者不能统一写成待测，更不能写成 PASS。

## 本轮审查发现

已有 Work 的 PR #13 生产改动仅修复 Playwright 桥接数组别名；其余为验收证据。本轮核对了上传报告与仓库报告哈希，不以模型名称决定可信度。新增实现也进行独立交叉审查和实际执行：

- Rust 真实 Linux 编译发现 macOS 专用 API/feature 约束，已按目标平台修正。
- 系统电源不能把外围 USB 设备充电误当主机 AC，新增实际 sysfs 用例。
- 更新排除项时原生观察工厂原来会重建 macOS helper，现统一选择实际平台。
- PEFT 的正数选层 LoRA 原参数组合必定失败，修正后真实梯度和层归属通过。
- Suite 升级夹具继承 `PYTHONPATH=.:suite` 时会把源码 egg-info 当已安装版本，真实 pip 留下重复 dist-info；夹具改用 `python -I -m pip`，保持全部升级/失败/回滚断言。
- Linux 会议 helper 的 SIGTERM 只设置 Event，不能唤醒正在等待 ASR 的 `communicate`；现由独立停止线程终止并等待已拥有的子进程，真实 ASR 取消和完整回归通过。
- Pulse 17 的真实 JSON 用 `monitor_source` 表达来源类别，原先假设的字段不成立；已按上游实现修正入口解析，未知结构报告不可用。
- 真实 DEB 提取发现 Tauri 会复制 venv 的三个 Python 解释器链接；打包入口现重新生成系统解释器链接、包内摘要和安装大小，再执行搬移后的实际导入检查。
- 使用 PR #1、PR #9 的真实旧源码补验后，发现 Shell 描述的小改动也会改变旧 Desktop Session 配置指纹。已保留原工具描述和权限提示的精确合同，Linux 环境事实加入请求视图：V5 为临时视图，非 V5 稳定缓存模式沿用精确请求快照的保存合同；没有忽略指纹差异或改写旧历史。新增旧检查点恢复、继续请求、错误策略拒绝及自定义同名 Shell 测试。

源码整理围绕这些实际平台与接口问题进行，不为重写而替换已工作的 Runtime、Permission Gateway 或恢复逻辑。

## 下一步材料

需要目标设备、真实用户样本/模型、图形会话或可用 Docker daemon 的工作整理到 [Work 交接](WORK_LINUX_REMAINING_20261116.md)。该交接也明确列出尚未实现的功能范围，不能由设备验收擅自标成通过。旧 534 队列保留为 1 PASS、3 FAIL、13 ERROR、517 无最终结果；最新源码需要另立 study，不能覆盖旧失败或换代码续写旧分数。
