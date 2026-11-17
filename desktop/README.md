# LocalPilot Desktop

2026-11-17 source candidate: Desktop **5.0.1-rc.17**; Core **5.0.0b35**; Suite **0.2.0b34**; Companion **0.5.7b12**; Channels **0.1.0a4**. Linux 原生桌面、离线模块资源和 DEB 构建入口已接入；本轮构建基线为 Debian 13 x86_64 / 系统 CPython 3.13。Intel Mac 仍待物理设备验收。本源码候选不是已发布的新 Release。

## 快速安装

在 [公开 Release](https://github.com/www080327-glitch/LocalPilot-OpenSource/releases) 选择实际存在、匹配系统及架构的资产。当前 Linux RC15 源码候选需要按 [Linux 构建与验收指南](docs/development/LINUX_20261116.md) 从源码构建；不要把下面的文件名当成已经发布的下载链接。[RC14 构建与原生短验记录](docs/evidence/audit-20261117-desktop/final-package-rc14/RESULTS.md)保留原制品的身份和结果；重新构建后应核对该次输出的 `SHA256SUMS`，不能套用历史制品哈希。

Linux 构建成功后，在含有 `SHA256SUMS` 和 DEB 的输出目录执行：

```sh
sha256sum -c SHA256SUMS
sudo apt install ./LocalPilot-5.0.1-rc.17-linux-x86_64.deb
localpilot-desktop
```

首次设置可选择现有的本机 OpenAI 兼容模型端点，也可在“连接云端模型”中选择 DeepSeek 或 OpenAI、填写模型和密钥，再点“保存并连接”。设置页也提供同一入口；OpenAI 默认 `gpt-6-luna`，保存配置不会发送模型任务。安装包不含模型权重；CPU / CUDA 推理由用户选择的本机服务提供。不要在 Linux 安装 macOS APP、使用 MLX 文件夹入口，或把 x86_64 DEB 安装到 ARM 设备。

独立测试构建使用 `LocalPilot-Test-5.0.1-rc.17-linux-x86_64.deb`、命令 `localpilot-desktop-test` 和身份 `io.localpilot.desktop.test`。启动前须按[根 README 的测试安装步骤](../README.md#linux-桌面候选)创建私有测试根目录和 `test-owner.json`，并显式传入 `LP_INSTALL_TEST_ROOT`；仅使用相同 Bundle ID 下的新后台目录不能证明旧版本的 WebView 隔离。RC.9 的存储隔离与认证恢复实现见 [恢复说明](docs/development/SESSION_WEBVIEW_RECOVERY_20261116.md)。Linux 桌面升级/降级由系统包管理器处理；设置中的组件事务仍独立管理 Core、Companion 和 Suite。该 DEB 依赖构建时的系统 Python **同一小版本**；Debian 13 x86_64 产物不承诺兼容 Debian 12 或其他发行版。RC14 x86_64 已完成提取运行的原生短验；Ubuntu 24.04 arm64 的独立 RC14 包已完成 RC13 夹具首装、升级、降级和恢复，详情见[原始安装证据](docs/evidence/audit-20261117-desktop/native-delivery-20261117/RESULTS.md)。RC16 的 schema 3 会话分段见[长期会话分段](../docs/development/PERSISTENT_SESSION_SEGMENTS_20261117.md)。RC17 增加任务逐条存储和模型职责选择，仍需按当前候选重新做原生交互验收；见[本轮实现](../docs/development/TASK_STORAGE_SCHEDULING_20261117.md)。

macOS 安装与隔离测试继续使用 [现有安装与回滚流程](../docs/development/MAC_PORTABILITY_20261114.md)；Intel 构建见 [Intel Mac 指南](docs/development/INTEL_MAC_20261116.md)。尚未核验的下载资产、安装、回滚或模型能力不作为通过项。

## 平台范围

Linux 使用标准窗口、桌面托盘、文件选择器、`xdg-open` 和普通 WebView 桌宠交互。macOS 的 AppKit、Liquid Glass 和透明像素点击穿透仅在 macOS 启用。Linux Companion 的 AT-SPI 只读观察与可选本地会议转写不等于 macOS Computer Use 的电脑操作能力。完整状态、系统依赖和剩余真机检查见 [Linux 指南](docs/development/LINUX_20261116.md)。

## 既有 macOS 记录

**历史 macOS arm64 5.0.0 版本说明（公开下载以 GitHub Release 实际资产为准）**，桌宠实现沿用已人工复核的 dev.23-edge.4。完整桌面使用 `LocalPilot.app` / `io.localpilot.desktop`；配套独立 Core **5.0.0b20**、Suite **0.2.0b21**、Companion **0.5.7b2**。

[公开 GitHub 历史发行与可用下载](https://github.com/www080327-glitch/LocalPilot-OpenSource/releases) · [源码与版本留存规则](../docs/development/GITHUB_RELEASE_HISTORY_POLICY.md)。历史 5.0.0 下载资产原属旧私有发行，尚未核验迁移到公开 Release；不要把新公开地址拼成未经验证的同名 DMG/ZIP。

[测试安装与回滚](../docs/development/MAC_PORTABILITY_20261114.md) · [当前桌面源码与验收边界](docs/development/PA_CONTINUATION_20261115.md) · [本机 Work 提示词](../docs/development/WORK_PA_COOPERATION_20261115.md) · [推荐版本清单](recommended-release.json) · [总说明](../README.md)

**2026-11-16 Intel Mac 更新：** macOS 15+ 的 Intel 首次设置和模型库已接入本机 OpenAI 兼容端点，可读取模型列表、保存真实上下文配置，并在任务结束后显式重启服务应用。新增依赖获取和原生源码构建路径；尚无本轮验收通过的 Intel APP / DMG，不能安装 arm64 包代替。具体构建步骤、CPU 模型接入及待验收项见 [Intel Mac 指南](docs/development/INTEL_MAC_20261116.md)。

桌宠支持六个边缘 Anchor、缩回/重新探头、底部潜水鲸尾、真实左右拖动姿态、独立角色比例、透明穿透和局部原生 Liquid Glass。小气泡点击展开现有聊天窗；工具委派仍复用 Core 授权、提交账本和 SSE，不产生第二套 Runtime。个人角色素材与姿态包不随源码或制品分发。

保留现有三栏 GUI，标准/极简 Agent 共用 Core。正式下载包含离线独立模块，未包含模型、用户状态或凭据。首次使用从完整桌面进行设置，开启角色需使用显示角色入口；本机历史 Test 应用数据不会自动迁移到正式身份。

构建使用 `LP_GUI_USE_INSTALLED_DEPS=1 scripts/build-macos.sh`；先准备并核验 `src-tauri/bundled-backends/`。只有隔离原生验收才传 `LP_GUI_TEST_CONFIG=src-tauri/tauri.test.conf.json`，该 Test 包不是默认下载。所有构建经过同一构建锁和一个 worker；发行目录只保留归档，签名 App 位于共享构建槽。

本源码仓库已公开；仅已经过校验的发行资产在公开 Release 提供下载。macOS 15+；Liquid Glass 需要 macOS 26+，其它系统降级。签名为 ad-hoc，未公证；干净 Mac、多显示器、全部原生矩阵与模型质量未获完整验收。公开树中的[既有独立测试 APP 记录](../docs/evidence/nationals-20261114-head-retest/RESULTS.md)与[本轮 Companion 检查](../docs/development/COMPANION_PA_20261114.md)分别说明对应版本和限制；缺失的早期附件不作为本轮验收证据。推荐发行不是全面生产认证，发布不会替换本机日常 App。

Channel GUI candidate: Desktop 5.0.1-rc.6; Core 5.0.0b20+channels.3; Suite 0.2.0b25; Companion 0.5.7b3; optional Channels 0.1.0a3. Final review: docs/acceptance/channels-final-review-20261028/ACCEPTANCE.md. The original seven-volume recovery set remains in docs/acceptance/channels-onboarding-20261027/RECOVERY_SET.json. Public installation and wipe admission remain NO_GO.

RC.7 personal installer candidate: Desktop 5.0.1-rc.7; Core 5.0.0b21+channels.3; Suite 0.2.0b26; Companion 0.5.7b3; optional Channels 0.1.0a3. Includes AIC source42816aca and a current-user macOS PKG. Ad-hoc signed, not notarized; qualification in desktop/docs/acceptance/rc7-oneclick-20261029/.
