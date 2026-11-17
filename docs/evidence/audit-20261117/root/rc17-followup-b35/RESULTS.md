# RC17 续作：Core b35 / Companion b12

本轮完成两个产品修复、源码回归、安装态验证和一项限定工作区的真实模型角色集成。**当前仍为 NOT_RELEASE_READY**：原 Full 工程复验被自动审批阻断，浏览器两项用例未进入页面断言，当前候选的原生交互、双架构 macOS 与两小时安装态 soak 仍未验收。

PR：<https://github.com/www080327-glitch/LocalPilot-OpenSource/pull/15>。本轮不合并、不创建 Tag 或 Release。

## 1. 准确来源

| 范围 | 不可变来源 | 验证关系 |
|---|---|---|
| 续作起点 | `6c923a95c749d1db2c6d2548e2109cd79b02d938` | 上轮 RC17 源码与 R9/R10/R11 原始证据 |
| 产品修复、版本、全量回归与四组件安装 | `8e27340e3d0cabbb37ace7a652de9b1f2f0d0eee` | 每组全量回归各有 820 文件前后清单；安装 payload 逐字对照此提交 |
| 最终只读角色 smoke 脚本及定向测试 | `b69542583954c49672a636ba43f1ef310238883c` | 相比上项仅修改角色脚本、对应测试、Work 文档；产品实现完全相同 |
| 后续提交 | 文档和本目录证据 | 不把文档/归档提交冒称为重新运行过同一套全量的源码提交 |

完整来源、文件散列与例外见 [SOURCE.json](SOURCE.json)。版本为 Core **5.0.0b35**、Companion **0.5.7b12**、Desktop **5.0.1-rc.17**、Suite **0.2.0b34**、Channels **0.1.0a4**。只有前两个组件本轮改变。

## 2. 已完成的产品修复

### V5 子任务第一次输出截断后，在原预算内继续

R10 的 Parser 子任务在 4096 单次输出上限处收到 `finish_reason=length`，截断的工具提案未执行，父任务随后试图创建第三个子任务而撞到原有两个子任务上限。本轮针对这一条确定的产品失败路径修复，不把失败简单归为模型能力。

现在子任务首次 length 后保留之前已完成的工具收据与全部调用用量，丢弃该次响应的全部工具提案（包括其中看似完整的同批提案）、半截文本及 native replay。宿主明确要求拆为较小的完整调用，然后在同一个子任务内继续一次。输出 token、总 token、steps、工具与子任务数量上限不增加；请求仍经过既有预算、取消与权限检查。

第二次截断仍停止，没有执行步或进入最终交付保留步时不尝试恢复。恢复次数从持久化用量判断，重启不会重置；`WorkerOutputRecovery` 事件和 ready checkpoint 保留过程。父任务 finalization 和产品验证等级不改变。

8 项新回归覆盖真实 TaskService、SQLite、Gateway、文件写入和 Shell 自测，并检查同批提案全部丢弃、既有收据、第二次截断、预算、checkpoint、权限与取消。相关 **97 项定向测试全部通过**。真实 Full 工程中的恢复效果仍待 R12 获准后验证，下面的只读 smoke 没有触发 length。

### 同一会话的来源有效性查询不再解码所有完整任务

上一版已经把全量 JSON 映射改为逐任务 SQLite 行，但 `session_context_current()` 仍逐条读取同会话的完整 payload。本轮增加派生的 `context_request`，只存既有检查需要的 memory ID、文件路径、observation ID/source reference；经规范化去重后，通过覆盖索引读取不同依赖集合，继续调用原来的动态来源有效性检查。

完整任务 payload、ID、未知字段和收据不变。权限撤销、memory 删除、文件变化和观察来源仍实时检查，没有缓存授权结论。旧 b11 writer 更新 payload 时会使派生列失效，新版通过部分索引只回填待处理行；新版正常更新只写一次完整 payload。迁移、真实旧 UPSERT、缺失 request、时间边界和 `put_if_absent` 均有回归。

已有逐行表的新增列、索引及首次回填在同一事务中完成；失败回滚保持旧表和数据。更早的全 JSON 版本仍沿用迁移前备份和原迁移事务。b11 可以继续读取完整 payload；退回全 JSON 旧版本仍须停止服务并恢复原备份，备份后的新增任务不在旧快照里。

## 3. 同机性能对照

实测真实 TaskStore/TaskController，基线为 `6c923a9`；每项先运行基线再运行候选，预热一次后测 5 次。夹具每任务约 21 KB，所有任务处于同一会话，具有一个共同的空依赖集合。此处测的是来源有效性查询，**不是 HTTP 状态接口、UI 延迟或任意依赖分布下的常数复杂度保证**。

| 历史条数 | 基线中位数 | 本轮中位数 | 首次逐行表升级 |
|---:|---:|---:|---:|
| 1,000 | 37.086 ms | 0.06798 ms | 143.022 ms |
| 10,000 | 367.011 ms | 0.73135 ms | 1,202.735 ms |

10,000 条下只解码 1 份不同依赖集合，稳态待回填行数为 0；SQL 计划实际使用覆盖索引。旧 writer 修改一条后首次查询为 0.786 ms；旧 writer 批量修改全部 10,000 条后首次回填为 853.209 ms，随后稳态中位数为 0.635 ms。完整 payload 和 ID 前后散列一致。

SQLite 仍扫描匹配的小型索引，所有不同依赖集合仍各自实时检查；分页计数语义未改。不能把这些数据扩展为所有历史查询都不随规模增长。原始采样、SQL trace、query plan 及一次性成本见 [PERF_COMPARISON.json](PERF_COMPARISON.json) 与 `session-context` 证据归档。

上轮单任务 HTTP 查询的约 1494 ms → 1.97 ms 属于上一轮整份 JSON → 逐行存储对照，保留在 [原始 RC17 报告](../task-storage-dispatch-b34/RESULTS.md)；本轮没有把不同路径的数字拼成同一次比较。

## 4. 回归与安装验证

| 验证 | PASS | SKIP | FAIL / ERROR | 来源 |
|---|---:|---:|---:|---|
| Core 全量 | 1,627 | 92 | 0 / 0 | 产品提交 `8e27340`；共 1,719 项 |
| Companion 全量 | 730 | 33 | 0 / 0 | 产品提交 `8e27340`；共 763 项 |
| Suite 全量 | 126 | 1 | 0 / 0 | 产品提交 `8e27340`；共 127 项 |
| 新截断路径及关联定向回归 | 97 | 0 | 0 / 0 | 同一产品文件散列；包含在全量中 |
| Companion 来源/迁移定向回归 | 64 | 0 | 0 / 0 | 最终另重复其中 12 项；不累加为独立案例 |
| 最终角色 smoke 本地 TLS/边界测试 | 3 | 0 | 0 / 0 | 脚本/测试提交 `b695425`；无外部模型调用 |
| 四组件全新安装后的测试 | 66 | 0 | 0 / 0 | 安装来自 `8e27340` 对应产物；44 Core + 22 Companion |

跳过不算通过。全量回归的前后 820 文件清单一致，并已独立比对 Git blob；并行发生的回归运行时间不作为性能对照。全量之后只改变角色 smoke harness、对应测试与文档，最终 harness 以其单独 3 项结果和真实 smoke 为证，不声称最终全树又跑过同一轮全量。

安装验证使用新建的 Python 3.12.14 环境，重新构建 Core/Companion wheel，Suite/Channels 沿用散列已核对的对应产物。四个 wheel 的 **346 个 payload 文件**与安装文件、冻结提交源码逐字一致，安装前后来源未漂移。记录的 152 个产品模块来自新环境的 `site-packages`，测试 `sys.path` 不含产品源码根；`pip check` 与 CLI 版本也通过。见 [PACKAGING_SUMMARY.json](PACKAGING_SUMMARY.json) 与安装证据归档。

## 5. 真实模型：只读服务角色集成 PASS

本次使用普通 Core 工作区受限只读会话；没有 Desktop Full 权限。Super Agent 仍负责统筹：父为 **gpt-6.1-sol / medium**，search 为 **gpt-6-luna / high**，review 为 **gpt-6.1-sol / medium**。

共 **10 次模型调用**（父 4、search 3、review 3），**7 条工具收据**（父 2 次 delegate + 1 次 wait_children；两子各 2 次 read_file），耗时 **84.112 秒**。每个子任务实际完整读取 24-byte marker 和 78-byte Python 夹具，读取 SHA、覆盖范围和回答吻合。工作区仅有这两份夹具及 fact.txt，前后散列一致。服务重启后 task/session、收据、子任务、结果和 Runtime evidence 完整保持一致。

host 的实际请求事件确认 model/effort；provider 响应只独立回显 model，没有回显 effort。只计算父聚合一次的 provider 用量为 **56,832 输入 token、1,489 输出 token**，其中 **31,101 缓存输入 token**；不是账单或成本估算。

必须保留的边界：

- 两子任务生命周期没有重叠；search 结束约 0.399 秒后 review 才启动。异步委派和收据回收已执行，本次没有证明并行提速。
- 父代理只收到子任务收据元数据，子正文由普通服务投影策略保留；因此未验证主模型综合子正文的协作，也未证明 token 节省。
- 此次没有 length，没有代码编辑或执行，不能替代原工程门禁或真实截断恢复测试。
- 外部 smoke PASS 不更改产品字段：`verification_status=not_run`、`engineering_status=unverified`、`task_outcome=unverified`、`task_succeeded=false`。

本地 TLS 测试还证明该独立 harness 中父与两子共 6 次绝对/相对路径越界读取被拒绝，外部合成哨兵正文没有进入后续请求。这是用既有工作区 resolver 验证本次范围，并没有更改 Desktop Full 的访问语义。真实模型结果与独立核验见 [WORKER_ROLE_SUMMARY.json](WORKER_ROLE_SUMMARY.json) 及原始归档。

## 6. 失败、阻断与剩余门禁

| 项目 | 当前状态 | 原因和后续 |
|---|---|---|
| 原 Full 工程 R12 / Luna high | **BLOCKED_BY_AUTOMATIC_APPROVAL_REVIEW** | 续跑被自动审批拒绝：可能将私有仓库内容发给 OpenAI；没有 RESULTS 终态，调用数与 usage 未知，不能写为模型 FAIL 或 PASS |
| 当前只读角色 smoke | **PASS，限上节范围** | 没有替代 R12，也未绕另一入口继续被拒绝的 Full 测试 |
| 浏览器 2 项用例 | **BLOCKED_AT_LAUNCH** | 1 次 Playwright 命令，两项都在 Chromium 单例 socket 创建时遇到 EPERM；0 页面断言 |
| 当前 Linux 原生 APP | **NOT_RUN** | 本机缺 cargo/rustc、GTK/WebKit 等开发环境和受支持安装 helper；附加桌面没有本候选 APP |
| Apple Silicon / 真实 Intel Mac | **NOT_RUN** | 当前环境没有这些真实机器；交叉编译、旧 RC14 结果不能替代 |
| 桌宠焦点、缩放、多屏、减少动态、可见动画 ≥24 Hz | **NOT_RUN** | 需当前原生 Test APP 和实际桌面证据；不能用 rAF 回调数代替可见变化 |
| 当前安装组合 Full + extended 两小时 soak | **NOT_RUN** | 未在新安装组合完成两小时真实任务；84 秒 smoke、旧版本 soak 均不替代 |

仓库元数据实际为 public，R12 工程夹具为合成内容，但该 Full 工具配置仍具有工作区外访问能力，不能据此声称技术上只会读合成文件。拒绝后没有重试该 Full 测试、代理转发或换入口绕过。若需补完，需要明确授权将 LocalPilot 开源仓库中验收所需系统提示、工具定义、合成工程文件与执行收据发送给 OpenAI 的 Luna/Sol；其他私人项目、凭据和用户资料不在范围。见 [ENGINEERING_R12_BLOCKED.json](ENGINEERING_R12_BLOCKED.json)。

保留的初次失败包括：默认解释器缺 watchdog 的初始化错误；SQLite trace 文本计数不等于真实 payload 写次数导致的首次断言失败（后改用实际 UPDATE 审计触发器验证一次写入）；开发角色 harness 时的初次局部失败摘要。未重建不存在的原始日志。上述修复后的定向/全量结果分开记录。上轮 R9 PASS、R10 FAIL、R11 PASS 和首次回归失败原封不动保留，不把旧 R11 或旧 macOS 成功套到本轮。

## 7. 证据与 Work 交接

[SUMMARY.md](SUMMARY.md) 列出全部归档和成员清单；[MANIFEST.json](MANIFEST.json) 与 [SHA256SUMS](SHA256SUMS) 给出归档散列。归档只使用明确允许的文件，逐份比对解包字节和源文件；私有 runtime、凭据、SQLite、模型及 wheel 不公开。安装产物由来源、wheel 散列和构建/安装日志定位，不把二进制塞入证据归档。

直接续接步骤见 [WORK_CONTINUE_20261117_B35.md](../../../../development/WORK_CONTINUE_20261117_B35.md)：浏览器原用例、当前 Test APP 构建、两种 Mac 真机、Linux、原生交互/动画、安装升级回滚、Full 工程审批与安装态两小时 soak，均保留独立通过条件。

此前已披露的 **Core archived-canonical 通用检索、Computer/Adaptive/精确云授权路由的执行段轮换、单个超长运行 turn 的块式持久化** 仍是另行跟踪的实现工作。这些没有在本次两个修复里完成，也不属于“实现已好、仅缺硬件验收”。后续应按具体负载和现有 Runtime 做最小范围改动。
