# 原始两小时 soak R1：执行会话中断记录

**结论：`INCOMPLETE_EXECUTION_SESSION_LOSS`。本轮未取得两小时完成证明，不能判定长任务资格通过。** 本报告只复核已归档的 R1 材料；没有发起 API 请求、检查私有 Core/凭据、控制进程、修改源码或重新运行测试。

## 归档完整性

[ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) 列出的 **6 个文件均存在，实际字节数和 SHA-256 全部一致**。本报告是后续独立复核，不改写该清单或这 6 个原始文件。

| 归档文件 | 字节数 | 字节数及 SHA-256 核对 |
|---|---:|---|
| `core.log` | 109 | 一致 |
| `resolved-runtime-budgets.json` | 1238 | 一致 |
| `soak-progress.json` | 157 | 一致 |
| `workspace/heartbeat.py` | 428 | 一致 |
| `workspace/heartbeat.jsonl` | 6569 | 一致 |
| `executor-interruption-20261116.json` | 4048 | 一致 |

## 实际观测与缺失证明

- [workspace/heartbeat.jsonl](workspace/heartbeat.jsonl) 有 **210 条**可解析心跳，elapsed 严格递增；最后一条为 **6270.103279763003 秒**，约 **104.5 分钟**。它证明这些心跳被写入，不能外推为连续完成 7200 秒。
- [soak-progress.json](soak-progress.json) 保留的另一份进度快照为 elapsed **6299.288929472001 秒**、`status=running`、`quiescent=false`。这是当时的非终态快照，不是恢复后查询、终态收据或完成证明；它与心跳的最后时间采用各自原始记录，不混成同一个计时值。
- 归档没有资格运行的 `RESULTS.json`，没有 `workspace/soak-finished.txt`，也没有模型在工具完成后回读并确认结果的证明。[heartbeat.py](workspace/heartbeat.py) 中的完成标记代码只是预期行为，不能替代实际生成的标记。
- 没有 terminal task receipt，也没有 owned Core 停止收据。因此不能声称任务正常结束、Core 已安全停止，或所有相关进程都已退出。

## 中断解释的边界

[executor-interruption-20261116.json](executor-interruption-20261116.json) 记录执行会话句柄 **11297、43321、7599** 同轮无法续接。协调器提供的失联时间约为 **2026-11-16 18:46 UTC**；该归档收据自身的 `observed_unix=1794855273.0353708` 对应 **18:54:33.035371 UTC**。后者是收据的观测时间，不能倒推成应用终止时间或精确失联时刻。

现有证据支持“执行会话连续性丢失”。**原因未知，没有确立应用权限中断这一原因。** 收据所述“选定 executor 中未见相关 runner/Core 进程”受该执行环境可见范围限制，不能提升成整机进程清点或停止证明。缺少终态同样不应被改写成某个具体应用失败原因。

## 源码归属与独立运行

本轮源码归属沿用既有 [SOURCE_LINEAGE.json](../SOURCE_LINEAGE.json) 中 `two-hour-soak` 条目：`qualification-source-r1` 冻结快照，runtime 子集标识为 `runtime-7fb18d68f0bf0ee8bbaa4fc3bab5b7712b906f1644110105697fa1444a6fb70f`。该标识来自已经核对的冻结快照子集，**不是本轮捕获的独立 soak source.json，更不是不存在的 RESULTS.source 字段**。既有 lineage 记录这 110 个 runtime 文件中 105 个与最终源码一致、5 个不同；归档 `core.log` 也仅记录 Core `5.0.0b26` ready、model health 未探测。不能把 R1 描述成最终 `91dd87c` 或 RC10 安装包的两小时执行。

协调器另行启动的最终源码两小时 R3 是独立运行。本复核不读取其活动输出、不预判结果，也不将 R1 的约 104.5 分钟与任何后续运行相加。新的完整两小时结论必须由该新运行自己的计时、终态、完成标记、模型回读及停止收据支持。
