# PR #2 可选渠道集成候选（2026-10-27）

状态：ARM64_AUTOMATED_ACCEPTED / INTEL_NOT_RUN / MAIN_NOT_MERGED。两套 wheel 矩阵已实测通过，完整结果和失败历史见 [实际验收](channels-pr2-acceptance-20261027.md)。不是正式发行版，不替换日常 APP。
完整审查见 [审查记录](channels-pr2-review-20261027.md)。

## 架构和版本

QQ Node / 微信 Node → 独立 Python facade → 既有 Core Agent Service API 1.0。
只有 Core 执行工具、管理审批及运行 Agent；没有新增 Agent Loop，没有修改权限网关。
模型/平台登录不在同一进程。

- 原 PR HEAD：1d7303d94dc9743d6d1ec97abad07160850a1adf，自身版本仍为 Core 5.0.0b16。
- 当前 main：df04ca709b699b170a29c2aaa337aeebe8a38ef4，Core 5.0.0b20。
- Desktop 5.0.0 正式 tag 与 main 之间仅有文档/证据差异；不能从此推断渠道兼容性已实测。
- Core 候选 wheel 元数据：5.0.0b20+channels.1。既有 Agent/API 实现仍保持 b20。
- Suite 候选：0.2.0b21+channels.1；Companion 0.5.7b2、Desktop 5.0.0 不改动。
- 独立可选 distribution：localpilot-channels 0.1.0a1，仅 transport facade 和 Node 资源，
  不包含 agent、localpilot_api 或 localpilot_service，因此可连接已经运行的官方 b20。
- Core wheel 也包含 facade 和入口，修复原包发现遗漏；正常安装不运行渠道、不安装 Node。
  若在 Core 环境直接使用其入口，不要再向该环境叠装/卸载同名 facade 包；Suite 默认用独立 venv。

## 构建与完整验收

arm64 已在独立 worktree 实际执行通过；Intel 尚未执行。以下命令供复验，使用独立候选 checkout/worktree。
构建工具只装入新的测试环境，不改日常 APP 的内嵌 Python。

```sh
python3.14 -m venv /new/private/channel-build
/new/private/channel-build/bin/python -m pip install build
/new/private/channel-build/bin/python scripts/build_channels_wheel.py --out /new/private/wheels
/new/private/channel-build/bin/python -m build --wheel --outdir /new/private/wheels .
/new/private/channel-build/bin/python -m build --wheel --outdir /new/private/wheels suite
```

原生 Apple Silicon 与原生 Intel 分开执行（路径必须尚不存在且在 checkout 外）：

```sh
python3.14 scripts/validate_channels_install.py --require-darwin --expected-machine arm64 --out /new/private/acceptance-arm64
python3.14 scripts/validate_channels_install.py --require-darwin --expected-machine x86_64 --out /new/private/acceptance-intel
```

验收脚本记录系统、Python/Node 架构、Python 3.14、Rosetta 状态、wheel SHA-256、
每阶段退出码和 Python 测试失败/错误/跳过项。禁止用 Rosetta 结果认证 Intel 或 arm64 原生环境。
默认从本地 Git 中固定 main 基线构建官方 b20；也可用 --baseline-wheel 指定独立构建的精确 b20。
脚本不自动 fetch，不覆盖其它 worktree。构建依赖可能需要 PyPI 网络，失败会保留 FAIL。

脚本在两个全新 venv 中分别运行：
候选 Core wheel + Suite wheel；
官方 b20 wheel + 独立可选渠道 wheel + Suite wheel。
测试目录只复制 tests、离线校验器以及从已安装 wheel 取得的 Node 资源，
不复制 Agent、Service 或 Python facade 源码。导入另用 -I 核实位于新 venv。
Suite 的完整 Companion/GUI 依赖回归不在此专项脚本内。

测试平台和模型均为合成 fixture；实际 HTTP、Core、SQLite、AgentSession、权限网关、
文件工具和回执均使用官方实现。微信批准后独立检查 approved.txt，
拒绝/过期后检查目标不存在；模型说“完成”不代替这些断言。
脚本不扫码、不连接真实 QQ WebSocket、不轮询真实 iLink、不调用真实模型或付费 API。

Windows 可重跑便携 Python/Node 部分；原生 Windows Core 的 fcntl/POSIX 限制保留 NOT_RUN。
WSL2 应在其自身 Linux 环境运行，结果不得标为 Windows 原生或 Mac。

## Suite 使用

先安装候选 Suite wheel；日常 Desktop 5.0.0 仍保持自己的原版 Suite。以下命令属于隔离测试 Suite。

```text
localpilot --home /new/private/channel-home channels list
localpilot --home /new/private/channel-home channels install --wheel /path/localpilot_channels-0.1.0a1-py3-none-any.whl
localpilot --home /new/private/channel-home channels configure --config /new/private/message-channels.json --core-config /new/private/official-service.json --state-dir /new/private/channel-data --port 8003
localpilot --home /new/private/channel-home channels doctor
localpilot --home /new/private/channel-home channels start adapter
localpilot --home /new/private/channel-home channels login wechat
localpilot --home /new/private/channel-home channels start qq
localpilot --home /new/private/channel-home channels start wechat
localpilot --home /new/private/channel-home channels status
localpilot --home /new/private/channel-home channels pending --channel CHANNEL --sender-id SENDER
localpilot --home /new/private/channel-home channels task --channel CHANNEL --sender-id SENDER --task-id ID
localpilot --home /new/private/channel-home channels stop qq
localpilot --home /new/private/channel-home channels stop wechat
localpilot --home /new/private/channel-home channels stop adapter
localpilot --home /new/private/channel-home channels uninstall --execute
```

这些是用户将来显式执行的命令；本轮未执行任何真实登录/连接。
configure 要求全新状态目录，并核对显式提供的受保护 Core 配置中的普通身份、路由和独立 Operator。
它不创建 Core 身份，不改 Core 配置，不申请新权限。运行前要在本机私下设置配置引用的环境变量。
JSON 配置只写环境变量名；不要把 Token、AppSecret 或二维码转贴到聊天。

QQ 额外需要 QQ_BOT_APP_ID / QQ_BOT_APP_SECRET。微信登录保存到新的受保护 state.json。
Node 子进程只得到各自平台凭据和入站密钥，不继承 Core Operator/模型凭据。
Python facade 只得到配置显式引用的服务凭据。平台凭据不交给 facade。
普通 Suite 的 list/status 和 GUI 升级不探测或安装 Node。渠道 run/doctor 单独检查 Node >=22.13、
原生 WebSocket、AbortSignal.any、精确 JSON 数字源和全部本地资源。
桥接只用 Node 内置模块，无 npm 依赖；模块缺失与 Node 缺失/过旧分别显示。

Suite 管理仅限自己记录的 PID、进程创建时间和完整命令行；身份不符不发送信号。
默认无常驻自动启动或自动重新连接。卸载只移除独立代码，保留所有配置、凭据和数据库。
实际失败时先 doctor/status；不打印原始远端错误、凭据或私密聊天。

## 安全与恢复边界

- macOS 只规范化固定的、root 拥有的 /var、/tmp、/etc 系统链接；
  规范化目标也必须是 root 拥有且不可被普通用户修改的目录。其它链接/Windows junction 拒绝。
  新状态目录必须 owner-only；已有不安全目录/文件拒绝，不自动 chmod 修补。
- SQLite 和 Node 状态/锁检查普通文件类型、属主、权限及硬链接数，读写使用 O_NOFOLLOW。
  可信祖先检查不等于对同一系统 UID 内任意恶意进程的隔离。
- 初始提交、决定与回复均先持久化意图。POST 的服务端 5xx 也保守保留 UNKNOWN，
  因为错误码不足以证明此前没有接受请求。普通鉴权/参数拒绝仍显示具体 HTTP 类别。
- 决定 UNKNOWN 的 hold 与决定指纹同事务保存；新决定 ID、重启或查询到 completed 均不能绕过。
  查询可核实任务状态，但不能声称丢失的批准响应已经确认。
  本候选没有自动解除 hold 或旧平台 blocked 状态的命令；需要人工独立对账。
- Node 普通关闭使用锁 inode 归属，旧对象重复 close 不删除后继进程的锁；
  info 只读，不占锁、不迁移/重写状态。非正常 SIGKILL 遗留锁保持 fail-closed，
  自动清除/迁移未实现，必须人工核实。不得随手删除旧真实桥接的锁。
- Python facade SIGINT/SIGTERM 停止接收新连接并等待已接收请求退出后关闭 SQLite；
  入站线程上限 16。高并发/故障下停止时长仍需实测。
- 渠道回执分列官方任务状态、成功工具收据、交付状态和独立 Verification。
  completed 表示官方任务终态；独立 Verification 默认 NOT_RUN，不能用模型文本或工具计数升格。
- 保存的 SQLite / state.json 包含私有回复或登录令牌，绝不能入库。
  现有真实平台账号、聊天、旧 JSONL 和旧 UNKNOWN 均不读取、不迁移、不重放。

## 合并限制

arm64 自动矩阵已通过，Intel 和完整 Desktop 边界仍保留未测。没有创建 Release，没有替换 APP。
维护者随后明确授权带已披露限制合入并安装本机；main/PR 已再次核对，原生 arm64 双 wheel 矩阵重跑通过。
详见 [合并与本机安装](channels-pr2-main-install-20261027.md)。
Intel 继续保留 NOT_RUN；维护者的合并决定不等同于 Intel 实测通过。
