# 公开评估执行工具补齐（2026-11-15）

本轮补齐可恢复执行、资源预检、逐请求预算审计和不等价比较阻断。它不新增题库或模型成绩，也不把接口测试当作 Agent 能力证明。

## 保留的正式队列

已有队列仍是 Terminal-Bench 2 的全部 89 题 × 两个实验臂 × 3 次，合计 534 个计划单元；原 study、配置、源码 revision 和失败记录不改。原始资料仅在本机 `/private/tmp/lp-pa15-eb71z3g1/public-eval/formal-rosetta-owned-534`，本轮云端没有该目录，也没有运行其中任何任务。

截至仓库的[上一条公开快照](../evidence/nationals-20261115-completion/PROGRESS_20261115_065014.md)，候选臂为 1 PASS、3 FAIL、13 ERROR、250 NOT_RUN，参考臂为 267 NOT_RUN。第 18 项镜像拉取因磁盘不足留下失败回执，原 Harbor 进程被暂停。这些数字是沿用的历史记录，不是此次新增结果。旧模型源码固定 `1c06e97`；新代码不得混入同一冻结队列。

当前实际基准接口固定在官方 [Harbor 0.26.0](https://github.com/laude-institute/harbor/tree/ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4)，commit `ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4`。任务源码 commit、逐文件摘要、实验臂、次数、超时倍率、无重试约束都由 `study.json` 及其配置摘要确定。

## 解决的三个真实缺口

### 1. 继续未完成的正式执行，同时保留已经开始的尝试

官方 [resume 命令](https://github.com/laude-institute/harbor/blob/ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4/src/harbor/cli/jobs.py) 默认过滤 `CancelledError`；[Job 初始化](https://github.com/laude-institute/harbor/blob/ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4/src/harbor/job.py) 还会删除没有 `result.json` 的任务目录。直接使用该默认行为会把已开始的失败尝试重放。

新的 `resume` 入口先检查每个已有任务：任务及 trial ID 唯一、配置对应冻结内容、结果达到终态，且通过真实 Harbor 的 `JobConfig`、`TrialConfig`、`TrialResult` 校验。只有全部已开始任务均可保留时，才使用原 `run --config` 继续未开始的任务。PASS、FAIL、ERROR（包括 CancelledError）一律保留。没有终态结果的目录阻止新进程接管；不会删除目录、把它改成成功或挑一次成功结果覆盖它。

每次执行使用新的回执文件名，保存 preflight、原命令、PID、日志、退出状态。继续任务前复制原 job 顶层记录，保存所有已结算 trial 文件的哈希；执行后检查这些文件没有变化。中断会额外保留中断类型、PID 和当时的退出状态。

如果原进程仍为 SIGSTOP，可用 `resume --continue-pid PID`。该入口核对 UID、完整命令参数、运行目录、Docker socket 与暂停状态，只给同一进程及其已暂停子进程发 SIGCONT，不创建替代尝试。若原进程已消失且存在没有终态的 trial，自动续跑明确阻断；保留该未结算记录，并按独立新 study 处理后续实验。

### 2. 真实预算从发送前记账，失败不会恢复额度

`harbor_model_budget.py` 仍使用实际 oMLX tokenizer 计数，两个实验臂共用同一 transport。新增账本从 `budget_initialized` 开始，记录模型、完整限制和 tokenizer/template 文件摘要；每次发送前写 `admitted`，预留输入 token 加最大输出。只有收到可核对的实际 usage 才结算并返还未使用的输出额度。

提供方输入 token 必须与本地计数一致，输出 token 必须是非负整数且不超过本次上限。缺失 usage、输入不一致、输出越界、HTTP 失败或流式结果缺少最终结算都会留下原始记录并使该尝试失去预算资格；失败不会获得新的免费预算，也不会在同一 backend 中再次发送模型请求。预算总量和请求次数继续保留。

`harbor_tokenizer_process.py` 给持久 tokenizer 子进程的 stdin/stdout 同时设置有界读写，覆盖子进程不读大请求和不返回结果两种真实阻塞。超时、EOF、坏 JSON 不会被当作 0 token；父进程会等待并回收实际创建的子进程。

旧日志只有结算行、没有发送前记录时保留为 `UNQUALIFIED`。不补写历史 admission，不反向伪造过去未采集的预算证据。

### 3. 保留分数和失败，但拒绝不等价比较

导入器仍逐个列出全部计划单元，保留原始结果路径和摘要。新的 `comparison_qualification` 独立核对候选和参考模型、endpoint、模型请求超时、任务超时覆盖、tokenizer、请求/输入/输出/总 token 上限、模板配置和顺序执行约束；正式实验还要求冻结模型 revision、量化声明、tokenizer 摘要以及每个实际尝试的完整预算账本。

不满足条件时，已观察到的上游 verifier 结果和原始失败仍展示，但比较为 `BLOCKED_NON_EQUIVALENT_OR_UNQUALIFIED`，CLI 退出 2。没有结果、重复、坏结果、未完成作业继续阻断完整审计。描述性配对结果不等于统计上的“不弱于”，也不是官方榜单提交或认证。

参考臂仍是官方 Terminus2 的 parser、tmux 交互与任务循环，替换的是同一受计量模型 transport。因此它应称为“共享模型与预算的 Terminus2 参考臂”，不能标成官方榜单上同名 Agent 的原始配置成绩。

当前 LocalPilot Harbor adapter 只把 Shell 桥接到任务容器，禁用子 Agent，也不注册宿主机原生工具。它检验该范围内的主 Session；不覆盖 Companion、桌面 Computer Use 或完整 SuperAgent 多子 Agent 能力。扩大此工具集和计量范围必须另行定义并冻结协议。

## 入口及职责

| 文件 | 职责 |
|---|---|
| `scripts/public_agent_eval.py` | freeze / preflight / run / resume / audit CLI、冻结任务与逐任务结果归一化 |
| `scripts/harbor_study_runner.py` | 保留已有结果、续跑、原进程 SIGCONT、独立执行回执 |
| `scripts/harbor_preflight.py` | 只读检查源码、官方 schema、VM/主机资源、模型列表、tokenizer |
| `scripts/harbor_run_contract.py` | 在固定 Harbor interpreter 中执行真实模型类型校验，读取上游任务资源要求 |
| `scripts/harbor_model_budget.py` | 两臂共享的模型请求预算与 usage 结算 |
| `scripts/harbor_tokenizer_process.py` | 有界 tokenizer 协议及 tokenizer 文件指纹 |
| `scripts/harbor_budget_audit.py` | 对冻结预算、账本及比较条件逐项核对 |
| `scripts/harbor_owned_cache.py` | 仅处理已批准的专用 Docker daemon 的 image/builder cache |

新增冻结记录保存当前产品及评估 Python 源码摘要。新 runner 会拒绝在另一组代码上执行该 study。旧 study 没有此摘要时，只能从候选臂冻结 Git revision 对应的干净原始目录继续；不能从最新工作目录执行旧配置。

## 资源预检的含义

`preflight` 不拉镜像、不创建容器、不加载权重、不清理文件。它检查：

- Harbor commit 与工作树、基准 commit 与逐文件任务摘要、运行源码绑定。
- 真实官方 schema 和任务声明的 CPU、内存、storage；GPU/TPU 要求目前明确不支持此 Docker 预检。
- 明确传入的 Unix Docker socket、daemon ID、可分配 CPU/内存；不使用隐含默认 Docker context。
- 主机可用内存达到注册的模型 reserve；主机可用磁盘达到 `max(任务峰值 storage × 并发数, 5 GiB) + 5 GiB`；guest 可用磁盘达到 `max(任务峰值 storage × 并发数, 5 GiB)`。
- 5 分钟内的 guest `df` 记录，绑定相同 Docker socket 和 daemon ID。Docker info 没有 guest 可用磁盘字段，不用镜像逻辑大小冒充实际可用空间。
- loopback `/models` 能列出注册模型，tokenizer 文件摘要吻合。模型列表不能证明权重身份、已经加载或实际推理成功。

磁盘阈值是启动时的操作下限，不是磁盘预留，也不保证未知镜像解压峰值能够放下；作业执行期间仍需要观察磁盘。此轮没有提供自动空间释放、自动改变 VM 大小或中途重试。

专用缓存清理的新计划必须同时冻结 `daemon_id`。相同 socket 被另一个 daemon 复用时跳过清理；存在活动容器或状态不明时跳过。仅允许原有精确两条 image/builder prune 命令，第一条失败就停止，异常/超时/部分 stdout/stderr 均写回执。没有 system prune 或 volume 删除。原 534 的旧计划不改，新要求只用于新代码下的新计划。

## Work 执行步骤

先按当前主交接处理磁盘和独立模型环境。下面变量都需要取本机实际值，不要把示例占位符当作路径：

```bash
EVAL_PY=/实际/harbor-venv/bin/python
TOKENIZER_PY=/实际/omlx-venv/bin/python
EVAL_TOOLS=/实际/最新源码目录
FROZEN_RUNTIME=/实际/冻结源码目录
BENCHMARK_REPO=/实际/terminal-bench-2固定commit
HARBOR_REPO=/实际/harbor固定commit
STUDY=/private/tmp/lp-pa15-eb71z3g1/public-eval/formal-rosetta-owned-534
DOCKER_SOCKET=unix:///private/tmp/实际专用VM/docker.sock
```

Harbor 需要 Python 3.12+。在独立验证环境安装固定源码的依赖和 psutil；不要改产品依赖锁，不把本轮按环境解析出的版本冒称旧冻结锁。新 runner 对正式本地实验设置官方 LiteLLM 的 `LITELLM_LOCAL_MODEL_COST_MAP=True`：Terminus2 导入 LiteLLM 时使用其内置价格表，避免一条与共享本地 transport 无关的启动联网请求。直接运行 adapter 契约测试时也设置该变量。

用实际 VM 命令取得数据盘 `df` 和 `docker --host "$DOCKER_SOCKET" info --format '{{.ID}}'`，写新的 JSON；不猜 daemon ID、bytes 或时间。文件格式：

```json
{
  "docker_host": "unix:///private/tmp/实际专用VM/docker.sock",
  "daemon_id": "实际 docker info ID",
  "observed_at": "实际测量时刻的 ISO8601，含时区",
  "guest_available_bytes": 0,
  "command": "实际执行的 guest df 命令"
}
```

上面的 0 只表示必须填写实测值，不是可用空间。执行预检时输出文件必须为新文件：

```bash
"$EVAL_PY" "$EVAL_TOOLS/scripts/public_agent_eval.py" preflight \
  --study "$STUDY" --arm localpilot --repeat 1 \
  --repository "$BENCHMARK_REPO" --harbor-repository "$HARBOR_REPO" \
  --runtime-repository "$FROZEN_RUNTIME" --python "$EVAL_PY" \
  --docker-host "$DOCKER_SOCKET" --resource-evidence /实际/新guest-df.json \
  --output /实际/新preflight.json
```

若第 18 项仍由原始暂停进程持有，普通预检会如实报告该未结算任务的 schema 不完整。核验原 PID 后使用下面入口，它会保留该任务并在通过其它资源检查后继续原进程：

```bash
"$EVAL_PY" "$EVAL_TOOLS/scripts/public_agent_eval.py" resume \
  --study "$STUDY" --arm localpilot --repeat 1 --continue-pid 实际原HarborPID \
  --repository "$BENCHMARK_REPO" --harbor-repository "$HARBOR_REPO" \
  --runtime-repository "$FROZEN_RUNTIME" --python "$EVAL_PY" \
  --docker-host "$DOCKER_SOCKET" --resource-evidence /实际/新guest-df.json
```

在完整任务之间停止的作业可使用同样 `resume` 命令但去掉 `--continue-pid`；新作业使用 `run`。其余 arm/repeat 从冻结 study 读取，依次执行，不能并行两个本地模型任务。每个新作业重新提供新鲜 guest 磁盘记录。任何未结算尝试都不删除或重播。

审计单独运行，可在资源未就绪时执行：

```bash
"$EVAL_PY" "$EVAL_TOOLS/scripts/public_agent_eval.py" audit \
  --study "$STUDY" --output /实际/新audit.json
```

旧 study 缺少新的身份字段或发送前预算账本时，仍能继续原协议并保留结果，但不会被此工具升级成“已证实同模型同预算”的新比较。要使用新的协议和最新产品代码，创建独立新 study，给真实的 `model_identity.model_name/revision/quantization/tokenizer_sha256`；不要编辑现有冻结文件。可通过 `scripts.harbor_tokenizer_process.tokenizer_fingerprint(实际本地目录)` 只读取得 tokenizer 摘要。

真实模型四项资格验证仍需 Work 执行：

```bash
LOCALPILOT_BUDGET_MODEL=实际注册模型ID \
LOCALPILOT_BUDGET_ENDPOINT=http://127.0.0.1:实际端口/v1 \
LOCALPILOT_BUDGET_TOKENIZER_PATH=/实际/本地tokenizer目录 \
LOCALPILOT_BUDGET_TOKENIZER_PYTHON="$TOKENIZER_PY" \
LITELLM_LOCAL_MODEL_COST_MAP=True \
"$EVAL_PY" -m unittest tests.test_harbor_model_budget -v
```

这四项校验输入计数、stream usage、tool schema/history、共享 Terminus transport 的真实依赖，不代表 534 正式任务完成。

## 本轮已执行的验证

在独立 venv 安装固定 Harbor 0.26.0 源码及其实际解析依赖，额外安装 psutil 7.2.2；未改产品 `.venv` 或生产依赖。最终运行命令：

```bash
LOCALPILOT_HARBOR_CONTRACT=1 LITELLM_LOCAL_MODEL_COST_MAP=True \
/workspace/scratch/2a488f6eabf5/harbor-contract-venv/bin/python -m unittest \
  tests.test_public_agent_eval tests.test_harbor_adapter tests.test_harbor_model_budget \
  tests.test_harbor_budget_protocol tests.test_harbor_budget_audit \
  tests.test_harbor_study_runner tests.test_harbor_owned_cache -v
```

覆盖实际官方 Pydantic schema、官方 BaseAgent/Terminus2、真实产品 Session、本地 HTTP/SSE、实际 tokenizer 协议子进程、真实 stop/continue 子进程和 subprocess Docker 协议夹具。夹具不使用真实权重或 Docker daemon，不代表容器/模型/比赛成绩。

| 最终环境 | 总数 | PASS | SKIP | FAIL / ERROR | 用时 |
|---|---:|---:|---:|---:|---:|
| 独立固定 Harbor 环境，启用官方契约 | 66 | 62 | 4（真实模型 opt-in） | 0 / 0 | 18.741 秒 |
| 产品 `.venv`，不安装 Harbor | 66 | 52 | 14（Harbor 契约及真实模型） | 0 / 0 | 11.954 秒 |

中间失败保留说明：独立 Harbor 环境首次新增续跑测试因缺 psutil 出 1 ERROR；补齐 psutil 后重跑。Terminus2 transport 补测首次因其导入的 LiteLLM 在线价格表读取在 SOCKS 环境缺 socksio 出 1 ERROR；使用上述官方离线价格表开关后通过，没有隐藏重试或调用收费模型。这两次早期失败输出在本轮工具记录中，不能标成“首次即通过”。最终原始日志位于云端工作目录的 `validation/eval-completion-20261115/harbor-contract-final.log` 和 `project-venv-final.log`。

实际模型加载/推理、真实 Docker 镜像运行、原 534 队列继续执行均为 **NOT_RUN**；不能从这些协议回归推出“不弱于主流 Agent”。

## Issue #3：缺失的是历史材料

[Issue #3](https://github.com/www080327-glitch/LocalPilot-OpenSource/issues/3) 尚未提供历史 benchmark 源码出处。公开 Git 历史对 `benchmarks/` 没有可恢复实现；`tests/optional_benchmarks.py` 的历史只有说明缺失材料的 SKIP 修改。因此保留 12 个测试模块的 honest NOT_RUN，没有创建同名空实现、删断言或导入第三方同名包来降低 SKIP。

| 当前被门控的测试模块 | 实际导入的缺失模块（`benchmarks.` 前缀） |
|---|---|
| `test_adaptive_benchmark.py` | `adaptive_profiles`, `adaptive_runtime`, `adaptive_tasks` |
| `test_aic_terminal_budget.py` | `bfcl_hybrid`, `hybrid_accounting` |
| `test_benchmark.py` | `run`, `tasks` |
| `test_convergence.py` | `summarize_mlx` |
| `test_mlx_benchmark.py` | `mlx_context`, `mlx_worker` |
| `test_real_hybrid_accounting.py` | `summarize_real_hybrid` |
| `test_runtime_stabilization.py` | `runtime_control_cases` |
| `test_selector_mlp.py` | `mlx_context`, `selector_eval` |
| `test_strict_benchmark.py` | `contracts`, `run`, `strict`, `strict_tasks`, `tasks` |
| `test_v48_benchmark.py` | `v48_confirmation_corpus`, `v48_long`, `v48_qualified_corpus`, `v48_second_confirmation`, `v48_tasks` |
| `test_v48_resource_controls.py` | `v48_power`, `v48_runtime` |
| `test_v49_accounting.py` | `v49_analysis` |

这是 12 个测试文件、24 个去重的直接导入模块；不等于历史实现仅有 24 个文件。仍需要提供其完整包及传递依赖、题目/夹具/隐藏检查来源、对应 commit 或原始归档哈希、运行入口/参数、数据及代码再分发许可证。若有第三方题库、生成数据或模型文件，还需要逐项来源与许可，不可仅凭项目根 Apache-2.0 声明替代它们。材料经核验后，原测试入口仍是标准 unittest，例如 `python -m unittest tests.test_benchmark`；当前入口会准确报 SKIP。

公开产品的路由、权限、取消、历史恢复及预算回归是独立的生产代码测试，继续执行；它们不冒充以上缺失历史研究的实现或复现结果。
