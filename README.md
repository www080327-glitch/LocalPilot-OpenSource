# LocalPilot

LocalPilot 是一个能在自己电脑上执行真实文件任务，并支持本地与云端模型协同的 AI Agent。

本仓库为 MIT 公开源码版，来自 RC.7 初始化修复候选，导出源提交为 `4a497c2f`。首次公开采用独立历史，未包含原私有仓库的备份、账号配置、API 密钥、模型权重、录屏或私人执行记录。

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

最近初始化修复仅完成编译与打包检查，未执行完整产品验收。历史小样本实验不构成通用质量或费用承诺。

## License

LocalPilot 自有代码采用 [MIT License](LICENSE)。第三方组件保留其各自许可证及版权声明，详见 `third_party/`、`docs/licenses/`、`desktop/licenses/` 和 `DEEPSEEK_HARNESS_REUSE_LICENSES.md`。模型权重不包含在本仓库中，其使用条件由模型发布者规定。
