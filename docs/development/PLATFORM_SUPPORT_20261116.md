# Intel 优先适配、Linux 范围与原计划对照

日期：2026-11-16（Asia/Shanghai）。本轮从 PR #11 的 `47e39faf3e97fbd13a562a9ec74efa30dfcc7b42` 继续，保留它的原生签名、测试 APP 隐私说明和全部验收记录。用户已要求将完成的源码同步到 `main`；这项源码集成不等同于发布新安装包。

当前 Python 组件为 Core **5.0.0b22**、Suite **0.2.0b27**、Companion **0.5.7b4**；Desktop 保持 **5.0.1-rc.7**，Channels 保持 **0.1.0a3**。相同 Desktop 版本的不同构建必须同时记录 Git SHA、组件版本和产物哈希，不能凭 RC.7 文件名推定为同一个 APP。

## 结论与支持范围

Intel 现在有完整的源码接入路径：本机 CPU 模型服务器 → Core 的标准 Agent / 隔离推理 → Companion 的轻聊与既有推理控制窗。首次向导、模型库、独立配置应用、电源判断、请求取消与依赖材料获取均有对应实现和回归。**尚未有当前源码的物理 Intel Mac、真实 GGUF 模型和原生安装包验收结果。**

| 能力 | Apple Silicon macOS | Intel macOS | Linux x86_64 |
| --- | --- | --- | --- |
| Core/Suite Python CLI、HTTP/SSE、文件工具和 SQLite | 既有实现；新源码须原生复验 | 本地 HTTP 路径，不需要 MPS | 本轮实际子进程、文件和恢复测试 |
| Companion 服务、文件观察、指定文字来源、SQLite | 既有实现 | 可移植路径；实际电源、性能待验 | 实际服务和来源恢复测试 |
| 外部本地 OpenAI 兼容模型 | 支持协议；具体模型另验 | CPU/GGUF 是主要路径 | 支持协议；具体模型另验 |
| MLX / oMLX 内置集成 | Apple Silicon 专用 | 明确不支持，不尝试启动 MLX worker | 明确不支持 |
| MLX LoRA | 有人工样本与训练入口，尚无训练效果验收 | 不支持 | 不支持 |
| 原生 APP / AX / Swift / 实时会议 | macOS 15+ 桌面；系统音轨仍有 TCC 阻碍 | 保持 macOS 15+；需要 Intel 原生构建和权限验收 | 暂缓，没有实现原生桌面替代 |
| 宿主 Shell | 现有 macOS Seatbelt 实现 | 同一实现，需真机验收 | 尚未提供等价实现，不能视为全功能 Linux Agent |
| 模型速度、内存、能力对照 | 取决于具体模型与机器 | 未测，不能由量化名称推算合格 | 协议测试不测真实模型能力 |

## Intel 的具体改动

### 首次使用与配置

Intel 和 Linux 不再进入 Apple Silicon MLX 推荐问卷；显式传入的 CPU 模型参数会交给已有 Agent CLI。首次向导与模型库提供共享的本机端点表单，不以 oMLX 搜索/下载作为 Intel 唯一路径。

`discover_local_endpoint` 只调用直接环回端点的 `/v1/models`，不运行推理，不下载或加载权重。入口把 `localhost` 统一为数字环回地址，与 Companion 的 HTTP 约束一致。上下文由用户按服务器实际配置填写，模型列表不能代替窗口或工具能力验证。

保存配置创建新路由，保留旧路由和 Session 指纹。新端点同时用于 Companion 时，还会创建独立的 `reasoning_only` 路由，禁用文件/执行能力和子 Agent；标准任务路由保持原工作区授权。Companion 绑定这两条新路由，避免继续指向首次初始化的不可用占位路由。资源确认身份仅有 `read/resource_control`，不取得工具审批权限。

保存状态写入 `model-configuration-pending.json`，关闭/重开界面后仍可应用。用户明确应用时复用原 Core/Companion 服务停止和恢复；普通 Core 停止会拒绝活动任务或待处理批准，恢复失败保留 pending 标记。备份/恢复也保留该标记。它不是另一套进程管理器。

选择 Companion 电源策略不会暗改观察范围、自动云调用、电池授权或系统设置。切换模型清除不适用于 HTTP 的旧 MLX adapter 引用，并把输出预算限制在新上下文内。请求关闭思考是显式选项；如果服务器仍返回思考文本，产品保留原文，不过滤成伪造的合格答案。

### 电源与取消

无电池 Mac 使用 `pmset -g batt` 的真实 AC/Battery 来源。系统低功耗解析兼容 `powermode` 0/1/2；旧 Intel 缺少低功耗键时，只在同一供电来源的能力列表确实不支持该特征时视为无低功耗限制。Linux 未实现 macOS 电源策略，可由用户明确选择当前请求的电池/未知电源授权。

Core 将已有 oMLX/vLLM HTTP 请求取消逻辑下沉到共享 LocalHTTP 运输层。关闭的是这次请求的连接，不是外部服务器或模型进程。取消意图仍走同一 Task/收据体系，晚到的工具提案不得产生副作用。等待 HTTP 响应头时可能尚无可关闭的响应对象，因此状态必须保持 `stopping`，直到任务真正静止；不能宣称提供方计算已停止或模型已卸载。

Companion 的手动启动不再错误地要求已开启“自动本地升级”；自动路径继续遵守自己的开关和现有控制窗要求。推理控制使用同一 Core API，没有新增调度器。具体真实 HTTP/进程测试与限制见 [Core 说明](CORE_PORTABILITY_20261116.md) 和 [Companion 说明](COMPANION_INTEL_20261116.md)。

### 原生资源

wheel 校验同时覆盖目标 Python/ABI、架构与最低系统版本。现有 35 个固定依赖中，33 个有官方兼容 Intel wheel，`watchdog==6.0.0` 与 `cryptography==50.0.2` 需要固定源码原生构建。脚本校验官方哈希、记录工具和依赖来源；没有两项真实产物时明确不生成可交付的 Intel 锁。

这项检查不能由更改 wheel 文件名、复制 arm64 哈希或在 Linux 编译同名包替代。构建和操作命令见 [Intel 桌面指南](../../desktop/docs/development/INTEL_MAC_20261116.md)。

## 之前的要求是否全部达到

**没有全部达到。** 主要产品路径已经有实现，下面把代码实现、真实验收和仍未选择实现的能力分开列明。

| 原计划 | 目前状态 | 仍欠缺的依据或实现 |
| --- | --- | --- |
| Companion → 主 Agent → 多子 Agent | 复用 AgentSession、HybridController 与持久 Task；本轮补外部 CPU 控制接入 | 当前版本真实本地/云端多子 Agent、取消/恢复与最终任务质量 |
| 五档本地/云端策略 | 五档来源偏好、调用来源统计已有实现 | 真实任务下的请求/token/成本比例；五档不是固定百分比承诺 |
| 不弱于主流 Agent | 公开任务/参考实现的可复查评测入口、共享预算和容器子 Agent 已有实现 | 正式完整对照没有跑完；旧 534 队列仍为 1 PASS、3 FAIL、13 ERROR、517 无最终结果，不能报告排名或非劣结论 |
| 即时反馈、异步完成反馈 | 已有确认、子任务和结果回传 | 实际主/子模型和原生客户端组合仍需验收 |
| PA 广泛只读活动来源 | 已授权的窗口/文字/文件/Codex/会议来源、引用与撤销链路已有实现 | 真实会议音轨、未知历史问答、晚间及睡眠唤醒；不能承诺回答未经授权或未观测的信息 |
| 最高 APP 权限 | 已有四档权限与当前用户范围的完全权限 | 操作系统 TCC/文件授权仍有效；完全权限不是绕过操作系统 |
| Skills 代替模型自改 | 稳定目录、按需加载、人工审核及子 Agent 继承已有实现 | 大型实际 Skills 集的效果和性能 |
| 固定提示/Skills KV | 稳定前缀、后端缓存、50 GiB 受管可重建缓存配额已有实现 | 真模型冷/热/重载实验未完整；缓存受身份、模板、后端和淘汰规则约束，不是永久不失效 |
| 后训练 | 人工审阅样本、LoRA 计划/执行与候选 adapter 入口已有实现 | 真实训练和独立集增益尚未运行；RL 执行器未实现，已有 dense 模式也不等于整个模型全部参数训练 |
| Intel Mac | CPU 端点、Companion/Core 请求控制、电源与原生构建代码本轮补齐 | 物理 Intel、真实依赖编译、模型和安装/故障回滚 |
| Linux | 实际服务、CLI、文件/HTTP/SQLite 范围完成回归 | 原生桌面、会议音轨和宿主 Shell 暂缓 |
| 升级/回滚与代码整理 | 四组件及 APP 事务、历史迁移、模块拆分已有实现；本轮继续消除重复 HTTP 取消实现 | 当前 Intel 原生包和独立反向安装回滚仍需实际材料 |
| Apache 2.0 公开源码 | 自有代码 Apache-2.0；第三方 MIT 等声明保留 | 大模型、数据集及第三方代码不被自动重新许可 |

Issue [#6](https://github.com/www080327-glitch/LocalPilot-OpenSource/issues/6) 和 [#7](https://github.com/www080327-glitch/LocalPilot-OpenSource/issues/7) 的代码实现有推进，真实双向模型协作与当前原生升级验收仍有缺项，因此不以本轮测试自动关闭问题。

## 获取与验证

源码快速安装见 [根 README](../../README.md)。全量计数、环境阻碍、失败历史、产物来源和测试命令见 [本轮证据](../evidence/intel-portability-20261116/RESULTS.md)。只将当前环境无法完成的工作交给 [本机 Work](WORK_INTEL_20261116.md)。旧 evidence 不改写，本轮结果不补记为旧 534 队列的成功。
