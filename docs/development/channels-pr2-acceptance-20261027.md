# PR #2 macOS arm64 实际验收（2026-10-27）

**两套隔离 wheel 矩阵通过；维护者随后明确授权合入 main 与独立本机安装，Intel 仍 NOT_RUN。**

后续复验和安装见 [合并与本机安装](channels-pr2-main-install-20261027.md)。以下执行历史保留原始边界。

[完整机器可读证据](../evidence/channels-pr2-arm64-20261027/acceptance-summary.json) ·
[26 文件审查](channels-pr2-review-20261027.md) ·
[Suite 使用与验收脚本](channels-pr2-integration-20261027.md) ·
[最新 Gate](channels-pr2-gates-20261027.json)。

## 实际执行与版本

执行恢复后建立独立 LocalPilot-5-channels-review worktree，基于 c1aa4fa。
远端 main 仍为 df04ca709b699b170a29c2aaa337aeebe8a38ef4，
PR HEAD 仍为 1d7303d94dc9743d6d1ec97abad07160850a1adf。

实测 Darwin/macOS 27.0.1，Python 3.14.6 原生 arm64，
Node 24.20.0 arm64，SQLite 3.50.4。硬件具体型号查询受限，未把用户描述当作本轮硬件取证。
没有使用 Rosetta 代替 Intel，没有运行真实模型或付费 API。

本机修复提交为 123f819a 和 1efb0e5c（短 SHA），最终完整安装矩阵基于后者。
矩阵结束、权限和 wheel 对照探针通过后，执行环境再次 unavailable。
因此原始日志和 wheel 留在本机；本报告保存已返回的实际结果，不声称已上传二进制。
远端通过 GitHub 保存相同运行时补丁及脱敏结果；原 PR、main、其它 Work 均不改写。
额外的逐任务快照采集未确认完成，不捏造任务 ID 或逐条收据快照。

## 安装后的实际结果

| 安装组合 | Python | Node | wheel 外部目录导入/入口 | 无 Node 的 Suite list |
|---|---|---|---|---|
| 候选 Core 5.0.0b20+channels.1 + Suite 0.2.0b21+channels.1 | 123 通过，0 失败/错误/跳过 | 77 通过，0 失败/跳过 | PASS | PASS |
| 官方 Core 5.0.0b20 + 独立渠道 0.1.0a1 + 候选 Suite | 123 通过，0 失败/错误/跳过 | 77 通过，0 失败/跳过 | PASS | PASS |

合计 246 次 Python 用例执行、154 次 Node 用例执行；同一固定测试集在两种 Core 安装组合分别运行，
不是 400 个独立功能。测试从只含测试/离线校验器/已安装 Node 资源的外部 harness 启动；
Agent、Service、facade、Suite 的导入位置另用 -I 检查为全新 venv。

官方 b20 wheel 由固定 main 源码构建，SHA-256 为
08a864c3314ab362f17ea7b4d1690f1bfbd528bbffc5a7e9cdb88ac5a77893cc。
对比确认它确实没有 localpilot_channels；候选 wheel 包含该包。
122 个既有 Agent/Computer/API/Service/Plugin Python 文件在两个 wheel 中逐字节一致，
没有引入第二套 Agent Runtime，没有更改既有权限实现。
Suite 专项安装使用 --no-deps，以避免下载/运行无关 Companion；完整 GUI/Companion 升级回归未运行。

## 真实 Core 与模拟渠道 E2E

通过的 test_real_tools_and_both_node_bridges_with_synthetic_platform_http 使用：
QQ/微信模拟平台 HTTP → 实际 Node Bridge → 实际 Python facade →
官方 HTTP/SQLite/AgentSession/权限网关/Registry → 真实文件工具 → 持久审计 → 渠道查询/回执。
模型输出来自确定性脚本；平台从不扫码、建立真实 QQ 连接或轮询真实 iLink。

该场景实际断言：4 次 list_directory；批准后 approved.txt 内容为 OK；
拒绝后 rejected.txt 不存在；6 条工具审计覆盖 4 个读取、1 个成功 patch 和 1 个拒绝收据。
重复消息/决定不再执行；QQ 批准命令不转交；不同 sender 的回复目标/context 不串用。
这些是通过的断言，不是未采集的逐任务原始快照。

实际官方 API 用例还通过：
普通身份拒绝批准，跨 owner 查询 404，内容变化/幂等冲突 409，
Core 重启后换新 Action ID、旧票据 409，审批真实过期后无写入。
微信决定必须经过独立测试 Operator，模型文本不能批准。
HTTP 断线、提交 UNKNOWN、审批响应丢失、换决定 ID、SQLite 重启均不重放。

工具收据、任务终态、最终交付和独立 Verification 分开显示。
线上 facade 的 independent_verification 保持 NOT_RUN；
测试侧对具体目标的独立文件断言通过，不冒充线上已自动验证所有文件任务。

## macOS、安全和故障

实机确认 /var 的链接文本是相对的 private/var。
修复仅在固定根目录系统别名上做单跳规范化，且检查链接属主和固定规范目标；
用户控制的父/末级链接、硬链接、已有宽权限状态均拒绝，不 blanket resolve、不自动 chmod 旧文件。

新建中文/空格状态目录实测：
目录 0700，channels.sqlite3、-wal、-shm、owner.sqlite3 均 0600、当前用户属主、nlink=1；
目录没有额外 ACL 条目，PRAGMA quick_check=ok，重开配置保持。
模拟损坏 SQLite 文件实际被拒绝。
PRAGMA query_only=ON 的原生 SQLite 写失败分别验证了提交前不发请求、
真实工具已执行但收据落盘失败后保持 UNKNOWN、重开后不重放。

原生 Node WebSocket 通过本地 loopback 握手、正常取消、SIGINT、SIGTERM；
该测试与旧 FakeSocket 测试分开，不声称真实 QQ 网关通过。
Suite 安装后的 facade 通过 SIGINT/SIGTERM、重启、任务查询/待处理诊断和安全卸载；
卸载保留配置/数据库，卸载后 stop 仍可安全幂等调用。

已知凭据进入正文/原因时被拒绝；JSON 引号和反斜线转义形式也已补充脱敏回归。
配置、Node 状态、SQLite 和锁使用私有权限及 no-follow；Node 不继承 Core Operator/模型凭据。
没有读现有平台账户、凭据或聊天，没有修改日常 APP 或系统代理/电源设置。

## 所有失败、UNKNOWN 与未运行

- arm64-01：FAIL。基线归档中的历史 APP 绝对链接被安全过滤器拒绝。
  后续只提取普通文件/目录，保留安全过滤，跳过 2 个历史链接；不读取链接目标。
- 早期 source-node-01：FAIL/中断。系统相对链接仍被误拒；精确总数未恢复。
  修复后路径/原生 socket 10 项通过，后续完整 Node 77 项通过。
- arm64-02：121 项 Python 中 6 failures、1 error，包含清理失败重复计数。
  三个旧 Core 回归使用默认全局锁目录，测试隔离后通过；生产 file-lock/权限实现没有修改。
  Suite 还在 macOS framework exec 前记录了进程命令行，导致后续安全身份校验失败。
- arm64-02 早期失败实例的进程清理未完全确认；不据此声称全局旧进程已清空。
  后续 fixture 增加已知 PID/创建时间/命令参数核对的独立清理，
  最终安装矩阵的 stop/restart/uninstall 用例通过；未做宽泛进程扫描或杀进程。
- arm64-03：121 项中 1 failure。卸载后清理调用 stop 得到“组件未安装”；
  将停止逻辑独立于组件安装状态后，完整 123 项通过。
- arm64-04：两套完整矩阵全部通过；前面的失败日志不删除、不改写为 PASS。
- 合成 UNKNOWN 场景是预期保守隔离；查询到 completed 不清 decision_hold，不伪造批准已确认。
- 历史真实微信 pending/UNKNOWN 保持原状，没有读取、迁移或重放。
- Intel 原生、Windows/WSL2 本轮重跑、真实 QQ/微信账号、完整 Desktop GUI 启动/升级、
  长时间运行、物理断电/极端并发退出均 NOT_RUN。已有手机微信成功仅是队友历史证据。
- 第二次环境离线后，额外逐任务快照与二进制上传 NOT_CONFIRMED/未完成；
  本报告的 E2E 证据是通过的实际集成断言和已返回日志结果。
- Intel 交接脚本增加了 sysctl 不可用时的 fail-closed 预检；该脚本保护是离线后源码补充，
  不是新的 Intel 或 arm64 运行记录。

## wheel 与 Desktop 兼容性

三种 wheel 均已实际构建，文件名和 SHA-256 在机器证据中。
本机位置为 LocalPilot-channels-acceptance/arm64-04/wheels（仓库外的私有验收目录）。
没有创建 Release，没有把不安全早期 wheel 当作最终包，也没有替换日常 APP。

Desktop 5.0.0 的既有 Core/API 源码保持一致；渠道是独立进程/独立可选 venv。
普通 Suite/GUI 不要求 Node。实际无 Node list 和组件卸载路径通过。
这支持 CLI/API 兼容性，不能升级为完整 APP/GUI 的启动、升级或签名实测。

## 最终 Gate 与合并方案

| Gate | 结论 | 实测范围/限制 |
|---|---|---|
| CHANNEL_CODE_REVIEW_GO | **GO** | 26 original PR files reviewed; confirmed defects patched and native regression matrix passed |
| MACOS_ARM64_GO | **GO** | Darwin 27.0.1, Python 3.14.6, Node 24.20.0 arm64, SQLite 3.50.4; isolated adapter/component tests |
| MACOS_X86_64_GO | **NOT_RUN** | No native Intel execution environment; handoff script provided, no Rosetta substitution |
| CHANNEL_PACKAGING_GO | **GO** | Core, Suite and optional facade wheels built and installed into fresh venvs; source-free imports verified |
| QQ_AGENT_E2E_GO | **GO** | Synthetic QQ HTTP transport through installed facade to real Core/file tools, receipts and query; no live QQ account |
| WECHAT_AGENT_E2E_GO | **GO** | Synthetic WeChat transport, separate test Operator, approve/reject/expiry/UNKNOWN/restart and independent file assertions; no live WeChat account |
| CHANNEL_SECURITY_GO | **GO** | Tested macOS identity/permission/replay/private-state/credential contracts; no claim of global OS or physical account certification |
| MAIN_MERGE_GO | **GO** | 维护者明确授权带已披露限制合入；原生 arm64 双 wheel 矩阵重跑通过；Intel/真实平台/完整 GUI 仍 NOT_RUN |

初次验收时因 Intel/完整 GUI 未测而保留候选。维护者随后明确指示合入并安装本机，
重新核对 main/PR 无变更，双 wheel 矩阵原生 arm64 再次全部通过后允许普通 merge。
Intel 仍需日后原生执行同一脚本；不将授权决定写成 Intel 或完整 GUI 实测通过。禁止 force push。
原 PR 作者提交继续保留在祖先历史中；不提交 DB、私密聊天、真实身份/Token、权重或旧状态。
