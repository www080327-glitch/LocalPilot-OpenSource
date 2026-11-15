# PA 产品补齐与源码整理（2026-11-15）

本轮从 Draft PR #9 的 `0a7fdff36f45a471130293b508b5d008f40cecf9` 继续。PR #1 的 `94e0e6f` 和 PR #9 的原生验收、失败历史、冻结评测全部保留。这里描述新候选的实现；实际运行结果见本轮 evidence，不能用旧 `d2b2fae` APP 的 PASS 代替新代码的原生资格。

## 原计划与当前实现

| 目标 | 本轮交付 | 仍需实际环境给出的证据 |
|---|---|---|
| Companion → 主 Agent → 多个本地/云端 Worker | 复用 AgentSession、HybridController、TaskService 和同一异步调度器；多个注册模型、即时确认、子任务结果与持久收据 | 新候选真实模型规划与任务质量 |
| 五档来源策略 | 保留 local-only/local-first/balanced/cloud-first/cloud-only；新协作 Agent 可选择多个已配置伙伴 | 每档在真实任务下的调用/延迟/成本分布 |
| 已有会话继续换模型 | 已完成 child tree 保留原后端、消息、收据、调用身份；主模型及同步/异步模式可在兼容的空闲边界切换 | 新 APP 原生界面与真实模型复测 |
| Skills 按需使用 | 稳定目录、内容摘要、按需 load_skill；新 Worker 继承宿主已经审核的 Skills/工具，保留只读上限 | 大规模实际 Skills 集的上下文和模型表现 |
| PA 活动记忆 | 显式 Codex/会议来源、同步/停用/撤销、来源问答、时间与覆盖边界；新增本地会议采集入口 | 用户允许的真实历史、会议和系统授权 |
| 晨晚问候/唤醒 | 保留已有原生唤醒接线；补软件时段、安静时段、重启去重检查 | 晚间及真实系统睡眠唤醒 |
| 后训练 | 人工审阅样本、来源分组切分、JSONL/manifest、固定 mlx-lm 的离线训练计划和显式启动 | 实际 LoRA 训练、独立集比较；不能报告能力提高 |
| KV 与缓存 | 保留已实现的受管 50 GiB 准入；主/子模型可沿用显式稳定前缀；固定 Skill 目录不逐轮变序 | 新候选冷/热、模型重载与服务重启的后端计数和 TTFT |
| Intel Mac | 架构选择、真实目标依赖锁生成/校验、Node 资源选择、Mach-O 检查、本地兼容端点入口 | Intel 真实 wheel、x86_64 APP、CPU 模型性能 |
| 一次维护与失败回滚 | GUI、Core、Companion、Suite、Channels 纳入现有计划/执行/回滚机制 | 新完整 APP 与原生 Channels runtime 升级资格 |
| 外部榜单 | 正式运行预检、冻结源码和预算、无损续跑、结果及共享 transport 审计 | 完整对照队列；没有排名或非劣结论 |
| 开源与历史 | 自有新代码延续 Apache-2.0，保留第三方许可证；可执行代码/测试/文档进入 Draft PR | 未公开历史 benchmark 原件及历史 Release 资产来源 |

## 多模型配置与实际比例

新的 `cooperation.routes` 是已注册、同工作区、工具可用、非受管加载器的伙伴 route ID 列表。旧 `cloud_route` / `local_route` 配置继续工作，旧配置的完整恢复指纹由真实旧源码比较测试覆盖。

```json
{
  "async_policy": {
    "max_running_children": 4,
    "max_running_per_session": 3,
    "max_model_requests": 3,
    "max_local_model_requests": 1,
    "max_cloud_model_requests": 2
  },
  "routes": {
    "pa-main": {
      "workspace": "/absolute/authorized/workspace",
      "engine": "v5",
      "orchestration_mode": "async",
      "cloud_egress": "CLOUD_ALLOWED",
      "backend": {
        "kind": "local-openai",
        "model": "existing-local-model",
        "base_url": "http://127.0.0.1:8048/v1",
        "context_budget": 32768
      },
      "cooperation": {
        "routes": ["registered-local-worker", "registered-cloud-worker"],
        "optimizer": {"mode": "local-first"}
      },
      "budgets": {
        "max_steps": 48,
        "max_tool_calls": 64,
        "max_token_units": 4194304,
        "max_subagents_per_turn": 4,
        "max_worker_steps": 12,
        "max_worker_tool_calls": 16,
        "max_worker_token_units": 524288
      }
    }
  }
}
```

这是配置片段，伙伴 route、客户端映射、现有凭据及服务目录仍需使用真实配置。`CLOUD_ALLOWED` 是明确的云端外发授权，不应复制到没有这项授权的私人活动路径。Companion 的默认升级仍选本地。Worker 使用 runtime schema 给出的 `backend_id`；新伙伴内部别名为 `route:<注册 route ID>`，不会覆盖主模型的 `selected`。

原有服务没有异步设置时，新增协作 route 会给旧 route 标记 `orchestration_mode: "sync"`，给新 route 标记 `"async"`，共享顶层资源限制。旧 Session 的实际配置保持同步，不需要删除旧库。保存配置后由用户通过现有服务控制入口恢复 Core；保存不是模型已连接或已完成推理的证明。

五档是来源偏好，不是固定的本地/云端百分比。`HybridController.summary().source_mix` 对同一任务的主/子 Agent 统计已分派请求、本地/云端请求占比、提供方报告的输入输出 token。任何调用缺 usage 时，完整 token 占比为 `null/UNKNOWN`；未取得分派证据的尝试单列。API 实际费用仍需要真实计费记录，不能由 token 占比推成零费用。

## 完整历史与调度迁移

已完成 Worker 保留旧后端，主模型迁移不重新标记过去的模型身份。Session 保存每个历史 child 的原 route、Desktop 选项、扩展和完整配置摘要；重启用原宿主工厂重建这棵历史树，再恢复原 checkpoint。原始任务、messages、ledger、completed call IDs、UNKNOWN 和幂等键不重写，也不触发推理或工具重放。

因此，仍应保留历史子代理引用的 route 配置。删除旧 route、替换其后端或更改工具契约会使恢复明确拒绝；一个失去来源的旧后端不能被新模型冒名顶替。已声明的私有目录迁移要同时对历史 descriptor 做精确反投影和完整摘要比较。

空闲模型选择可在同一共享调度器下切换同步/异步 route。忙碌、待批准、UNKNOWN、不同工作区/工具/预算/验证契约仍明确拒绝。原生 Computer Use 或 calibrated adaptive 的跨模型迁移仍是不同契约，不声称任意运行状态下都能热切换。

直接更改已有 route 的顶层异步资源策略时，可显式配置：

```json
{
  "restore_async_policy_migration": {
    "version": 1,
    "sessions": [
      {
        "session_id": "从原库读取的准确 Session ID",
        "configuration_sha256": "原 checkpoint 的准确 64 位摘要"
      }
    ]
  }
}
```

它只允许所有执行节点都已结束、没有未决批准/调用/UNKNOWN 的 Session。只反投影原异步策略后比较全部宿主配置，不忽略权限、路径、工具或模型变化。成功后追加新 checkpoint，旧 journal 保持不变。可与显式 Skill/私有路径迁移配合；不同的历史材料仍须有对应依据。

## 记忆、会议和训练的区别

Codex 导入只处理用户/助手可见文本，隐藏推理和工具载荷不进入活动记忆。助手文字保留 `MODEL_INFERRED / reported_unverified_text`，不会因压缩或索引而变成外部验证事实。来源由用户选择，停用、撤销、暂停及时影响可检索范围；不会自动扫描默认私人历史目录。

会议可以导入已有转录，也新增显式开启的本地语音采集。Swift helper 分别处理麦克风与系统音轨，只输出最终文字及来源/时间，原始音视频不落盘；没有屏幕帧输出。音轨失败时整个会话结束，不悄悄降为单路。它不是说话人身份识别，也不能保证语音转写无误。

本地 Speech 必须同时满足 `supportsOnDeviceRecognition` 与 `requiresOnDeviceRecognition`。没有本地识别能力时返回不可用，不转向云端。系统音轨依赖 macOS 13+ ScreenCaptureKit，正常请求系统权限。用户明确开始才请求授权，停止或控制进程退出即结束采集。50 秒分段在内存中缓冲下一段，并给最终转写设置有界等待。新 helper 的 macOS 编译、权限对话框和真实音轨为本轮环境不能验证的项目。

官方接口依据：[本地识别开关](https://developer.apple.com/documentation/speech/sfspeechrecognitionrequest/requiresondevicerecognition)、[本地能力](https://developer.apple.com/documentation/speech/sfspeechrecognizer/supportsondevicerecognition)、[Speech 权限与用途声明](https://developer.apple.com/documentation/speech/asking-permission-to-use-speech-recognition)、[音频采集与 macOS 13 起始版本](https://developer.apple.com/documentation/screencapturekit/scstreamconfiguration/capturesaudio)、[Speech 错误码](https://developer.apple.com/documentation/speech/sfspeechrecognitiontask/error)。

活动观察不是训练标签。后训练入口只使用人工确认的样本，按来源分组划分训练/验证集合，保存数据与配置摘要。训练不会由模型自行启动，也不自动替换当前产品模型。使用锁定的 `mlx-lm==0.31.3` 接口；其 `full` 模式实际解冻选定 Transformer 层，不能宣称已经训练整个模型的所有参数。实际 LoRA 及质量增益仍需要本机运行和独立集比较。

## 缓存和 Intel 的实际含义

固定系统提示、排序后的 Skill 目录和稳定工具 schema 支持后端复用前缀。新版 Worker 在显式新协作配置中沿用伙伴 route 的稳定前缀选项；不同模型、模板、目录摘要不会冒充同一缓存身份。50 GiB 是已确认归属的可重建前缀缓存容量准入上限，不是机器可用空间，也不是永不失效的承诺。缓存内容仍受后端 LRU、版本和模型身份约束。

Intel 的产品路径是原生 x86_64 客户端/资源校验与已配置的 CPU OpenAI 兼容本地服务。它不依赖 MPS/MLX 可用，也不把远端服务包装成本地。源码支持不能代替真实 x86_64 wheel、Mach-O、模型加载和性能验收；没有真实资源时生成锁工具必须拒绝编造 hash。MLX 后训练不因此在 Intel 上变为可用。

## 源码整理与验证边界

- `AgentSession` 按模型请求、原生电脑控制、Worker 执行和公开状态类型分离；新建/恢复 Worker 共用 `child_sessions.py`，避免两套继承逻辑漂移。
- Desktop 的会话恢复、连接和 SSE 流分到具体 hooks；升级、来源管理、协作模型配置有独立组件。
- Companion 拆成观察、对话、任务、命令组件；公共入口保留，命令用明确 handler 分派。
- 主/子模型运输层构造合并，Desktop 模型迁移和历史 Worker 来源有单独模块。
- 维护和公开评估按已有职责拆模块，不增加第二套 Runtime、Router 或包管理器。

这些调整以实际文件、SQLite、HTTP/TLS、子进程和既有测试验证。测试模型响应只证明协议和状态迁移；不能证明主 Agent 不弱于主流产品。

旧 534 次正式对照冻结在 `1c06e97`。新候选源码不能接管旧实验并被当作相同样本；保留其已发生的 1 PASS / 3 FAIL / 13 ERROR 和全部未结算分母。若评估新候选，需要新的 study ID 与冻结源码，在同一公开任务、模型、预算和参考协议下完整运行。详见 [公开评估补齐](EVALUATION_COMPLETION_20261115.md)。

历史 benchmark 的 12 个公开门控测试文件依赖尚未公开的原实现/夹具；本轮没有从断言反造“历史实现”来消除 SKIP。真实 Release 归档、AIC 表单提交、模型训练效果和完整外部榜单也不属于可以由源码测试代替的结果。

## 独立 wheel 的归属与开源声明

旧 Core 和独立 Channels 分发同时拥有 `localpilot_channels`、console entry point 与渠道资源，pip 卸载/回滚其中一个会删除或覆盖另一个的文件。新 Core 只包含 Core；渠道代码、入口和资源由 Channels wheel 唯一拥有。遇到仍包含渠道的旧 Core，统一维护必须同时有准确的 Channels 目标与回滚 wheel，并在回滚最后重新安装独立 Channels。也覆盖 Core 刚开始安装便失败、还没有轮到 Channels 安装的情况。

四个真实新 wheel 包含 255 个唯一 Python 文件，均已与当前源码逐字节核对；Companion 的会议 Swift 和原有 AX 数据文件也在包内。在另一个全新 Python 环境、仓库之外运行导入、入口帮助、Suite 版本、真实文件工具与渠道生命周期检查，避免可编辑源码掩盖打包缺失。Linux wheel 验证不替代 macOS 完整资源与 APP 资格。

根自有源码维持 Apache-2.0。Companion、Suite 的 wheel 包含完整 Apache 许可证与 SPDX 元数据；Core 的 DeepSeek 适配、Channels 的 iLink 适配保留实际 MIT 署名，因此这两个分发如实声明 `Apache-2.0 AND MIT`。这不改变第三方代码的许可，也不把第三方模型、数据或未公开 benchmark 自动重许可。setuptools 的正式 SPDX / license-files 配置以 77+ 为最低构建要求，运行时 Python 要求不变。构建时另发现 `companion.observers.shared_ax` 缺显式包声明，已在源头补齐并重建，相关警告消失。

## 本轮记录与下一步

最终命令、计数、跳过原因、失败历史、四个 wheel 摘要和脱敏日志见 [本轮验证记录](../evidence/pa-completion-20261115/RESULTS.md)。统一的 [Work 本机提示词](WORK_PA_COMPLETION_20261115.md)覆盖新候选剩余原生验收、公开评估、真实来源、后训练和 Intel 材料；不要求再次改写已完成的体系。
