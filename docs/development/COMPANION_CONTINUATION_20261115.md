# Companion PA：来源延续、稳定会议记录与候选试用

本轮基线为 PR #10 的 `92ad9a30b9fda43bc185d96c99e5cb0a8ce8ec02`，工作分支为 `codex/pa-cooperation-20261115`。开发与测试环境为 Linux x86_64、Python 3.12；没有读取真实私人历史、采集音频、训练或下载模型。上一轮的来源连接、原生转写、训练准备和边界见 [COMPANION_PA_COMPLETION_20261115.md](COMPANION_PA_COMPLETION_20261115.md)。本轮保留所有旧 evidence，未修改原生 PASS 的适用范围。

## 1. 已确认并修复的来源缺口

此前观察检索只打包摘要，正式 Agent transport 又丢弃 `evidence_type`、`evidence_epistemic` 等字段。主 Agent 能看见一段文字，却不一定知道它是自动转写、助手自述，或者它的行号、片段与读取范围。

现在检索保留精简 evidence：读取状态、locator、时间依据、字幕 cue、mic/system 音轨、转写标记、版本哈希及完成状态。正式 Task 请求继续携带 observation ID、source reference、version、evidence digest、raw state 和证据类别；系统指令明确要求保留来源定位，不把 `MODEL_INFERRED` 或 reported 文字当成已核验事实。完整 AX 树仍不随普通问答导出。云端继续沿用既有 question-only 契约，本轮没有放宽云出站。

已导入的 `meeting-notes.txt` 现在可以按文件名提问，并在回答中引用它。此前显式文件检查只认识旧文件观察目录，会把已连接的会议文件误报为不存在。正常观察问答现在也返回 `observation_sources`，包括来源 ID、路径、locator、证据类别和读取状态。生成期间来源被替换或暂停时，回答不会继续展示旧摘录；这与已有“整理近期窗口”入口保持一致。

### Session 与任务结果的来源关系

此前仅在提交当前任务时检查来源；之后既有 Session 可以继续带入已经撤销的文本，任务结果摘要也可能脱离原来源单独进入下一次问答。

本轮在复用 Session 前检查该 Session 既有请求的当前来源。原始观察过期、文件变化、授权来源停用/撤销或记忆被遗忘时，自动续问会解绑旧 Session 并使用新 Session；显式指定失效的已知 Session 会返回不可用。已执行任务、Task ID、收据和旧历史保留，不自动取消或重放。

任务结果进入检索时也检查它自己的请求，以及同 Session 中此前请求的依赖。一个没有再次携带摘录的续问结果，仍然受前一轮来源约束。缺失原请求的旧任务摘要继续留在管理历史中，但不再参与可检索上下文，避免猜测它依赖哪些已撤销资料。提交状态 UNKNOWN 的原意图和幂等键继续保留，不因此生成替代提交。

以上不是从 Core 撤回已经发送的文本，也不删除已有工具收据；它约束的是 Companion 后续使用与 Session 续接。

## 2. 长会议的记录与停止状态

此前所有最终片段追加到同一个 `transcript.jsonl`。每次追加都会改变整文件版本，再次导入所有旧片段。这会使先前回答或样本的 observation ID 失效，并让历史版本数量随片段数呈平方增长。

新会议使用一个已明确授权的会话目录，最终片段分别保存为不可变文件，例如：

```text
meetings/meeting-UUID/segment-000001-mic.jsonl
meetings/meeting-UUID/segment-000002-system.jsonl
```

每次仅同步新片段。旧片段的 observation ID、版本和已审阅样本在会议继续时保持有效；文件数和观察版本数随片段数线性增长。既有外部 JSONL/字幕导入格式保持兼容，旧会议文件不做自动搬移或重写。来源停用、撤销、暂停、清空和原保留期继续有效。

停止状态现在记录明确结束时间，并要求 helper 终态与进程退出码相符。无终态就退出、宣布 stopped 后非零退出，以及需要强制终止的进程，都会记为失败，不假称完整结束。正常停止继续冲刷 final；暂停、撤销及清空继续丢弃排队文字。

真实子进程协议测试覆盖了 80 个合成片段：最终恰为 80 条观察和 80 个版本，每次同步一个新文件。它证明 Python 控制器、SQLite 与文件链路的行为，**不代表真实语音持续采集、Apple Speech 准确率或 80 段原生音轨已验收**。本轮没有改动 Swift helper；原生编译、TCC、麦克风和系统声仍需本机验证。

来源注册和外部整目录同步仍有既有数量/容量上限。长会议的逐段同步不会通过反复全量扫描来维持实时记录，覆盖报告仍应按具体同步结果解释。

## 3. 显式审阅训练样本

问候、活动摘要及有可追溯观察来源的轻量回答会保存精确的 `question_id`，并返回 `answer_id`。记忆关闭时不保存此关系，`answer_id=null`。删除原问题后，对应答案不再作为可审阅候选或对话回忆来源。

新入口只准备候选；用户核对来源、编辑问题和最终答案后，才调用既有保存操作。不会自动把模型回答当成正确标签。保存时再次读取原答案的来源 ID，不接受 GUI 将它替换成另一组来源。原文已经被保留期压缩时，候选和已有样本暂不可导出，避免把完整目标答案配上已经缺少细节的上下文。

当前 GUI 候选支持问候和最多 16 条原始观察支撑的活动问答；需要旧文档记忆混合上下文、缺失问答关系、过多来源或来源失效的回答不会被伪装成可完整审阅。手动 CLI 的 `handoff` 样本入口保留。

### JSON 命令契约

| 命令 | 输入 | 返回/作用 |
|---|---|---|
| `training_candidates` | `{limit?:20}`，1–50 | 当前近期可审阅的候选，含 answer ID、问题、回答、目的、来源数量、创建时间；不保存 |
| `training_review` | `{answer_id}` | `candidate` 含问题、最终回答、purpose、observation IDs 和可核对 sources；失效返回 `unavailable` |
| `training_example_add` | `{answer_id?,question,answer,purpose,observation_ids?}` | GUI 带 answer ID 即可；后端重新绑定原来源。人工 CLI 不带 answer ID 的旧入口保持兼容 |
| `training_examples` / `training_example_delete` | `{}` / `{id}` | 查看与删除明确保存的样本 |
| `training_export` | `{seed?,validation_fraction?}` | 依旧检查来源与独立来源分组，输出私有 train/valid/manifest，`training=NOT_RUN` |

Desktop 设置中的审阅列表、来源展示、编辑、保存/删除/导出，以及宠物完成回答的单条审阅，由 Desktop 模块接入。宠物使用其原有独立 Companion 服务配置，不连接到另一个数据目录。本轮 Linux 后端回归不替代真实原生界面验收。

CLI 示例：

```sh
python -m companion --config "$CONFIG" --json ask '会议说了什么？'
python -m companion --config "$CONFIG" --json training-candidates --limit 20
python -m companion --config "$CONFIG" --json training-review ANSWER_ID
python -m companion --config "$CONFIG" --json training-example-add --answer-id ANSWER_ID --purpose activity_qa --question '这份记录提到什么？' --answer '填写你核对来源并修改后的最终答案。'
python -m companion --config "$CONFIG" --json training-examples
python -m companion --config "$CONFIG" --json training-example-delete REVIEWED_ID
python -m companion --config "$CONFIG" --json training-export
```

已导出的独立文件仍按既有明确说明单独管理；撤销来源会阻止后续检索/导出，不会声称已经撤回独立数据集或消除了训练产物中的信息。

## 4. 训练候选有明确的试用入口

此前启动器可以生成 adapter，但 Companion worker 只加载基座路径，无法实际选择它。本轮新增 `model_adapter_path` 配置，默认空值保持现有模型行为。它仅适用于本地 `mlx` 后端；配置在 HTTP/oMLX 后端上不会被悄悄忽略。

训练计划现在保存基座 `config.json` 和 `tokenizer_config.json` 的哈希。成功训练还必须有 `adapter_config.json`，收据保存其哈希、adapter 权重字节数和 SHA-256，并返回 `candidate_config`。候选检查要求：完成的 Companion run、对应原始路径、相符的基座配置、fine-tune 配置、adapter 配置和权重哈希。检查不会加载 tensor、下载或改变运行配置。缺少这些来源字段的旧收据不会自动被认定为可用候选。

```sh
python -m companion.model.candidate --model /path/to/original-base --adapter /path/to/completed-run/adapters
```

通过身份检查后返回的 `config_fragment` 形如：

```json
{
  "backend": "mlx",
  "model_path": "/path/to/original-base",
  "model_adapter_path": "/path/to/completed-run/adapters"
}
```

将该片段写入**另一个隔离 Companion 配置**，使用独立 `data_dir`，再通过原 `run/start` 与 `ask` 入口进行候选测试。没有自动推广、融合或覆盖日常模型。清空 `model_adapter_path` 可回到基座；运行中的本地模型选择发生变化时，已有 worker 会先卸载，避免继续返回上一个选择的结果。电源与轻量资源策略仍生效，adapter 字节数也计入轻量预算。

worker 在加载前复核候选，并固定要求 `mlx-lm==0.31.3`，然后使用该版本真实接口 `load(..., adapter_path=...)`。成功的生成指标包含候选 SHA-256 与类型，便于比较基线和候选。本轮读取了精确发布 commit `ed1fca4cef15a824c5f1702c80f70b4cffc8e4dd` 的官方实现：

- [mlx_lm.utils.load](https://github.com/ml-explore/mlx-lm/blob/ed1fca4cef15a824c5f1702c80f70b4cffc8e4dd/mlx_lm/utils.py)，Git blob `ef3d266b97e4995d065f6c6e41f7cf928c49a805`。
- [mlx_lm.tuner.utils.load_adapters](https://github.com/ml-explore/mlx-lm/blob/ed1fca4cef15a824c5f1702c80f70b4cffc8e4dd/mlx_lm/tuner/utils.py)，Git blob `e40155a0eb4b2c55e1dfea7e51df6bd9fdada5af`。

官方 load 支持 LoRA 和 full 训练输出的 adapter/layer 权重。这里的 full 仍沿用上一轮记录的实际范围：指定 Transformer 层，不包含 embedding/head；不是新的全模型参数训练承诺。

**身份检查不证明 tensor 可加载或模型质量。** 基座身份目前是原路径和配置哈希，没有逐个哈希基座权重，返回值明确 `base_weights_verified=false`。保持训练时使用的原基座，真实加载后再比较 held-out 表现、出处准确性、委派行为与资源占用。实际训练、候选 tensor 加载、推理和 A/B 均为 **NOT_RUN**。

## 5. 验证结果与保留的失败

全量命令：

```sh
.venv/bin/python -m unittest discover -s companion/tests -t . -v
```

| 记录 | 结果 |
|---|---|
| 本轮基线 | 630 项：605 PASS、25 SKIP、0 FAIL/ERROR，35.972 秒 |
| 首轮来源/会议/审阅聚焦 | 90 项：87 PASS、1 FAIL、2 ERROR，4.981 秒；见下面原因 |
| 修正后的聚焦 | 113 PASS，5.691 秒 |
| 首轮全量（含新候选入口） | 650 项：624 PASS、25 SKIP、1 FAIL，36.949 秒；见下面原因 |
| 最终新增链路聚焦 | 66 PASS，4.564 秒 |
| **最终全 Companion** | **652 项：627 PASS、25 SKIP、0 FAIL、0 ERROR，37.443 秒** |
| Python 编译与 `git diff --check -- companion` | PASS |
| 固定上游 adapter 接口核验 | PASS；静态接口核对，非真实 MLX 推理 |

首轮三个失败均是新增测试夹具问题：保留期参数不允许 0 天；真实 Agent 消息包含 Host working state，需要选择实际任务 JSON；插入新用例时误将暂停测试末尾放进另一个方法。后续改正夹具，未绕过产品规则。

首轮全量的一个失败是候选 worker 测试没有显式设置其合成环境的电源选项，Linux 上电源状态未知，真实 ModelManager 正确在 `power_policy` 停止。该隔离测试随后明确设置 `allow_local_on_battery=True`，验证候选不匹配会在导入可选 MLX 前失败；产品电源策略未更改。

全部日志位于仓库外的本机 `validation/`，保留原失败：

- `companion-continuation-20261115-baseline.log`
- `companion-continuation-20261115-focus-r1.log`
- `companion-continuation-20261115-focus-r2.log`
- `companion-continuation-20261115-focus-r3.log`
- `companion-continuation-20261115-full-r1.log`
- `companion-continuation-20261115-full-r2.log`
- `companion-candidate-interface-20261115.json`
- 上游源码快照 `mlx0313-load-utils.py`、`mlx0313-tuner-utils.py`

Task 测试使用真实 loopback HTTP、Agent Service、Session 和 SQLite，但模型为 scripted fixture。会议测试使用真实 Popen 与 JSONL 协议，但不采音。候选测试使用明确标记的合成字节与收据，其中真实 worker 验证加载前拒绝；没有把这些测试写成模型、原生采音或产品能力榜单通过。

## 本机 Work 接续验收提示词

请在当前 PR HEAD 的隔离 checkout/配置/测试 APP 中验收这次 Companion 改动。先核对源码、wheel 内源码、实际 Python 与 APP 身份，保留原日志和日常服务。先用你自己准备的合成 Codex 导出与会议文件，不自动扫描真实私人目录。

1. 来源接入后，检查按文件名提问、回答的 observation ID、版本、locator、证据类别和 mic/system 标签。使用真实已配置本地 Agent 做一次复杂问答；停用/撤销原来源后，再提问应建立新 Session，旧任务/收据仍能在历史核对，旧摘录和继承它的任务结果不得重新进入模型上下文。没有模型时将这一真实推理项记为 NOT_RUN。
2. 在设置与宠物入口分别打开“审阅为训练样本”，核对候选就是所点回答的原问题与已显示最终答案。编辑后明确保存，检查列表、删除、导出；关闭记忆、删除原问题、修改/撤销来源、原文被压缩时，不能把失效资料保存成可用训练样本。保留来源分组、train/valid 和文件哈希证据。
3. 编译既有 Swift helper，记录 SDK、架构、签名和 TCC 归属。分别测试 microphone/system/both 的允许、拒绝和不支持场景。做至少 110 秒的跨轮换会议，在 49–55 秒内停止一次，并测试静音停止；检查真实音轨、final、结束时间、全局停止入口、暂停/撤销/退出和没有音视频落盘。旧片段 ID 在后续片段到来后必须保持有效，文件/观察版本应随片段线性增加。不能用本轮合成 JSONL 测试替代这一步。
4. 仅在已有精确 MLX 依赖、本地基座、足够资源和足够人工审阅数据时，执行上一文档的显式训练命令。没有就保持 NOT_RUN，不下载大模型或捏造完成收据。对真实完成的 run 使用 `python -m companion.model.candidate` 检查身份，在另一个 Companion 配置中设置返回的 `model_adapter_path`。实际加载并保存候选 SHA、冷/热延迟、内存、相同测试集的基线/候选结果；是否推广需要这些真实结果，本轮不自动改变日常模型。
5. 晚间问候、实际睡眠/唤醒和 Intel 原生路径仍引用各自原始证据边界；不要通过修改系统时间或模拟桥把未执行的原生项写为 PASS。每项记录 PASS/FAIL/NOT_RUN、命令、环境、收据和具体限制。
