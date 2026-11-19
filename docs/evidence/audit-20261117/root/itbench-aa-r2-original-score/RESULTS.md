# ITBench-AA 原始 R2：完整缓存复用评分

## 结论

原始 R2 cohort 的评分为 **8.583333333333334 / 40，即 21.458333333333336%**。26 例使用已存在的归一化结果评分，14 例按候选失败规则计零，judge error 为 0。本次缓存复算实际创建评审后端 **0 次**、新增 judge 请求 **0 次**、候选重跑 **0 次**。这是独立实现对公开 40 例的评估，不能作为官方 AA 榜单或通用能力声明。[评分汇总](grading/SUMMARY.json.gz) · [CACHE_REUSE](CACHE_REUSE.json) · [独立核验](cache-run/VERIFICATION.json)

| 指标 | 实际值 |
| --- | ---: |
| 固定题数 / 分母 | 40 / 40 |
| 原始候选完成 / 输出有效 | 26 / 28 |
| `graded` / `candidate_zero` / `judge_error` | 26 / 14 / 0 |
| 满分 / 部分分 / 已评分零分 | 7 / 4 / 15 |
| `score_sum` | 8.583333333333334 |
| 40 例平均分 | 0.21458333333333335 |

15 个已评分零分是在既定归一化与计分口径下未匹配到参考根因，不将归一化未匹配直接等同于绝对诊断错误。两题 019、020 有有效输出但状态仍为 `incomplete`，按原规则计零；其余原始失败和中断边界均保留。[原始候选汇总](RUN_SUMMARY.json.gz) · [原始 R2 失败分类](../itbench-aa-r2/RESULTS.md)

## 全量缓存复用，而非选分数

在新的 scratch 目录复制原始 `study.json`、`RUN_SUMMARY.json`、40 个 `case-result.json` 和已有 28 个 `agent_output.json`，合计 70 个输入文件。原始 R2 历史目录未改动。与 continuation cohort 未替换的 34 题逐项比对，所有 receipt / prediction 原字节及 study 完全相同。[准备证明](CACHE_REUSE_PREPARED.json)

排除的固定索引为 **023、025、026、027、028、029**；这些题在原始 R2 中都是模型开始前的传输失败，按原规则计零。其余 34 题的所有评分终态及已有 started 缓存完整复制，包含失败、低分和零分：共 61 个缓存文件，即 34 个终态、26 个 started 和一个评分 manifest。没有按结果选择缓存，也没有为六题生成新的评审请求。[缓存前后完整 hash](CACHE_REUSE.json)

复算直接调用冻结 b29 的真实 `grade_run`，`backend_factory` 使用一旦调用就记录并抛错的 guard，传入的 key 路径是不存在的占位符；没有读取私有凭据。固定 SHA256 的参考数据只在内存读取，用于验证相同 fingerprint 和确定性零分计算。实际 `backend_factory_attempts=0`；全部 34 题 fingerprint 验证通过，六个原始失败题按规则生成零分终态。[guard 源码](cache-run/guard.py) · [执行证明](CACHE_REUSE.json)

独立核验确认 70 个来源/复制输入文件、34 个复用终态、61 个缓存均逐字节不变；continuation 的 72 个评分文件和 349 个公开候选文件也全部保留原 hash。逐题计数算术与冻结源码真实 `summarize` 完全匹配。[独立核验](cache-run/VERIFICATION.json)

## 与 continuation cohort 的区别

[Continuation 评分](../itbench-aa-r2-transport-completed/RESULTS.md) 为 22.291666666666664%，30 例 eligible、10 例候选计零；原始 cohort 为 21.458333333333336%，26 例 eligible、14 例候选计零。两者分数差异只来自索引 029 的 `1/3` 分，其余 39 题分数相同；浮点相减记录约为 `0.33333333333333215`。这是对两个明确不同的 cohort 使用同一批缓存，不是额外独立模型试验或多次评审取高分。[差异核验](cache-run/VERIFICATION.json)

## 固定来源与运行边界

- 评分器 commit：`8e92deb8b6a0acbba1d139851b1d805246304c61`。
- tree：`813a2544f1553d9c6a5e8a01982f2f512eec5e5b`。
- grader SHA256：`4cd3f405f7a4d1c05edb6bf5d5530657c69de6b934bf59c2cdf01df7e2f20b76`。
- Python：3.12.14；归一化缓存的配置保持 `gpt-5.5` / `medium` / 最大输出 16384 tokens。
- 参考 SHA256：`6073f64edc4e011fbf4d4677ca04f5b4ff84d2041d1786c0f54b3e3e7392a745`。

候选仍来自原始 `qualification-source-r2` 的 110 文件 Runtime 快照；不是 b29/RC12 的模型验证。原始 `study.json` 的历史 “packaged Core HTTP” 字样不改变其实际通过 `PYTHONPATH` 加载源码运行的事实。后续生产改动不修改本评分结果或触发重评。

原生 Terminal 第 20 个独立标签启动一次：supervisor 开始 `1794863357.2812564`，结束 `1794863357.9991045`，exit 0，耗时 **0.7178480625152588 秒**。这是缓存复算及参考加载的外层耗时，不是候选推理或 26 次新评审的耗时。[job](cache-run/job.json) · [log](cache-run/grading.log) · [exit](cache-run/exit.json)

原始中断候选 033、035 的 guard 耗时和停止标记仍保留其历史限制，未保存的运行时间或 usage 没有补造为零。没有自动重试评审或候选，也没有修改原始 R2、continuation 回执、冻结源码、评分规则或预算。

## 归档

[ALLOWLIST.json](ALLOWLIST.json) 为明确文件清单，[ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) 记录所有来源及归档字节大小 / SHA256。两个汇总使用确定性 gzip，解压可还原原件。此目录不包含 raw labels、judge 请求、私有 Core、凭据、SQLite、工作区或模型权重；参考原件没有落盘。缓存提供商输出保留原回执，核验仅检查元数据、计分算术和文件身份。
