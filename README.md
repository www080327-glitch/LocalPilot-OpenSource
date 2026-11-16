# LocalPilot

随着 AI Agent 的发展，越来越多的人希望让 AI 真正帮助自己完成任务，但高昂的云端 API 费用让许多人望而却步。虽然本地模型可以降低使用成本，复杂的部署流程、模型与 Agent 的兼容问题，以及长上下文带来的推理延迟，仍让普通用户难以入门。

为此，我们开发了 LocalPilot，一款本地与云端协同 AI Agent。它将模型配置、管理、任务执行和个人助理整合在一起，支持由主 Agent 调用多个子 Agent，并按任务选择本地或云端模型。任务质量、速度和费用以实际模型与任务记录为准。

LocalPilot 采用 Apache 2.0 开源协议，致力于让强大、易用且低成本的 AI Agent 走进更多人的生活。

**源码公开、历史留在 GitHub**：本仓库是后续产品开发的公开源码入口。已验证的历史安装包与源码版本保存在 [GitHub Releases](https://github.com/www080327-glitch/LocalPilot-OpenSource/releases)；开发中改动保存在 Git 分支与 PR。仅为真实测试或构建保留本机工作树，不把本机旧 APP 当作历史发行数据库。具体规则见 [公开源码和历史版本约定](docs/development/GITHUB_RELEASE_HISTORY_POLICY.md)。

## 当前源码组件版本

本源码树包含 Desktop **5.0.1-rc.12**、Core **5.0.0b29**、Suite **0.2.0b32**、Companion **0.5.7b8** 和独立 Channels **0.1.0a4**。源码版本不代表已经发布或通过全部原生安装验收；可用发行资产以 GitHub Releases 为准。

本轮增加完整权限下的显式长任务预算、OpenAI Responses 接入、Super Agent 实际模型验证，以及桌宠 30 Hz 动画和交互修正。四类各 10 项独立修复、逐项证据和未完成的平台验收统一记录在 [本轮完整审计](docs/development/AUDIT_20261117.md)。公开 ITBench-AA 测试只使用 40 道公开题与 LocalPilot 自身运行时；其结果不是 Artificial Analysis 官方榜单分数。两小时运行、最终原生包与公开题评测以该报告的实际状态为准。

2026-11-16 在 PR #14 基线上继续修复缓存 Session 的认证恢复、Test APP 的独立 WebView 存储和 Harbor 原进程路径别名，并增加显式 OpenAI 云端后端。续作补齐 Companion 的 OpenAI 准入和提供方记录，以及 compact 模式下的 Skills 用途目录。Linux 实际 WebKit 已完成 A/B 草稿、主题、来源偏好隔离及重开检查。云端真实模型使用官方 **Qwen3.5-2B** 的受控 Q8_0 转换；固定 **MMLU-Pro 32 题**与不同批次产品任务分别记录，不据小样本声称 AA 排名。当前范围见 [实现与状态](docs/development/NATIVE_POLISH_20261116.md)，最终交付、包身份和剩余项见 [续作验收记录](docs/evidence/native-continuation-20261116/RESULTS.md)；[前阶段全部结果](docs/evidence/native-polish-20261116/RESULTS.md)及失败保持可查。

上一轮 Linux 适配补齐宿主 Shell、Tauri/DEB 构建、发行版 Python 离线组件、XDG/systemd、电源读取、只读桌面来源和本地会议转写，并增加显式 CPU/CUDA 后训练入口。此前 Qwen2.5-0.5B 的 **5 PASS / 4 FAIL** 及其原协议保留在 [Linux 适配与计划状态](docs/development/LINUX_COMPLETION_20261116.md)和 [原验收记录](docs/evidence/linux-completion-20261116/RESULTS.md)，不由新模型结果覆盖。

此前 Intel 接入已补齐本机 CPU/HTTP 入口、模型列表、真实上下文预算和配置应用；PR #13 的 M1 Max 回归仍是 arm64 证据。Intel 真机要求与原结果保留在 [平台支持与验收](docs/development/PLATFORM_SUPPORT_20261116.md) 和 [原生跟进记录](docs/evidence/intel-device-followup-20261116/RESULTS.md)。

2026-11-15 的续作见 [PA 协作评测与来源一致性](docs/development/PA_COOPERATION_20261115.md)：公开评测增加同容器子 Agent 和共享总预算，Companion 保留完整来源依赖、稳定会议分段与人工样本审阅，补齐候选 adapter 加载入口，并继续拆分桌面与 Core 主干。[实际验证记录](docs/evidence/pa-cooperation-20261115/RESULTS.md)与 [Mac 续验记录](docs/evidence/pa-cooperation-20261115-mac/RESULTS.md)分别保留云端与原生结果。

此前的实现见 [PA 产品补齐与源码整理](docs/development/PA_COMPLETION_20261115.md)：多模型协作、保留历史子 Agent 的换模与恢复、来源问答、显式本地会议转写、人工审阅的训练数据、统一升级回滚和 Intel 构建路径。原生 APP、Intel、真实会议与正式能力对照按各自证据验收，不能由源码测试或旧 APP 的结果代替。

2026-11-14 的后续开发检查见 [PA 与主 Agent 接入状态](docs/development/PA_READINESS_20261114.md)，包含异步子代理配置、按需 Skills、Companion 活动证据、同会话换模与测试 APP 回滚。真实模型、原生安装和公开基准仍按各项证据验收；这些源码改动不代表新发行已合格。[本机继续验收步骤](docs/development/WORK_CONTINUE_20261114.md)列出了剩余工作与已确认的恢复兼容边界。

## 平台支持

| 平台 | 当前可用路径 | 验收边界 |
| --- | --- | --- |
| Apple Silicon Mac | macOS 15+ 桌面 APP；oMLX/MLX 或已有本地 HTTP 服务；云端模型 | 既有 arm64 构建和回归通过；RC.8 本机首次设置报告 Session 404。本轮 RC.9 已修复对应软件路径，原生 WebKit 隔离及 Qwen3.6-35B 任务仍需 Mac 复验。 |
| **Intel Mac** | **优先支持本地 HTTP + CPU 推理**；Core/Suite CLI、Companion 服务；x86_64 桌面资源与构建路径 | 代码和跨平台协议测试已补齐；尚无通过 Intel 真机验收的安装包。桌面构建仍要求 macOS 15+。 |
| **Linux x86_64** | **CLI、受限/Full Shell、HTTP/SSE、恢复、本地模型；Tauri/DEB 构建入口；Companion 文件/文字及可选桌面/音轨接入** | Debian 13 实测服务、Shell、真实 Qwen3.5-2B；Chromium UI 47/47 通过，使用合成原生桥；实际 X11/WebKit 首次设置及 A/B profile 重开通过。原生检查使用明确的只读依赖映射，系统 DEB 首装/升级/回滚、Wayland、音轨及登录/睡眠仍未验收。 |
| Linux aarch64 / 其他发行版 | 架构分支和 Node 资源入口；源码 CLI 可按系统依赖安装 | 本轮未做对应机器、ELF、系统依赖或桌面实测；不称为已验收平台。 |

Intel 本地推理使用外部 CPU 服务，例如 [llama.cpp](https://github.com/ggml-org/llama.cpp) 与兼容的 GGUF 模型。LocalPilot 的 HTTP 路径不依赖 MLX 或 MPS；是否使用 CPU、Metal 或其他加速由模型服务器决定。现有 MLX 权重不能直接当作 GGUF 使用，内置 MLX/LoRA 也不会自动变成 Intel CPU 实现。[LM Studio 官方系统要求](https://lmstudio.ai/docs/app/system-requirements)目前不支持 Intel Mac，因此不把它作为 Intel 安装方案。

## 简易快速安装

### Intel Mac / Linux：先用源码 CLI

准备 Python 3.11 或更新版本、Git，以及一个已经启动的本机 OpenAI 兼容模型服务。Intel 源码入门建议使用标准 CPython 3.11–3.13；Python 3.14 的 macOS watchdog 依赖可能需要 Xcode Command Line Tools 从源码构建。以下命令安装 Core、Companion、Suite，不下载模型，也不启动观察。

Debian/Ubuntu 用户可先准备源码 CLI 依赖。`bubblewrap` 和 `util-linux` 用于 Linux 受限 Shell 与宿主断言；还需要发行版允许对应的非特权 namespace。不可用时会明确失败。

```sh
sudo apt install git python3 python3-venv bubblewrap util-linux
```

```sh
git clone https://github.com/www080327-glitch/LocalPilot-OpenSource.git
cd LocalPilot-OpenSource
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install . ./companion ./suite
localpilot --version
```

如果使用已有 `llama-server` 和已下载的兼容 GGUF，可在另一个终端按下面的形式启动。将文件路径替换成自己的模型；模型必须支持所用模板和工具调用。`8192` 是本例实际配置的上下文窗口，`--n-gpu-layers 0` 选择 CPU。服务参数以 [llama.cpp 官方文档](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)及所装版本的 `--help` 为准。

```sh
llama-server --model /absolute/path/to/your-model.gguf \
  --host 127.0.0.1 --port 8080 --alias local-model \
  --ctx-size 8192 --n-gpu-layers 0 --jinja
```

连接这个服务，使用独立目录保存配置和任务：

```sh
export LOCALPILOT_HOME="$HOME/.local/share/localpilot-portable"
mkdir -p "$HOME/LocalPilotWorkspace"
localpilot init --workspace "$HOME/LocalPilotWorkspace" \
  --model local-model --base-url http://127.0.0.1:8080/v1 \
  --context-budget 8192 --model-timeout 120
localpilot start
localpilot models
localpilot ask '用一句话介绍你能做什么。'
localpilot agent '列出工作文件夹里的文件，并读取其中的项目说明。'
localpilot status
```

将 `local-model`、端口和上下文替换为服务实际值。`models` 显示已注册路由，不能单凭它判断模型质量或工具调用能力。CPU 首 token 较慢时可在初始化时调大 `--model-timeout`；这与任务整体时限不同。模型服务器不报告 usage 时，用量保持未知。

默认要求可确认的外部供电。Linux 服务器或容器常没有电源信息；愿意在电池或未知电源状态执行本次前台请求时，显式使用：

```sh
localpilot ask --allow-local-on-battery '你好。'
localpilot agent --allow-local-on-battery '读取工作文件夹里的项目说明。'
```

该选项不会保存成后台授权或修改操作系统电源设置。用完后执行 `localpilot stop`；外部模型服务由它自己的启动方式停止。上述 CLI 初始化默认提供文件 Agent；Shell 权限来自已授权的桌面 Session/宿主工具配置，不会因安装了 Bubblewrap 自动开放执行权限。文件修改沿用批准流程，`localpilot task --help` 提供查询、批准和取消命令。Companion 的独立配置见 [Companion README](companion/README.md)。

### Linux 桌面候选

Linux 桌面采用发行版原生 DEB，内含四组件 wheel 与隔离环境，依赖构建时匹配的系统 Python minor、GTK/WebKit；不含模型。本轮构建的是 **Debian 13 x86_64 独立 Test 候选**，包信息和 SHA-256 见 [续作验收记录](docs/evidence/native-continuation-20261116/RESULTS.md)，构建命令见 [Linux 桌面说明](desktop/docs/development/LINUX_20261116.md)。取得**与自己发行版和架构匹配、已核对 SHA-256 的候选包**后安装：

```sh
sudo apt install ./LocalPilot-Test-5.0.1-rc.9-linux-x86_64.deb
```

Test 候选要求显式的独立测试目录。首次创建一个尚不存在的目录并写入私有身份标记：

```sh
export LP_INSTALL_TEST_ROOT="$HOME/LocalPilot-Test-rc9"
(umask 077; mkdir "$LP_INSTALL_TEST_ROOT" && \
  printf '%s\n' '{"purpose":"LocalPilot installation E2E"}' \
    > "$LP_INSTALL_TEST_ROOT/test-owner.json")
localpilot-desktop-test
```

再次打开时复用同一个目录，无需重建或改写标记：

```sh
LP_INSTALL_TEST_ROOT="$HOME/LocalPilot-Test-rc9" localpilot-desktop-test
```

这是独立候选包的安装形式，当前没有新的公开 Linux Release 下载；DEB 提取、自检与模块运行已有验证。实际 X11/WebKit 的首次设置、A/B 隔离和重开已验证，系统首装/升级/回滚仍待验收。Test 包使用自己的身份和明确的数据目录；普通正式身份不要求这个测试变量。较新 Debian 构建不能据此承诺兼容所有旧 Ubuntu；AppImage/Flatpak 尚未交付。Companion 可选桌面观察、systemd 和本地音轨的配置见 [Linux Companion](docs/development/LINUX_COMPANION_20261116.md)。

### Apple Silicon：已有桌面安装包

[下载历史 macOS arm64 安装包](https://github.com/www080327-glitch/LocalPilot-OpenSource/releases/tag/desktop-v5.0.1-rc.7-chat-20261030)。截至本轮，公开资产仍是 **2026-10-30 的 RC.7 预发行**，包含 PKG、安装说明和 SHA256；它不含 11 月新增的 Intel/PA 修复。`main` 更新不会自动更新这些资产，本轮没有发布新 Release。

桌面版目前支持 Apple Silicon Mac，要求 macOS 15 或更新版本。安装包约 150 MB，自带 Python 和后台组件。本地模型通过 oMLX 运行，首次向导会引导安装或连接已有 oMLX；模型权重单独下载或导入。

1. 下载发布页里的 `LocalPilot-…-arm64.pkg`，双击后跟随系统安装器完成安装。
2. 在启动台或 Spotlight 中搜索 LocalPilot 并打开。安装位置是个人“应用程序”文件夹。
3. 按首次向导准备本机服务，选择已有本地模型，或填写 DeepSeek API 密钥。
4. 选择工作文件夹，输入你想完成的任务。

当前安装包尚未公证。macOS 如有拦截，请先核对下载来源，再按系统提示允许打开。

### 新源码桌面版与升级

新源码在首次向导或模型库中提供“连接本机模型服务”：输入环回地址、读取模型列表、选择实际上下文、保存，然后点击“应用配置并重启服务”。已有会话与模型路由保留；活动 Core 任务或待批准操作会阻止普通重启，需先处理它们。将端点同时用于 Companion 时，应明确选择低功耗策略；关闭低功耗策略不会自动允许电池推理。

Intel 原生构建入口和依赖来源见 [Intel 桌面构建说明](desktop/docs/development/INTEL_MAC_20261116.md)。只有通过资源、架构、签名、真实模型及安装/回滚检查的对应架构 APP 才能作为新的桌面安装候选。

对于已有发行包的常规升级：

1. 退出正在运行的 LocalPilot，安装新版 PKG，再重新打开。
2. 在设置里点“检查并更新内置组件”，使后台服务与桌面版一起更新。
3. 使用微信的用户，再到微信连接入口点“继续连接微信”更新渠道组件。现有配置和未过期的登录会保留。

## 主要功能

| 功能 | 怎么用 |
| --- | --- |
| 文件任务 | 让 Agent 读取 CSV、统计数据、写报告、创建或修改 Markdown 文件。结果保存在你选的工作目录。 |
| 模型管理 | 导入已有模型、查看下载进度、选择模型并自动加载。支持思考开关的本地模型显示关闭／开启两档。 |
| 本地与云端 | 按任务选择本地模型或 DeepSeek，也可以选择本地优先等来源策略。切换模型时分别保存各自的思考设置。 |
| 连续对话 | 一段会话保留提问、回答和执行记录。切换权限或 Agent 模式不会清空对话。 |
| 手机入口 | 微信扫码连接后可从手机提交任务，查看进度和实际回答；完成后自动回传，长结果分段发送。 |
| 桌面宠物 | Companion 提供独立的轻聊和桌面入口，可在设置中开关。 |

## 试一个文件任务

先把一份 `sales.csv` 放进选定的工作文件夹，然后输入：

```text
读取 sales.csv，按月份统计收入，生成 report.md。
报告里写清楚每个月的收入、变化趋势和总收入。
完成后重新读取报告，核对数字。
```

也可以直接从简单的文件操作开始：

```text
在这个文件夹创建 项目说明.md，写一个标题和三条待办，然后读回内容。
```

执行过程中可以查看工具调用和文件结果。文件是否创建、内容是否正确，最终以实际文件和读回结果为准。

## 模型和任务设置

Apple Silicon 可通过 oMLX 连接 MLX 模型；Intel 与 Linux 可连接已有本地 OpenAI 兼容服务。是否适合当前任务还取决于模型的工具调用能力、可用内存和实际上下文长度。DeepSeek 通过 API 接入；OpenAI 可通过新的显式 `openai` 路由接入主 Agent、子 Agent 和五档来源策略，配置方法见 [OpenAI 与公开评估说明](docs/development/OPENAI_AND_PUBLIC_EVALUATION_20261116.md)。密钥只使用本机私有凭据机制，不写进路由 JSON。当前没有 OpenAI 专用密钥向导，实际 API 可用性、usage 和费用必须分别核实。

来源选项包括完全本地、本地优先、平衡、云端优先和完全云端。完全本地不会调用云端模型；使用云端模型时，允许读取的任务上下文会交给所选服务处理。

| 权限模式 | 行为 |
| --- | --- |
| 只读 | 可以读取文件和运行只读 Shell，不修改文件。 |
| 请求批准 | 读取文件自动执行，修改和命令执行前询问。 |
| 工作区写入 | 自动处理工作文件夹内的文件，超出范围的修改先询问。 |
| 完全权限 | 使用当前操作系统用户的读写、Shell 和联网权限，APP 内不再重复询问批准。 |

操作系统本身的文件访问授权仍由系统控制。**完全权限下的 Shell 使用当前 OS 用户权限，并不是独立的文件读取沙箱**；内置文件工具仍阻止直接访问 `.localpilot/secrets` 凭据目录，但不能把这项限制误认为 Shell 也无法访问系统用户可读取的文件。云端出站授权与文件权限分别控制。Linux 只读/工作区 Shell 使用 Bubblewrap，工作区模式另允许既有 OS 临时目录写入；详情见 [Linux Core](docs/development/LINUX_CORE_20261116.md)。命令报错会保留错误信息，Agent 可以检查现状、修正命令；执行结果确实无法确认时，不会自动重做原操作。

## 在微信里使用

在设置中点击“扫码连接微信”，手机扫码并确认，再发一句话完成身份绑定。之后直接发问题或任务要求即可。

- 任务还在运行时会先返回进度，完成后自动发来实际回答。
- 长报告分段发送，普通回复不附带长任务 ID 和诊断字段。
- 发“进度”或“查看结果”可以查询最近的任务；“详细状态”可以查看执行信息。
- 电脑需要开机，并保持 Core 和微信连接运行。退出 APP 后要继续使用，可在连接设置中开启后台运行。

QQ 入口也在设置中，目前通过官方机器人接入，需要自行准备机器人账号信息。

## 从源码运行

Core 单独使用 Python 3.10+；上面的整套源码安装因 Suite 要求 Python 3.11+。只开发 Core 时：

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

浏览器页面用于开发预览。原生桌面还需要 Rust 和独立组件资源；macOS 使用 Xcode 工具链，Linux 使用发行版 GTK/WebKit 开发库。相关入口在 `desktop/scripts/`。Core 部署见 [SERVICE_DEPLOYMENT.md](SERVICE_DEPLOYMENT.md)，具体修复与开发说明在 [docs/development](docs/development)。

| 目录 | 内容 |
| --- | --- |
| `desktop/` | React、TypeScript 和 Tauri 桌面客户端 |
| `agent/`、`localpilot_service/` | 任务运行、工具调用和 Core 服务 |
| `suite/` | 安装、配置和组件管理 |
| `integrations/`、`localpilot_channels/` | 微信、QQ 和外部集成 |
| `companion/` | 桌面宠物模块 |
| `tests/` | 单元与集成检查 |

## 使用范围

目前提供的是 AIC 阶段的开发候选，公开桌面安装包仍仅有旧 macOS Apple Silicon 版本。模型速度、输出质量和费用会随模型、机器和任务变化。项目中的历史小样本实验不能代表所有任务。

Companion → 主 Agent → 多子 Agent、五档来源偏好、按需 Skills、来源记忆、人工审阅训练数据与受管缓存已有实现。Linux 增加固定依赖的 CPU/CUDA LoRA/全参数训练和独立测试集比较，CPU 上已实际更新并重载微型模型；这不代表真实个人数据的训练收益。固定提示/Skill 在本轮 llama.cpp 上验证了热缓存和显式磁盘恢复；外部 HTTP 模型服务器的通用自动缓存管理尚未实现。

**主 Agent 不弱于主流产品、真实多模型协作质量、LoRA 增益和跨后端永久 KV 缓存均没有得到完整实测证明**。旧 534 次正式对照仍为 1 PASS、3 FAIL、13 ERROR、517 无最终结果。MMLU-Pro 小样本提供模型知识题证据，不替代 Agent 任务对照。系统音轨、真实睡眠唤醒和 Intel 原生验收仍有缺项；当前完整状态见 [本轮计划对照](docs/development/NATIVE_POLISH_20261116.md)，剩余实际设备工作见 [Work 继续执行提示词](docs/development/WORK_NATIVE_POLISH_20261116.md)。

遇到问题时，请附上版本、模型名称、操作步骤和错误提示。提交日志前先检查并移除 API 密钥和个人信息。

## 开源与致谢

LocalPilot 自有代码使用 [Apache License 2.0](LICENSE)。第三方代码保留各自的许可证。

感谢 DeepSeek Harness 与 oMLX 等项目。复用范围见 [DeepSeek Harness 复用与许可证说明](DEEPSEEK_HARNESS_REUSE_LICENSES.md)，其余声明在 `third_party/`、`docs/licenses/` 和 `desktop/licenses/` 中。
