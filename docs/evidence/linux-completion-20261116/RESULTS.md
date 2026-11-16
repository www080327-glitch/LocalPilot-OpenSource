# Linux 续作、旧版本兼容与真实执行验收

日期：2026-11-16。基线：PR #13 已合入的 `0cc99d57990e81302b941b6f5a160093dd298d4b`。本轮完成 Linux 运行路径、原生构建与实际服务/模型/训练验证；不将尚未运行的原生桌面或实际质量失败写成通过。

当前源码版本为 Desktop **5.0.1-rc.8**、Core **5.0.0b23**、Suite **0.2.0b28**、Companion **0.5.7b5**、Channels **0.1.0a3**。源码快照见 [SOURCE_SHA256.json](SOURCE_SHA256.json)，构建输入和制品见 [Desktop 验收](../../../desktop/docs/evidence/linux-20261116/RESULTS.md)。本报告随源码提交，不能用提交前基线 SHA 代替最终源码身份。

## 范围与环境

本轮在 Debian 13 x86_64 / Linux 6.18.57 执行。普通 Python 测试为 CPython 3.12.14；桌面资源实际使用发行版 CPython 3.13.5。OpenAI SDK、Harbor 合同、Torch 训练分别使用隔离环境。环境版本保存在公开日志中的 `ENVIRONMENT.json`；Rust、GTK/WebKit、资源和依赖来源见 Desktop 记录。

仓库已有的 Runtime、Permission Gateway、五档来源偏好、Session/Task/SQLite、UNKNOWN 收据与子 Agent 调度继续共用。Linux 新增 Bubblewrap Shell、宿主断言、硬件/电源、XDG/systemd、AT-SPI/X11 只读来源、Pulse/PipeWire-Pulse 与本地 whisper.cpp；桌面代码按目标平台编译。人工审阅训练增加独立测试集和 Linux CPU/CUDA 入口，没有自动自训练。

当前环境允许实际 CPU 推理、Shell、HTTP/SSE、文件和进程操作，但 D-Bus/Chromium 创建 Unix socket 被拒绝，没有可用 Docker daemon、真实声卡会话或 Intel Mac。没有修改宿主限制来获得测试通过。

## 验证结果

各组存在交叉覆盖，不把这些数字相加为独立测试总量。SKIP、ignored、BLOCKED 与模型质量 FAIL 分开保留。

| 组别 | 结果 | 实际范围 / 日志 |
| --- | --- | --- |
| Core 最终全量 | **1449 PASS、93 SKIP、0 FAIL/ERROR**，1542 项，160.806 秒 | `core/core-full-r4.log`；启用真实 PR #1/#9 源码，包含恢复兼容与线程子 Agent；无 ResourceWarning |
| Companion 全量 | **686 PASS、33 SKIP、0 FAIL/ERROR**，719 项，30.903 秒 | `companion/full-final-r4.log`；25 Mac helper、1 Linux GUI、2 ASR opt-in、5 Torch opt-in 跳过，后两组另行真实执行 |
| Suite 全量 | **112 PASS、1 SKIP、0 FAIL/ERROR**，113 项，27.503 秒 | `suite/full-r2.log`；实际 pip/wheel 升级、失败、回滚及 Linux Node 路径 |
| OpenAI SDK / Core HTTP | **42 PASS**，2.690 秒 | `core/sdk-final-r3.log`；最终 Session 兼容修复后重跑，实际 SDK/HTTP，脚本模型 |
| Harbor 官方合同与审计 | **72 PASS、4 真实模型 SKIP**，76 项，22.216 秒 | `core/harbor-r1.log`；官方 Harbor 0.26.0，不是 Docker 正式 study |
| 已安装资源 Channels | **12 PASS、0 SKIP**，5.864 秒 | `companion/installed-channel-tests-r1/installed-channels.log`；final-r2 CPython 3.13.5 资源，真实进程/HTTP/SQLite，账号和模型是夹具 |
| 审阅数据与独立评估 | **24 PASS** | `training-r1.log`；真实本地 HTTP 协议夹具，参考答案不发给被测服务 |
| CPU 训练 | **5 PASS、0 SKIP**，18.271 秒 | `core/portable-training-review-r2.log`；真实 Torch/PEFT 梯度、保存与重载，不是训练命令 dry-run |
| 真实 whisper.cpp | **2 PASS**，1.410 秒 | `companion/real-whisper-r2.log`；公开英语音频、实际转写/取消，不是真实中文会议 |
| 最终真实 CPU 模型 | **5 PASS、4 FAIL、0 ERROR**，194.171 秒 | `real-model/qualification-r4/RESULTS.json`；固定官方模型与预算，包含严格 Shell 读回检查；失败保留 |
| Rust 默认 | **45 PASS、3 ignored** | `desktop/cargo-test-linux-final.log`；实际 Linux 编译和执行 |
| Rust 显式 Core 集成 | **1 PASS**，属于上行默认 ignored 中的一项 | `desktop/rust-real-core-final-r2-runtime.log`；真实 Core、恢复和身份检查，脚本模型 |
| Vitest | **72 PASS / 13 files** | `desktop/vitest-final.log` |
| TypeScript / Vite | **PASS** | `desktop/vite-final.log`，最终打包再次构建 |
| Playwright | **41 项收集；实际浏览器启动 BLOCKED** | 官方 Chromium 下载截断；系统 Chromium AF_UNIX `EPERM`。首个用例在浏览器启动失败，其余 40 未运行。没有套用此前 M1 的 38 PASS |
| Linux DEB / 实际搬移运行 | **PASS；未系统安装** | 四组件与二进制依赖导入、版本、`pip check`、Node 实际运行；精确包信息见 Desktop 证据 |

### 命令与复验

普通完整回归沿仓库已有 unittest 入口运行：

```sh
.venv/bin/python -m unittest discover -s tests -t . -v
.venv/bin/python -m unittest discover -s companion/tests -t . -v
PYTHONPATH=.:suite .venv/bin/python -m unittest discover -s suite/tests -v
```

旧源码 worktree 使用真实 PR #9 `0a7fdff36f45a471130293b508b5d008f40cecf9` 和 PR #1 `94e0e6ff2c8da974d20530d7a0faa50844d052f4`，通过 `LOCALPILOT_PR9_SOURCE` / `LOCALPILOT_LEGACY_SOURCE` 传入现有兼容测试；不在测试中抄写旧业务实现。相应全量复验也保留这两个环境变量。

旧版本与宿主工具的最终定向组为 **59 PASS、0 SKIP**（`core/real-legacy-migration-r7.log`，11.638 秒）；独立复核还单独重复五档 PR #9 恢复/继续请求/错误 capability 拒绝。中间 Core r2 因无宿主策略的子 Agent 出现 **51 FAIL、14 ERROR、93 SKIP**，原始完整日志保留；修正后 r3 为 1448 PASS / 93 SKIP，最终严格工具身份检查后的 r4 为上表 1449 PASS / 93 SKIP。中间运行期间源文件可能继续修正，具体执行范围在 `core/summary.json` 标注；只有最终 r4 按冻结源码资格报告。

SDK 命令为隔离 SDK 环境的 Python 加 `PYTHONPATH=.`，执行 `tests.test_openai_compatibility_audit` 与 `tests.test_runtime_api_sdk`。Harbor 命令启用既有 `LOCALPILOT_HARBOR_CONTRACT=1`，使用官方 0.26.0 schema/adapter，并设置 `LITELLM_LOCAL_MODEL_COST_MAP=True` 避免无关在线成本表更新。公开任务执行仍未开展。

训练、ASR、真实模型和桌面构建的可复跑命令分别见 [训练](../../development/REVIEWED_TRAINING_20261116.md)、[Companion](../../development/LINUX_COMPANION_20261116.md)、[Core](../../development/LINUX_CORE_20261116.md) 和 [Desktop](../../../desktop/docs/development/LINUX_20261116.md)。命令所需真实模型/系统依赖不由测试夹具替代。

## 最终独立 Test DEB

最终成功槽为 `desktop/release/linux-test-v5.0.1-rc.8/20261116-162122-43/`，文件为 `LocalPilot-Test-5.0.1-rc.8-linux-x86_64.deb`，**114,593,010 bytes**，SHA256：

```text
be2a72ea8c79a240b0671e29129fa2b2c40e4cea687ff6b749147945c8f4565b
```

包身份 `local-pilot-test`，应用身份 `io.localpilot.desktop.test`；平台范围 Debian 13 x86_64，匹配系统 CPython 3.13。40 个 wheel 为四组件、35 项依赖和 pip。四组件中的 **268 Python + 17 Swift = 285 个源文件**经检查与构建输入一致；实际 DEB 提取后再次核对最后三个 Core 兼容文件，包含 `session_models.py` 的 `0bb3cc99a0625fa8a0871d513cb85a500d5342c753434f14a924e386a1547590`。

提取目录特意包含空格，四组件与三项二进制依赖导入、各版本入口、`pip check`、Node 22.23.4 和原生 bundle self-check 均通过。三个解释器入口指向 `/usr/bin/python3.13`，未重复打包系统 Python。最终安装资源上的原生 Core 恢复/身份用例又通过一次（1.24 秒）；是上表同一个用例，不额外累计。

`installed:false`、`services_started:false`、`user_data_opened:false`。这些检查不等于真实包管理安装、GUI 启动或用户模型任务通过。前面的 r3/r4 成功包是旧源码的中间产物；失败槽及其日志也保留，本次交付只取上述最终槽。完整 JSON 见 [PACKAGE_RESULT](../../../desktop/docs/evidence/linux-20261116/PACKAGE_RESULT.json)。

## 真实模型与缓存

使用官方 `Qwen/Qwen2.5-0.5B-Instruct-GGUF` 的 `Q5_K_M` 文件，revision `9217f5db79a29953eb74d5343926648285ec7e67`，SHA256 `041474553fcabfc2a2d67903f9d2c2e50bd92528e670da4f33b5d0ce6e59fd55`。官方 llama.cpp build 12359 / commit `b1b770d90d94cad9e9ea5b993bdbc383a522fb28`，CPU、2 threads、8192 context、单 slot。新建自有 Core 和提供方进程；不连接用户已有 oMLX/LM Studio，不调用付费云服务。

第二轮 `qualification-r2` 为 **5 PASS、4 FAIL、0 ERROR**。缓存、算术、Core 流式取消/SSE409、Shell UNKNOWN/重开、Companion 轻聊通过；文件回答、完整 Shell 任务、子 Agent 文件回答和 Companion 委派文件回答失败。原始工具输出已经包含事实，小模型仍会遗漏或声称已经读取。没有给模型补答案、移除失败或按执行终态推定完成用户目标。

固定提示和已有 Skill 的实际缓存数据：1257 prompt tokens；cold cached=0，hot cached=1256，显式保存并重启提供方后 restore cached=1256；slot 保存/恢复 1258 tokens。这证明本次固定模型/模板的显式缓存恢复，不证明产品自动管理任意 HTTP 服务的磁盘 KV，也不保证改变模型、模板或 Skill 后缓存仍有效。

真实 Shell 取消后保留一个 UNKNOWN effect；Core 重启和同幂等键重提没有重复 append。取消时 Core 达到 cancelled/quiescent，但提供方即时 slot 仍可能是 `is_processing=true`，因此不声称提供方计算立即停止。

最终源码的 **`qualification-r4` 为 5 PASS、4 FAIL、0 ERROR，194.171 秒**。通过/失败的五加四项与上述分类相同；严格 Shell 判定还要求实际 `read_file` 收据和最终答案，模型只创建文件并声称读回会明确失败。此前 r3 原始报告为 6 PASS / 3 FAIL，其中 Shell 的宽松判定被独立复查纠正，实际应为 5 PASS / 4 FAIL；原报告未改，纠正说明见 `core/real-model-r3-review.json`。

四轮原始任务、模型调用、token、缓存、父子关系和失败保存在本目录压缩日志中。r2 资格摘要曾误读 usage 所在字段，原摘要保留，`core/real-model-observed-usage.json` 根据原始 `result.model_calls/runtime_metrics` 补充实际值；当前资格脚本已使用正确字段。未报告的 usage 保持 UNKNOWN。本地 API 费用 $0，能源未计量。各轮自己拥有的 Core 与 llama.cpp 都已退出。

## 训练和会议证据的含义

Torch 环境为 `torch 2.9.1+cpu`、`transformers 4.57.3`、`peft 0.18.1`、`safetensors 0.7.0`。真实 CPU 测试使用随机初始化的小型 Qwen，执行全层/最后一层 LoRA、adapter 重载、全参数 embedding/head 更新、答案标签掩码与不可用 CUDA 失败路径。它证明实现能够训练和装载，不证明真实个人数据上的收益。没有人工确认的用户训练集、CUDA/MLX 新版真机训练、强化学习或自动候选晋级。

真实 whisper.cpp 为官方 v1.9.5 / `d1be6fde11ac6e0407606b4e42fe72d34add8037`，tiny.en revision `5359861c739e955e79d9a303bcbc70fb988958b1`，模型 SHA256 `921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f`。公开约 11 秒英语样本通过生产 memfd 转写，正常识别约 0.988 秒；实际取消会回收进程且不写晚到结果。生产转写路径未另存音频，公开输入样本保留用于复验。该结果不替代真实 Pulse 声卡、系统音轨、中文会议或 Mac TCC。

## 审查发现与失败保留

| 发现 | 处理与证据 |
| --- | --- |
| PR #9 Desktop 配置指纹因 Shell 描述变更而漂移 | 首次真实旧源码检查出现 5 个 policy 子用例 FAIL。保留精确历史描述/权限 prompt，Linux 事实只加入 native scoped Shell 的本次请求；旧检查点恢复和错误策略拒绝另测。没有放宽指纹比较 |
| 新旧检查点测试首轮夹具错误 | 首轮遗漏模型路由，后一轮遗漏 local health HTTP 夹具并检查了错误的异常包装层；均在独立日志保留，补齐后真实恢复通过 |
| Linux 请求提示未处理无宿主策略的子 Agent | 全量回归发现 `scope_policy=None` 导致新的提示 guard 报错。按既有可空合同处理为无 native policy，补 absent/None 容器 Shell 与真实线程子 Agent 用例；没有给通用子 Agent 注入宿主 Shell 能力 |
| 同名自定义 Shell 不等于原生宿主 Shell | 独立复查实际复现 scope3 配置下的自定义 Shell 被误注入 Linux 原生说明，改用已有 `qualified_shell` 工具身份判断。V5 请求视图保持临时；非 V5 的稳定缓存模式仍按既有合同保存精确请求快照，不改写旧历史或配置指纹 |
| PEFT 正数选层 LoRA 参数组合错误 | 实际复现 `all-linear` 与 `layers_to_transform` 不兼容；改为真实线性模块后缀，验证最后一层 14 个 LoRA 参数、B 权重更新且基座不变 |
| Suite 升级测试受到源码 PYTHONPATH 污染 | 首轮全量 3 FAIL；实际 pip 探针证明重复 dist-info。测试 pip 入口改为 `python -I -m pip`，真实升级/回滚断言未删，全量随后通过 |
| Linux ASR helper SIGTERM 不能唤醒等待 | 实际子进程复现；信号只设 Event，由独立停止线程终止并等待所拥有子进程，真实转写取消和全量复验 |
| Pulse 来源字段假设错误 | 依据实际上游 `monitor_source` JSON 修正入口分类，未知结构明确不可用；设备协议夹具和 Companion 全量通过 |
| 电源与观察平台错误 | USB 外围设备的充电不再当整机 AC；更新排除项重建观察器时选择真实平台 |
| Linux 原生构建与打包问题 | 目标专用 Rust API/feature、包精确身份/版本、ARM 资产名称、DEB Python 链接及打包报告 `st_size()` 错误均有实际发现与修正；早期日志/失败槽保留 |
| 资格脚本轮询过密 | r1 为 3 PASS / 1 FAIL / 5 ERROR，50 ms 轮询触发 Core 既有 120 请求/分钟限制。改为 1 秒轮询，产品限额未改 |
| 第三轮 Shell 资格判定不够完整 | r3 原始判定只核对文件写入和 completed，漏查任务要求的 `read_file` 与最终答案。原始 PASS 保留并明确纠正；最终判定同时要求实际读回收据和答案，不改变模型或预算来消除失败 |
| 首个 HTTP Shell 测试字段错误 | 使用不存在的 `unknown_receipts` 导致 1 ERROR；改用现有 `unknown_effects` 后通过，失败日志保留 |
| GUI 环境无法运行 | 官方浏览器下载截断、系统 Chromium 与 D-Bus socket `EPERM`；保持 BLOCKED，没有替换为合成 UI 通过 |

原始日志以追加新文件方式保留。开发中首次错误既包括产品缺陷，也包括新测试/构建脚本错误；均未从记录删除。旧 534 队列未触碰，仍为 **1 PASS、3 FAIL、13 ERROR、517 无最终结果**。本轮没有正式公开 study、排名或非劣结论。

## 未完成与交接

- 物理 Intel Mac、macOS 15+ 原生 x86_64 构建/模型/安装回滚仍 **NOT_RUN**；M1、Rosetta 和 universal2 文件不能替代。
- Linux 原生 GUI、真实 DEB 首装/升级/降级、登录/睡眠/通知、Pulse 设备和真实会议仍缺正常桌面环境。当前只有 DEB 提取运行通过。
- Apple Silicon 当前 RC.8 的新 APP、真实任务、TCC/责任链、系统音轨和睡眠唤醒仍需本机验收；以前版本通过项不自动继承。
- 强模型真实多模型协作、五档实际费用/来源、公平公开对照与真实个人训练收益仍缺合格证据。CPU 0.5B 链路测试不能代替这些要求。
- 通用 unmanaged HTTP 自动磁盘 KV 与 Linux Core 原生 Computer Use **尚未实现**；Linux AT-SPI 只读观察不能算作电脑操作工具。
- 没有发布 Release、提交比赛/落地表单或变更用户现有服务。独立 Test DEB 不冒充正式发行。

完整原计划对照见 [LINUX_COMPLETION_20261116.md](../../development/LINUX_COMPLETION_20261116.md)；仅需真实设备、数据和可用容器环境的执行交接见 [WORK_LINUX_REMAINING_20261116.md](../../development/WORK_LINUX_REMAINING_20261116.md)。

## 公开证据格式

[LOG_MANIFEST.json](LOG_MANIFEST.json) 列出每个原始文件的 SHA256、公开文本 SHA256 和 gzip SHA256。公开导出只去除 ANSI 并将工作目录前缀替换为 `<WORKSPACE>`，使用固定 gzip mtime；不会改写测试结论。原始凭据、私有 SQLite、模型权重、KV 二进制和私人数据不进入仓库。`SOURCE_SHA256.json` 覆盖本轮变化的生产/构建/测试/版本源文件；文档自身由 Git 提交标识。
