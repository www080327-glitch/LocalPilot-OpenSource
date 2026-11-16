# 最终 Linux 包原生启动冒烟（2026-11-16）

## 结果

**PASS。** 新包在全新、独立的 C 测试目录中通过真实 Tauri/WebKitGTK 首次设置，离线安装包内组件并连接 Core，主界面实际显示 **Core 5.0.0b26**。没有配置模型端点、下载模型权重、提交任务或连接消息账号。结束时按候选哈希、进程归属和 C 根目录核对后停止本轮实例，回执为 `STOPPED`、`owned_remaining=[]`；桌面只剩原终端。

本轮使用提取后的 DEB 和既有只读 WebKit helper overlay，保留 WebKit sandbox，**没有做系统级 DEB 安装**。没有再次运行 A/B 隔离场景，也没有修改 A/B 测试根目录或上一层的 45 文件清单。

## 精确包身份

| 项目 | 受测身份 |
| --- | --- |
| Desktop | 5.0.1-rc.9，`io.localpilot.desktop.test` |
| Core / Suite / Companion / Channels | 5.0.0b26 / 0.2.0b31 / 0.5.7b7 / 0.1.0a3 |
| 构建源码提交 | `59fad12de6f57006fc7510805af2dfd1718c16ea` |
| DEB | `LocalPilot-Test-5.0.1-rc.9-linux-x86_64.deb`，114590266 字节 |
| DEB SHA-256 | `4faf7b91de548355aa717800d2f38fc65cccc8a7e87d501f36c1e3312b29a587` |
| 实际运行 ELF SHA-256 | `6cb3172ca81b9a8eeedf22f69d091585d19d1a157682f5ada8ce7bba43d1e11a` |
| 构建输出目录 | `validation/package-b26-b7-b31-uZQqOv/build-source/desktop/release/linux-test-v5.0.1-rc.9/20261116-224140-69/` |
| 本轮独立目录 | `validation/native-final-smoke-20261116/profile-c/` |

DEB 在提取前重新计算哈希，与构建报告一致。实际 ELF 与上一轮完整 A/B、重开及路径别名验收的 ELF 字节相同；新包更换了后端组件，因此本轮单独核对新资源安装和服务启动，不把上一轮旧后端结果改写成新整包结果。构建报告保留 `source_dirty: true`，本记录不把提交号当作干净工作树证明。

## 实际原生操作与交叉核对

| 检查 | 结果及证据 |
| --- | --- |
| 全新 C 根目录首次打开 | PASS；真实窗口显示 RC.9 首次设置及 Linux 说明。见 [首次运行截图](screenshots/c-first-run.jpg)。 |
| 准备并连接组件 | PASS；点击“准备 LocalPilot”安装包内独立组件，点击“连接 LocalPilot”，跳过模型和消息平台配置，完成设置。 |
| 主界面服务版本 | PASS；实际主界面显示 `服务已连接`、`Core 5.0.0b26`，输入框为空。见 [主界面截图](screenshots/c-main-core-b26.jpg)。 |
| 新后端版本 | PASS；C 根目录已安装的四个发行包 METADATA 分别为 b26、b31、b7、a3，Core 服务日志为 b26、`ready`、`model_health: NOT_PROBED`。见 [Profile 核对](PROFILE_COUNTS.json) 和 [服务日志](logs/core-service.log)。 |
| 零模型任务 | PASS；停止后以只读 SQLite 连接核对 `checkpoints=0`、`journal=0`。三个模型路由均为 `unavailable`、`not_deployed`。没有发送任务或模型测试请求。 |
| 停止自有进程 | PASS；只向核验通过的本轮 UI 主进程发送 SIGTERM，相关 WebKit 和 Python 子进程均退出。见 [停止回执](logs/native-final-c-stop.json) 和 [退出后桌面](screenshots/c-stopped.jpg)。 |

这是一次手工原生冒烟，不加入后端、Vitest、Rust 或 Playwright 自动测试累计数。A/B 状态持久化与别名测试仍参见[上一轮原生记录](../RESULTS.md)，本轮没有重复这些操作。

## 保留日志与范围

本次首次启动和组件准备没有出现阻断错误。原始 stderr 保留了验证环境中 AT-SPI socket 不可见及只读主目录无法写 shader cache 的警告；窗口渲染和点击流程正常完成，不能据此声称通过完整可访问性或图形加速验收。验证没有改变系统依赖、X11 认证策略或 WebKit sandbox 设置。

原始执行目录为 `/workspace/scratch/c0f3ec78c621/validation/native-final-smoke-20261116/`。只复制了截图、过程记录、验证脚本和无凭据的版本/计数快照；没有复制测试数据库、连接 token、私钥或用户目录。本轮不扩展为系统安装、升级、故障回滚、模型执行、消息平台、音频、Wayland 或 macOS 验收。

可复核材料：[结构化结论](SUMMARY.json)、[包构建报告](PACKAGE_RESULT.json)、[Profile 核对](PROFILE_COUNTS.json)、[上一层证据完整性](PRIOR_MANIFEST_CHECK.json)、[旧截图标签更正说明](PRIOR_SCREENSHOT_LABEL_NOTE.md)、[本轮逐文件 SHA-256](MANIFEST.json)。
