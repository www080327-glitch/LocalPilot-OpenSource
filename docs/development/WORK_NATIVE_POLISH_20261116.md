# Work：剩余真实设备和账户验收

以下提示词交给本机 Work。云端已完成的代码、真实 Qwen3.5-2B CPU 验证及 Linux GTK 修复无需重造；只接续实际无法在云端完成的设备、账户和数据项目。所有结果必须区分受测源码、组件版本、安装包身份与运行实例。

```text
继续 LocalPilot 本轮交付分支 codex/native-polish-final-20261116 的真实设备验收。当前两个提交仅在本地，GitHub 推送被自动审批拒绝，尚未创建远端分支或 PR；对外推送需要用户明确授权。先取得本轮提交（经授权推送的分支或已核对的离线 bundle），核对 HEAD 与本机差异，不停留在旧 main d846fef。先阅读：
README.md
docs/development/NATIVE_POLISH_20261116.md
docs/development/REQUIREMENTS_AUDIT_20261116.md
docs/evidence/native-continuation-20261116/RESULTS.md
desktop/docs/evidence/native-continuation-20261116/RESULTS.md
docs/evidence/native-polish-20261116/RESULTS.md
desktop/docs/development/SESSION_WEBVIEW_RECOVERY_20261116.md
docs/development/OPENAI_AND_PUBLIC_EVALUATION_20261116.md
docs/development/PUBLIC_AGENT_EVALUATION_20261114.md
以及本机 device-acceptance-20261116-r2 全部原始结果。

用户已授权继续开发和测试；先使用已核对的本地交付提交完成剩余验证，不把本提示词当成外部 GitHub 推送、合并或发布授权。
逐个检查代码和真实结果，不依据作者、模型名称或旧总结判定通过。
先保全本机 dirty main 的 diff、未跟踪文件及日志；与最新 main 比较后使用隔离分支/工作树。
不要 reset、覆盖或把未审查本机改动整包提交。所有 FAIL/ERROR/UNKNOWN 保留。
不发布 Release，不提交比赛、落地意向或榜单表单，不自动充值或创建订阅。

一、先完成 Mac RC.9 原生隔离和恢复
1. 记录 git SHA、组件版本、OS/架构、磁盘/内存、已有 APP/服务/PID、各自根目录。
   确认旧 Test APP 是否仍在运行和是否有任务；有任务先记录并安全完成/处理，
   只退出明确属于本测试的旧 Test APP。不能明确隔离时使用独立 macOS 用户会话。
   日常 APP 和外部 oMLX 服务保持原有状态，不自行接管或停掉它们。
2. 用仓库 desktop/scripts/build-macos.sh 的现有 Test override 构建，核对真实组件 wheel
   与源码、依赖哈希、Mach-O 架构、签名及 helper 签名。用现有安装器生成计划，
   校验备份归档后安装独立 Test 身份；不得绕过“正在运行”保护。
3. 建立两个互不重用的私有 LP_INSTALL_TEST_ROOT A/B，并各自写入私有
   test-owner.json，purpose 精确为 LocalPilot installation E2E。
   从原生 APP 启动，A 写唯一未发送草稿、权限/模型偏好等哨兵，退出后以 B 启动：
   B 不应出现 A 哨兵。重开 A 及其真实路径别名，A 哨兵应保留。
   主窗口、宠物、气泡、首次设置与任务审核入口须使用同一根目录的 profile。
   对旧默认 WebKit profile 只做前后证据，不猜测回写、清空或自动迁移。
4. 分别覆盖有效 Session、当前服务确认的 session_not_found 404、503/断网、
   不同 Suite home、旧未发送草稿与历史 UNKNOWN。只有认证 404 可开新草稿；
   503/断网不丢选择，未确认 Session 不发附件查询，不自动提交或重放旧任务。

已完成的续作：Linux 原生 A/B 和别名重开通过；同步子Shell取消传播已修复，
真实Shell/HTTP/SQLite/同键不重放与65项相关回归通过。该链路测试的模型回复为脚本。
新增真实2B诊断仍0/2（重复工具调用、最终incomplete），不能改判。
因此下列Mac真实模型与原生任务仍要按自身收据验证，不重做云端普通协议测试。

二、Mac 使用已有 Qwen3.6-35B 做真实任务
5. 核实模型的真实仓库、revision、逐文件 SHA、量化和模板。不能只凭 /models 名称。
   若实际是 Heretic/Uncensored 等派生权重，按实际全名记录，不冒充官方原权重。
   复用已有合适权重，不再下载另一套 35B；先检查加载预算和可用内存。
6. 在安装后的当前 APP 上跑四档权限与五档来源、文件任务、Shell、真实子 Agent
   读文件、两个不同模型的协作、Companion→Core→子 Agent、即时反馈与完成反馈。
   依据子 Agent 自己的工具收据与结果判断，不把父 Agent 代读算子 Agent 完成。
   单独保留无参数引导任务；另设规定合法参数的诊断，不用后者覆盖前者失败。
7. 实测父/子 Shell 取消、GUI/服务退出重开、Session 换模、UNKNOWN 同键不重放、
   原生 SSE HTTP 409 全链路。对每次请求记录 configured/returned model、provider
   usage、延迟、完成状态、收据和实际文件；用量不可得写 UNKNOWN。
8. 当前 b26/b31/b7 候选跑真实首装/升级与故障回滚，覆盖 APP 和三组件失败；核对旧数据和日常
   APP 摘要。验证备份 ZIP 不等于执行反向安装回滚，分别报告。

三、Mac 原生个人助理能力
9. 从真正获 TCC 授权的 APP 身份启动音轨 helper；核对系统责任进程，而非仅看
   父进程名称。若责任仍归 ChatGPT/终端或系统拒绝，保留退出码/零音轨为 BLOCKED，
   不重签其他宿主、不修改 TCC 数据库、不伪造采集成功。
10. 用参与者同意的测试会议验证实际麦克风/系统音轨、分段、本地 ASR、来源引用、
    删除/撤销和后续问答。用明确授权应用内本次发生的 Codex 工作和会议活动验证
    “无需再次手工提供内容”的问答；未获权限的隐藏历史不能推测为已采集。
11. 实测早晚问好、勿扰、静音、去重、锁屏/解锁、真实系统睡眠/唤醒和电源变化。
    oMLX 固定提示/Skills KV 分别测冷、热、模型卸载、服务重启，保存 provider
    指标和磁盘证据。通用 HTTP 自动持久 KV 尚未实现，不能用热命中冒充永久保存。
    Skills 按需加载另核对真实选择效果：full 和 compact 现均保留 load_skill 简介目录，
    正文按需加载，旧持久化 schema 合同不变，已有七项回归。仍需分别记录两种视图
    的真实模型选择准确率，不把实现测试当作大量业务 Skills 的质量验收。

四、物理 Intel Mac
12. 必须在物理 Intel Mac 上记录 uname -m、硬件/OS 和 Python 架构。没有设备就
    保持 BLOCKED，M1/Rosetta/universal2 切片不替代真机验收。
    按 desktop/docs/development/INTEL_MAC_20261116.md 准备原生 x86_64 Python、
    watchdog/cryptography 构建材料及静态 OpenSSL，核验来源后走现有构建脚本。
    模型使用已有 llama.cpp 等 CPU/HTTP 服务与合适 GGUF；MLX 权重不能直接用于
    Intel，不把 LM Studio 作为官方支持的 Intel 路径。
13. 实测启动、模型选择/上下文、真实文件与 Shell 任务、子 Agent、取消/恢复、
    安装升级/故障回滚、X86_64 Mach-O 和签名。评估内存与首 token 延迟，结果
    如实记录；不要预先承诺 35B 在所有 Intel Mac 上可用。

五、完整 Debian 13 x86_64 桌面
14. 使用已有获授权的 Debian 桌面/VM。云端首个 RC.9 候选已提取、自检但原生启动
    因 /usr/lib/x86_64-linux-gnu/webkit2gtk-4.1/WebKitNetworkProcess 缺失而阻塞；
    后来已通过只读 helper 映射完成实际 WebKit 首次设置、A/B及别名重开；该结果
    不等于系统安装。本轮候选声明了 libwebkit2gtk-4.1-0 等依赖，需真正安装到系统或使用预装环境。
    校验最终 DEB SHA 后用 sudo apt install ./LocalPilot-Test-5.0.1-rc.9-linux-x86_64.deb。
    用 dpkg-query -W libwebkit2gtk-4.1-0、dpkg -L 核对 helper，不能仅设置
    LD_LIBRARY_PATH 视为装好，不能禁 WebKit sandbox 或 patch 二进制来报 PASS。
15. 按 README 创建带私有 test-owner.json 的独立测试根目录，再启动
    LP_INSTALL_TEST_ROOT=... localpilot-desktop-test。跑首装、升级、失败回滚、
    实际 WebKit 的 A/B profile 哨兵、Session 恢复和真实模型任务。
    Linux 至少 Qwen3.5-0.8B/2B；本轮官方 2B 的权重/转换哈希在公开证据中。
16. 分开验收 X11 与 Wayland、AT-SPI 静态正文、应用排除/暂停、systemd 登录、
    logind 睡眠唤醒、Pulse monitor/麦克风与本地 whisper.cpp ASR。
    Wayland 元数据不足或应用不暴露 Accessibility 时明确能力不可用，不要求绕过
    compositor 的访问限制；Shell Full 仍受当前 OS 用户与操作系统授权约束。

六、云端模型及公开对照
17. 用户允许 DeepSeek 余额不足时使用 OpenAI。先从既有私有配置确认真实 key，
    不在聊天/日志/Git 显示密钥。官方已确认 Pro $100 可获每月 $100 API 福利；
    核实用户是否领取、关联的 API organization/project、余额与到期日。
    使用该组织 project key，先单次 smoke 验证实际模型/工具/usage；无需自动充值。
    Mac launchd 不继承任意 shell 变量；凭据走现有私有 clients.env，代理使用系统配置，
    不只依赖终端 export。OpenAI 通过独立路由配置，GUI没有新增一键OpenAI向导。
    标价成本、赠送额度抵扣、现金支出分开；无账单证据写 UNKNOWN。
18. 用独立 openai 路由配置当前产品 Agent，不只用 curl 问一道乘法。各路由覆盖
    主/子 Agent、五档来源、批准、流式取消、恢复与真实用量。
    不在已有任务或冻结 study 中自动换 provider；每个模型身份与结果分别保留。
19. 在专用且已授权的 Docker daemon 上先运行仓库 preflight，记录 daemon ID、
    socket、磁盘/内存和官方任务镜像。原旧 534 队列不能被新运行覆盖；只能按原
    冻结环境、原 PID/UID/argv/cwd/daemon 精确续接，不把 UNKNOWN 重放为新任务。
20. 新版本/模型/预算建新的 study。先开发 smoke，再冻结 Terminal-Bench + 官方
    Harbor verifier 的同模型配对、预算和重复次数。现有正式 measured-tokenizer
    协议仅资格验证本地模型；云端要先制定并验证独立的用量/成本/缺失用量协议，
    不能删除资格检查来通过。MMLU-Pro 32题为低资源模型探测，不叫 AA 排名。
    若需要更大输出预算，预先命名新协议并完整重跑，保留本轮 512 token 的原结果。

七、个人模型后训练
21. 只有拿到用户人工确认样本和独立评估集后，才执行现有 reviewed-data 导出及
    LoRA/全参训练；来源撤销、用户拒绝、评估集隔离和候选回退按仓库现有流程。
    不把未审阅观察记录、生成标签或测试答案充当确认数据，不自动模型自改进。
    当前仅训练入口/微型受控训练被验证，尚无真实 PA 训练收益。

收尾：逐项输出 PASS/FAIL/ERROR/SKIP/NOT_RUN/BLOCKED 和完整分母；保存精确命令、
源码/包/模型 SHA、provider usage、错误、脱敏日志与哈希清单。真实模型失败不允许
靠放宽收据、权限或把父任务算子任务来变绿。只提交审阅后的最小修复和脱敏证据，
更新 README 的真实状态；合并前核对受测文件与提交一致。没有设备/账户/数据时给出
所缺的具体条件和已做的工作，不重复让云端重跑已完成的普通回归。
```
