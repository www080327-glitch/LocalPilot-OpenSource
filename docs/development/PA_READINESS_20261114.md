# PA 与主 Agent 接入检查（2026-11-14）

> Mac 后续：真实原生、模型与失败回滚的新证据见 [Mac 验收](../evidence/nationals-20261114-pa-mac/RESULTS.md)。下文是本轮初始接入状态，不能覆盖该后续记录。

基线是公开 Draft PR #1 的 `94e0e6ff2c8da974d20530d7a0faa50844d052f4`。本轮是该候选之上的源码修复与隔离验收准备；不是新 Release，也不能替代真实模型和 macOS APP 验收。

## 采用现有 Runtime 的分工

用户入口/已授权活动 → Companion 事件与轻量记忆 → 现有 Agent Service / TaskService → 主 Session → 本地或云端子 Session → 持久结果/SSE → Companion 反馈。

- Companion 负责及时确认、问候、可见活动的索引与证据摘要。无需为固定问候调用大模型。
- 主 Agent 使用现有 V5 Session、Hybrid 和异步调度器分配工作；任务、幂等键、工具收据、取消和 UNKNOWN 仍只有一个事实来源。
- 子 Agent 仅在可分离子任务上协作；本地模型服务可以同时有多个排队子任务，但物理推理请求限流。并发数不是能力分数。
- 模型自行追加或更新 Skill 不属于本轮。宿主审核、显式选择 Skill 后，模型可按用途加载正文。

DeepSeek 参考仓库、固定 SHA、MIT 与本项目已有 Harness 复用的区分见 [官方来源核验](AIC_OFFICIAL_REQUIREMENTS_20261114.md)。本轮参考其分派/执行/反馈思想，未移植其另一套 Runtime，也未复制原型代码。

## 异步子 Agent 的实际配置入口

原 Core 已有 `AsyncPolicy` 和调度器，但 `deployment.build()` 不接受配置。本轮将其接入服务与各 Session，使用同一个调度器，注册表返回 `orchestration` 和限制。

在**新的隔离配置**顶层可加入：

```json
{
  "async_policy": {
    "max_running_children": 4,
    "max_running_per_session": 3,
    "max_model_requests": 3,
    "max_local_model_requests": 1,
    "max_cloud_model_requests": 2
  }
}
```

这是需合并进完整 `service.json` 的片段。数字是保守起点，不是对用户硬件的性能保证；其他字段沿用 `agent.async_runtime.AsyncPolicy`。它不授予任何云端外发权限。省略字段时保留旧的同步路径。原生 Computer Use 与此异步模式暂不在同一服务配置中启用，校验会明确拒绝；未宣称并发控制同一个桌面已经合格。

已用真实本机 HTTP、配置构造、线程调度、工具读取和 SQLite 重启测试两个 Worker 重叠执行、收据保留与同幂等键不二次提交。模型响应为受控 fixture；这证明接线，不证明模型会正确规划。

### 五档来源和四档权限是两条轴

| 来源 | 路由意图 |
|---|---|
| `local-only` | 全过程不调用云端 |
| `local-first` | 本地优先，符合条件才升级 |
| `balanced` | 根据已有策略选择本地/云端 |
| `cloud-first` | 云端优先，可将适合工作交本地 |
| `cloud-only` | 只使用云端模型 |

这五档不是五个固定百分比。真实比例应由每条路由的调用量、token、时间和费用给出；成本未知不能当 0。Companion 触发路径优先使用本地；不能仅因为本地缺权重就把私人活动自动发到云端。

权限仍是只读、请求批准、工作区写入、完全权限。完全权限加既有 `CLOUD_ALLOWED` 时，Hybrid 委派和切换复用宿主授权，不再多一次同义批准。只读子任务不会因父级全权变为可写；OS/TCC、未授予的出站范围、上下文容量和未知收据也不是按钮能抹去的状态。

## Skills 与前缀

`load_skill` 的 schema 现在提供稳定排序的 ID、版本、用途和 bundle 摘要，模型可先选择，再读取完整正文。宿主显式选中且审核过的 Skill 读取属于只读能力，不再无条件要求第二次同义批准。依赖、启用状态和 bundle 内容仍要符合所选版本；运行中内容改变需要新 Session。

**已确认的升级限制：**旧实现选中 Skill 的持久 Session 使用旧工具 schema。新目录元数据改变工具指纹，旧 SQLite 在新服务启动时可能被 `PersistenceError: Host configuration changed` 拒绝。更改 `async_policy` 同样影响恢复契约。必须先保留旧库并在独立目录验证，不可删库、改历史哈希或放松所有指纹来伪造兼容。精确迁移尚未实现。

固定 schema/提示前缀有助于服务端复用；它不是 KV 张量永久驻留的证明。现有受管 oMLX 为单模型 2 GB SSD/128 MB hot 配置，新建 oMLX 设置为 8 GB SSD；Companion worker 仍有逐请求 fresh cache 路径。没有全产品 50 GiB 自动清理，也没有保证重启后命中。详见 [缓存与 Intel 核对](MAC_PORTABILITY_20261114.md)。

后续验证必须固定模型 revision、量化、tokenizer、chat template、提示和 Skills 内容，分别跑冷/热、卸载重载、服务重启；记录缓存计数、TTFT 与总耗时。模型/模板/Skill 任一变化都应按实际后端契约失效。没有计数证据时只能报告配置开启，不能写“永久 KV 已实现”。

## Companion 当前可回答的范围

本轮补充确定性时段问候、wake/活动触发、发生时间对齐的今日/昨日摘要、证据 ID、立即 accepted 反馈和终态通知。SSE 409 时重新读取快照并从新游标续接，补回已生成文本、不重复前缀、不重新提交任务。

观察源仍受用户授权与实际可见性限制。已授权的前台应用、窗口和可访问文字可以形成活动证据；会议音频、未开启转录、隐藏窗口、不可访问的 Codex 内部状态不自动变成已知事实。没有本轮新增的 ASR 或全天录屏能力。回答必须说明覆盖区间与来源，找不到证据就说未观察到，不能把摘要措辞当作感知能力。

Companion 的最高级只读可见性应由用户可检查的来源权限体现，不应靠假定获得 root 或绕开 macOS 授权来描述。数据持久记忆与模型微调是不同层；本轮没有用活动记录训练权重。

## 模型健康和同会话换模

`POST /localpilot/v1/model-health` 对已授权路由做显式只读探测；模型库提供“检查连接”。结果分开记录端点、发现请求鉴权、是否列出/加载模型、推理、工具执行。公开 `/models` 接受请求不能证明密钥对付费推理有效。DeepSeek 现有适配器不支持此只读路径时返回 NOT_PROBED，不借机发送推理请求。原 oMLX 状态缺 loaded 证据时改为未知，不凭缺字段判定未加载。

同 Session 换模通过新的 desktop model 操作，保留会话 ID、canonical history、收据与历史任务原模型；新推理用当前 Session 模型。具体契约和拒绝条件见 [会话迁移说明](SESSION_MODEL_SWITCH_20261114.md)。忙碌、关闭、UNKNOWN、不同工作区/工具/恢复契约或仍保留子 Agent runtime 的会话不能强行迁移；GUI 保留原对话与草稿，显示原因。它不是任意后端无条件热切换。

## 尚需真实环境完成

1. 新候选 APP 原生构建/安装/回滚、系统授权、Shell 与子代理取消、任务及 Session 重启、原生 SSE 409。
2. 已安装权重上的主/子 Agent、四档权限、五档路由、Companion 本地默认与即时反馈。
3. 固定公开基准的 LocalPilot 容器执行 adapter，以及所有正式模型对照运行；目前只有冻结/启动/导入审计工具和官方 schema 契约测试。
4. Intel 原生二进制/依赖/整包资格、CPU 模型性能；目前只完成硬件识别和现有 HTTP 接入回退。
5. 50 GiB 自有可重建缓存策略、真实 KV 重启命中、统一升级产品流程、App 进一步拆分。
6. 可选 LoRA/后训练：先获得有授权且独立划分的数据、强基线与可重复评估，再决定。问候、信息缺失和恢复错误优先在软件层解决；增加参数训练不能补出从未采集的会议内容。

执行顺序及完整提示词见 [Work 交接](WORK_CONTINUE_20261114.md)；测试计数以对应本轮验收记录为准。
