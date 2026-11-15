# Personal Agent 产品入口与 macOS 维护补齐（2026-11-15）

本记录描述 `codex/pa-completion-20261115` 上的实现与本环境证据。真实模型质量、macOS 原生运行、Intel 性能与签名资格独立验收。不得把脚本/HTTP/浏览器预览通过称为原生产品通过。

## 已实现的产品流程

### 统一 GUI / Core / Companion / Suite / Channels 升级

设置 → 软件更新 → **统一升级与回滚**。可选择整个解包 APP、多个独立组件 wheel 或单独 GUI；整个 APP 模式精确取其资源目录中的四个组件 wheel。每个将被更新的已安装组件必须有对应当前版本的回滚 wheel。

Suite 为这次操作建立私有计划目录 `HOME/upgrades/upgrade_<id>/`，记录当前/目标版本、Python 与 APP 路径、Bundle ID、组件组合依赖、目标/回滚 wheel SHA256、活动服务和消息平台代码快照。wheel 复制到计划目录，之后重新核对这些副本与已安装版本，用户只需在完整计划上进行一次最终执行确认。

- APP 安装实现已移到 `localpilot_suite.app_install`。原 `desktop/scripts/install-local-app.py` 是兼容包装器，保留 `--source / --test-app / --plan / --execute / --receipt` 及原隐藏参数 `--desktop-link`。
- 日常身份只写 `~/Applications/LocalPilot.app`；测试身份只写 `~/Applications/LocalPilot Test.app`。历史计划仍按当前 APP 的 Bundle ID 核对；连接同一 Suite 的测试 APP 不能执行日常 APP 历史替换计划。原 APP 先归档、解包复核，再将退役或失败 APP 移入废纸篓；不新增桌面替身、不删除应用数据。
- 整体更新顺序是组件 pip 安装 → 新进程导入、模块版本及 API 1.0 验证 → Channels 独立运行目录 → APP。安装使用离线 `--no-index --no-deps`，不主动下载依赖。
- Channels 既包含独立 Python 分发，也包含 QQ／微信或 CLI 建立的运行目录。更新复用既有 `channels install`，旧 `runtime` 与 `installation.json` 留在 `code-archives`。配置、消息数据库、UNKNOWN、账号和授权保持原位，渠道不会自动重连。`channels-wheel.json` 指向这次审阅并保留的 wheel，后续组件检查以此 SHA256 为准。
- 每个修改阶段先写回执。失败按反向恢复；独立 Channels 最后恢复。旧 Core wheel 若同时拥有 Channels 包，计划强制包含其独立目标与回滚 wheel，即使尚未执行到 Channels 安装阶段，也在旧 Core 恢复后重装确切 Channels 旧包；pip 成功但导入/API 检查失败也触发回滚。导入与 pip 日志保留在计划目录。旧升级回执不能覆盖其后又安装的其他组件版本或 APP。
- Core、Companion 以及已安装的渠道进程必须先停止。维护流程不会自动终止活动任务，不清除 UNKNOWN，不重新提交任务。
- 涉及 APP 替换时，Suite 独立助手等待当前 GUI 退出，然后完成替换/回滚并重开应用。Suite 的 Python 必须已搬移到 APP 之外的独立组件目录。重开使用 `--maintenance-return`；本次启动跳过旧的自动 Core 恢复，先让用户查看回执，再显式恢复服务。
- 完成回执幂等返回，重复执行不会重装；失败或中断回执需要先检查或回滚。助手未能完成时的 `handoff-error.json` 也在 GUI 历史入口可见。

CLI 示例（占位路径需要换为本机审阅过的真实路径）：

```sh
localpilot --home "$LP_TEST_HOME" --json upgrade all \
  --wheel /reviewed/core-new.whl --previous-wheel /reviewed/core-old.whl \
  --wheel /reviewed/companion-new.whl --previous-wheel /reviewed/companion-old.whl \
  --wheel /reviewed/suite-new.whl --previous-wheel /reviewed/suite-old.whl \
  --wheel /reviewed/channels-new.whl --previous-wheel /reviewed/channels-old.whl
localpilot --home "$LP_TEST_HOME" --json upgrade status
localpilot --home "$LP_TEST_HOME" --json upgrade all --plan upgrade_REVIEWED_ID --execute
localpilot --home "$LP_TEST_HOME" --json upgrade all --plan upgrade_REVIEWED_ID --rollback
```

APP 模式使用 `upgrade bundle --app '/reviewed/LocalPilot Test.app' --test-app`，另提供四个 `--previous-wheel`。在 GUI 中执行 APP 模式才会自动进行“退出当前 GUI、等待、换包、重开”的交接；普通 CLI 的直接执行要求已退出目标 APP。

### 新建协作 Agent 与本机 CPU 服务入口

模型库 → **模型端点与多 Agent 配置**。

- 协作 Agent 选择一个主模型、多个不同的已注册子模型以及五档来源策略，生成新的 `cooperation.routes` 配置。只接受同一已授权工作区、可使用工具、非托管特殊模型且不带实验 Computer Use 的路由。
- 新建协作路由之前检查**已安装 Core 的能力清单**是否声明 `route_orchestration_v1`，不以相同版本字符串推断支持。
- 新路由有显式主/子 Agent 预算。异步首次开启时写共享资源限制，本机模型并发为 1、云模型并发为 2；已有所有路由显式保持 `sync`。已有顶层异步策略不被改写。
- 现有路由不被替换，已有任务、会话和恢复指纹保持；另存旧配置备份。保存不会停止或启动 Core，不发推理请求；用户等待活动任务结束后通过既有服务按钮重启。
- 本机端点入口只接受显式 loopback OpenAI 兼容地址、模型 ID 和真实上下文上限；新增 `local-openai` 路由，可选把 Companion 配成 `local-http`。这条路径可连接 CPU 推理服务，无 MLX 依赖；加速和 CPU 回退由所连接的推理服务自行检测和执行。Intel 不被简单等同为“MPS 永远不可用”。
- 配置完成结果明确给出 `connection=NOT_PROBED` 与 `inference=NOT_RUN`。注册可用路由不证明模型已加载或真实工具调用成功。
- 完成任务的本地/云请求比例优先采用 Core 的 `source_mix`，其中包含子代理实际发出的调用。无 usage 不计算 token 百分比；五档配置不是固定百分比。

### Companion 来源、会议与审阅样本

设置 → Companion 独立设置。

- 原生文件/文件夹选择后，直接通过认证命令注册 Codex 可见用户/助手文本，或 TXT/Markdown/VTT/SRT 会议文本。用户明确选择的来源持续同步；可查看覆盖和部分失败、立即同步、停用/恢复授权、撤销并移除关联记忆。
- 会议控制通过 `meeting_start / meeting_stop / meeting_status` 接入 Companion。默认不启动，用户选择麦克风、系统音轨或两者后显式开始。全局状态条在关闭设置后仍显示当前采集并可停止；请求结果不确定时显示待确认，不自动再次开始。
- App 常驻状态 hook 读取 Companion 的真实采集状态；重启后的 `interrupted` 不显示成正在录制。原生 helper、ScreenCaptureKit、TCC 与设备上语音识别属于 Mac 验收，不由 UI 推断成功。
- 主 APP 与独立测试 APP 的 Info.plist 已加入准确的麦克风和本机语音转写用途文案。不会由前端绕过系统权限。
- “导出已审阅样本”调用 `training_export`，只导出通过样本接口显式保存的问答。按钮不生成标签、不训练模型。输出的独立文件可能含用户私有文本；来源撤销后的再次导出由 Companion 重新检查授权。实际训练使用 Companion 的显式 CLI。

## App 职责拆分

- `useTaskState.ts`：任务快照、消息、SSE 增量去重与修复、watch/unwatch、活动任务轮询。
- `useServiceConnection.ts`：服务身份与模型目录、历史加载、重连与一次启动恢复、维护返回例外。
- `useSessionRecovery.ts`：按真实 Session 汇聚任务视图、同主体草稿恢复、当前 Session 模型、宠物任务交接。恢复视图不伪造服务任务、不重放工具。
- `useCompanionMeeting.ts`：会议状态与用户显式控制，生命周期独立于设置弹窗。
- 统一维护、模型配置、来源和会议控件是独立组件。App 继续负责页面组合、用户交互与现有偏好，无另建 Agent Runtime。

## Intel 构建路径

`build-macos.sh` 接受 **同架构原生构建**的 arm64 或 x86_64，保留单 worker 和版本化归档流程。新增工具不把 arm64 wheel 改名为 x86_64。

1. 在目标架构 Mac 使用其原生 Python 3.14，准备四个组件 wheel 以及基线锁要求的同版本依赖 wheel。
2. 用实际本地 wheel 生成新架构锁并审阅来源。生成器只记录实际 SHA256 与平台 tag，不证明第三方构建来源：

   ```sh
   python3 desktop/scripts/lock-runtime-dependencies.py \
     --wheels /reviewed/intel-dependencies --arch x86_64 \
     --out /reviewed/runtime-dependencies-x86_64.json
   ```

3. 通过原流程准备**新的空资源目录**，明确传锁：

   ```sh
   python3 desktop/scripts/prepare-bundled-backends.py \
     --wheels /reviewed/component-wheels --dependencies /reviewed/intel-dependencies \
     --dependency-lock /reviewed/runtime-dependencies-x86_64.json --arch x86_64 \
     --channel-runtime /reviewed/node-v22.23.4-darwin-x64.tar.gz
   ```

4. 构建时设置 `LP_GUI_DEPENDENCY_LOCK` 为上述已审阅锁，再使用 `desktop/scripts/build-macos.sh` 和现有显式测试配置。macOS 原生打包器依主机架构命名 APP ZIP/DMG/manifest，检查每个 Mach-O 含目标架构；四组件 wheel 的 Python 文件必须和当前源码一致且不能重复归属，Core 不能再拥有 Channels entrypoint 或资源；Python 与 Node 都不能混入另一个架构。Node 复用 Suite 已有的两个官方归档固定哈希。
5. PKG 支持目标架构与 `--test-app`，从 APP 的当前版本生成安装版本，保持当前用户安装域、不请求提权。Release 选择按 GUI 运行架构筛选。

现有 arm64 锁在 x86_64 下会明确拒绝。这里没有真实 Intel wheel、Mac SDK、运行时或模型，**Intel APP/PKG 构建、原生启动、CPU 推理性能及真实模型都是 NOT_RUN**。最低 macOS 版本仍按现有产品设置为 15.0，未擅自降低其 API 要求。

## 本环境验证

| 范围 | 已观察结果 | 说明 |
|---|---|---|
| Suite 全量（最终快照） | 101 PASS，1 SKIP，共 102 | 46.508 秒；SKIP 是 macOS 固定系统路径别名 |
| 统一组件/Channels 升级 | 12 PASS | 真实临时 venv、真实 pip、真实 wheel/导入；全组件安装后导入失败回滚、Channels 缺资产回滚、旧回执拒绝覆盖后续版本、已退出 GUI 失败回执、旧 Core 重复归属与早期失败最后恢复 Channels |
| 配置新路由 | 5 PASS | 真实私有配置、真实 Core/SQLite Session 创建与重启；旧指纹保留、新异步路由生效，模型无推理 |
| APP 临时目录交换 | 11 PASS | 保留日常 APP；成功后的显式回滚、验签/注册失败路径。原生命令边界替代，不等于 Mac 签名通过 |
| 目标架构依赖锁 | 3 PASS | 实际临时 ZIP/metadata/hash；arm64/Linux wheel 不可假充 Intel Mac |
| Desktop TypeScript/Vite | PASS | 包含新维护、来源、配置与会议控制 UI |
| Desktop Vitest | 54 PASS | 真实 Session 视图恢复 3 项；新子代理 source mix 1 项 |
| Rust 编译/格式 | NOT_RUN | 容器没有 cargo；`cargo fmt` 返回 command not found |
| 原生 APP、会议音轨、Intel 实机 | NOT_RUN | Linux 环境无 macOS SDK/TCC/音轨 |
| Playwright 原生替代 | NOT_RUN | 本轮未把浏览器预览用作原生验收 |

独立只读审查还发现并修复：历史计划身份检查遗漏，以及 GUI 已退出的正常等待分支中 execute 异常未写助手失败回执。前者加入共享 Rust 判断测试（本环境 NOT_RUN），后者由真实退出子进程与旧计划失效的 Linux 回归覆盖。

完整本机日志位于工作目录：`validation/mac-portability-20261115-suite-final.log`、`validation/mac-portability-20261115-desktop-final.log`、`validation/mac-portability-20261115-install.log`、`validation/mac-portability-20261115-architecture.log`。这些是 Linux 与临时夹具证据，不是 Mac 原生产品资格。

最早一次配置回归的清理器重复 suspend 已关闭的测试 Session，产生 1 ERROR 与未关审计文件警告；清理器改为检查 closed 并关闭 access 后，5 项全通过。不是产品恢复断言失败。更早的升级夹具曾用 `>=5` 错误匹配 `5.0.0b1`；将合成夹具要求写准确后，真实 pip 路径通过。

## 本机 Work 交接提示词

在当前仓库真实 HEAD 上继续，不复述已完成的旧轮次验收，也不替换日常 APP。先读 AGENTS.md、desktop/AGENTS.md 与本记录，记录 HEAD、dirty 状态和当前进程。仅使用隔离测试身份 `io.localpilot.desktop.test`、独立数据/工作区；不得删除真实用户数据、模型、旧 APP、日志或 UNKNOWN。

1. 在现有 Mac 工具链运行 `cargo fmt --check` 和有意义的 Rust 测试/编译，修复本轮 Native IPC/`upgrades.rs` 接入的真实编译问题。不要手改生成权限或构建产物。前端运行 `npm run build`、`npm test`；只对新入口补有意义的原生交互验证。
2. 使用现有完整组件和依赖材料重建新的测试 APP 归档。保留旧独立组件 Python 路径、当前四个组件原版本 wheel 与原 APP；确认测试 APP 安装目的地和日常 APP 哈希。
3. 从 GUI 统一升级入口审阅并执行 GUI + 四组件计划：保存版本/路径/SHA256/活动服务截图与回执；确认未自动终止活动任务。安全停止后检查当前 GUI 退出、独立助手换包、目标 GUI 重开、Core/Companion/Channels 保持待显式恢复。检查原 Session、原请求、工具收据、幂等 key 和 UNKNOWN 字节/语义保持。
4. 不重复旧的三组件 pip 回滚与四类 APP 故障用例；重点补**新的组合事务**，至少覆盖 Channels 独立运行目录失败后整组回滚、组件导入验证失败、旧 Core 包同时拥有 Channels 时的完整/早期失败回滚、助手启动或交接失败后的历史入口，以及已更新到下一版本时旧回执拒绝覆盖。原数据不改、失败材料不丢、渠道不自动重连。用临时受控包/临时安装目录制造失败，不破坏日常安装。
5. 在模型库配置一个现有本机 OpenAI 兼容端点及真实 model/context，必要时让 Companion 使用 local-http。检查它只新增路由、不启动 MLX、不强制下载；明确重启后依次记录注册、连接发现、已加载、真实推理和工具调用的证据，不相互替代。
6. 用同工作区多个实际可用模型新建协作路由，检查五档策略、async 限额与主/子预算。已有会话重启后保留旧指纹；新路由能委派真实子 Agent，观察真实模型来源比例、取消与 UNKNOWN；真实模型不可用项标 NOT_RUN，不以脚本模型替代能力结论。
7. 原生选择受控 Codex/会议文本目录，检查来源首次同步、持续变化、部分覆盖、停用、恢复、撤销后即时不可检索。不要扫描未选择的私人目录；原文与私有导出只保留本机脱敏证据。
8. 编译并运行 Companion 的原生会议 helper；依次检查 mic/system/both 的权限许可、拒绝、设备上识别不可用、停止、APP 设置关闭后的全局停止条、断联未知和重启 interrupted。音轨状态分别留证；只有真正捕获并得到文字才能记 PASS。不得用合成 NDJSON 宣称真实麦克风或系统音轨成功。
9. 如果有 Intel Mac，使用真实 x86_64 Python、逐项审阅的 x86_64/universal2 wheel 和独立生成的依赖锁，走原生构建/归档/安装/重开与 CPU 服务推理。没有 Intel 机器或合格依赖就保留 NOT_RUN，列具体缺少物，不用 arm64 制品改名冒充。
10. 汇总 PASS/FAIL/BLOCKED/NOT_RUN、命令、版本、材料路径与失败日志；不合并、不发 Release、不提交比赛表单或对外消息。
