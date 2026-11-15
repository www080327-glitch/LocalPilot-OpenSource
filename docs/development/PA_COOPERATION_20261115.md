# PA 协作评测、来源一致性与主干整理（2026-11-15）

本轮接续 [Draft PR #10](https://github.com/www080327-glitch/LocalPilot-OpenSource/pull/10) 的 `92ad9a30b9fda43bc185d96c99e5cb0a8ce8ec02`，分支为 `codex/pa-cooperation-20261115`。PR #1、#9、#10 的代码基线与 evidence 保留，不把旧原生 APP 的 PASS 转记为新候选的结果。

## 原计划的交付状态

| 目标 | 已实现的代码与本轮推进 | 尚需真实材料或设备 |
|---|---|---|
| Companion → 主 Agent → 多个本地/云端 Worker | 延续同一个 AgentSession/HybridController/TaskService；本轮补宿主指定 Worker 工具工厂，使公开评测中的 Worker 也使用任务环境 | 新候选真实模型五档任务质量、调用来源与成本 |
| 公开、可复查的能力对照 | Harbor 可显式启用多 Agent；父子共用同一模型、同一个请求/token 总预算和容器工具，冻结于新 study | 真实模型、Docker 与完整新队列；没有排名或非劣结论 |
| 全面但有来源的 PA 记忆 | 保留已授权观察入口；本轮修复正式交接遗漏证据类型、撤销来源后复用旧 Session、派生任务摘要的来源失效 | 用户授权的真实 Codex 历史、会议、晚间与睡眠唤醒 |
| 会议与即时反馈 | 不可变会议分段；Core 离线也能查询/停止 Companion 采集，错误状态保留停止入口；原有即时确认/任务结果反馈继续使用 | Swift 编译、TCC 与 mic/system/both 实际音轨 |
| 人工审阅后训练 | GUI/宠物可审阅实际回答与原始来源、编辑并显式保存样本；明确配置训练候选 adapter，默认配置不自动改写 | 实际 LoRA、候选加载推理与独立测试集比较 |
| Skills 与缓存 | 延续稳定目录、按需加载与受管缓存；宿主自定义工具域不注入桌面插件或宿主文件工具 | 真实固定 Skills 集、KV 冷/热/重载性能 |
| Intel Mac | 保留 x86_64 目标资源锁的生成/校验路径、Mach-O 检查及本地 CPU HTTP 服务入口，前端取消固定 arm64 版本文案 | Intel 硬件、真实依赖与 CPU 推理；现有资源锁仍为 arm64 材料 |
| 一次维护与回滚 | 保留 GUI + 四组件事务；本轮修复维护返回展示、助手错误被旧收据遮住、Channels 版本缺项 | 新完整 APP 原生退出/换包/重开与失败回滚 |
| 代码维护 | App 按任务详情、设置、模型选择分离；清除不可达旧委派流程；Core 工具执行/收据集中成一个模块 | 完整功能仍按原流程验收，行数减少不代表质量得分 |

原计划的核心路径已经有实现。真实模型表现、原生平台行为与正式对照仍没有全部验收，不能把这份代码清单写成“产品已全部完成”。

## 子 Agent 的工具域

新增 `AgentSession(child_registry_factory=..., child_registry_contract=...)`，供宿主为新建和恢复的 Worker 构造工具注册表。工厂收到工作区身份、权限模式、能力上限和数据策略；这些仍由宿主确定。非空 JSON 契约进入持久配置摘要，恢复同时检查已经保存的 Worker 工具 schema。

```python
def worker_registry(workspace, *, permission_mode, capabilities, data_policy):
    registry = ToolRegistry(workspace, permission_mode=permission_mode,
                            capabilities=capabilities, data_policy=data_policy)
    # Register the host's actual task-environment bridge here.
    return registry

session = AgentSession(parent_registry, backend=backend,
    child_registry_factory=worker_registry,
    child_registry_contract={"kind": "task-environment", "version": 1})
```

这只是接口形状，空注册表本身不提供可执行工具。实际 Harbor 工厂只注册连接该任务 `environment.exec` 的 Shell。自定义工厂不会再附加默认 `read_file`、`execute`、宿主插件或 Computer 工具；父级动态授权检查仍继承，工厂自身另有授权检查时两者均须通过。普通产品 Session 未设置工厂时保持原有继承路径，配置摘要也不新增默认字段。

此修复针对一个具体问题：旧评测禁止子 Agent，而直接打开它会让默认构造器给 Worker 注册宿主文件工具。现在可以在同一个容器工具域中执行父子任务。只读 Worker 仍不拥有任意 Shell 的写入能力；需要 Shell 的 Worker 应显式申请 `read_only=false`，不把任意命令伪装成只读。

同步/异步回归实际写入独立任务目录，检查宿主目录不变、真实 SQLite 收据恢复、幂等请求不重放、只读上限和工具身份变化后的恢复拒绝。它们是产品协议测试，不是实际模型能力分数。

## 公开评测的边界

新 `orchestration="multi-agent"` 是显式选项，默认单 Agent 仍可运行。新选项要求 `local-openai` 和已配置的测量预算；父子共享一个后端对象、一个调度器和一个模型请求槽。工具执行可以重叠，推理不会各自另开额度。

真实请求 usage 与父子 Runtime 统计交叉核对。请求或 token 预算耗尽发生在发送前时单列记录，任务仍按实际结果失败/未完成；计量器失败、内存条件不成立、缺失 usage、取消后没有可移植终止收据等不会变成合格对照。关闭计量子进程不依赖证据文件成功落盘。

旧 534 次对照仍固定 `1c06e97`，历史快照为 **1 PASS / 3 FAIL / 13 ERROR / 517 无最终结果**。本轮没有运行或改写旧队列。新候选必须另建 study，冻结源码、模型、任务、预算与参考实现。单模型总预算一致的容器对照不等于多模型成本等价，也不覆盖完整桌面 PA。

精确配置、实际测试和执行步骤见 [公开评测续作](EVALUATION_CONTINUATION_20261115.md)。

## 来源撤销与训练候选

Companion 的任务交接保留 `evidence_type`、`evidence_epistemic`、摘要和派生关系。已授权来源停止可用后，基于它的任务摘要不再参加检索；自动会话绑定会转到新 Session，原 Session、任务与收据保留。没有足够输入来源关系的旧任务结果保留为历史记录，不据此恢复可检索上下文。正在执行的任务不会因为绑定失效而被自动重放。

自身采集的会议按不可变片段存储并只同步新增文件，避免每追加一句都重导入整场会议、使先前观察 ID 失效。外部转录导入保持已有版本变化语义。

人工审阅从实际已显示的回答读取问题、回答与原来源。保存前再次确认来源仍可用，允许用户修订标签，不自动保存模型答案为训练真值。训练结果给出独立候选配置；候选 adapter 的运行记录、文件和 base 模型必须对应。实际权重加载和质量增益仍为 NOT_RUN。

本轮选择人工审阅后的 LoRA 路径。既有 `full` 入口对应固定 MLX-LM 支持的 Transformer 层 dense 训练，不包括 embedding/head，不能称作全模型所有参数训练；强化学习执行器仍为 NOT_IMPLEMENTED。这两项边界不能写成仅缺一次本机测试。

详见 [Companion 续作](COMPANION_CONTINUATION_20261115.md) 和 [桌面续作](../../desktop/docs/development/PA_CONTINUATION_20261115.md)。

## 主干整理与实际故障

`agent/session.py` 从 PR #10 的 1564 行降到 1240 行；工具分派、资源指纹、收据记账的九个方法移入 `session_tools.py`，移动前后方法 AST 一致。公开 Session 入口、消息、收据和配置格式保留。

检查发现原 `_fingerprint` 使用 `Path` 却没有导入：需要审批的真实脚本执行因此无法进入正常批准状态。新增用例先复现失败，再补正确导入，验证批准后实际子进程只执行一次，以及文件变更后旧批准无法启动进程。该故障和最早测试夹具错误的日志均保留。

桌面任务详情、设置和模型选择采用已有 React 组件方式分离；删除的旧委派弹窗及心跳没有可达入口，现行 Pet 委派和主窗口云端确认保留。维护助手失败与安装事务收据分别展示，避免旧“成功”记录遮住本次交接失败。

独立 wheel 环境反复暴露 SIGINT 后渠道重开失败。补充固定阶段、异常类名和 errno 后，实际进程探测捕获到根因：`Popen` 刚返回时 `psutil.cmdline()` 可暂时为空，同一进程随后命令行完全匹配；旧启动器误把空观测判为参数改变。修复只将初次空观测延后到既有就绪检查后确认，不增加启动重试或等待时间。初次非空但不同、最终仍空、最终参数改变及保存失败均拒绝并回收同一个子进程。身份记录错误不再被 HTTP 连接重试捕获；私有诊断和首次失败保留，公开错误码不变。原生 macOS 启动仍需本机验证。

最终计数、所有限制和源文件清单以 [本轮证据](../evidence/pa-cooperation-20261115/RESULTS.md) 为准。下一步本机执行使用 [Work 提示词](WORK_PA_COOPERATION_20261115.md)，保留前几轮真实验收和所有失败历史。
