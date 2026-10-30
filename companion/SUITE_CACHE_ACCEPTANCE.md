# 缓存实测与验收边界 — RC2

缓存前缀修复 0d5037c0/fed2409b 已进入本发行候选的源码。最初原工作目录的 v2-computer-use 分支没有该修复；本轮以正确缓存主线为基础构造发行快照，发布到 main 时保留它，不修改原工作目录。标准 Agent 和极简咨询仍是不同路由。

`test_service_cache_prefix` / `test_v49_context_cache` 覆盖静态前缀、多轮复用、工具 Schema 排序、动态状态后置、授权历史、配置恢复及压缩后 UNKNOWN/审批/工具消息配对。这些是脚本控制结果。服务端真实使用量由 provider 的 `prompt_tokens_details.cached_tokens` 或明确 cache hit/miss 字段归一化；缺失值为 UNKNOWN，不按相似文本估算。嵌套 cache details 原先未进入展示的问题已修复，冲突或不可能计数会拒绝。

## 接通电源后的真实服务结果

| 实验 | 模型调用 | cached input | total input | 命中率 | 任务与证据 |
| --- | ---: | ---: | ---: | ---: | --- |
| Qwen 写入、审批、重启恢复 | 3 | 12,288 | 37,406 | 32.85% | completed；verification passed；一次写入；进程释放 |
| 标准 Agent 本地→云端接管 | 4 | 3,072 | 24,232 | 12.68% | Qwen 两次 + DeepSeek 两次；独立切换/出站/写入审批；verification passed |
| 全新环境 CLI Agent 读取 | 2 | 0 | 8,962 | 0% | Qwen；completed；verification passed；退出后继续与恢复通过 |
| 仅原问题 DeepSeek 咨询 | 1 | 0 | 25 | 0% | 回答 42；零工具；verification NOT_RUN |

这些样本跨配置、会话、工具和冷启动，不能作为严格性能 A/B 或整体加速结论。接管中的本地两次请求 cached=0 / input=9,689，云端两次 cached=3,072 / input=14,543；切换没有建立跨模型共享缓存的证据。它证明现有授权投影下可完成任务并获得真实统计。

逐调用 input/cached/output/latency/task status 在 `docs/evidence/suite-release-20261021/cache-metrics.json`。例如审批恢复任务三个调用分别为：0/7,985（29.058s）、4,096/12,143（24.928s）、8,192/17,278（46.268s）。总 cached 12,288 / input 37,406，不是 99%。真实故障注入的 1-token Qwen 请求单独记账，不混入成功任务分母。

实际 API 账单费用：**UNKNOWN**，无 provider 账单记录。未配置单价时不伪造费用；本地硬件成本亦未计价。Provider 原生 TTFT：**UNKNOWN**。另有客户端 Runtime 事件的 `ModelResponseStarted → first TextDelta` 实测，单独标注范围：审批任务 23.000s / 45.131s；接管 9.209s / 14.567s / 0.978s。它不等于供应商 TTFT，也不用于无文本的纯工具调用。

## 历史云端样本

省电阶段单独记录 9 次真实 DeepSeek 请求，cached 14,208 / input 23,433（60.63%），输出 277 tokens。该阶段没有 Qwen；只证明当时的云端 API、工具与缓存路径。它与 RC2 最终样本分开统计，不混合分母。缺失的本地 usage 仍保留 UNKNOWN，不倒填历史记录。

## 准入结论

真实前缀复用确有服务端计数支持，但收益依任务变化；一次新环境任务命中为零。**持续 99%、长会话稳态收益、真实模型压缩前后语义对照均未证明，后两项分别保留 UNKNOWN/NOT_RUN。** 不通过删上下文、审批、UNKNOWN 或证据来提高命中。缓存专项为 PASS_SCOPED，不是性能或长期稳定性保证。
