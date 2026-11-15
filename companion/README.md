# LocalPilot Companion 0.5.7b3

[公开桌面版本与候选记录](https://github.com/www080327-glitch/LocalPilot-OpenSource/releases) · [安装与个人素材](../docs/releases/desktop-5.0.0/INSTALL.md)。本页为独立 Companion 服务，不改变其版本和授权边界；历史版本记录不代表当前候选已通过原生验收。

Independent macOS arm64 service and CLI. Rules and cached Qwen3.5-0.8B handle lightweight interaction. A configured authenticated LocalPilot API provides larger reasoning and explicitly confirmed standard Agent work. Companion contains no LocalPilot Runtime and has no implicit tool approval authority.

Install this package independently with `python -m pip install '.[mlx]'`, or use the joint Suite installation in the repository root README. The optional MLX extra installs libraries, not model weights. Reference an existing local model directory in your own config; battery or unknown power blocks local inference by default.

```sh
companion --help
companion --config /path/to/companion.json run
companion --config /path/to/companion.json ask '你好'
companion --config /path/to/companion.json status
companion --config /path/to/companion.json ui --show
```

Help confirmation permits submitting a task. Tool approval stays with the Core Permission Gateway and a separate trusted operator. Cloud consultation needs its own explicit consent and a new question-only Session. Closing a card, declining help, and stopping a task are distinct actions. UNKNOWN never authorizes replay.

API and client contract: 1.0. Current integrated Core: 5.0.0b20 (API 1.0). Historical 4.9.2 RC consumer evidence remains historical. Initial migration from old Companion 0.5.4 requires upgrading Companion first. Keep data outside the installation directory.

This is a scoped release candidate. A real ordinary arithmetic prompt produced an incorrect 0.8B answer; factual accuracy is not guaranteed by the routing or host verifier. See the joint release report and failure ledger. Other platforms and all-day stability remain unverified.

The full 549-test regression uses the owning monorepo checkout by default. Set LOCALPILOT_SOURCE explicitly for an independent Core checkout; do not implicitly mix a sibling historical Runtime with current tests. Install the validation extra for document fixtures. Tests use scripted backends; they do not establish real-model factual accuracy or all-day GUI stability.

## 桌面宠物候选（2026-10-25）

隔离实现与边界见 [宠物架构](../docs/acceptance/companion-pet-20261025/ARCHITECTURE.md)。本候选复用 Companion 服务，新增 `pet_ask`、记忆控制和认证流式展示通道；不包含新的 Agent Runtime。独立 Tauri 测试包使用专属应用身份，不替换日常 LocalPilot.app。真实工具委派与长期性能尚未获准作为 Beta 通过结论。

## 当前推荐桌宠

Desktop 5.0.0 沿用 dev.23-edge.4 的边缘姿态、方向动画、独立比例和原生玻璃气泡。通过完整桌面入口开启，个人资源不随制品分发。用户已确认 edge.4 玻璃和文字；新的全量真实模型回归未跑。[版本与验收边界](../docs/releases/desktop-5.0.0/RELEASE_NOTES.md)。上节 2026-10-25 的候选记录保留为历史，不能覆盖新版发布状态。

## PA 日常回顾与反馈（2026-11-14 候选）

在现有观察范围内，可以直接问“我今天做了什么？”或“回顾我昨天的工作”，也可以运行：

```sh
companion --config /path/to/companion.json activity --day today --limit 30
companion --config /path/to/companion.json activity --day yesterday
```

回顾按本机日历日查询仍保留的观察发生时间，附来源 ID、应用/文件、静态文字摘录和读取状态。它不调用模型，不将窗口出现或模型回复当作已完成工作的证据。已撤销、遗忘或过期的来源不会重新出现；没有记录不等于没有工作。会议需要已有、获准读取的文字或转录；本候选不录音或转写会议音频。

晨晚问候由轻量规则生成，沿用勿扰、静音、每日去重和通知频率设置，并在授权范围内的系统唤醒或应用激活时检查。宠物流先发送收到确认，随后返回正文或明确失败。已委派任务的完成、失败、UNKNOWN 和需人工状态保存在任务详情；未通过验收的普通回答会明确标注。

本地默认复杂问题仍走现有正式 Task API；需要工具的宠物请求沿用 Desktop 的任务交接。实现、测试边界与 Mac 接力见 [Companion PA 记录](../docs/development/COMPANION_PA_20261114.md)。
