# RC16 长期会话与 Companion 续验 — 2026-11-17

**源码与组件验证完成；候选仍为 `NOT_RELEASE_READY`。** 本轮没有创建 Tag、Release 或新的原生 APP/DEB。Super Agent R8 的外部代码验收通过，但原编排门禁未通过；不能将整轮标成工程 PASS。

## 源码与交付

- Runtime 改动：[63ec8ab](https://github.com/www080327-glitch/LocalPilot-OpenSource/commit/63ec8ab0676b77de6be9dad3f16332d459dcdc8f)，tree `36d464811bbfd9538274d88bd2c13fbcf80374be`。
- 版本门禁测试补齐：[5a519b7](https://github.com/www080327-glitch/LocalPilot-OpenSource/commit/5a519b7e35d9d4902b2c0a0ee73f36eacff71325)，tree `af97c2417c751285e549d14ef95ba536a1dfbd92`。第二个提交只改测试夹具及两个负对照，不改生产代码。
- 组件：Desktop **5.0.1-rc.16**；Core **5.0.0b33**；Companion **0.5.7b10**；Suite **0.2.0b33**；Channels **0.1.0a4**。
- 本地受测 commit 与远端提交具有相同 Git tree；逐套件和最终源码的对应检查见 [SOURCE.json](SOURCE.json)。原四类各十项审计不重复计数，本轮继续解决具体长期运行问题。

## 完成的修复

### 1. 同一 Core 会话的活动执行记录分段

SQLite 持久化的 V5 会话默认在下一任务开始前检查 Runtime 的 UTF-8 序列化大小；达到 2 MiB 时，把原始 Runtime 段、旧终态任务与新活动检查点在同一事务内保存。Session ID 和 turn 递增关系保持不变。

保留最近完整 turn 的工具收据、完成调用、子任务及 finalization 账本，保留全部目标和工作状态；实际已准入的 RequestHistory 原文与 scope 不重新总结，只精确重基游标。旧任务输出、收据、事件与幂等键继续按原 ID 读取。

两项实际恢复边界有专门回归：首次模型 dispatch 前失败时不能裁掉尚未进入请求缓存的上一轮最后回答；没有新 attempt 的轮次也不能让 Hybrid 调用身份重新从零编号。保留近期身份和未准入尾部解决这两个问题，隔离负对照能分别抓住回归。

默认产品 Hybrid/Cooperative 路由已覆盖，包括实际 `deployment.build()` 的本地 HTTP 模型传输。Computer、Adaptive、已有 exact egress grants 的会话继续使用原有历史方式；当前任务、待批准工作及未解决副作用不被裁剪。默认阈值不是单任务或数据库大小的硬上限。

### 2. SQLite 启动日志校验与 schema 3

恢复不再为 lifetime journal 创建完整 Python 列表。主键唯一、整数修订号、COUNT/MIN/MAX 和最新 SHA 保留原连续性校验语义。20,000 条真实 journal 的一次诊断中，Python 分配峰值从 **4,990,492 B** 降为 **2,856 B**；这不是整个进程 RSS 或恒定启动时间保证。

schema 1/2 升级前生成经完整性和版本校验的私有备份；归档与活动检查点同事务提交。实际 b32 reader 拒绝 schema 3，数据库字节未改变。降级仍需停止服务并恢复升级前备份，不能只修改 `user_version`。原始事务故障、迁移和旧 reader 证据见 [reviews/MANIFEST.json](reviews/MANIFEST.json)。

### 3. Companion 云端恢复和长期任务列表

接受云端任务后中断恢复漏掉 `provider_kind` 的问题已修复。真实 HTTP/SQLite 测试确认原提交不重放，恢复后下一条云端问题能正常创建独立执行会话。

原始 1001 条任务夹具使 `ui_snapshot` 达 **26,080,845 字节**，超过 Swift 客户端 2 MiB 上限。任务页现在默认 30 条、最多 50 条，提供总数与 timestamp/ID 游标；界面保留“较早任务 / 最新任务”，精确 task ID 查询继续访问旧记录。

真实认证 HTTP 测试在 **13,036,521 字节**的存量任务 JSON 上读取两页，响应为 **66,846 / 66,841 字节**，原任务 JSON 字节完全不变。两个既有快照字段继续存在，并复用一次分页计算。状态/取消更新从普通路径的 **5 次全图读、2 次写**降为 **3 次读、1 次写**。

底层 `localpilot_tasks` 仍是完整 JSON 映射；一万条合成历史的状态查询仍约 1.76 秒中位数，不能称为无限历史的恒定成本。Swift 页面本轮只有源码检查，没有原生编译或点击验收。详情和原失败见 [companion/MANIFEST.json](companion/MANIFEST.json)。

## 默认阈值存储对照

同一脚本化 provider 协议，实际运行 AgentSession、Hybrid、read_file 和 SQLite：b32 基线 180 轮，b33 最终源码 360 轮。脚本化回答不属于模型能力评测；时长和启动耗时保留为单次诊断，存在其他并行测试，因此不主张速度比。

| 指标 | b32，第 180 轮 | b33，第 180 轮 | b33，第 360 轮 |
| --- | ---: | ---: | ---: |
| 活动 Runtime 字节 | 3,052,686 | 1,732,540 | 1,538,990 |
| 活动 checkpoint 字节 | 9,867,305 | 4,538,050 | 3,548,851 |
| 活动 canonical 消息 | 721 | 297 | 213 |
| 活动工具收据 | 180 | 74 | 53 |
| 活动任务 | 180 | 74 | 53 |
| 已轮换次数 | 0 | 1 | 3 |

最终源码在第 **108、210、309** 轮开始新任务前轮换。360 轮的活动 Runtime 峰值 **2,120,083 B**，活动 checkpoint 峰值 **6,169,063 B**；保留三个原始归档段，307 条归档任务和 53 条活动任务。只读复查确认 **360 条原始用户输入和 360 轮 read_file 收据全部可追溯**，全部 archive/checkpoint SHA 有效，旧幂等键、SSE、任务结果与未完成目标原文保持一致，重启不发模型请求。

完整数据库最终为 **22,589,440 B**，归档历史仍占磁盘。证据和逐轮采样见 [storage/SUMMARY.json](storage/SUMMARY.json)。较早候选 r1 在运行中发生源码修改，保留为开发诊断，不作为最终源码证据。

## 真实 GPT-6 Luna 验证

### 常驻会话、轮换与重启：PASS_WITH_SCOPE_LIMITS

一次实际 Responses run，4 个任务、8 次模型调用、64.417 秒。第一任务依次读取两个文件，第二、三任务各只读新文件并复述已有随机 marker，重启后的第四任务不使用工具仍按顺序复述全部四个 marker。独立核对强于 runner 原包含判断，逐行顺序全部一致。

7/7 相邻请求的解析后 input 数组前缀、工具及 reasoning 设置一致；没有 HTTP wire 抓包，不能将它表述成传输层字节抓取。8 条提供方 diagnostics 明确返回 `input_transformations=[]`，不据此推断未公开内部推理。用量为 **36,587 input / 276 output / 29,113 cached input**。

实际发生两次归档轮换。旧任务读取与旧幂等键重试没有额外模型调用，原始档案与快照一致，自有服务已停止。这里把轮换阈值设置为 **1 字节**以触发集成路径；生产默认值仍为 2 MiB，模型窗口压缩为 0 次。Gateway 为 Full，工具能力限定只读，不能称为高权限写入或长时间 soak。

四个产品结果仍为 **`task_outcome=unverified`、`verification_status=not_run`、`task_succeeded=false`**，completion 为 settled/delivered；外部 marker 验收没有改写产品判定。独立审阅 **43/43** 项通过，完整原始结果、提供方记录、请求与审阅见 [live/MANIFEST.json](live/MANIFEST.json)。

### Super Agent R8：整体工程 FAIL

使用与 R7 完全相同的 runner、prompt、12 份夹具、预算及原始验收条件，只运行一次。协议 PASS，外部语义 PASS，编排 FAIL，所以 overall engineering FAIL；原 runner 退出 1，Core 已停止，源 tree 前后相同。

两个子 Agent 均 async/completed/collected，各改自己的指定模块，生命周期重叠 **122.728484 秒**。父 17 次调用、两个子各 7 次，共 **31 次模型调用、68 条工具收据**。原始外部验收在 Core 停止后重新执行，**17/17 测试、4/4 CLI 通过**。

未过条件是 Parser 子 Agent 没有自己的成功 ParserTests 收据。父把有效的 Python 路径改写成不存在的 `.venv/bin/python`，两个子任务均遇到 exit 127；Aggregate 子改用 python3 并通过自己的 3 项测试，Parser 子如实报告 tests did not run。父后来补跑全量与 9 项 ParserTests，仍不满足冻结协议要求的子任务独立验收。另两条 delegate 参数错误也原样保留，未重跑掩盖失败。

没有证据表明这次是 Runtime Shell 故障；同轮父与另一子使用 python3 正常。产品自身仍为 unverified/not_run/false。结果与完整收据见 [engineering/RESULTS.md](engineering/RESULTS.md)、[失败分析](engineering/FAILURE_ANALYSIS.json)；旧 R7 的 PASS 保持旧版本归属。本轮没有新增或声称 Artificial Analysis 官方排名。

## 最终回归矩阵

| 验证 | 实际结果 | 范围 |
| --- | --- | --- |
| Core 全量最终 r3 | **1,693 = 1,594 PASS + 99 SKIP**；0 fail/error；191.76 s 外层 | 最终 279 个源码/测试文件前后一致，并与最终源码逐份相同 |
| Companion 全量 | **749 = 716 PASS + 33 SKIP**；0 fail/error；36.833 s unittest | 508 文件前后一致；之后只有独立的 Core 版本测试夹具变动 |
| Suite 全量 | **123 = 122 PASS + 1 SKIP**；0 fail/error；56.774 s unittest | macOS 固定系统别名用例跳过；两条 ResourceWarning 保留 |
| 四 wheel 隔离安装 | **12/12 PASS**，pip check、隔离 imports/CLI/schema 3 通过 | 287 份 Python/Swift 文件与源码、wheel、安装内容逐字一致 |
| Frontend | **74/74 PASS**，TypeScript/Vite build PASS | 13 个测试文件；依赖图未变 |
| Rust | fmt --check PASS | 格式检查，不是原生编译 |
| 版本一致性 | 正对照及 Companion/Suite 两项负对照通过 | 实际 checker；临时副本不影响工作树 |
| Browser Pet 场景 | **8 个 launch blocked，0 页面断言** | 环境复查基于 b961 的同一 Pet TS/测试代码；不能记为当前 native UI PASS |

Core r1 因确认的未准入尾部问题中断，退出 130；r2 保留了版本门禁最小测试副本缺文件的单项失败；补齐夹具后 r3 全部通过。Suite 原 runner 只计测试名同一行的 `ok`，因此原 `passed=121`；一条警告使 `ok` 独占行，`postcheck.json` 结合 123 总数和 1 skip 校正为 122，原文件未覆写。所有失败、跳过、警告和开发证据均可在对应归档查看。

## 未满足的门禁与交付边界

- 当前环境为 Linux x86_64。GTK3/WebKitGTK 开发依赖不可用；Chromium 的 AF_UNIX socket 被环境拒绝。同进程树 Vite 返回 200，但独立 exec 与云端浏览器 loopback 均连接拒绝。没有绕过隔离策略。
- 本轮没有当前候选的原生 Tauri/Swift 构建、Linux GUI、Apple Silicon/Intel Mac 安装和交互验收。新 Swift 分页布局、气泡焦点、多显示器、缩放、减少动态效果及可见动画 ≥24 Hz 都不能标成新 PASS。
- 旧 RC14 Ubuntu arm64 安装/升级/降级、旧 Linux 动画样本与两小时 soak 保持各自原始版本归属，不证明 RC16 schema 3 或当前原生交互。
- Core 通用 archived-canonical 搜索工具、Computer/Adaptive/exact-grant 轮换、运行中单个超长 turn 的块式持久化，以及 Companion 逐任务数据库存储不在这次已完成范围。
- 没有发布原生安装包、Tag 或 GitHub Release。组件 wheel 在隔离环境完成安装 gate，构建哈希与日志在 [runtime/SUMMARY.json](runtime/SUMMARY.json)；这不等于系统原生发布合格。

## 证据使用方式

每组 `MANIFEST.json` 记录归档文件 SHA、成员的原始及公开 SHA、字节数和路径脱敏次数；`evidence.tar.gz` 使用确定性时间戳。归档内 `RAW_MANIFEST.json` 描述未公开原件，公开成员以组清单的 published hash 为准。Engineering 使用自己的逐文件原始/公开/gzip 解压清单，保持原 fixture 字节及有意空白。

私有 API key、Core 配置、SQLite、凭据、运行时 venv 和构建目录均未公开。路径脱敏不改变结果、收据或 fixture 语义。根 [MANIFEST.json](MANIFEST.json) 覆盖所有公开文件并排除自身。
