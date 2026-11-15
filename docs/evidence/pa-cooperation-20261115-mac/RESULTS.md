# LocalPilot PR #11 本机续验

日期：2026-11-15（Asia/Shanghai）

仓库分支：`codex/pa-cooperation-20261115`

代码修复提交：`4492522463473901c610851a1a4926195770cb94`

起始 PR HEAD：`c3368f77742cf00d709cbfc334df9cb2473189a1`

既有受测运行代码：`71fc7c6d99cb6794c5a8e1e77f8141290157b79f`
平台：macOS 27.0.1，arm64，Swift 6.4.2，macOS SDK 27.2，Python 3.14.6，Node 24.20.0。

本报告补充，不替换 [本轮 Linux/云端证据](../pa-cooperation-20261115/RESULTS.md) 或此前失败记录。独立测试 APP 使用 `io.localpilot.desktop.test` 与独立 test root；日常 APP、PR #1/#9/#10、旧工作树和旧 evidence 未替换或删除。

## 本机结果

| 项目 | 状态 | 实测范围与限制 |
|---|---|---|
| 四组件候选与独立 APP 构建 | **PASS** | 全新 run 目录；4 组件 wheel 逐字节审计及 Python 资源审计通过；Test bundle、arm64、严格签名、ZIP 解包复核与 DMG 校验通过。 |
| 独立 APP 安装/重开 | **PASS（有限）** | 走 reviewed plan/execute；保留旧 APP 回滚 ZIP 并验证提取树哈希；新 APP 启动并显示既有 test profile。没有执行真实反向回滚或启动助手异常后的 GUI 交接。 |
| Rust、TypeScript、Vite、Vitest、文档 | **PASS** | Rust 42 PASS / 3 ignored；Vitest 68 PASS；TypeScript、Vite 与 docs 检查通过。Prettier 与 rustfmt 检查有既有格式差异，未全局格式化。 |
| Companion 会议/来源/训练聚焦 | **PASS（协议）** | 会议 14 PASS / 1 OS 权限项 SKIP；来源 20 PASS；训练 20 PASS。协议夹具不是实采音轨、真实来源问答或 LoRA。 |
| Playwright UI | **PASS** | 首轮 27/34，7 个 Companion 页面失败；trace 确认 UI 初始化的 `product_control/workspace_grants` 桥接夹具缺失，导致 `grants.find` 渲染异常。补回空授权列表后同套件 **34/34**。这是测试夹具修复，没有产品级防御改动。 |
| Core 真实本地模型 smoke | **PASS / 质量有限** | 隔离 Core → LM Studio 本地 OpenAI 兼容接口，真实模型回答 `7×8` 为 56；输出另含可见 `<think>` 段，要求仅数字未满足。模型仓库/revision 与 provider token usage/费用未核实，usage 保持 UNKNOWN。 |
| 真实本机工具权限矩阵 | **PASS** | Read-only 读成功且 shell 写被拒；Request-approval 显示真实审批卡片，人工拒绝后文件不存在；Workspace-write 用 `apply_patch` 写入并读回；Full-access 用受限 workspace Shell 写入并读回。仅操作独立测试 Workspace。 |
| 原生 SSE 409 | **PASS** | 对隔离 Core 的已完成合成任务请求快照 cursor + 1，实际 HTTP 409，`invalid_cursor`；没有修改任务。 |
| Daily APP 被 Test APP 计划拒绝 | **PASS（dry-run）** | 用实际 daily bundle ID `io.localpilot.desktop` 调用 test-only `upgrade desktop --app … --test-app`，在身份检查处以 `App identity differs from the selected installed entry` 拒绝；未写计划、未运行安装器。首次 `upgrade bundle` 尝试因缺少所需四组件 wheel 先行拒绝，原始失败保留。 |
| Companion 实际源问答 | **FAIL / NOT VERIFIED** | 合成 Codex 可见记录与 VTT 已导入并留在隔离 Companion。真实本地模型调用发生，但返回不完整或带工具响应，Companion 拒绝；无可审阅答案 ID，来源真实性/质量未通过。未把协议测试当真实问答成绩。 |
| 会议 mic/system/both 实采 | **BLOCKED：TCC 责任进程归属** | 从 Test APP 界面和隔离 CLI 两条入口测试 system 音轨。helper 在请求 Speech 权限时以 SIGABRT / exit `-6` 退出，0 段、`raw_audio_saved=false`、`cloud_fallback=false`。崩溃报告注明责任进程是桌面宿主 `ChatGPT`，不是已授权的 `LocalPilot Test` bundle；helper 的签名 Info.plist 本身含 Speech、Microphone 与 ScreenCapture usage strings。没有重置/编辑 TCC 数据库；mic/both、长会议轮换与静音停止未继续。 |
| 样本人工审阅、LoRA、adapter 推理 | **NOT_RUN** | Companion 没有成功的真实模型答案可供人工标注；未造标签、未训练或加载 adapter。 |
| 真实模型资格/正式 Harbor 对照 | **BLOCKED / NOT_RUN** | LM Studio model ID 与缓存仓库身份/revision 未建立可信映射；oMLX 缓存的 35B snapshot 为 20.429 GB、revision `38740b847e4cb78f352aba30aa41c76e08e6eb46`，但 tokenizer 与独立 smoke 未完成，模型未加载。VM 无 Docker，磁盘余量低于既定 15 GiB 余量；没有运行新 study 或旧 534 队列。 |
| 子 Agent、真实取消/恢复、五档来源、KV 冷热 | **NOT_RUN / 部分** | 已有会话任务含两个真实 Core 工具调用，但没有实际 Worker 子任务。只测试了本地路线；云端模型未配置，五档选择器可见不等于五档任务通过。未运行真实取消/UNKNOWN 恢复、冷/热 KV 或 oMLX 加载/卸载。 |
| 晚间问候/睡眠唤醒与 Intel | **NOT_RUN** | 未调整时钟或模拟睡眠；本机为 arm64，没有 Intel Mac。 |

四档权限是权限策略验收，不替代五档模型来源。Core、Companion、Suite 协议用例不替代真实模型成绩。旧 534 队列保持 `1 PASS / 3 FAIL / 13 ERROR / 517 无最终结果`，冻结源码 `1c06e97` 未动。

## 候选制品与哈希

本次 APP 构建 manifest 的 source commit 为 `c3368f77742cf00d709cbfc334df9cb2473189a1`，`source_dirty=true`；之后作为 `4492522` 提交的改动只涉及 Companion helper 构建、Test-only Tauri 隐私 plist 和 Playwright 桥接夹具。APP 内 4 组件 wheel 对应已审计源码：

| 制品 | SHA-256 |
|---|---|
| Core wheel | `7e474f8346535b88613be58a85f87d58cb90309033762001d820d4610caa37f3` |
| Channels wheel | `ff6724feef826186df45ddcbce5128ec6fa2b953e9d2f67ec5949c95ee912885` |
| Companion wheel | `39828e4db4737bc0c25935269d667b1319c785c31e64d03e387006641f80392e` |
| Suite wheel | `1f6cefc194d70c5912b557bea2502fe8bca41d743d108d9224b3804f06a33d13` |
| 独立 APP ZIP | `50156aca04f1f4af5a5c3be08d308cb95a65bc021f786468faecd2b718991a76` |
| 独立 APP DMG | `5ec41b34823ac108b24cad5b84dcafeaf9e2588e8bbb8d560c1a40ed7c371d99` |
| MeetingTranscriber 源码 | `11efaf51d89a69c598990555a92f8a1428cf9d8093200a9ef934c15bdb595462` |
| MeetingTranscriber 实际 helper | `25639c1a95cc7417c4f0a09d315a2a7296ff53e88d2de0f7ab580485f487f20c` |

APP run：`desktop/release/test-v5.0.1-rc.7/20261115-232524-47179/`。签名为 ad-hoc、未公证；bundle ID `io.localpilot.desktop.test`，架构 arm64。Test Info.plist 在该包中包含麦克风、Speech 和 ScreenCapture 用途说明。实际安装收据与旧 APP archive/restored-tree 哈希保留在私有收据中。

## 命令和日志

关键命令（均在仓库现有流程内）：

```sh
cd desktop
LP_GUI_TEST_CONFIG=src-tauri/tauri.test.conf.json \
LP_GUI_USE_INSTALLED_DEPS=1 \
CARGO_TARGET_DIR="$HOME/.cache/localpilot-desktop/target-pa-cooperation-20261115" \
./scripts/build-macos.sh

npm test
npm run build
./node_modules/.bin/tsc --noEmit --noUnusedLocals --noUnusedParameters
npm run check:docs
npm run test:ui -- --reporter=line

cargo test --locked --manifest-path src-tauri/Cargo.toml
```

原始完整日志、trace、构建 manifest、安装计划/收据、错误 `.ips` 的本地系统路径与模型配置均在 worktree 的 `docs/evidence/pa-cooperation-20261115-mac/.private/` 和被 `.gitignore` 忽略的 `desktop/docs/evidence/…/.private/` 下，仅本机保留，没有加入公开提交。重点日志名：`test-app-build-tcc-plist.log`、`test-app-install-tcc-{plan,execute}.log`、`playwright-ui-r2.log`、`rust-tests-final.log`、`companion-meeting-tests.log`、`meeting-system-smoke-retry.log`、`meeting-system-ui-status-start.json`、`sse409-native.json`、`daily-app-as-test-plan-r2.json`。首次 Harbor 夹具错误与原有 UI 失败历史均未覆盖。

## 隐私与范围

没有把任何原始音频/视频、凭据、用户目录配置或模型文件放入公开报告；测试录音状态均为零段。没有改动、删除或搬移旧 534 任务、模型、缓存、UNKNOWN、原工作树或旧 evidence；没有合并、发布 Release、替换日常 APP、提交比赛表单或发对外消息。PR 保持 Draft。
