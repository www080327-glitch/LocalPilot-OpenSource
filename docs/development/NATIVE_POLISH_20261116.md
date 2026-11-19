# 原生恢复、Linux 文字来源和真实模型续验（2026-11-16）

## 本轮结论

本轮以 PR #14 合入的 `d846fef0f4b442d57e6e37f856a59c5a1a1337de` 为基线，继续解决真实暴露的问题。最终续作版本为 Desktop **5.0.1-rc.9**、Core **5.0.0b26**、Suite **0.2.0b31**、Companion **0.5.7b7**、Channels **0.1.0a3**；原 b25/b30/b6 的冻结证据保留。这是源码和隔离测试候选，不是新的正式 Release。

Linux x86_64 已有真实服务、模型、文件、Shell、取消/恢复和 GTK 文字观察证据；实际 X11/WebKit 首次设置、A/B profile 隔离、重开和路径别名检查已补完；系统安装、Wayland、音轨及睡眠验收仍有缺口。Intel Mac 已有 CPU/HTTP 路径与 x86_64 构建入口，仍没有物理 Intel 设备验收结果。不能用 Linux CPU、M1 Max 或 Rosetta 的结果替代它。

最终包身份与续作结果见 [续作验收](../evidence/native-continuation-20261116/RESULTS.md)，原阶段命令、失败历史和证据边界保留在 [前阶段验收记录](../evidence/native-polish-20261116/RESULTS.md)。逐项需求审查见 [需求对照](REQUIREMENTS_AUDIT_20261116.md)，实际设备剩余操作见 [Work 提示词](WORK_NATIVE_POLISH_20261116.md)。

## 具体修改及原因

### 缓存 Session 的认证恢复

旧客户端可能保留另一个测试目录的 `lp.currentChat`。此前附件面板会在 Session 尚未被当前服务确认时发请求，出现 `HTTP 404: Session not found`。现在仅使用当前任务快照、成功创建的 Session 或认证 GET 确认的 Session。只有 `404 + session_not_found` 才打开新草稿；网络故障、403、503、非结构化 404 均保留选择并报错。连接作用域增加 Suite home，同一 origin 切换服务根目录也会重新确认。

原有草稿、服务端历史和 UNKNOWN 收据保留，不因恢复动作自动提交或重放任务。RC.8 基线用例确实失败，RC.9 在真实 Chromium + 合成 IPC 的 47 项界面回归中全部通过；Mac 原生仍待复验。实现与证据见 [Desktop 恢复说明](../../desktop/docs/development/SESSION_WEBVIEW_RECOVERY_20261116.md)。

### Test APP 的 WebView 存储隔离

`LP_INSTALL_TEST_ROOT` 以前只隔离后台文件，不能证明 WebKit/localStorage 隔离。现在测试应用以规范化测试根目录与 Bundle ID 生成稳定存储身份：macOS 使用命名的持久 WKWebsiteDataStore，Linux 使用测试根目录内的数据目录。主窗口、宠物、气泡、首次设置和审核窗口共用同一作用域；不同根目录分开，相同根目录及路径别名可重开。

测试身份要求私有 `test-owner.json`；日常身份继续使用原配置。此前缺系统 WebKit helper 的失败保留。续作以只读依赖映射启动原生 X11/WebKit，已验证 A/B 未发送草稿、主题、来源偏好、各自重开和真实路径别名；准确候选版本及映射条件见 [原生 profile 验收](../../desktop/docs/evidence/native-continuation-20261116/RESULTS.md)。这仍不等于系统 DEB 安装，也不代替 Mac WebKit 验收。

### Linux AT-SPI 真正读取正文

真实 GTK 测试发现两个问题：helper 丢弃了已有 `AT_SPI_BUS_ADDRESS`；PyGObject 将 `get_text_iface()` 暴露为 Accessible 对象，同名 `get_text()` 不接受起止参数，原逻辑捕获 TypeError 后只留下窗口元数据。

修复保留明确的 accessibility bus 地址，并调用 `Atspi.Text.get_text()`。测试夹具使用自己的 D-Bus runtime，向 activation 环境同步 owned Xvfb DISPLAY；没有增加轮询、读取范围或期限。最终源码 8 项定向测试通过，涵盖真实正文、输入和密码排除、来源撤销、应用排除、暂停停止 helper。完整 Companion 回归与独立原生结果分别保留，不能把重复的 8 项加总成新增测试数。

### OpenAI 与五档来源策略

增加显式 `openai` 后端，使用官方 HTTPS 默认地址、现有私有凭据注入、`max_completion_tokens` 和流式 usage。Core、Suite、Channels 与 Desktop 的云端分类一致；修复 `cloud_only` 把允许云端传出的本地主模型当成纯云端的判断。

现有 DeepSeek 和兼容端点请求语义、历史配置身份保持。账户余额不足不触发隐式换模型；新 provider 用独立路由和独立研究记录。续作补齐 Companion 的 OpenAI 白名单、控制窗模型名称及子 Agent provider 身份；62 项针对性测试通过。当前无真实 API key，合同测试不代表 OpenAI 模型能力或余额验收。最新 Pro API 赠送额度规则、配置示例和正式研究门槛见 [OpenAI 说明](OPENAI_AND_PUBLIC_EVALUATION_20261116.md)。

### Harbor 原进程识别

原控制器直接比较 cwd 字符串，可能漏掉 macOS `/var` 与 `/private/var` 的同一路径。修复只规范化两侧真实路径，保留原 PID 的用户、命令、Docker 环境及暂停状态核对。真实 Linux 符号链接进程测试覆盖旧版漏检、新版精确续接，不代表旧 534 次队列已恢复或完成。

### 子 Agent 启动预算与工具参数

规定合法参数的真实 Qwen 诊断发现，旧默认子 Agent 预算 32,768 units 在预留提示词、工具 schema 和输出空间后不足以开始工具步骤，首个请求就进入 finalizing。新 Session 的默认 worker 上限改为 131,072，仍由父任务剩余额度封顶；显式设置的旧上限不会自动提高。这些 units 是宿主准入记账单位，不冒充 provider 实测 token。

升级时，旧 Session 只要完整配置满足原合同或已声明的迁移规则，就保留旧 32,768 上限、历史子 Agent 和 UNKNOWN 收据；旧 Session 换到未显式指定预算的路由也保留该值。新建 Session 使用新默认。模型、显式预算或其他未批准配置变化仍拒绝恢复。测试使用旧源码实际生成的 SQLite、真实文件副作用和新源码恢复，确认不发推理、不重放工具。

另外，compact schema 以前连参数描述也全部移除，模型看不到“路径必须相对于工作目录”等约束。现在模型请求保留参数语义；续作进一步保留 `load_skill` 的用途/版本目录，正文仍按需加载，持久化的 canonical schema 保持原样。真实注册器/加载/快照恢复及 HTTP 参数语义的七项测试通过。完全本地路由不再向模型提供只适用于云端 worker 的 tier 字段。这些修复来自实际失败，不靠扩大权限或把父 Agent 的读取算作子 Agent 的成功。

### 同步子 Agent 的 Shell 取消传播

续作增加真实子 Shell、HTTP 取消、SQLite 重启及同键不重放的集成检查，发现父 Session 的取消意图没有立即传给正在执行 Shell 的同步子 Session。子 Shell 轮询自己的停止事件，而子 Session 原先只能等工具返回后才检查父事件，导致 Shell 继续等待、Core 退出也被阻塞。降低测试轮询频率、排除 429 后仍可复现。

修复只在 `request_cancel()` 将同一停止意图传给当前未结束的子 Session，不增加锁、重试或第二套收据结算。真实子 Shell 及时停止，未知副作用仍保留 UNKNOWN；Core 重启保留父子收据，同一幂等请求没有增加文件写入或模型调用。65 项取消/异步/可移植性回归通过。该集成测试仅模型响应使用脚本，实际 HTTP、Runtime、Shell 子进程及 SQLite 都走生产实现，不能当成真实模型任务通过。

## 真实模型与公开证据如何解读

云端改用官方 `Qwen/Qwen3.5-2B` 固定 revision，经完整原文件哈希核验后受控转换为 Q8_0，使用真实 llama.cpp CPU 服务。首轮九项产品任务为 **7 PASS、2 FAIL**：读取文件、Shell 写入读回、SSE 取消/409、UNKNOWN 重启不重放及基础 Companion 调用已有真实通过；自主子 Agent 和 Companion→Core 的参数选择/时限失败仍计入原分母。

规定合法参数的首轮三项诊断仍为 3 FAIL，并暴露了上述预算问题。修复后的四项诊断采用新源码、新预算和单独协议，不改原失败；单模型父子链路也不能代替不同本地/云端模型的协作质量。原始九项和公开样本冻结在 Core b24 / Suite b29 / Companion b5，后续 b25/b30/b6 的结果另行记录，不能混写为同一受测版本。

新四项一次执行结果为 **2 PASS、2 FAIL**：自主和规定参数的子 Agent 都亲自读取并完成父任务交付。Shell 情况只验证到真实子模型请求取消，未在期限内执行 Shell；Companion 已实际读文件并给出正确完整内容与引用，但重复读取耗尽步骤预算，最终 `incomplete`，仍计失败。完整条件与失败边界见 [修复后的诊断](../evidence/qwen35-linux-20261116/CORRECTED_RESULTS.md)。这是本次 2B、六步和 512 输出 token 条件的结果，不能据此宣称主流 Agent 非劣，也不能把最后文本正确改报成整个任务通过。

公开模型样本使用固定 revision 的 MMLU-Pro，预先选定 32 题、zero-shot、每题一次、512 输出 token。全部题目包括截断和错误保留在分母。该小样本不是完整 MMLU-Pro、AA 官方综合指数或 Agent 排名；正式工具能力比较继续使用仓库的 Terminal-Bench/Harbor 流程，当前缺可用 Docker daemon。具体数值与协议以 [模型证据](../evidence/qwen35-linux-20261116/RESULTS.md)为准。

固定提示与 Skill 的热缓存、显式磁盘 slot 保存/重启后恢复已有真实 llama.cpp 证据；这不等于外部 HTTP 的通用自动永久 KV。Mac oMLX 的冷/热/卸载/重启测量仍需本机 Work。

续作又以独立冻结源码跑了两项明确步骤的诊断：父任务最多六步，child 明确请求三步/两次工具；Shell marker 等待上限延至 450 秒，任务上限 600 秒，仍为每次 512 输出 token。结果 **0 PASS、2 FAIL**：child 重复查目录、没有执行 Shell；Companion 一次物理读取后三次缓存读取，最终错误解释工具状态，任务 `incomplete`。没有超时、请求错误或源码中途改变，也没有再调提示重试。该模型快照早于后来发现的取消传播修复，完整协议与判定见[新诊断证据](../evidence/model-continuation-20261116/RESULTS.md)。

## 后续优先级

1. 在 Mac 上验收新测试 profile、Session 恢复与已有 Qwen3.6-35B；再做真实子 Agent、四权限、取消/恢复和安装故障回滚。
2. 找到物理 Intel Mac，运行原生 x86_64 构建、CPU 模型任务和安装/回滚；硬件缺失时明确 BLOCKED。
3. 在装有完整系统依赖的 Debian 13 桌面完成 DEB 安装与原生 WebKit 交互，分别验收 X11、Wayland、Pulse 音轨和登录/睡眠。
4. 核实实际云端 API 组织/额度，完成不同模型的任务与用量记录，再冻结新的公开对照研究。旧 534 队列和失败历史保留。
5. 获得人工确认的训练样本和独立测试集后，再做个人模型训练与增益评估。已有训练入口和微型训练验证不代表个人数据训练完成。
