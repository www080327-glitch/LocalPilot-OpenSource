# LocalPilot Companion 0.5.7b5

[公开桌面版本与候选记录](https://github.com/www080327-glitch/LocalPilot-OpenSource/releases) · [安装与个人素材](../docs/releases/desktop-5.0.0/INSTALL.md)。本页为独立 Companion 服务，不改变其版本和授权边界；历史版本记录不代表当前候选已通过原生验收。

Independent service and CLI. Apple Silicon macOS can use the bundled MLX worker; Intel macOS and Linux can use an explicitly configured local OpenAI-compatible HTTP model server. File observation, source imports and SQLite memory use the portable service. macOS has Swift observation and meeting helpers; Linux now has optional AT-SPI/X11 read-only observation and Pulse/PipeWire-Pulse audio with local whisper.cpp. Actual graphical sessions, audio hardware and sleep/wake still require device validation. A configured authenticated LocalPilot API provides larger reasoning and explicitly confirmed standard Agent work. Companion contains no LocalPilot Runtime and has no implicit tool approval authority.

Linux configuration, optional system packages and explicit systemd user startup: [Linux Companion](../docs/development/LINUX_COMPANION_20261116.md). Reviewed train/validation/test exports, offline LoRA/full training and exact-match evaluation: [Post-training workflow](../docs/development/REVIEWED_TRAINING_20261116.md). Neither observation nor the model starts training automatically.

From the repository root, install the independent package with `python -m pip install ./companion`, or use the joint Suite installation in the repository root README. Only Apple Silicon users choosing the built-in worker need `python -m pip install './companion[mlx]'`. The optional MLX extra installs libraries, not model weights. Reference an existing local model directory or an already running local HTTP server in your own config; battery or unknown power blocks local inference by default.

```sh
companion --help
companion --config /path/to/companion.json run
companion --config /path/to/companion.json ask '你好'
companion --config /path/to/companion.json status
companion --config /path/to/companion.json ui --show
```

Help confirmation permits submitting a task. Tool approval stays with the Core Permission Gateway and a separate trusted operator. Cloud consultation needs its own explicit consent and a new question-only Session. Closing a card, declining help, and stopping a task are distinct actions. UNKNOWN never authorizes replay.

API and client contract: 1.0. Current integrated Core: 5.0.0b23 (API 1.0). Historical 4.9.2 RC consumer evidence remains historical. Initial migration from old Companion 0.5.4 requires upgrading Companion first. Keep data outside the installation directory.

This is a scoped release candidate. A real ordinary arithmetic prompt produced an incorrect 0.8B answer; factual accuracy is not guaranteed by the routing or host verifier. See the joint release report and failure ledger. The portable Linux service has regression coverage; Intel hardware, native macOS lifecycle and all-day stability still require device validation.

The regression suite uses the owning monorepo checkout by default. Set LOCALPILOT_SOURCE explicitly for an independent Core checkout; do not implicitly mix a sibling historical Runtime with current tests. Install the validation extra for document fixtures. Model protocol tests use scripted backends, alongside real HTTP, process, filesystem and SQLite checks; they do not establish real-model factual accuracy or all-day GUI stability.

## Intel Mac 与 Linux 服务配置

Intel Mac 使用本机 CPU 或其他受支持硬件驱动的模型服务；Companion 不会尝试在 Intel 上导入 MLX，也不会把 MLX 权重自动转换为 GGUF。先启动你自己的本地服务，再将它实际报告的模型 ID 和数字环回地址填入配置：

```json
{
  "data_dir": "~/Library/Application Support/LocalPilotCompanion",
  "backend": "local-http",
  "http_model_endpoint": "http://127.0.0.1:1234/v1",
  "http_model_name": "REPLACE_WITH_SERVER_MODEL_ID",
  "http_model_host_local_only": true,
  "http_model_disable_thinking": false,
  "low_power_policy": "system",
  "allow_local_on_battery": false
}
```

地址只是格式示例；服务必须确实只在本机执行推理，不能由环回代理转发到云端。用 `companion --config /path/to/companion.json model-smoke --prompt '7 * 8'` 检查实际连接。`http_model_disable_thinking=true` 会向兼容服务发送 `chat_template_kwargs.enable_thinking=false`；服务可能不支持或忽略它，Companion 不删除返回文本中的思考内容，也不会把截断或工具调用响应当成完成。

`system` 跟随当前系统电源策略：macOS 使用当前 `pmset` 档位；Linux 使用 sysfs 和 power-profiles-daemon/ACPI profile。缺少可信供电信息仍为 UNKNOWN。默认 `always` 低功耗策略会阻止未托管的 `local-http` 推理，改用该后端时应明确选择 `system` 或 `off`。`off` 只关闭 Companion 的低功耗门控，不修改系统电源设置，也不授权电池推理。退出 Companion 不会停止你单独运行的模型服务器。Linux 可省略示例中的 macOS `data_dir`，使用 XDG 默认目录。

在 Suite 的本地端点配置中同时选择用于 Companion，会建立独立的纯推理路由与标准 Agent 路由，并保留旧路由和 Session。手动确认的任务不要求开启自动升级；`localpilot_auto_local` 继续控制自动升级偏好。委派仍经过可见停止控件、单次资源同意与 Core 的工具权限处理。外部 HTTP 路由能取消本次客户端请求；如果服务还没返回响应头，停止需要等待响应头或请求超时。界面会保持停止中，直到任务确认静止；这不证明外部服务已停止计算，也不会卸载其模型。

Linux 已提供系统电源读取、XDG 数据目录、显式 systemd 用户服务，以及可选 AT-SPI/X11 只读观察和 Pulse/PipeWire-Pulse 本地会议转写。Swift UI、macOS AX、launchd 和 Core 原生 Computer Use 控制仍不是 Linux 实现。系统无法报告交流供电时，前台本地推理仍需由使用者明确设置 `allow_local_on_battery=true`；不要把未知电源自动认定为交流供电。

最新配置与实际验收边界见 [Linux Companion](../docs/development/LINUX_COMPANION_20261116.md)；此前 [Intel 接入记录](../docs/development/COMPANION_INTEL_20261116.md) 保留为对应版本证据。

## 桌面宠物候选（2026-10-25）

隔离实现与边界见 [宠物架构](../docs/acceptance/companion-pet-20261025/ARCHITECTURE.md)。本候选复用 Companion 服务，新增 `pet_ask`、记忆控制和认证流式展示通道；不包含新的 Agent Runtime。独立 Tauri 测试包使用专属应用身份，不替换日常 LocalPilot.app。真实工具委派与长期性能尚未获准作为 Beta 通过结论。

## 当前推荐桌宠

Desktop 5.0.0 沿用 dev.23-edge.4 的边缘姿态、方向动画、独立比例和原生玻璃气泡。通过完整桌面入口开启，个人资源不随制品分发。用户已确认 edge.4 玻璃和文字；新的全量真实模型回归未跑。[版本与验收边界](../docs/releases/desktop-5.0.0/RELEASE_NOTES.md)。上节 2026-10-25 的候选记录保留为历史，不能覆盖新版发布状态。

## PA 日常回顾与反馈（2026-11-14 历史候选）

在现有观察范围内，可以直接问“我今天做了什么？”或“回顾我昨天的工作”，也可以运行：

```sh
companion --config /path/to/companion.json activity --day today --limit 30
companion --config /path/to/companion.json activity --day yesterday
```

回顾按本机日历日查询仍保留的观察发生时间，附来源 ID、应用/文件、静态文字摘录和读取状态。它不调用模型，不将窗口出现或模型回复当作已完成工作的证据。已撤销、遗忘或过期的来源不会重新出现；没有记录不等于没有工作。该历史候选仅使用已有会议文字；后续版本已增加显式本地音轨转写，当前 Linux 路径与限制见本页顶部指南。

晨晚问候由轻量规则生成，沿用勿扰、静音、每日去重和通知频率设置，并在授权范围内的系统唤醒或应用激活时检查。宠物流先发送收到确认，随后返回正文或明确失败。已委派任务的完成、失败、UNKNOWN 和需人工状态保存在任务详情；未通过验收的普通回答会明确标注。

本地默认复杂问题仍走现有正式 Task API；需要工具的宠物请求沿用 Desktop 的任务交接。实现、测试边界与 Mac 接力见 [Companion PA 记录](../docs/development/COMPANION_PA_20261114.md)。
