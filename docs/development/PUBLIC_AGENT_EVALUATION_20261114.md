# 公开 Agent 基准接入与复现协议（2026-11-14）

## 当前交付和证据边界

`scripts/public_agent_eval.py` 提供任务预注册、官方 Harbor 作业生成/启动、逐任务结果导入和配对比较。它不自建题库、不替换官方验证器、不把软件回归测试计为模型成功率。

2026-11-15 的 Mac 续测已在真实 Docker 容器完成官方 hello-world 开发 smoke，严格审计 LocalPilot 1 PASS、Nop 1 FAIL；它不是 Terminal-Bench 或 AA 榜单成绩。`scripts.localpilot_harbor:LocalPilotHarborAgent` 使用现有 V5 `AgentSession`，通过官方 `environment.exec` 执行任务容器 Shell，仅注册该容器工具，不注册 Mac 文件或 Shell 工具。受控解析器单测、产品回归、历史 adapted BFCL、开发 smoke 与正式比较分别报告，详见文末 Mac 记录。

本接口按以下官方源码审查：

- Harbor `0.26.0`，commit `ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4`。
- [JobConfig](https://github.com/harbor-framework/harbor/blob/ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4/src/harbor/models/job/config.py)、[TrialConfig](https://github.com/harbor-framework/harbor/blob/ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4/src/harbor/models/trial/config.py)。
- [TrialResult](https://github.com/harbor-framework/harbor/blob/ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4/src/harbor/models/trial/result.py)、[VerifierResult](https://github.com/harbor-framework/harbor/blob/ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4/src/harbor/models/verifier/result.py)、[AgentContext](https://github.com/harbor-framework/harbor/blob/ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4/src/harbor/models/agent/context.py)。
- [BaseAgent](https://github.com/harbor-framework/harbor/blob/ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4/src/harbor/agents/base.py) 与 [官方 CLI](https://github.com/harbor-framework/harbor/blob/ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4/src/harbor/cli/main.py)。

源码要求 Python 3.12+。评估工具使用标准库，不给 LocalPilot 生产环境添加 Harbor 依赖；Harbor 放在独立的评估环境。没有复制 Harbor 实现或原始基准题目进本仓库。

## 先确定所证明的能力

建议主 Agent 首先接入固定版本的 Terminal-Bench，再根据能力范围补 τ²-Bench 或 OSWorld。完整官方基准与预注册子集必须分别命名；一个小子集只能用于接入验证或范围受限的比较。

| 目标 | 可采用的官方资源 | 比较限制 |
|---|---|---|
| 终端工具与任务完成 | [Terminal-Bench](https://www.tbench.ai/benchmarks)、[Harbor](https://github.com/harbor-framework/harbor) | 固定任务、容器、超时、模型、harness 版本；由官方验证器判断结果 |
| 工具对话与用户协作 | [τ²-Bench](https://github.com/sierra-research/tau2-bench) | 另需固定用户模拟器模型和配置；本脚本还未适配其输出 |
| 原生 GUI 操作 | [OSWorld](https://github.com/xlang-ai/OSWorld) | 需要对应虚拟机与官方评估环境；不能用浏览器合成桥替代 |
| 办公文件成果 | [GDPval-AA 方法](https://artificialanalysis.ai/methodology/intelligence-benchmarking) | 自行使用公开 GDPval 任务的盲评不等于 AA 官方 Elo |
| 检索与通用助理 | [GAIA 数据卡](https://huggingface.co/datasets/gaia-benchmark/GAIA) | 有访问与禁止公开转发的条件；不得把题目直接公开进 Apache 仓库 |

AA 旧版的 Terminal-Bench Hard 和 τ²-Bench Telecom 方法仍在其官方方法页。应指定究竟复现哪一版，不能将旧任务与新榜单数字直接比较。[AA-AnalystAgent](https://artificialanalysis.ai/evaluations/aa-analyst-agent) 的完整问题、源文件与参考答案未公开；开源 Stirrup 不等于该数据集也开源。

## 1. 准备模型、官方基准和独立运行环境

Work 先安装可用的 Docker，确认模型服务可从评估容器访问。在独立目录克隆官方 benchmark 和 Harbor，把两者都 checkout 到完整 commit。正式运行前固定 benchmark release 与 commit 的对应关系。

```bash
git clone https://github.com/harbor-framework/harbor.git /absolute/eval/harbor
git -C /absolute/eval/harbor checkout ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4
python3.12 -m venv /absolute/eval/venv
/absolute/eval/venv/bin/python -m pip install -e /absolute/eval/harbor
```

这些路径为需要替换的示例，不代表已存在的本机路径。安装时记录实际依赖锁与环境信息。不能为了复现而改动日常 LocalPilot 的环境。

完整 LocalPilot 接入应实现官方 `BaseAgent` 的 `name()`、`version()`、`setup(environment)` 和 `run(instruction, environment, context)`。`run` 必须使用现有 LocalPilot Runtime/Session，让正常工具调用在 **Harbor 的任务容器内** 执行；不能将工具执行留在宿主 Mac，再把文字回答当作完成了容器任务。可以把固定 LocalPilot wheel 与薄启动器安装进该容器，然后通过 `environment.exec` 启动；另一种方式是将已有工具适配到 Harbor environment，前提是实际读写对象一致。由实现者按现有 CLI/Session 接口选择，不能另写一个简化 Agent 循环冒充产品。

`AgentContext` 中记录真实可得的 `n_input_tokens`、`n_cache_tokens`、`n_output_tokens`、`cost_usd`；输入 token 已包含 cache token，不再把 cache token 加到总输入。模型价格或用量未知时保留空值。需要多模型/子代理计量时额外保留产品自身逐路由证据，本脚本目前只汇总 Harbor 提供的总量。

## 2. 写明实验配置，再冻结

先做 `purpose: "smoke"` 的接入检查，再单独创建正式 `evaluation`。不要边看结果边修改原试验。

以下 JSON 是格式示例，`YOUR_*`、revision 和模型必须换成实际值；示例本身不可作为实验注册：

```json
{
  "benchmark": "terminal-bench@2.0",
  "repository_url": "https://github.com/harbor-framework/terminal-bench-2",
  "purpose": "evaluation",
  "repeats": 3,
  "arms": [
    {
      "id": "localpilot",
      "revision": "YOUR_LOCALPILOT_FULL_COMMIT",
      "agent": {
        "import_path": "YOUR_ADAPTER_MODULE:LocalPilotHarborAgent",
        "model_name": "YOUR_PROVIDER/YOUR_MODEL",
        "kwargs": {}
      }
    },
    {
      "id": "reference",
      "revision": "PINNED_REFERENCE_AGENT_REVISION",
      "agent": {
        "name": "mini-swe-agent",
        "model_name": "YOUR_PROVIDER/YOUR_MODEL",
        "kwargs": {}
      }
    }
  ],
  "execution": {
    "n_concurrent_trials": 1,
    "timeout_multiplier": 1.0
  },
  "comparison": {"candidate": "localpilot", "baseline": "reference"}
}
```

`tasks` 可选：省略时选择 `--task-prefix` 下发现的所有 `task.toml`；指定时必须是相对 Git 根目录的非重复任务目录列表。它不是字符串模糊匹配，不会悄悄忽略不存在的任务。多步骤任务当前明确拒绝。

```bash
python3.12 scripts/public_agent_eval.py freeze \
  --spec /absolute/eval/spec.json \
  --repository /absolute/eval/terminal-bench-checkout \
  --task-prefix tasks \
  --output /absolute/eval/study-001
```

如果官方仓库直接将各任务放在根目录，省略 `--task-prefix tasks`。不要假定不同基准版本的目录一致。

冻结过程读取真实 Git HEAD，要求所选任务目录干净，保存各文件 SHA-256、任务名称和路径。它生成 `study.json` 和每个 arm×repeat 独立的 Harbor 配置，固定 `n_attempts=1`、`max_retries=0` 和 Docker 环境。重复实验用不同 job，防止失败被重试后的成功覆盖。

`all_tasks_in_checkout_prefix` 仅代表所选 checkout/prefix 中发现的全部任务，不自动证明与官方完整发布任务数一致。正式报告仍须对照官方 release 清单。将 `study.json` 的哈希及脱敏配置在运行前提交到审查分支或时间戳记录；本地文件的生成时间和哈希不构成第三方时间戳认证。

产物含绝对作业目录，冻结后不要移动或手改；改变位置、模型、预算或题目需创建新研究。API 密钥留在环境变量或原有凭据机制，不能写进 spec、agent kwargs 或公开证据。

## 3. 按冻结的作业运行

```bash
python3.12 scripts/public_agent_eval.py run \
  --study /absolute/eval/study-001 \
  --arm localpilot --repeat 1 \
  --harbor-repository /absolute/eval/harbor \
  --python /absolute/eval/venv/bin/python
```

每个注册的 arm、repeat 都执行一次。`run` 校验 Harbor checkout 的精确 SHA 与已跟踪文件状态，从该 checkout 加载官方 CLI，记录启动与退出；它不绕过已有作业重新运行，不把进程退出 0 当作任务通过。未安装依赖、缺少 LocalPilot adapter 或模型不可访问时会留下启动日志，必须报告实际失败。

无需使用本脚本启动器时，也可以按生成文件运行官方命令：

```bash
/absolute/eval/venv/bin/harbor run --config /absolute/eval/study-001/configs/GENERATED_JOB_NAME.json
```

此时由执行者另外记录 Harbor 的安装来源和版本。审计器检查结果与冻结配置一致，但不能从用户提供的 JSON 独立证明其实际运行了哪一个模型或实现。

## 4. 导入所有逐任务结果

```bash
python3.12 scripts/public_agent_eval.py audit \
  --study /absolute/eval/study-001 \
  --output /absolute/eval/study-001-audit.json
```

按固定 Harbor 布局读取每个 job 的 `config.json`、`result.json` 和各 trial 子目录的 `result.json`。保留原始文件哈希，核对源 commit、任务、模型配置、Docker 环境、超时倍率与未关闭的官方 verifier。`agent.kwargs` 以及 agent 超时、端点、额外 Skills/上下文等配置必须与冻结值完全相同；不接受运行后才追加的步骤预算、历史轨迹、分阶段超时倍率或容器资源/挂载覆盖。当前环境资源由官方任务配置决定；需要覆盖时须先扩展冻结协议。作业中出现额外 retry、不同 attempt 数、未知任务、复用 trial id、重复结果、预注册前结果或无法解析的 JSON 都会明确记录，并阻止有效配对结论。

| 状态 | 统计方式 |
|---|---|
| `PASS` | 完整执行和验证，唯一二值 `reward=1`，无异常 |
| `FAIL` | 完整执行和验证，`reward=0` |
| `ERROR` | 异常或无效 reward 标记；即便此前 verifier 给出 1，也不算严格完成 |
| `INCOMPLETE` | 没有完成时间、执行/验证阶段未结束，或缺验证结果 |
| `NOT_RUN` | 注册的任务结果缺失，保留在总分母 |
| `DUPLICATE` | 同一 arm/repeat/task 有多条结果，全部列出，不择优 |
| `INVALID` | 输入或来源配置不合约，保留问题和证据位置 |

本脚本的严格完成率与 Harbor 可能保留的异常后有效 reward 是两个口径：两者字段分别保存，不能冒充原始榜单口径。当前只支持单步骤、单个名为 `reward` 的二值验证结果；多指标、连续奖励、多步骤、定制 verifier、regrade 与其他基准格式必须先扩展并验证适配器。

有缺失时，`strict_success_rate_all_planned` 是按全部计划尝试计算的保守下界，`rate_is_lower_bound=true`；不能将它误读为完整实验。审计不完整时退出码为 2，仍写出完整审计报告；完整且无结构问题时退出码为 0，即使有真实任务失败。模型失败不能被转换成“审计脚本失败后扔掉该行”。

`known_sum` 与 `reported_trials`/`missing_trials` 一同报告费用和用量；空费用不是 0 美元。

## 5. 配对比较与可对外声明的结论

审计完整后，对相同任务的各次尝试先取平均，再计算候选减基线的逐任务差异、均值和胜/平/负任务数。另报告每次尝试成功率、所有重复均成功的比例、至少一次成功的比例。

这个结果是描述性配对比较，不自动给出“不弱于主流 Agent”的结论：没有预注册的非劣界值、足够样本和对应统计检验时，差异不显著不能视为等效。输出始终保留 `noninferiority_established=false`，也不声称它是官方榜单提交。

应分别做：

1. **同模型、同预算、同任务**：检验 LocalPilot 调度与工具执行是否降低该模型的任务表现。
2. **明确版本的主流产品对照**：单列模型、工具、费用和环境差异，避免把模型强弱都归因于架构。
3. **五档协同对照**：若要比较五档，则冻结同一任务集，统计真实本地/云端请求及全部尝试资源，不把模型注册比例当实际调用比例。

公开题目、官方解答和 verifier 不能进入 Agent 的可见材料、Skills、训练数据或试验后调参反馈。需要调试的任务另设 development；最终评估任务只在方案冻结后使用。

## 本轮验证

```bash
.venv/bin/python -m unittest -v tests.test_public_agent_eval
```

2026-11-14：**19 PASS、1 SKIP**，共 20 项，0.907 秒；跳过的是需要独立 Harbor 环境的官方类型契约检查。测试使用真实临时 Git 仓库、文件、JSON 和 CLI，无 mock；它们验证此脚本的实际行为，不代表运行了外部 benchmark。

另在独立的 Python 3.12 环境中安装上述固定 commit 的 Harbor（`--no-deps -e`）及类型检查所需依赖 `pydantic==2.14.3`、`shortuuid==1.0.13`、`toml==0.10.2`、`pathspec==1.1.1`、`packaging==26.3` 后执行：

```bash
LOCALPILOT_HARBOR_CONTRACT=1 /absolute/eval/schema-venv/bin/python \
  -m unittest -v tests.test_public_agent_eval
```

结果为 **20 PASS、0 SKIP**，1.207 秒。契约测试读取已安装 Harbor 的实际源码位置并核对完整 Git SHA 和包版本，将作业配置、逐任务结果与作业汇总交给官方 `JobConfig`、`TrialResult`、`JobStats`、`JobResult` 校验和序列化，再导入本审计器。它验证官方默认字段、序列化结构和此接口兼容，仍然使用解析器夹具。

这个最小 schema 环境不包含完整 Harbor 执行依赖，不能直接用于运行模型或 Docker。正式 Work 环境应按前文完整安装并单独记录端到端运行结果。两类验证不得混成同一能力成功率。

## Mac 续接的容器适配器

固定 Harbor 版本不变。`agent.import_path` 使用 `scripts.localpilot_harbor:LocalPilotHarborAgent`，在仓库根目录启动评估；`agent.kwargs` 必须提前冻结 `endpoint`、`provider_kind`（`local-openai`/`remote-openai`/`deepseek-native`）、`api_key_env`（变量名称）、上下文及步骤/工具/token/输出/请求超时预算。模型 ID 原样传给已配置服务。API 密钥只从指定环境变量读取，不能放入 JSON。云端要求 HTTPS 和明确凭据。

该适配器使用产品 Runtime 的权限、工具收据、V5 完成状态与一次请求预算，不另写执行循环。Harbor 提供容器 cwd 与命令执行边界；工具参数中的宿主 workspace 仅是空注册表身份，不作为执行目标。任务文件不上传到宿主工具目录。子 Agent、MCP、Skills 和原轨迹导入尚未在此适配器资格验证，明确禁用或拒绝。官方 verifier 仍是任务结果来源。

用量仅在所有已完成请求均有对应字段且没有失败请求时汇总；缓存 token 是输入 token 子集。实际价格未绑定，`cost_usd` 保持未知。Harbor 取消会向 Runtime 请求停止；官方 `exec` 无统一可移植的远端子进程停止回执，取消时明确记录容器进程状态未确认，依赖 Harbor 销毁环境，不能宣称取消已完成。

6 项可选官方 API 契约测试包括真实 loopback HTTP 和实际 AgentSession 工具调用；其中容器 API 使用明确命名的协议 fixture。它们不是 Docker 任务或模型得分。最初缺 Docker 的启动失败保留 NOT_RUN；随后安装隔离 VM/工具并完成真实 smoke，全部中间 FAIL/ERROR 保留。正式候选在 smoke 成功后冻结 534 次计划，尚未执行或发布成绩。


## 2026-11-15 Mac 真实执行

原生云端后端与正式 Runtime 已在官方任务容器实际执行；官方 verifier 与严格结果、全部失败历史及 89×2×3 候选冻结见 [Mac 验收](../evidence/nationals-20261114-pa-mac/RESULTS.md)。本轮因内存提醒不再加载 35B；未把受控 API 测试或单个 smoke 写成官方榜单分数。
