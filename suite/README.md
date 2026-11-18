# LocalPilot Suite 0.2.0b34

2026-11-18 source candidate: Desktop 5.0.1-rc.18; Core 5.0.0b35; Suite 0.2.0b34; Companion 0.5.7b12; Channels 0.1.0a4. Linux adds platform capabilities and official pinned Node archives for x86_64/aarch64; x86_64 installation and execution were tested. Intel native qualification remains open. This is not a new Release. See [Linux implementation and evidence](../docs/development/LINUX_COMPLETION_20261116.md).

[公开 GitHub 桌面历史版本与可用下载](https://github.com/www080327-glitch/LocalPilot-OpenSource/releases) · [安装与边界](../README.md#简易快速安装)。本页为独立 Suite CLI，模块版本不随 Desktop 版本号变化。

当前协作模型配置可为伙伴指定只读探索和只读审阅职责，主 Super Agent 继续统筹；无职责配置保留原行为。见[配置与兼容性说明](../docs/development/TASK_STORAGE_SCHEDULING_20261117.md)。

Thin CLI and installation coordination for independently installed Core and Companion packages. This distribution contains no Agent Runtime or copied module source. It exposes `localpilot`; Core also works through `localpilot-core`, and Companion through `companion`.

Install the three reviewed wheels together, or use the root repository README for Git installation. Run `localpilot --help`, `localpilot init`, `localpilot doctor`, `localpilot start` and `localpilot companion start`. Model weights and credentials are supplied through existing local references and never included in this package.

For cached Qwen3.6-35B with the installed oMLX application, use `localpilot init --workspace /your/workspace --managed-qwen35`. Otherwise configure your existing local OpenAI-compatible service explicitly. The managed preset discovers a supported existing Companion 0.8B cache; it does not download models.

Each module can be upgraded or rolled back separately with explicit wheel files. Stop the affected service first. User data lives in a separate private data directory. API negotiation rejects incompatible services before task submission; ordinary tokens never approve tools.

See `docs/SUITE_CLI.md`, `docs/SUITE_INSTALL_UPGRADE_ROLLBACK.md`, `docs/SUITE_API_COMPATIBILITY.md` and `docs/SUITE_CACHE_ACCEPTANCE.md` for the scoped RC limits.

The earlier Desktop 5.0.0 integration used Core 5.0.0b20 and Companion 0.5.7b2. Current source versions are listed above; the root README and GitHub Releases distinguish source candidates from available packages. Historical RC reports keep their original scope. `localpilot maintenance apps --scan` diagnoses app copies and Core lifecycle; use a reviewed dry-run plan before reversible archive/Trash cleanup. macOS Core defaults to a user launchd job without KeepAlive or login autostart; `service-unregister` safely stops and unregisters it.

Channel GUI candidate: Desktop 5.0.1-rc.6; Core 5.0.0b20+channels.3; Suite 0.2.0b25; Companion 0.5.7b3; optional Channels 0.1.0a3. See ../docs/acceptance/channels-final-review-20261028/ACCEPTANCE.md for bounded qualification; public install and wipe admission remain NO_GO.

RC.7 personal installer candidate: Desktop 5.0.1-rc.7; Core 5.0.0b21+channels.3; Suite 0.2.0b26; Companion 0.5.7b3; optional Channels 0.1.0a3. Includes AIC source42816aca and a current-user macOS PKG. Ad-hoc signed, not notarized; qualification in desktop/docs/acceptance/rc7-oneclick-20261029/.
