# ITBench-AA 原始 R2：40 题运行状态与失败分类

## 结论与范围

**原始 R2 的 40 份 `case-result.json` 已全部形成，26 题的 Runtime 状态为 `completed`，28 题通过 runner 的输出格式检查；评分尚未执行。** 本报告将原始固定 40 题作为一个独立集合，保留其基础设施失败和执行器中断。另行启动的六题网络失败续跑不计入以下数字，也不覆盖本轮原始记录。

[RUN_SUMMARY.json.gz](RUN_SUMMARY.json.gz) 解压后的原始汇总头部为 `planned=40`、`completed=26`、`outputs_valid=28`、`errors=8`、`graded=false`。本次逐项读取 001–040 的终态元数据，确认其内容与汇总的 `cases` 数组逐项相等。`errors=8` 仅统计 case 外层的 `error`：六个下载连接错误和两个中断恢复保护错误；它不是“所有未完成任务”的数量。

这里的 `output_valid` 只表示 runner 找到了并解析了 `agent_output.json`，其中 `contributing_factors` 是列表，列表元素的 `name`、`reasoning`、`evidence` 均为字符串。该判定既不核对诊断与参考答案，也不核验引证是否正确；它甚至不要求列表非空。因此 **28 份格式有效输出不是 28 题正确，26 个 completed 也不是准确率或 AA 成绩**。本报告没有读取诊断正文、参考标签或评分结果。

## 原始 40 题的互斥分类

| 分类 | 题号 | 数量 | Runtime 状态 | 输出格式有效 |
| --- | --- | ---: | --- | --- |
| Runtime 完成且格式有效 | 001–003、006–018、021–022、031–032、034、036–040 | 26 | `completed` | 是 |
| 格式有效，但 Runtime 保留未完成状态 | 019、020 | 2 | `incomplete` | 是 |
| 重复非法 Shell timeout，参数修复额度耗尽 | 004、024 | 2 | `incomplete` | 否 |
| 单次模型输出触及配置上限，响应未完整结束 | 005 | 1 | `failed` | 否 |
| 长度上限触发收尾，恢复后仍有未完成目标 | 030 | 1 | `incomplete` | 否 |
| 候选开始前下载连接失败 | 023、025–029 | 6 | 无 task 终态 | 否 |
| 已开始的候选遭执行器中断，恢复时拒绝重跑 | 033、035 | 2 | 无保存的 task 终态 | 否 |
| 合计 | 001–040 | **40** | — | **28 是 / 12 否** |

Runtime 状态单独计数为 **26 completed、5 incomplete、1 failed、8 null**；共有 **14 题不属于 completed**。其中 019、020 必须计入这 14 题，不能因文件格式有效而略去。

## 六份已有 task 终态但未完成的记录

下表的步数和工具数来自原始 task 的 `result.total_steps`、`result.total_tool_calls`，后者是工具提议数，不一定等于已执行回执数。耗时来自 case 的 `task_seconds`，不含前面的输入下载阶段。

| 题号与证据 | task 状态 / 格式 | 模型步骤 | 工具提议 | task 秒数 | 终止证据 |
| --- | --- | ---: | ---: | ---: | --- |
| [004 metadata](case-004/case-result.json) / [task](case-004/candidate-task.json.gz) | incomplete / 无效 | 5 | 10 | 51.377 | 两次相同的 timeout 参数越界，第二次 `repair_allowed=false`、剩余额度 0 |
| [005 metadata](case-005/case-result.json) / [task](case-005/candidate-task.json.gz) | failed / 无效 | 34 | 40 | 682.716 | 最后一次响应 `finish_reason=length`、8192 输出 tokens，带一个未执行完整的工具提议 |
| [019 metadata](case-019/case-result.json) / [task](case-019/candidate-task.json.gz) | incomplete / 有效 | 33 | 36 | 416.230 | 最后响应 stop；一次未派发的 schema 拒绝没有关联修复标记，execution=settled、delivery=incomplete |
| [020 metadata](case-020/case-result.json) / [task](case-020/candidate-task.json.gz) | incomplete / 有效 | 27 | 32 | 308.841 | 最后响应 stop；一次未派发的 schema 拒绝没有关联修复标记，execution=settled、delivery=incomplete |
| [024 metadata](case-024/case-result.json) / [task](case-024/candidate-task.json.gz) | incomplete / 无效 | 4 | 4 | 29.327 | 两次相同的 timeout 参数越界，第二次 `repair_allowed=false`、剩余额度 0 |
| [030 metadata](case-030/case-result.json) / [task](case-030/candidate-task.json.gz) | incomplete / 无效 | 16 | 33 | 310.480 | length/8192 后恢复为 stop/968；仍有一个未完成目标，收尾未交付完成 |

### 004、024：模型重复提交非法 timeout

两题均连续两次提交 `shell.timeout=120000`，Schema 明确返回 `$.timeout: violates maximum=3600`。两次均为 `stage=not_dispatched`、`action_sent=false`，没有启动对应 Shell。第一次回执允许修复且剩余一次，第二次为 `repair_allowed=false`、`repair_attempts_remaining=0`。冻结 Runtime 在该分支终止为 `incomplete`，并保留一个未完成目标。

这是具体工具参数错误及其修复额度耗尽，不能写成 1200 秒的任务截止时间到达、100 个模型步骤耗尽，或用户未批准操作。120000 很像把毫秒值用于秒字段，但证据能直接确认的是数值和 Schema 不符，不能确认模型内部如何理解单位。

### 005：配置的单次输出上限，未完整的工具响应不执行

最后一次模型响应为 `length`、8192 输出 tokens，包含一个工具提议；该不完整响应中的工具没有执行，task 返回 `runtime_error`。原错误中的 “no tools executed” 指的是这一条不完整响应，不能解释为整题没有用过工具：之前已有 **34 个成功 Shell 回执**，另有一个已经观察到进程退出码 1 的 Shell 回执。工具提议总数为 40，保存的回执数为 39。

该题没有进入 `delivery_length` 的最终答复恢复分支：`finalization_reason=null`，completion attempts 为 0。冻结实现仅在长度截断发生于最终收尾阶段、或响应不带工具提议时尝试该类恢复。这里记录的是 **实验配置的 `max_output_tokens=8192` 被触及**，不是证明 Luna 模型本身最多支持 8192 输出 tokens。

### 019、020：格式有效不等于 Runtime 完成

019 的最后响应为 `stop` / 427 输出 tokens，020 为 `stop` / 1198 输出 tokens。两题均为 `completion.execution=settled`、`delivery=incomplete`、`attempts=0`，没有收尾失败历史；所有 completion obligations 均为零或 false，包括未完成目标、未完成 worker、审批和未知回执。两题的 `verification_status` 仍是 `not_run`。

两题各有一次 `timeout=120000` 被 Schema 拒绝、未派发的 Shell 提议，随后继续执行其他工具，但没有任何回执把该失败标为 `repaired_proposals`。冻结 `Session._finish` 中的规则会将 **未关联修复的 mutating 工具失败回执** 判为 `incomplete`；Shell 被注册为 mutating。该条件足以解释“任务产出格式有效、执行义务已 settled，Runtime 仍不完成”的状态组合。

019 还保留一个 Shell 退出码 1 的回执，020 保留两个退出码 1 的 Shell 回执及一个 `manage_goal` 的 `KeyError`。已观察到进程退出的 `failed_process` 在上述 `_finish` 分支被明确跳过，不应把这些普通非零退出单独说成尚未结束的进程。019 有 23 个成功 Shell 回执，020 有 15 个；它们没有因首次非法 timeout 立即终止，也没有像 004、024 那样耗尽同一参数的修复额度。

这里描述的是冻结 Runtime 的状态判定和保存的工具回执，没有检查两份诊断的内容或正确性，也没有为了改变统计而修改旧状态。

### 030：长度截断后的恢复答复仍未完成目标

第 15 次响应为 `length` / 8192 输出 tokens、没有工具提议，触发 `finalization_reason=delivery_length`。第 16 次恢复响应正常返回 `stop` / 968 输出 tokens；completion attempts 为 2，历史记录保存第一次的 `kind=length`。

终态仍有 `unfinished_goals=1`，其余 completion obligations 均为零或 false。冻结 `Session._prepare_delivery` 因未完成目标将 execution 设为 `incomplete`，随后 `_finish` 保留 `incomplete`，没有把第二次正常 stop 视为任务完成。不能说第二次也遭截断，或仅凭 attempts=2 就声称全局步数用尽。

该题早先一次 timeout Schema 错误后继续运行，保存了 28 个成功 Shell 回执。故主要终止分类是 **长度限制触发收尾后仍有未完成目标**，不是重复非法参数导致修复额度耗尽。

## 基础设施失败与执行器中断

### 六个候选开始前的 Tunnel 403

[023](case-023/case-result.json)、[025](case-025/case-result.json)、[026](case-026/case-result.json)、[027](case-027/case-result.json)、[028](case-028/case-result.json)、[029](case-029/case-result.json) 均记录：

```text
URLError: <urlopen error Tunnel connection failed: 403 Forbidden>
```

这些目录都没有 `candidate-started.json`、完整的 `input-manifest.json` 或 task 回执。冻结 runner 在完成下载后才写 candidate-started 标记并启动、提交 Core task，因此将这六题归为 **候选模型开始前的输入下载基础设施失败**，不是根据 `task_status=null` 单独推断。对应原始 `total_seconds` 分别为 381.289、159.965、159.073、72.419、20.423、20.420 秒，主要是失败及重试流程耗时，不能当作模型推理耗时。

### 033、035：已开始，中断后不重试候选

[033 metadata](case-033/case-result.json) 与 [035 metadata](case-035/case-result.json) 的错误均为：

```text
RuntimeError: Interrupted candidate attempt retained; not rerun under pass@1
```

两题已存在原始 [033 candidate-started](case-033/candidate-started.json)、[035 candidate-started](case-035/candidate-started.json) 标记及输入清单，与上述六个候选开始前失败的题目不同；没有保存完整的终态 task 或其 model_calls 数组。原目录恢复使用未改动 runner 的保护分支，拒绝重新开始这两题，未通过重新调用模型来补写或替换结果。

执行器会话丢失的历史记录见 [executor-interruption-20261116.json](../cloud-soak-2h-r1-interrupted/executor-interruption-20261116.json)。[RESUME.json](RESUME.json) 保存恢复前已结束 33 题的结果哈希；[RESUME_VERIFICATION.json](RESUME_VERIFICATION.json) 记录这 33 份结果在恢复后逐字节不变，以及当前 110 文件 Runtime 清单和 runner 未改变的复核。恢复只完成此前尚未开始的 036–040，另外为 033、035 写入不重跑的保护结果。

033 的 `total_seconds=0.000023966`、035 的 `total_seconds=0.000060812` 是 **恢复时命中保护分支的耗时**，不是原候选任务的实际耗时。`task_seconds` 为空，原候选中断前的完整时长和最终模型用量未知。

两条恢复记录的 `owned_core_stopped=true` 也有明确范围：保护分支在创建新 CloudCore 之前抛错，finally 的 `core is None or core.process is None` 因此成立。它证明恢复没有启动新的 Core，**不能独立证明中断前的旧 Core 已正常收尾**，也不能据此将原有模型消耗记为零。

## 可用模型用量、预算与审批观察

32 题保存了 task 终态及 model_calls 数组，包括 26 个 completed、5 个 incomplete 和 1 个 failed。以下是这些**已保存回执**的算术汇总，不是完整账单或含丢失区间的全实验总消耗：

| 项目 | 已保存记录的结果 |
| --- | ---: |
| 含调用记录的 task | 32 |
| model_calls 条数 | 920 |
| 返回的 input_tokens 合计 | 36,746,417 |
| 返回的 output_tokens 合计 | 885,975 |
| 缺失 input_tokens / output_tokens 字段的调用 | 0 / 0 |
| reported_model 为 gpt-6-luna 的调用 | 920 |
| finish_reason=tool_calls / stop / length | 889 / 29 / 2 |

六个下载失败的题目没有开始候选模型；033、035 已开始但缺少完整的末段记录，不能以空数组代替“零调用/零 tokens”。因此上述调用和 tokens 总数只代表保存下来的部分。记录中 `runtime_metrics.model_attempts` 合计也是 920、`failed_attempts` 合计为 0，但后者不能否定外层下载错误、执行器丢失或 length 响应造成的任务失败。

冻结配置为每题 1200 秒、100 个模型步骤、200 个工具提议、单次输出最多 8192 tokens，四题并行。六份可检查的非 completed task 均在 29.327–682.716 秒内结束，最多 34 步、40 个工具提议；没有以全局 deadline、模型步骤或工具次数用尽作为终止理由的证据。8192 的限制属于本次实验配置，和目标模型的最大能力不同。

32 份保存的 task 终态没有非空的 `required_action`；六份非 completed task 的 `completion.obligations.pending_approval` 都是 false，未见审批挂起导致上述终止。对 033、035 丢失的执行区间不作“从未等待审批”的推断。40 份 case 外层都有 `owned_core_stopped=true`，但其中两条恢复保护记录必须按前述有限含义解释，不能将该字段直接转述为“40 次原始 Core 均正常停止”。

## 实验身份、源码与证据摘要

[study.json](study.json) 固定数据集 `ArtificialAnalysis/ITBench-AA` 的 public split，revision 为 `76df38a82288f75ba9e41dc8c515033332497473`，每题一次；候选为 LocalPilot Core V5 + `gpt-6-luna`，Responses API，reasoning=medium，Full 权限及 standard profile。输入工作区按题分开，不代表操作系统安全沙箱。

冻结 study 中历史文字写有 “packaged Core HTTP”。**实际进程是通过 `PYTHONPATH` 加载 `qualification-source-r2` 源码并使用 Core HTTP 接口运行，不是用最终 RC10 的 DEB 二进制执行这 40 题。** 这里保留 study 原件，只在报告澄清其历史表述。原始运行及原目录恢复使用相同 runner、Python 3.12.14 和 110 文件 Runtime 清单。

本次重算该清单所指冻结快照的全部 110 个文件 SHA-256，逐项相等；按原算法 `sha256(json.dumps(files, sort_keys=True).encode())` 得到相同 manifest digest。它只覆盖所记录的 Runtime 子集，不是完整产品、Desktop 或外部依赖身份。相对最终源码 `91dd87c6fd4678c103d6383dec1c1385deb38f9a` 的差异及可重建范围见 [Runtime 子集重建](../runtime-source-reconstruction/README.md) 与 [SOURCE_LINEAGE.json](../SOURCE_LINEAGE.json)。不能将较早源码实测表述成最终 RC10 整包实测。

| 原件 / 身份 | SHA-256 |
| --- | --- |
| [RUN_SUMMARY.json.gz](RUN_SUMMARY.json.gz) 解压后的原始 JSON 字节 | `8f6dab4e6eae8256776ab33203efacb8e1b2777ec6f04012b60d733ed48b03a3` |
| [study.json](study.json) 文件 | `48f91eb52521b364f07d5aa56791672d49e78fa747bc7643ef3c16ecef3803ca` |
| [source.json](source.json) 文件 | `b647719c7980512058f20ad0c38cb5f56518807809b7e1528f8321f61e4d3960` |
| source.json 内 110 文件 manifest digest | `c8f42a51536163e7f7ddee04823cc103d03a0e26913201cad8108e959b6d84c2` |
| [runner.json](runner.json) 记录、与冻结脚本字节相符的 runner SHA | `c1ec023219a86cac38c499f8503f65b56b333791f28147fba12a04780764ecff` |

归档仅以 gzip 无损封装大型汇总；原始文件字节数和解压后摘要由 [ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) 记录。每题的 case-result JSON 及已有 candidate-task gzip 均保留原字节。

## 与后续续跑和评分的关系

本次审阅时，023、025–029 的网络失败续跑在另外的输出位置运行。无论它随后如何结束，本报告的原始 R2 均保持 **40 题、26 completed、28 格式有效、8 个外层 error**；补充运行须单列自己的条件、来源和结果，不静默替换原始 cohort。

此时 `graded=false`。运行状态、格式检查和用量汇总不构成官方 AA leaderboard 成绩，也不足以与其它系统的准确率作比较。后续评分需要单独关联冻结候选输出、评分方法和固定分母；本报告不预填分数，也没有为审阅重新运行模型、测试或业务任务。
