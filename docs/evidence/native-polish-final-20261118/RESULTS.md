# LocalPilot PR #15 原生验收续作（2026-11-18）

**状态：NOT_RELEASE_READY。** 本轮补齐 Apple Silicon 上当前 `LocalPilot Test` 安装/升级/回滚/恢复，并在可启动 Chromium 的环境完成原有两项 Playwright 页面用例。仍有原生动画、真实 Intel Mac、Linux、R12 模型调用和安装态两小时 soak 门禁未通过或未执行；失败和缺设备项均保留。

## 来源与环境

- 仓库：`www080327-glitch/LocalPilot-OpenSource`；PR #15；分支 `codex/native-polish-final-20261116`。
- 被验收产品源码：交付 head `97dae142a2deccfb1ed0add0c2cd49b4b02a8fad`，Git tree `4becdaf178d79ef3253841e10f9bf4fd3a9f8b2b`。本轮提交只新增证据，没有修改产品源码。
- 当前主机：Apple Silicon `arm64`，macOS `27.0.1`（build `26A434`）；Node `v24.20.0`、npm `11.19.0`、Playwright `1.64.1`。Chromium 使用仓库锁定的 Playwright 浏览器缓存。
- 已安装候选：Desktop `5.0.1-rc.17` / Core `5.0.0b35` / Companion `0.5.7b12` / Suite `0.2.0b34` / Channels `0.1.0a4`。
- 主机上的实际构建/安装来源和文件树散列见 `INSTALL_MATRIX.json`；实际安装进程模块导入来自安装目录下 runtime 的 `site-packages`，独立 harness 不含产品源码，见 `SOURCE_IMPORTS.json`。Core 子进程环境与私有原始进程收据仅放在 `.private/`。

## 浏览器页面用例

在能正常启动 Chromium 的 Apple Silicon macOS 环境，通过仓库现有脚本执行，**2 项通过、0 跳过、0 失败**：

1. `optional worker roles preserve the chosen coordinator and configured efforts` — PASS。
2. `removing a partner or choosing it as primary clears both optional roles` — PASS。

运行命令和原始 Playwright JSON reporter 保存在 `.private/browser/`。没有更改用例断言；实际通过页面测试，不是只确认 Chromium 启动。Playwright 运行时无需 `npm ci`（node_modules 与 lockfile 依赖已安装），详见 `COMMANDS.md`。

## Test APP 安装矩阵

使用仓库 `scripts/install-local-app.py --test-app` 的 plan / execute / receipt 流程，在独立 `io.localpilot.desktop.test` 身份及用途标记为 `LocalPilot installation E2E` 的 0700 测试数据根下完成：

| 步骤 | 结果 | 关键核对 |
|---|---|---|
| rc.7 → rc.17 升级 | PASS | 旧版恢复包可验证；旧 APP 按流程移入废纸篓；用户数据未改 |
| rc.17 → rc.7 回滚 | PASS | 回滚包恢复到 rc.17 文件树；签名退出码 0；用户数据未改 |
| rc.7 → rc.17 恢复 | PASS | 最终版本、bundle ID、arm64、签名及候选树 SHA 均匹配 |

最终 Test APP 为 `LocalPilot Test 5.0.1-rc.17`。安装计划、执行收据、启动日志和停止记录位于 `.private/install/`。测试过程中保留了另一个验收的数据根；没有清理其数据。

回滚 ZIP 的第一次工作区内解包因 FinderInfo/File Provider 元数据导致签名检查失败。该失败被保留；随后按相同 `ditto -x -k` 流程解包到新建的本机 Cache 目录，签名与文件树 SHA 通过，没有剥离 xattr。详见 `ROLLBACK_EXTRACTION.json` 和私有失败日志。

## 桌宠与桌面交互

- 气泡输入焦点：PASS；合成字符出现在原生输入框内，随后清空，没有提交任务。
- 退出/隐藏：通过现有桌宠隐藏/显示控制 PASS；气泡标题栏 X 按钮未单独核验。
- 原生缩放路径：测试根内设置 1.0 → 1.2 时窗口从 240×220 → 288×264 逻辑点，恢复 1.0 后窗口回到 240×220。**UI 滑块本身 NOT_RUN**。
- 系统“减少动态效果”：开启时本机诊断 `edge.motion=false`，关闭后恢复 `true`；应用设置也已切换并恢复。系统偏好已恢复测试前状态。
- 六个锚点的原生窗口定位：PASS，单显示器、scale factor 2.0；位置和诊断明细见 `ANCHOR_RESULTS.json`。这不等于物理拖动测试。
- 物理拖动、多屏：NOT_RUN。只有一个内建显示器；当前角色没有可见边缘姿态，渲染透传指针事件。
- 可见动画 ≥24 Hz：FAIL。原始 6009 ms `measure_animation` 采样中，RETRACTING 与 PEEKING 可见变化均为 0，观测 0 Hz；角色资源仍为 pending / opacity 0。未用 rAF 回调率冒充可见动画帧率，也没有可录制的可见动画视频。主界面与边缘 pending 状态截图均已按用户授权纳入公开证据 `screenshots/`。

## Full R12 与安装态 Full + extended soak

在收到限定范围授权后，以原 Luna high 路径、原夹具、原 runner 重试 R12。未发生自动审批拒绝；调用在模型推理前收到 HTTP 401，耗时约 2.91 秒，0 模型调用、0 子任务、provider usage UNKNOWN；Core 已停止。原夹具 manifest SHA 与之前记录一致。没有因认证失败转用 Sol。结论为**失败于认证、工程结果未验证**，不将其说成模型能力失败或通过。见 `R12_RESULT_SUMMARY.json` 与 `.private/r12-luna-high/`。

随后在真实 rc.17 安装环境，用只含两份验收 runner 副本的独立 harness 启动 Full + extended 7200 秒 soak。父进程与实际 Core 子进程的产品模块均从已安装 runtime 的 `site-packages` 导入；源码目录不在 harness 或产品模块路径中。请求在约 2.07 秒因同一 HTTP 401 失败，0 心跳、无完成收据、无后续 `read_file` 收据、0 子任务/模型调用，usage UNKNOWN；owned Core 已停止。**两小时门禁未通过**。没有使用 Sol；认证错误不构成能力瓶颈。见 `SOURCE_IMPORTS.json`、`INSTALLED_SOAK_SUMMARY.json` 和 `.private/installed-soak-*`。

## 仍未完成 / 硬件缺项

- 真实 Intel Mac 原生构建和安装验收：**NOT_RUN**，本机是 arm64。
- 适用 Linux 原生构建和安装验收：**NOT_RUN**，本轮没有受支持 Linux 主机、系统包 helper 和 GTK/WebKitGTK/Rust 原生构建环境。
- 桌宠物理拖动、UI 滑块、多显示器、可见动画：未通过或 NOT_RUN，见上节。
- R12 真正模型执行：HTTP 401，工程结果未验证；等待用户提供新的、有效且权限受限的本地密钥文件路径后才能重跑。
- Full + extended 两小时安装态任务：HTTP 401 前置失败，0/240 心跳；完成收据缺失。
- 安装矩阵在 Apple Silicon 主机通过，不代表 Intel 或 Linux 平台通过。

保留状态 `NOT_RELEASE_READY`。本轮没有合并 PR、创建 Tag 或 Release。证据提交已推送到目标分支，并从 GitHub 读回确认 PR head；PR 仍为 open。
