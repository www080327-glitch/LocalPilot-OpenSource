# 两小时 soak R3：第二次执行会话中断

**结论：NOT_PASS / INCOMPLETE_EXECUTION_SESSION_LOSS。** 本轮只保存了约 48 分钟的心跳，没有两小时完成、模型回读或正常停止证明。原因为 **UNKNOWN**，不能解释为应用权限中断。

## 已保存的观察

| 证据 | 实际记录 |
| --- | --- |
| [heartbeat.jsonl](workspace/heartbeat.jsonl) | 97 条可解析心跳，elapsed 严格递增；最后为 **2880.0511786159987 秒，约 48.0 分钟** |
| [soak-progress.json](soak-progress.json) | elapsed **2920.2362048180003 秒**，`status=running`、`quiescent=false` |
| [heartbeat.py](workspace/heartbeat.py) | 预定运行 7200 秒并写入完成标记的脚本；脚本本身不是完成证明 |
| [core.log](core.log) | Core **5.0.0b27** ready，`model_health=NOT_PROBED` |
| [外层日志](cloud-soak-2h-r3-final.log) | 原件为 0 字节，不能据此证明进程已正常退出 |

心跳和 progress 是两个独立时钟的原始快照，不能把 progress 的 2920.236 秒当作最后心跳时间。没有运行器 `RESULTS.json`、终态 `soak-task.json`、`workspace/soak-finished.txt` 或启动 job 指定的 exit receipt；也没有保存工具完成后的模型回读证明。因此，归档不合成终态，不声明 Core 正常停止、全部进程退出或两小时资格通过。

## 中断原因与时间边界

[第二次中断记录](executor-interruption-20261116-second.json) 保存执行会话 **39371、36136、59322** 续接返回 `Unknown process id`，以及 `functions_store_lost=true`。协调器记录的失联时间约为 **2026-11-16 19:45 UTC**；该收据本身的观测时间是 **2026-11-16 19:47:17.380026 UTC**。后者是收据生成时的观察，不能倒推为应用的精确终止时间。

证据支持执行器会话及内存状态连续性丢失，**根因仍未知**。不同执行环境的 PID 可见范围不足以证明整机所有进程消失；本报告也没有检查原始 SQLite 或私有 Core 来补写解释。不能将此次中断归因于应用权限、审批、模型拒绝或某个确定的系统故障。

## 源码归属

[启动 job](cloud-soak-2h-r3-final-job.json) 指向 `final-source-91dd87c` 中的 `scripts/qualify_openai_agent.py --case soak --soak-seconds 7200`。公开副本仅将 `--key-file` 后的私有路径替换为占位符，未读取密钥文件；原始与归档字节摘要均保留在清单中。

[SOURCE_IDENTITY.json](SOURCE_IDENTITY.json) 是**中断后依据启动元数据及仍固定的 checkout 所作的核对**，不是运行器在当时保存过的 source.json 或不存在的 RESULTS.source。checkout 的 tracked 状态为空，HEAD 为 `91dd87c6fd4678c103d6383dec1c1385deb38f9a`，tree 为 `c19b18071de42ed42feb25519671a559f38dec18`；按原 source_identity 范围核对的 **110 个 Runtime 文件均与该提交的 Git 对象一致**，manifest SHA-256 为 `21350877c16f1a9d77e95f9a1e781cf7854478310c3d879bd5e6bd7318e33f7a`。该记录不覆盖全部外部依赖，也不表示最终 RC11 二进制运行。

## 同次中断涉及的 transport 续跑题目

中断记录还显示独立 transport 续跑的 **case 025 已开始、当时尚无结果**。保存的 [candidate-started](transport-case-025/candidate-started.json) 与随后 [恢复保护结果](transport-case-025/case-result.json) 支持这一边界：恢复返回 `Interrupted candidate attempt retained; not rerun under pass@1`，没有重新调用候选模型来补写该题。

这里指的是 **transport 续跑中的 025**，不是原始 R2 中候选开始前 Tunnel 403 的那份 025。其恢复记录的约 **0.00001349 秒**是命中保护分支的耗时，没有 `task_seconds` 字段；缺少完整候选用量，不能记为零消耗。`owned_core_stopped=true` 由创建新 Core 前命中保护而来，只证明恢复未创建新 Core，不能证明中断前进程正常收尾。本次仅复制这两份状态元数据，没有读取候选答案或参考标签。

## 归档与后续运行

[ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) 逐文件记录原件路径、大小与 SHA-256，以及归档大小与 SHA-256；明确区分原样复制、启动 job 的单字段路径替换，以及本报告和源码核对记录的事后生成。白名单之外的工作区文件、私有 Core、服务配置、密钥和原始 SQLite 均未复制。

本轮与 [R1 中断运行](../cloud-soak-2h-r1-interrupted/RESULTS.md) 相互独立，**不把 R1 的约 104.5 分钟与 R3 的约 48.0 分钟相加**。协调器已另行将 R4 改用 native Terminal、源码 `03535fe` 测试；本归档没有读取 R4 活动输出，也不预判它的结果。任何新的两小时结论必须由该次运行自身的计时、终态、标记、回读和停止证据支持。
