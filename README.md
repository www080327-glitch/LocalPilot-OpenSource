# LocalPilot

随着 AI Agent 的发展，越来越多的人希望让 AI 真正帮助自己完成任务，但高昂的云端 API 费用让许多人望而却步。虽然本地模型可以降低使用成本，复杂的部署流程、模型与 Agent 的兼容问题，以及长上下文带来的推理延迟，仍让普通用户难以入门。
为此，我们开发了 LocalPilot，一款面向大众的本地与云端协同 AI Agent。它将模型部署、管理和任务执行整合在一起，让用户无需复杂配置，就能轻松使用本地智能体。同时，我们针对 DeepSeek、Qwen 等模型优化了任务执行与长上下文缓存，并通过智能路由，让本地模型承担更多任务，在保持任务完成能力的同时降低云端费用。
LocalPilot 采用 Apache 2.0 开源协议，致力于让强大、易用且低成本的 AI Agent 走进更多人的生活。

本仓库为 Apache 2.0 公开源码版，来自 RC.7 思考开关修复候选，导出源提交为 `a18599f8`。首次公开采用独立历史，未包含原私有仓库的备份、账号配置、API 密钥、模型权重、录屏或私人执行记录。

## 下载桌面版

[下载 RC.7 交互修复版（macOS Apple Silicon）](https://github.com/www080327-glitch/LocalPilot-OpenSource/releases/tag/desktop-v5.0.1-rc.7-input-20261030)。安装包、安装说明和 SHA256 校验文件均在发布页。此版本为未公证的个人工程预发布候选，需 macOS 15+。

## 功能

- 桌面任务界面：选择工作文件夹，执行文件读取、分析和报告生成。
- 本地模型及 DeepSeek 等云端模型接入；云端任务和文件出站按配置授权。
- Core 负责持久任务、工具审批、执行记录与结果状态。
- 可选微信扫码及 QQ 机器人入口，连接状态与任务权限分别管理。
- 独立 Companion 桌面宠物模块。

## 项目结构

- `desktop/`：React、TypeScript、Tauri macOS 桌面客户端。
- `agent/`、`localpilot_service/`：Agent 和 Core 服务。
- `suite/`：安装、配置及组件管理。
- `companion/`：Companion 模块。
- `integrations/`、`localpilot_channels/`：消息渠道与外部集成。
- `tests/`：单元和集成检查源码。

## 开发

Python 3.10+ 可安装 Core：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
localpilot-core --help
```

桌面前端：

```sh
cd desktop
npm ci
npm run dev
```

原生桌面构建另需 macOS、Rust / Tauri 环境，以及通过 `desktop/scripts/prepare-bundled-backends.py` 准备的独立组件。公开源码不包含打包后的 Python 运行时和依赖轮子。相关安装说明见 `SERVICE_DEPLOYMENT.md` 和 `docs/development/`。

## 当前状态

这是竞赛阶段的工程候选，尚未公证。RC.7 的初始化界面已精简，下载进度与模型加载状态独立显示，完整模型哈希校验移至模型管理。微信扫码后需手机确认并发送一句话，才能自动识别单个新发送者；多个发送者需在高级设置选择。没有声称微信端到端流程已验证通过。

权限模式按 DSH 的文件策略与批准策略对齐；完全权限不再弹应用内批准，不扣留合法工具正文，切换权限保留会话。详见 `docs/development/desktop-permissions-v3.md`。最近权限修复完成针对性文件、Shell、上下文与界面检查，未重新执行真实模型验收。历史小样本实验不构成通用质量或费用承诺。

输入框默认回车换行，可在设置中改为回车发送；中文输入组合确认不触发发送。已结束的 Shell 非零退出保留错误并允许检查修正，超时和丢失的执行结果仍保持 UNKNOWN。详见 `docs/development/input-and-shell-repair.md`。

本地思考控件沿用原滑条，支持的模型仅显示关闭／开启两档；开关实际映射到推理请求。不同模型分别记住档位，避免云端设置串到本地模型。详见 `docs/development/omlx-thinking-toggle.md`。

## License

LocalPilot 自有代码采用 [Apache License 2.0](LICENSE)。第三方组件保留其各自许可证及版权声明，详见 `third_party/`、`docs/licenses/`、`desktop/licenses/` 和 `DEEPSEEK_HARNESS_REUSE_LICENSES.md`。模型权重不包含在本仓库中，其使用条件由模型发布者规定。
