# LocalPilot Desktop 5.0.0

**官方推荐的 macOS arm64 下载版本**，桌宠实现沿用已人工复核的 dev.23-edge.4。完整桌面使用 `LocalPilot.app` / `io.localpilot.desktop`；配套独立 Core **5.0.0b20**、Suite **0.2.0b21**、Companion **0.5.7b2**。

[默认下载 DMG](https://github.com/www080327-glitch/LocalPilot/releases/latest/download/LocalPilot-5.0.0-arm64.dmg) · [APP ZIP](https://github.com/www080327-glitch/LocalPilot/releases/latest/download/LocalPilot-5.0.0-arm64.app.zip) · [最新推荐 Release](https://github.com/www080327-glitch/LocalPilot/releases/latest) · [校验和](https://github.com/www080327-glitch/LocalPilot/releases/latest/download/SHA256SUMS)

[安装与回滚](../docs/releases/desktop-5.0.0/INSTALL.md) · [更新说明与验收边界](../docs/releases/desktop-5.0.0/RELEASE_NOTES.md) · [推荐版本清单](recommended-release.json) · [总说明](../README.md)

桌宠支持六个边缘 Anchor、缩回/重新探头、底部潜水鲸尾、真实左右拖动姿态、独立角色比例、透明穿透和局部原生 Liquid Glass。小气泡点击展开现有聊天窗；工具委派仍复用 Core 授权、提交账本和 SSE，不产生第二套 Runtime。个人角色素材与姿态包不随源码或制品分发。

保留现有三栏 GUI，标准/极简 Agent 共用 Core。正式下载包含离线独立模块，未包含模型、用户状态或凭据。首次使用从完整桌面进行设置，开启角色需使用显示角色入口；本机历史 Test 应用数据不会自动迁移到正式身份。

构建使用 `LP_GUI_USE_INSTALLED_DEPS=1 scripts/build-macos.sh`；先准备并核验 `src-tauri/bundled-backends/`。只有隔离原生验收才传 `LP_GUI_TEST_CONFIG=src-tauri/tauri.pet-test.conf.json`，该 Test 包不是默认下载。所有构建经过同一构建锁和一个 worker；发行目录只保留归档，签名 App 位于共享构建槽。

仓库私有，下载需已有访问权限。macOS 15+；Liquid Glass 需要 macOS 26+，其它系统降级。签名为 ad-hoc，未公证；干净 Mac、多显示器、全部原生矩阵与模型质量未获完整验收。[历史集成证据](../docs/integration/20261025/ACCEPTANCE.md)与[桌宠验收](../docs/acceptance/edge-pet-20261026/ACCEPTANCE.md)保持版本边界。推荐发行不是全面生产认证，发布不会替换本机日常 App。

Channel GUI candidate: Desktop 5.0.1-rc.6; Core 5.0.0b20+channels.3; Suite 0.2.0b25; Companion 0.5.7b3; optional Channels 0.1.0a3. Final review: docs/acceptance/channels-final-review-20261028/ACCEPTANCE.md. The original seven-volume recovery set remains in docs/acceptance/channels-onboarding-20261027/RECOVERY_SET.json. Public installation and wipe admission remain NO_GO.

RC.7 personal installer candidate: Desktop 5.0.1-rc.7; Core 5.0.0b21+channels.3; Suite 0.2.0b26; Companion 0.5.7b3; optional Channels 0.1.0a3. Includes AIC source42816aca and a current-user macOS PKG. Ad-hoc signed, not notarized; qualification in desktop/docs/acceptance/rc7-oneclick-20261029/.
