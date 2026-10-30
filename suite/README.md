# LocalPilot Suite 0.2.0b21

[官方推荐桌面下载：LocalPilot Desktop 5.0.0](https://github.com/www080327-glitch/LocalPilot/releases/latest) · [安装与边界](../docs/releases/desktop-5.0.0/INSTALL.md)。本页为独立 Suite CLI，模块版本不随 Desktop 版本号变化。

Thin CLI and installation coordination for independently installed Core and Companion packages. This distribution contains no Agent Runtime or copied module source. It exposes `localpilot`; Core also works through `localpilot-core`, and Companion through `companion`.

Install the three reviewed wheels together, or use the root repository README for Git installation. Run `localpilot --help`, `localpilot init`, `localpilot doctor`, `localpilot start` and `localpilot companion start`. Model weights and credentials are supplied through existing local references and never included in this package.

For cached Qwen3.6-35B with the installed oMLX application, use `localpilot init --workspace /your/workspace --managed-qwen35`. Otherwise configure your existing local OpenAI-compatible service explicitly. The managed preset discovers a supported existing Companion 0.8B cache; it does not download models.

Each module can be upgraded or rolled back separately with explicit wheel files. Stop the affected service first. User data lives in a separate private data directory. API negotiation rejects incompatible services before task submission; ordinary tokens never approve tools.

See `docs/SUITE_CLI.md`, `docs/SUITE_INSTALL_UPGRADE_ROLLBACK.md`, `docs/SUITE_API_COMPATIBILITY.md` and `docs/SUITE_CACHE_ACCEPTANCE.md` for the scoped RC limits.

Current integration: Core 5.0.0b20, Desktop 5.0.0, Companion 0.5.7b2. See the root README and docs/releases/desktop-5.0.0 for the recommended Desktop release and scoped limits; historical RC reports are not current release claims. `localpilot maintenance apps --scan` diagnoses app copies and Core lifecycle; use a reviewed dry-run plan before reversible archive/Trash cleanup. macOS Core defaults to a user launchd job without KeepAlive or login autostart; `service-unregister` safely stops and unregisters it.

Channel GUI candidate: Desktop 5.0.1-rc.6; Core 5.0.0b20+channels.3; Suite 0.2.0b25; Companion 0.5.7b3; optional Channels 0.1.0a3. See ../docs/acceptance/channels-final-review-20261028/ACCEPTANCE.md for bounded qualification; public install and wipe admission remain NO_GO.

RC.7 personal installer candidate: Desktop 5.0.1-rc.7; Core 5.0.0b21+channels.3; Suite 0.2.0b26; Companion 0.5.7b3; optional Channels 0.1.0a3. Includes AIC source42816aca and a current-user macOS PKG. Ad-hoc signed, not notarized; qualification in desktop/docs/acceptance/rc7-oneclick-20261029/.
