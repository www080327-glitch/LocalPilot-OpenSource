# 公开评估：可选的同容器子 Agent 模式（2026-11-15）

本轮为 `LocalPilotHarborAgent` 增加可选的 `orchestration="multi-agent"`，复用产品 `AgentSession`、子任务预算、异步调度及父子用量合并。它评测的是同一模型、同一总预算下的调度方式。真实模型成绩、Docker 任务执行、多模型公平性和原生 Companion 能力均未由本轮证明。

原有默认仍为 `single`，子 Agent 额度为 0。已有 534 项 study、配置、队列、记录和冻结源码均未修改；新模式必须创建独立的新 study。原队列的续跑与资源预检说明保留在 [EVALUATION_COMPLETION_20261115.md](EVALUATION_COMPLETION_20261115.md)，此文件不更新其历史成绩。

## 接口和执行边界

官方基线仍固定 Harbor **0.26.0**，commit `ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4`。本轮直接阅读该 checkout 的接口，并通过其真实 `AgentConfig`、`AgentFactory`、`ExecResult`、`AgentContext` 执行协议测试。当前官方[自定义 Agent 文档](https://docs.harborframework.com/agents/custom-agents)说明，运行在任务环境外的 Agent 循环应使用 `BaseAgent`，通过 `BaseEnvironment` 操作任务环境。版本行为以固定源码为准：

- [BaseAgent](https://github.com/harbor-framework/harbor/blob/ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4/src/harbor/agents/base.py)
- [AgentFactory](https://github.com/harbor-framework/harbor/blob/ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4/src/harbor/agents/factory.py)
- [BaseEnvironment](https://github.com/harbor-framework/harbor/blob/ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4/src/harbor/environments/base.py)
- [AgentContext](https://github.com/harbor-framework/harbor/blob/ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4/src/harbor/models/agent/context.py)

新模式将同一个 `ContainerRegistryFactory` 交给父会话和产品的 `child_registry_factory` 接口。工厂只注册 `shell`，绑定同一个 Harbor environment 对象、事件循环和 `setup()` 实测的容器 cwd。子会话不会先获得默认宿主文件工具，再事后删除。宿主的空 `registry-identity` 目录仅用于注册表身份；文件读写和 Shell 命令均由 `environment.exec(command=..., cwd=容器路径, timeout_sec=...)` 执行。

Core 的工厂契约为：

```python
factory(workspace, *, permission_mode, capabilities, data_policy) -> ToolRegistry
```

适配器传入的身份描述是 `{"kind":"harbor-container-shell","version":1,"cwd":实际容器cwd}`。Core 验证工厂结果继承 workspace、权限、能力和数据策略；自定义工厂不注入默认宿主工具或插件。主 Agent 的协调动作仍由产品 Runtime 处理，持久化宿主证据属于运行器自身行为，不作为模型可调用的文件工具暴露。

任意 Shell 无法可靠证明只读，因此 Shell 仍声明为 mutating/execute。`read_only=true` 子任务即使在完全权限下也不能执行 Shell；需要 Shell 的子任务须明确 `read_only=false`。提示词要求并行编辑分配不重叠的文件，之后收集子任务结果并核验。此模式没有在 Shell 上虚构文件锁或事务回滚能力。

## 冻结的调度与预算

| 配置或约束 | 行为 |
| --- | --- |
| `orchestration` | 默认 `single`；显式 `multi-agent` 才启用 |
| `max_children` | 新模式默认 4，正整数，作为本轮总子任务上限 |
| `max_running_children` | 默认 2，正整数，不得超过 `max_children` |
| `max_worker_steps` / `max_worker_tool_calls` | 新模式默认 6 次模型步、8 次工具提案上限 |
| `max_worker_token_units` | 新模式默认 131072，产品内部保守 admission units，不能当作真实 tokenizer token |
| `max_worker_output_tokens` | 新模式默认 1024；默认值按父输出上限缩小，显式超过父上限时拒绝 |
| 子任务深度 | 1；本轮只开放父 Agent 调度一层工作 Agent |
| 模型 | `local-openai`，同一 loopback endpoint 和同一 backend 实例 |
| 推理并发 | 父与全部子任务合计 1 个产品 scheduler model slot |
| 工具执行并发 | 可重叠，全部指向同一任务环境 |
| 模型额度 | 全部共享一份 `model-budget.jsonl` 和同一个 tokenizer 子进程 |
| 子任务内部额度 | 新模式显式冻结上述四个上限，仍受产品 `SessionBudgets` 的父预算预留约束；不为每个 worker 增加一份模型总额度 |

新模式要求 `model_budget`，并使用 `chat_template_kwargs={"enable_thinking":false}` 的已有测量 transport。一次模型请求仍先计真实输入 token、预留最大输出，再依据提供方 usage 结算。输入计数不一致、缺失 usage、HTTP/流式失败、输出越界继续使尝试失去资格。

审阅中实际发现，沿用原产品 worker 的 32768 admission units 时，约 20000 会留给最终回答，默认子 Agent 做一次 Shell 后就进入 token_reserve 收尾。因此只增加 opt-in 模式的内部上限，并将有效值写入冻结契约；没有扩大唯一的真实 `model_budget`。新增回归使用默认 worker 参数，让两个真实产品子会话各执行写入、追加、读取三次 Shell 后再汇总，合计 11 次 HTTP 请求；总请求上限为 3 时仍只能发送 3 次，不会借子任务获得新额度。

新增发送前拒绝记录只在新模式启用，旧默认日志格式保持原有行为：

- `requests` / `tokens`：模型预算已耗尽，尚未发送 HTTP。额度不会恢复；对应的产品 `failed_attempts` 与账本逐一对账。该任务可以作为预算内失败被纳入比较，不能因此变成成功。
- `memory_headroom` / `tokenizer_failure`：保存拒绝记录，但资源或计量前提不成立，审计为 `UNQUALIFIED`。
- 记录证据失败仍通过 `finally` 关闭 tokenizer 子进程；不会因磁盘写失败遗留计数进程。

`localpilot-orchestration.json` 保存实际注册表工具、父子是否共用 backend/scheduler、实际模型槽、子任务列表、父子合并请求/usage 和取消状态。审计要求这些记录与冻结契约及预算账本一致，缺失或不一致就阻断比较。启用了多子 Agent 模式但实际没有委派时，报告 `observed_delegation=false`，不会将选项开启当作子 Agent 运行证据。

正常任务结果仍由原始 Harbor verifier 给出。PASS、FAIL、ERROR、NOT_RUN 和已有重试/重复检查不变。取消后的容器进程终止没有跨环境通用回执；即便稍后收到模型结算，取消的新模式尝试仍不能获得比较资格。

## 可比较的范围

`comparison_configuration` 继续要求相同的注册模型、endpoint、tokenizer、总请求/输入/输出/总 token 额度、任务超时，以及固定的模型 revision/量化/tokenizer 身份声明。新模式附加父子共享证据；单模型串行推理条件不能被误报为多个强模型协作。

参考臂仍是固定 Harbor 的 `BudgetedTerminusAgent`：它使用同一测量 transport，但保留官方 Terminus2 的任务循环、终端协议与解析。它不接收 LocalPilot 专用子任务参数；误传时冻结/资格检查拒绝，避免一个选项被参考适配器默默忽略。两个臂的工具协议与调度方式本就不同，因此结论仅限于**同模型、同模型总预算的 harness 比较**，不能声称架构、工具吞吐、墙钟成本或硬件消耗完全等价。

多模型、云端 worker、MCP/Skills、桌面 UI、会议理解、个人记忆、长期 Session 和日常产品全部能力仍不在本次适配范围。模型返回的得分或自评不参与成绩。

## 已执行验证

本轮使用已有独立 Harbor 验证环境，没有修改产品依赖。实际环境：Python 3.12.14、Harbor 0.26.0、psutil 7.2.2、pydantic 2.14.3、litellm 1.109.1；这些是本环境实际安装版本，不冒称旧版本锁。

最终命令：

```bash
LOCALPILOT_HARBOR_CONTRACT=1 LITELLM_LOCAL_MODEL_COST_MAP=True \
/workspace/scratch/2a488f6eabf5/harbor-contract-venv/bin/python -m unittest \
  tests.test_public_agent_eval tests.test_harbor_adapter tests.test_harbor_model_budget \
  tests.test_harbor_budget_protocol tests.test_harbor_budget_audit \
  tests.test_harbor_study_runner tests.test_harbor_owned_cache \
  tests.test_harbor_orchestration -v
```

最终 worker 预算修正后的结果：**76 项，72 PASS、4 SKIP、0 FAIL、0 ERROR，24.191 秒**。4 个 SKIP 均为已有真实模型资格测试，需要本机的模型及 tokenizer 环境。本次 10 个新增测试全部通过；其中 7 项实际加载官方 Harbor 契约。

新增验证使用真实 HTTP 服务、真实产品父子 AgentSession、真实持久 tokenizer 协议子进程，以及执行真实 Shell 写入的临时目录环境夹具。它验证跨线程调用环境的协议和预算边界，**不等于运行了 Docker 容器或真实模型**。覆盖两个子任务 Shell 重叠执行、共享请求/usage、请求上限前拒绝、只读禁止 Shell、禁止宿主默认文件工具回退、证据/槽/usage 不符拒绝、资源和计数失败、证据写失败仍回收进程、没有实际委派时不声称运行了子 Agent。

首轮新增测试为 5 PASS、1 ERROR：测试 HTTP 应答器误用 tool message 的 `name` 判断收集结果，而产品发送的 OpenAI 工具消息以 `tool_call_id` 关联。夹具因此重复请求等待，产品正常停止为 incomplete。修正夹具协议后通过，没有为测试放宽产品行为。该首次输出只在工具对话中保留，没有单独原始日志文件，临时目录已由测试清理。此前一次未开启官方 schema 环境开关的 72 项运行也通过，但其 7 SKIP 不是本段最终计数。

最终原始日志是云端工作目录 `validation/eval-continuation-20261115/harbor-contract-final-workers.log`，实际源码摘要与测试文件摘要保存在 `worker-budget-source.json`，环境版本见 `environment.json`。预算修正前 75 项的 `harbor-contract-final.log` 也保留，未覆盖。原有验收目录未修改。

## Work 需要完成的真实运行

1. 使用本轮完成后的固定源码 checkout 和独立评估环境；Harbor checkout 固定上述 commit。保留原 534 项队列的源码、配置与已开始尝试，用原协议处理其恢复。
2. 解决本机模型与磁盘/专用 Docker 环境条件，先执行已有 `tests.test_harbor_model_budget` 四项真实模型资格验证。使用既有入口，不把合成协议测试替换成这四项成绩。
3. 创建独立的 `new-study-spec.json`。模型名、endpoint、model_identity、tokenizer 路径和预算均填实际已核验值；候选臂增加下列 kwargs，参考臂使用相同模型总预算但不要传这些 LocalPilot 专用字段：

```json
{
  "orchestration": "multi-agent",
  "max_children": 4,
  "max_running_children": 2,
  "max_worker_steps": 6,
  "max_worker_tool_calls": 8,
  "max_worker_token_units": 131072,
  "max_worker_output_tokens": 1024
}
```

4. 保留官方任务选择和 verifier。先做独立 smoke，不把 smoke 的子集成绩当完整 benchmark。正式 study 必须在运行之前冻结任务、重复次数、两臂、模型身份和新源码。新 `study.json` 自动记录 `orchestration_contracts`，不能在旧 study 上改 mode 或额度。

```bash
"$EVAL_PY" scripts/public_agent_eval.py freeze \
  --spec /实际/new-study-spec.json --repository "$BENCHMARK_REPO" \
  --output "$NEW_STUDY"

"$EVAL_PY" scripts/public_agent_eval.py preflight \
  --study "$NEW_STUDY" --arm localpilot --repeat 1 \
  --repository "$BENCHMARK_REPO" --harbor-repository "$HARBOR_REPO" \
  --runtime-repository "$FROZEN_RUNTIME" --python "$EVAL_PY" \
  --docker-host "$DOCKER_SOCKET" --resource-evidence /实际/新guest-df.json \
  --output /实际/新preflight.json
```

5. 所有资源预检通过后用既有 `run`/`resume` 逐臂、逐次执行，保持 `n_concurrent_trials=1`，不自动重试已开始的失败。每个 trial 保留原始 Harbor 结果、预算账本、事件和 `localpilot-orchestration.json`。实际检查 Docker 中的父/子命令及产物归属，确认宿主没有模型工具写入。资源不足、取消未结算、计数不一致和协议失败如实保留。
6. 使用 `audit --study "$NEW_STUDY" --output /实际/新audit.json`。结果完整且比较资格成立之后，才报告 paired comparison；任何失败仍在原分母。另列实际委派数、零委派任务数、共享预算、总模型请求和用量。即使获得成绩，也只描述此任务集、模型与固定配置下的结果。

本轮尚未执行真实 Docker/模型 smoke 或正式 Terminal-Bench；这些项目为 **NOT_RUN**。没有发布外部榜单成绩，没有改变旧队列的完成率。
