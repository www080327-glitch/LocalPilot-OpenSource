# ITBench-AA R2 transport continuation：候选终态与评分

## 结论

这个 continuation cohort 的 40 例已全部形成终态回执，随后固定评分器完成了 30 例归一化评分；另外 10 例因候选未完成而按既定规则计零。总分为 **8.916666666666666 / 40，即 22.291666666666664%**，没有 judge error。它是 LocalPilot 对公开 40 例的一次候选尝试及独立归一化实现的评估，不是官方 Artificial Analysis 榜单成绩，也不能外推为通用工程能力。完整逐例记录见 [候选汇总](RUN_SUMMARY.json.gz)、[评分汇总](grading/SUMMARY.json.gz) 和[独立核验](grading-run/VERIFICATION.json)。

| 指标 | 实际值 |
| --- | ---: |
| 固定题数 / 评分分母 | 40 / 40 |
| 候选 `task_status=completed` | 30 |
| 候选 `output_valid=true` | 32 |
| 候选外层 `errors` | 3 |
| `graded` | 30 |
| `candidate_zero` | 10 |
| `judge_error` | 0 |
| 满分 / 部分分 / 已评分零分 | 7 / 5 / 18 |
| `score_sum` | 8.916666666666666 |
| 40 例平均分 | 0.22291666666666665 |

18 个已评分零分均是在既定归一化与计分口径下未匹配到参考根因；这不把归一化未匹配直接等同于绝对诊断错误。规则要求覆盖全部参考根因组后才按匹配组、误匹配组和未匹配预测计算精度；零分和部分分都保留，没有依据分数重跑。独立核验逐例检查了记录中的计数算术，并调用同一冻结源码的真实 `summarize`，与汇总完全一致。[核验记录](grading-run/VERIFICATION.json)

## cohort 与中断边界

原始 R2 的 6 个候选在模型开始前遭遇下载传输错误：索引 **023、025、026、027、028、029**。本 cohort 保留其余 34 题的原回执，只按预先保存的 continuation 协议处理这 6 题，任务预算与候选源码保持原配置。四题 026–029 最终完成且输出有效；023 形成 `incomplete`，025 在第二次执行器中断前已开始，恢复程序因此拒绝重新执行，留下 guard 的 `RuntimeError`。[协议](transport-continuation-protocol.json) · [continuation 身份](CONTINUATION.json) · [恢复记录](RESUME_AFTER_SESSION_LOSS.json)

最终 `candidate_zero` 索引为 **004、005、019、020、023、024、025、030、033、035**。其中 019、020 虽有有效输出文件，候选状态仍为 `incomplete`，没有被升级为完成。033、035 是原始 R2 已开始但执行器中断的候选；025 是 continuation 中的同类中断边界。恢复 guard 的耗时不是遗失候选的真实运行时间，历史 `owned_core_stopped` 字段也不能补出未保存的执行细节或 token usage；这三题的缺失 usage 不记成零使用量。[原始 R2 限制与分类](../itbench-aa-r2/RESULTS.md)

[恢复驱动 exit](transport/resume-exit.json) 的 `returncode=1` 对应“没有全部 40 题输出有效”，不表示缺失汇总或额外重跑。最终候选汇总已经包含全部 40 个回执。旧的首次评分曾在参考输入 schema 解析处退出，没有 judge 请求；缺省根因标记、可选空 namespace 和完全相同重复实体的最小入口适配及前后证据另存于 [reference adapter](../itbench-reference-adapter/RESULTS.md)。该适配没有修改归一化提示、评分公式、分母、模型或预算。

## 运行来源

| 部分 | 固定身份 |
| --- | --- |
| 候选运行 | `qualification-source-r2`，通过 `PYTHONPATH` 加载源码；不是 RC10、RC11 或 RC12 二进制 |
| 候选 110 个 Runtime 文件 manifest | `c8f42a51536163e7f7ddee04823cc103d03a0e26913201cad8108e959b6d84c2` |
| 候选 runner SHA256 | `c1ec023219a86cac38c499f8503f65b56b333791f28147fba12a04780764ecff` |
| 评分器 checkout commit | `8e92deb8b6a0acbba1d139851b1d805246304c61` |
| 评分器 checkout tree | `813a2544f1553d9c6a5e8a01982f2f512eec5e5b` |
| 评分脚本 SHA256 | `4cd3f405f7a4d1c05edb6bf5d5530657c69de6b934bf59c2cdf01df7e2f20b76` |
| Python | 3.12.14 |
| 参考 JSONL SHA256 | `6073f64edc4e011fbf4d4677ca04f5b4ff84d2041d1786c0f54b3e3e7392a745` |

[source.json](source.json)、[runner.json](runner.json) 保留候选的实际历史来源；[评分前 READY](grading-run/READY.json) 和[评分 manifest](grading/manifest.json) 绑定评分器。冻结 `study.json` 中历史用语 “packaged Core HTTP” 不应解释为候选在发行 DEB 中执行；实际是上述源码加载运行。后续生产修复不改变这一已冻结评估，也不触发重新评分。

## 评分执行与保留证明

原生 Terminal 第 16 个独立标签仅启动一次。supervisor 的开始时间为 `1794862818.1810434`，结束为 `1794862959.4712956`，耗时 **141.29025220870972 秒**，exit 0；该时间是归一化评分任务耗时，不是候选运行耗时。[job](grading-run/job.json) · [log](grading-run/grading.log) · [exit](grading-run/exit.json)

归一化配置为 `gpt-5.5`、`medium`、最大输出 16384 tokens、180 秒超时，每个 eligible case 一次归一化尝试。30 个 started 回执和终态逐一对应，提供商回报的模型均为 `gpt-5.5-2026-04-23`。回报 usage 合计为 prompt 28,132、completion 8,925、total 37,057 tokens；它们是本次 judge 的回报量，不是候选总用量。[评分 manifest](grading/manifest.json) · [逐例元数据核验](grading-run/VERIFICATION.json)

评分前确认全部 40 个终态回执与原汇总一致，参考加载前的 output-scoped Core 检查通过；没有读取运行中的候选答案。评分后的 349 个公开候选文件及 `RUN_SUMMARY.json` 均与评分前 SHA256 相同，35 个此前已完成的恢复回执、原始 R2 的 314 个公开回执也保留原 hash。原始 cohort 另在独立目录使用 34 题全部缓存复算，包含失败及低分，不新增评审请求：[原始 R2 缓存评分](../itbench-aa-r2-original-score/RESULTS.md)。

## 归档说明

[ALLOWLIST.json](ALLOWLIST.json) 列出所有获准复制的来源与转换；[ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) 记录来源/归档大小和 SHA256。三个汇总使用 `gzip.compress(mtime=0)`，解压后逐字节还原原件。job 或辅助驱动中若出现已知私有 key 文件路径，仅替换该路径并在 manifest 记录次数；没有读取凭据文件。参考数据仅在内存解析，没有归档原始 labels、judge 输入、private Core、工作区、SQLite 或模型权重。候选/提供商输出属于原始评估证据，保留其实际内容与哈希；这次核验只检查元数据、算术和文件身份，没有重新诊断题目。
