> 此文件保留首轮环境中断时的静态审查记录。执行已恢复并完成 arm64 双 wheel 矩阵；最新事实与所有历史失败见 [实际验收](channels-pr2-acceptance-20261027.md)。下文“本轮未执行/NOT_RUN”属于首轮历史阶段，当前结论以 [Gate JSON](channels-pr2-gates-20261027.json) 为准。

# LocalPilot 5 / PR #2 完整静态审查与候选状态

2026-10-27（Asia/Shanghai）。结论：**NO-GO for main**。
26/26 改动文件已逐项审阅；候选补丁已准备，**没有执行过构建、Python/Node 测试或本轮 E2E**。
这份文档不把“已写代码/测试”写成“已通过”。

## 执行阻塞与工作树

本轮最初的本机只读搜索得到 LocalPilot 各历史工作目录存在。
后续执行器返回 “exec-server transport disconnected”，用户环境状态随即为 unavailable。
因此没有成功创建独立本机 worktree，没有取得本轮 uname、Python/Node/SQLite 版本、
macOS 实际 UID/mode 或进程信号结果，也没有运行或变更日常 APP。

后续只通过 GitHub 连接读取源码、PR 和引用，并保存独立远端候选。
这是环境阻塞下的 source-only 分支，不是本机 worktree 或 Apple Silicon 验收的替代品。
没有尝试访问已有 QQ/微信凭据、聊天、SQLite、平台连接或旧 UNKNOWN；无模型调用或账号重启。

## 实际基线

- PR #2：open、未合并、26 文件、3,850 新增、0 删除，作者 pywang216。
- HEAD：1d7303d94dc9743d6d1ec97abad07160850a1adf。
- main：df04ca709b699b170a29c2aaa337aeebe8a38ef4。
- GitHub 合并预览：d1a051ea43552131a82951a711cd29197056d849；
  读取了 Git commit，确认两个父提交为上述 main 和 PR，tree 为 698d06bf03c9f04620e031c6588312bb32d6de2d。
- PR HEAD 自身 pyproject 是 Core **5.0.0b16**；main 是 **5.0.0b20**。
  候选使用合并预览的文件树，不能直接拿旧 HEAD 整棵树覆盖 main。
- 正式 Desktop tag desktop-v5.0.0 = c248d25b2158b65f67766fa9d523857b0d44eaef；
  正式包构建来源 f211e98799c6b2a4162229d155fb0a00bed764e7。
  GitHub compare 确认构建来源到当前 main 的 40 个差异文件均在 docs/，没有产品源码差异；
  tag 到 main 也是文档/证据变更。没有下载或执行正式 APP。
- PR HEAD 的 combined statuses 与 pull-request workflow runs 均为空；
  “无 CI 记录”不是 PASS。

已枚举远端全部分支（候选创建前）：

| 分支 | HEAD |
|---|---|
| `codex/edge-pet-20261026` | `df04ca709b699b170a29c2aaa337aeebe8a38ef4` |
| `codex/release-companion-0.5.5rc2-20261021` | `92ce6244daa459693de2c8b9cb3091dfe4a63f88` |
| `codex/release-core-4.9.2rc2-20261021` | `1e3b3feb62a1cb5a9b8a049ab7953b75a4c45a3c` |
| `codex/release-suite-0.1.0rc2-20261021` | `f43b5a2b9526d99777b8681012618fb1dbf78ba8` |
| `codex/unified-integration-20261025` | `7f2f8f120defed41e76e8369bf7a1e3e0070a069` |
| `feature/official-channel-adapter` | `1d7303d94dc9743d6d1ec97abad07160850a1adf` |
| `main` | `df04ca709b699b170a29c2aaa337aeebe8a38ef4` |
| `runtime-v1` | `2b7f9af9c81533834b34c03c642e540b314edcb6` |

这些远端读取不等于检查了不可用的本机分支、未提交变更或 worktree 状态。

## 确认的问题和候选处理

| ID | 优先级 | 原始触发/后果 | 候选处理 | 本轮验证 |
|---|---|---|---|---|
| R1 | P1 | main/PR 的 setuptools 包发现都漏掉 localpilot_channels；PR 文档也明确仅源码运行。 | Core include/入口/Node data-files；另建无 Agent Runtime 的可选 channels distribution。 | 配置缺陷确认；实际 wheel 内容 NOT_RUN |
| R2 | P1 | Store.regular_path 和审计 private 遍历所有父路径，/var 系统链接会被当作恶意链接拒绝。 | 仅信任固定 root-owned Darwin 别名及可信规范目标，其它用户链接/junction仍拒绝。 | 静态可触发；本机复现 NOT_RUN |
| R3 | P1 | Node State 仅检查最终目录是不是链接，未核对父链接、属主、权限或 state.json 链接；可能读取外部/宽权限状态。 | 共享私有路径层、祖先权限、文件属主/模式/nlink、O_NOFOLLOW，已有不安全路径不自动修补。 | 回归已写，NOT_RUN |
| R4 | P1 | Node close 无归属且不幂等；旧 State 重复 close 可删除后继 State 的活动锁。 | 保持 fd/inode 归属；关闭后 handle 清空；只删除自己创建的同一 inode。 | 回归已写，NOT_RUN |
| R5 | P1 | Adapter 仅按 decision_id 拦 UNKNOWN。若任务仍 pending，换新决定 ID 可再次 POST 同一 Action。 | 同事务持久 decision_hold；任何新 ID、重启、GET completed 均不解除；承认决定与记录一并落盘。 | 故障/重启/新 ID 回归已写，NOT_RUN |
| R6 | P1 | completed + 模型文本直接显示“已完成”，Node 丢弃 audit，用户无法分辨工具执行、交付和独立验证。 | 标签改为“官方任务结束”；分列 receipt、delivery、Verification=NOT_RUN；不推断独立验证通过。 | 模型口头完成/未知收据回归已写，NOT_RUN |
| R7 | P2 | engines 字段不会阻止直接 node CLI；旧版本可能缺 WebSocket 或精确 JSON 数字源。 | Suite 显示缺失/过旧/资源缺失，CLI 验证真实功能；不用 npm，不给普通用户装 Node。 | 诊断回归已写，NOT_RUN |
| R8 | P2 | Python 主入口只有 KeyboardInterrupt，SIGTERM 默认退出；绑定失败也未显式释放 adapter。 | 两种信号均排空已接收请求后关库；初始化失败释放资源；连接线程上限 16。 | SIGINT/SIGTERM/重启回归已写，NOT_RUN |
| R9 | P1 | mutating POST 返回 503 被当作确定拒绝，可能清活动任务；错误码不能通用证明此前未受理。 | 保留 HTTP 类别并将服务端 5xx 保守判为 UNKNOWN，禁止重投。 | 503 回归已写，NOT_RUN |
| R10 | P1 | 无 Suite 可选安装/生命周期；源码相对路径不构成 wheel 运行合同。 | 独立 venv 装可选 wheel，list/configure/doctor/start/stop/pending/task/login/uninstall，惰性加载。 | 新鲜安装/进程/真实 Core 测试已写，NOT_RUN |
| R11 | P1 | 正文原样进入 Core；用户若粘贴已知入站/服务/平台凭据，输出脱敏不能防止其进入模型上下文。 | Node 和 facade 在转发前拒绝包含已知凭据的输入/拒绝原因。 | 合成凭据回归已写，NOT_RUN |
| R12 | P2 | 配置普通 read_text；状态 DB 首次 SQLite 创建依赖默认 umask、之后才 chmod。 | 配置 owner-only regular/no-follow；DB 先以 0600 独占创建，拒绝已有宽权限/硬链接。 | 路径/既有文件不变性测试已写，NOT_RUN |

所有“候选处理”都指源码修改，不代表修复已经在 macOS 或任何 OS 上验证。
没有以禁用权限、放开所有 symlink、清空旧状态或自动重试解决兼容性。

## 26 个文件逐项审查

| # | 文件 | 审查结论 |
|---|---|---|
| 1 | [configs/message-channels.example.json](../../configs/message-channels.example.json) | 配置仅含环境变量名和占位身份；QQ 不提供 approval。保留普通主体与微信独立 Operator，不能把此示例当作已鉴权配置。 |
| 2 | [docs/development/official-channel-migration.md](../../docs/development/official-channel-migration.md) | 保留历史 Windows/WSL 验收边界；更新当前候选 wheel 说明。原文自述入口未进入 wheel，不能引用它证明打包成功。 |
| 3 | [docs/development/wechat-validation-20261027.md](../../docs/development/wechat-validation-20261027.md) | 历史真实微信/离线重放证据边界清楚；本轮未取得私有现场原始证据，也未重新发送。按原样保留。 |
| 4 | [integrations/qq-bridge/bridge.mjs](../../integrations/qq-bridge/bridge.mjs) | 独立身份、白名单、持久幂等、5 分钟保守回复窗口和跨发送者限制；修复父路径/权限/锁释放及结果证据展示，拒绝向 Core 转发已知凭据。 |
| 5 | [integrations/qq-bridge/cli.mjs](../../integrations/qq-bridge/cli.mjs) | 保留显式新状态要求和 SIGINT/SIGTERM；增加真实 Node 功能门槛、系统路径规范化与只读 info。没有运行真实账号。 |
| 6 | [integrations/qq-bridge/gateway.mjs](../../integrations/qq-bridge/gateway.mjs) | 核对官方主机白名单、单 shard、READY、心跳、队列上限、abort 后等待落盘；不自动重连。未改动。原生 WebSocket/退出时长待实测。 |
| 7 | [integrations/qq-bridge/package.json](../../integrations/qq-bridge/package.json) | Node >=22.13；仅使用内置模块，无 npm 依赖。单有 engines 声明不能阻止直接 node CLI 运行，已补运行时检查。 |
| 8 | [integrations/wechat-ilink-bridge/THIRD_PARTY_NOTICES.md](../../integrations/wechat-ilink-bridge/THIRD_PARTY_NOTICES.md) | 保留 NattoCB 协议来源与 MIT 归属，不引入上游 DSH Runtime。 |
| 9 | [integrations/wechat-ilink-bridge/bridge.mjs](../../integrations/wechat-ilink-bridge/bridge.mjs) | 检查 64 位消息 ID、登录域名、回复 context、重复发送抑制、独立审批 key/白名单、精确 Action ID/决定 ID；修复状态安全、锁与证据展示。 |
| 10 | [integrations/wechat-ilink-bridge/cli.mjs](../../integrations/wechat-ilink-bridge/cli.mjs) | 显式迁移状态不复用、取消信号、错误脱敏；增加 Node 功能检查与只读 info。扫码必须用户另行明确执行。 |
| 11 | [integrations/wechat-ilink-bridge/package.json](../../integrations/wechat-ilink-bridge/package.json) | 无 npm 依赖，Node 门槛与 QQ 一致；支持库资源通过 wheel 明确携带。 |
| 12 | [localpilot_channels/__init__.py](../../localpilot_channels/__init__.py) | 只有模块说明；没有导入或启动另一个 Agent。 |
| 13 | [localpilot_channels/__main__.py](../../localpilot_channels/__main__.py) | 原 SIGTERM 默认直接退出且配置读入未做私有文件检查；候选增加受保护 JSON 读取、信号排空与 bind 失败释放锁。 |
| 14 | [localpilot_channels/adapter.py](../../localpilot_channels/adapter.py) | 检查身份映射、提交落盘、owner/session、真实收据与审批；修复决定 UNKNOWN 换 ID、5xx 不确定性、凭据进入输入和 verification 展示。 |
| 15 | [localpilot_channels/client.py](../../localpilot_channels/client.py) | 严格数字 loopback、忽略代理、不重定向、不自动重试、不转发错误正文；API 1.0/subject/persistence 核对。补独立 uncertain 分类，保留 HTTP 状态。 |
| 16 | [localpilot_channels/server.py](../../localpilot_channels/server.py) | Origin 拒绝、独立入站鉴权、长度/JSON 检查和无内容日志；新增有鉴权的健康检查和 16 个连接线程上限。 |
| 17 | [localpilot_channels/store.py](../../localpilot_channels/store.py) | WAL/FULL、独占 owner 事务和原子 owner/message 更新正确；修复系统符号链接误拒绝、已有不安全文件、初建文件权限窗口。故障恢复仍需实际运行。 |
| 18 | [scripts/wechat_approval_final.py](../../scripts/wechat_approval_final.py) | 检查成功 changes 字段、只读预检、唯一 apply_patch、路径/摘要/普通主体/发送回执；修复可信系统路径并拒绝空 Action ID。只读证据校验，非线上自动审批器。 |
| 19 | [tests/channel_bridge_scenario.mjs](../../tests/channel_bridge_scenario.mjs) | 两个模拟平台 HTTP 到官方 facade 的场景；真实平台/扫码/WebSocket均未连接。原用例保留。 |
| 20 | [tests/channel_fixtures.py](../../tests/channel_fixtures.py) | 合成凭据/身份和脚本模型；RealOfficial 使用官方 Core/SQLite/AgentSession/工具，仅替换模型输出。不是用 fake Core 冒充真实 E2E。 |
| 21 | [tests/test_channel_adapter.py](../../tests/test_channel_adapter.py) | 覆盖多发送者、持久幂等、内容冲突、断线、凭据隔离、审计失败等；候选更新 503 预期为保守 UNKNOWN。 |
| 22 | [tests/test_channel_official_integration.py](../../tests/test_channel_official_integration.py) | 已有四项官方 Core 用例保留，增加实际过期审批测试；所有用例本轮 NOT_RUN。 |
| 23 | [tests/test_hybrid_projection_arguments.py](../../tests/test_hybrid_projection_arguments.py) | 唯一既有文件的新增测试：目录名元数据允许、文件正文继续 withheld；读取了完整原文件，未将 diff 上下文误作完整源码，也未改动隐私投影实现。 |
| 24 | [tests/test_qq_bridge.mjs](../../tests/test_qq_bridge.mjs) | 检查网关模拟、并发去重、身份、重启、发送丢失与已知凭据脱敏；仅调整更准确的任务终态标签。Node 原生网络行为本轮未运行。 |
| 25 | [tests/test_wechat_approval_audit.py](../../tests/test_wechat_approval_audit.py) | 13 项合成离线审计测试历史结果保留；不等价于新实时微信批准/拒绝。候选测试需随新路径检查重跑。 |
| 26 | [tests/test_wechat_ilink_bridge.mjs](../../tests/test_wechat_ilink_bridge.mjs) | 覆盖扫码模拟、精确大整数、接收重连、context、审批/拒绝、UNKNOWN、结果归属；仅调整终态标签，其它语义保留。 |

## API、安全与验证合同

读取当前 b20 的 localpilot_service/server.py、security.py、localpilot_api/service.py，
核对路径、返回字段、Action ID、ordinary/read/submit 与 Operator/control/approval_for、
owner 查询隔离、重启后新票据、UNKNOWN_BLOCKED 禁止继续等行为。
没有修改这些既有实现。**源码契约核对不是实际接口测试通过。**

QQ 只有普通入站 key，不能配置 approval；微信入站审批 key 与普通 key 独立。
真正批准由 facade 的独立 Operator 凭据调用官方 approve/reject，
使用 refresh 得到的当前 required_action.id；模型文本、原生收据或“同意”字样均不产生授权。
Suite configure 对显式 Core 配置拒绝 ordinary=operator、错误 route/token_env 或不匹配 approval_for。
healthz 的 subject/persistence/API 检查不能声称证明完整实际 role/scope；
最终权力继续由官方服务配置和端点检查执行。

提交响应丢失且无官方 ID：保持 UNKNOWN，不 POST 找回。
决定响应丢失：查询可更新任务终态，但 decision_hold 持久保留，不追加“applied”决定。
写入收据、模型最终文本、交付状态和独立文件检查分别计量；
工具成功计数不能证明任意用户文件目标正确。线上 facade 没有独立 verifier，
所以不生成 Verification PASS。测试用例的独立文件断言只认证对应合成测试目标。

凭据只通过环境变量进入自己需要的进程，不放进 argv/config README/任务工具参数；
消息进入 Core 前拒绝已知凭据。新 Node info 不读取后重写 state，不输出 token。
SQLite 包含私有回复/审批预览，微信 state.json 包含登录 token/context，
必须存于工具 workspace 和仓库之外的全新私有目录。并未采集本机真实 owner/mode。
Windows ACL、其它用户、真实 account、多机和长期运行均未认证。

## 测试清单与实际结果

| 项目 | 本轮实际结果 | 准备的执行方式/限制 |
|---|---|---|
| 本机独立 worktree | NOT_RUN / EXECUTION_BLOCKED | 初始只读搜索后执行 transport 中断；待环境恢复创建 |
| Python 3.14 / SQLite / fcntl / Unicode / 系统 temp / 线程 / 信号 | NOT_RUN | 双架构脚本 + 新路径、状态、Suite 信号回归 |
| Core 和 Suite wheel 构建、隔离安装、源码外运行 | NOT_RUN | validate_channels_install.py，包含额外 facade wheel |
| QQ → Node → Adapter → 官方 Core → list_directory → Receipt/query | NOT_RUN | 保留原真实 Core + 模拟平台场景，从 wheel 资产执行 |
| 微信批准/拒绝 → 实际 apply_patch → 文件独立检查 → 渠道回执 | NOT_RUN | 原双渠道场景 + 官方接口测试；完全合成平台/模型 |
| 跨 sender、重复/内容冲突、普通身份无批准权、旧票据 | NOT_RUN | 原用例保留并纳入 wheel 测试 |
| HTTP 断线、UNKNOWN、换决定 ID、SQLite 写失败 | NOT_RUN | 新保守隔离回归；不重放 |
| 审批过期、Core/Bridge/SQLite 重启 | NOT_RUN | 原重启用例 + 新真实 Task deadline/拒绝测试 |
| Node WebSocket 实际实现 / socket 退出 | NOT_RUN | 原测试使用 FakeSocket；新增 loopback 原生 WebSocket/子进程信号 fixture 已写，NOT_RUN |
| x86-64 Intel Mac | NOT_RUN | --require-darwin --expected-machine x86_64；拒绝 Rosetta |
| M1 Max / macOS arm64 | NOT_RUN | --require-darwin --expected-machine arm64；尚无本轮机型/版本读数 |
| Windows 原便携单元/Node/审计复测 | NOT_RUN | 脚本按平台列出未运行项，ACL 验收单列 |
| WSL2 官方 API 控制复测 | NOT_RUN | 当前 WSL 环境不可用，不用其它 OS 冒充 |
| 真实微信/QQ账号 | NOT_RUN | 不重启、不迁移、不扫码、不轮询、不发送 |
| Desktop 5.0.0 新 GUI/APP 实际启动、升级 | NOT_RUN | 源码和现有 API 不改动只支持兼容性意图，不能写 GUI 实测 PASS |
| OS 断电 / SIGKILL 遗留锁 / 高并发退出 / 长期运行 | NOT_RUN | Node 旧锁需独立人工核实；无自动清锁/自动解除 UNKNOWN |

队友既有报告：Windows 共享层 23 通过/官方 Core 4 跳过，Node 65 通过；
WSL 官方 API 等回归 82 通过、Node 65 通过；
独立微信审计校验器 Windows 与 WSL 各 13 通过。
历史真实微信批准后一次写入、拒绝零写入及两次只读预检仍仅是队友历史证据。
这些本轮未重跑，不能填入本轮 PASS 数。

修改过的 JavaScript 仅经移除模块 import/export 并替换 import.meta 的 V8 静态语法检查；
它不是 Node module import、native WebSocket、macOS 或运行测试。Python 语法/构建尚未执行。
本轮没有实际测试 FAIL 数可统计，因为执行未开始。
执行器失败确认为 EXECUTION_BLOCKED；原 PR 缺陷确认，候选验证 UNKNOWN/NOT_RUN。
原历史歧义 pending/UNKNOWN 不读不改。

## 尚未解除的合并门槛

1. 恢复 M1 执行环境，先创建独立 worktree，再运行完整安装矩阵并审查所有日志。
2. 新增原生 Node WebSocket 的本地 loopback/子进程取消/信号退出场景必须执行；
   原 FakeSocket 单元测试不能替代真实 Node socket。高并发停止时长也需要补验收。
3. 验证 Suite 新 CLI 的真实进程识别、错误诊断、卸载保留数据和 Node 缺失行为；
   没有 Python 语法/构建执行证据，不能直接投入日常 Suite。
4. 核对真实 macOS 属主/模式/WAL/SHM/锁，执行 SQLite 故障、重新打开和审批 UNKNOWN 事务测试。
5. 若无法取得原生 Intel Mac，保持 Intel NOT_RUN；不得发布双架构均通过。
6. 真实平台连接仅在用户另行授权后进行，使用全新状态，不沿用本轮模拟验收说法。
7. main 再次读取、检查所有新增差异/冲突，保持原 PR 作者历史；无 force push，无秘密/DB/权重/聊天入库。
8. 所有必需 GO 达成前不合 main、不发布 Release、不替换日常 APP。

## 交付与合并方案

候选提交的两个父提交分别为冻结的 main 与原 PR HEAD，因此原作者提交仍在历史中；
文件树以 GitHub 合并预览为起点，仅追加渠道候选修复与文档/测试。
这是候选分支，不是把 PR #2 合入 main。
本轮不把源码准备误报为完成所有目标，也不要求用户批准未验收内容。

环境恢复后维护者可先 fetch 候选，再：
`git worktree add ../LocalPilot-channels-review <候选分支>`；
在该 worktree 运行集成说明内两个 native 验收命令。
若 main 有新增提交，应在候选中普通 merge 并解决冲突后完整复测；
全部门槛通过后才建议 main 合并，保留原 PR 作者和已有代码归属。

机器可读状态：[gates](channels-pr2-gates-20261027.json)；
构建、命令、恢复边界：[集成说明](channels-pr2-integration-20261027.md)。

| Gate | 结论 | 原因 |
|---|---|---|
| CHANNEL_CODE_REVIEW_GO | **NO_GO** | 26/26 files statically reviewed; candidate patches have no executable validation |
| MACOS_ARM64_GO | **NOT_RUN** | Mac execution transport disconnected before architecture/runtime probes and worktree creation |
| MACOS_X86_64_GO | **NOT_RUN** | No native Intel Mac execution environment |
| CHANNEL_PACKAGING_GO | **NOT_RUN** | Packaging configuration and optional distribution prepared; no wheels built or installed this round |
| QQ_AGENT_E2E_GO | **NOT_RUN** | Installed-wheel real Core E2E prepared, not executed; no live QQ account connection |
| WECHAT_AGENT_E2E_GO | **NOT_RUN** | Approval/rejection/expiry/restart tests prepared, not executed; historical live WeChat is not a new test |
| CHANNEL_SECURITY_GO | **NO_GO** | Confirmed source defects patched in candidate; security, fault and shutdown regressions unrun |
| MAIN_MERGE_GO | **NO_GO** | No main merge until required acceptance and fresh main comparison succeed |
