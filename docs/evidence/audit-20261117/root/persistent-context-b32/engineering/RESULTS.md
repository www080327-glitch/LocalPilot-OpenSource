# Core b32 工程 R7 — 外部工程验收 PASS

**Protocol、Orchestration、Semantic、Engineering 四项固定验收均 PASS，原运行器退出码 0。** 两个真实异步云端子 Agent 分别实现 CSV 解析和精确聚合；父 Agent 集成 CLI，运行测试并生成结果。服务停止后，原运行器在新目录中使用原始不可变验收材料执行 **17 项测试和 4 个 CLI 场景，全部通过**。

这是同一固定任务在新 b32 源码上的一次版本回归。运行器、提示词、12 个原始夹具、预算和判据与 [b31 R6](../../engineering-luna-r6-b31-native/RESULTS.md) 完全一致；没有按结果重新运行或降低验收标准。它验证一个合成标准库项目，不能推导 AA 排名、一般任务成功率、小时级稳定性或原生桌面交互表现。

## 外部验收与产品收据

| 层面 | 实际记录 |
| --- | --- |
| 外部工程判据 | Protocol / Orchestration / Semantic / Engineering 全部 PASS |
| 任务生命周期 | `status=completed`、`quiescent=true`、`runtime_status=completed` |
| 产品交付字段 | `deliverable_status=present` |
| 产品内建验证 | `verification_status=not_run`、`engineering_status=unverified` |
| 产品任务判定 | `task_outcome=unverified`、`task_succeeded=false` |
| Completion | `execution=settled`、`delivery=delivered`，一次交付尝试 |
| 未完成义务 | 无待批准动作、排队调用、未完成目标/worker/接管、UNKNOWN 收据或 mutation intent |

外部 17 项测试与 4 个 CLI 场景有自己的运行收据，**不会覆盖产品内建未验证状态**。模型完成文本不参与外部通过判定。[原始任务压缩记录](engineering-task.json.gz)和[后验核对](POSTRUN_CHECKS.json)保留上述字段。

## 冻结源码与执行身份

| 项目 | 值 |
| --- | --- |
| 实际执行的本地 commit | `2f1d678be4e24b787f443f123391f273a177c1ef` |
| 完整 Git tree | `d2ef57414647fb2f71ad53447790242ad2adf02b` |
| 已发布的源码 commit | [`06f59e913484cf14d92c9811f2137e4e777db163`](https://github.com/www080327-glitch/LocalPilot-OpenSource/commit/06f59e913484cf14d92c9811f2137e4e777db163) |
| 本地与远端对应关系 | 已读取 fetch 后的 Git object，完整 tree 完全一致；原运行收据的本地 source 字段未改写 |
| Runtime 源码清单 SHA-256 | `b6a4f2cb70ec2b44f9a15b269a3da1cb045cca107ef13971abe47f19e580139f` |
| 原运行器 SHA-256 | `108f948c1b32fa9de95e48a1a84ede4b4b78a3d3ecfabe1c9977e4b7e21cc0fb` |
| 原提示词 SHA-256 | `9c2e3300ef2bff76b38b2c1c645f1bb9d1e112cff853a40779f4aeb8f69e693a` |
| Core 包 / 实际服务版本 | `5.0.0b32` / `5.0.0b32`，服务日志记录 ready |
| 模型 / 协议 / reasoning | 提供方实际返回 `gpt-6-luna` / Responses / medium |
| 主机 / Python | Linux x86_64，Python 3.12.14；指定任务 Python 环境 |
| UTC 起止 | 2026-11-17 04:18:16.132203 → 04:21:35.061371 |
| 模型与 Core / 外层耗时 | 198.181816 / 198.923557 秒 |
| 停止和完整性 | 自有 Core 已停止；源文件前后相同；执行前后 Git 工作树干净 |

运行入口是现有执行工具中的原仓库脚本，不是 macOS Native Terminal。唯一外层环境调整是把固定 Python 目录前置到继承的 PATH；网络、TLS 与其他继承环境未改动。[执行开始](EXECUTION_START.json)、[执行结束](EXECUTION_END.json)、[协议](PROTOCOL.json)、[原运行器](runner.py)和[服务日志](core.log)可查。

固定预算为 Full + standard，1,200 秒任务期限；父 Agent 100 steps / 200 tools；请求的每个子 Agent 20 steps / 40 tools，Host 上限 30 / 60；最多两个子 Agent，一秒轮询。除 source 身份外，完整 `PROTOCOL.json` 与 R6 逐字段相同。

## 实际工程过程

| 执行者 | 模型调用 / 工具收据 | 修改范围 | 成功的必需测试 | 终态 |
| --- | --- | --- | --- | --- |
| 子 Agent `1.1` | 7 / 15 | 仅 `logstats/parser.py` | 9 项 ParserTests，exit 0 | completed、async、collected |
| 子 Agent `1.2` | 5 / 9 | 仅 `logstats/aggregate.py` | 3 项 AggregateTests，exit 0 | completed、async、collected |
| 父 Agent | 包含于下述整体计数 | 集成 `logstats/__main__.py` | 全部 17 项测试及指定 CLI 实际运行 | completed、quiescent |

两个子 Agent 的 start→completed 生命周期重叠 **91.584536 秒**，该区间包括模型和工具等待，不能作为同时占用 CPU 的证明。父 Agent 收集子任务、运行 CLI 并实际生成 `result.json`。随后独立验收使用四个交付模块和运行器内存中的原始 SPEC/tests/fixtures：17 项测试 exit 0；basic、precision、empty 场景 exit 0；invalid 场景按约定 exit 2，无 traceback。[外部 unittest](external-unittest.json)、[四个 CLI 收据](external-cli.json)、[实际结果](final-project/result.json)均保留。

整体用量为 **27 次模型调用、53 条工具收据、899,356 输入 token、9,969 输出 token**；其中缓存输入 736,922 token。整体计数已经包括两个子 Agent，不能再次累加。失败模型请求 0，UNKNOWN-effect 收据 0；实际货币成本未知，没有查询余额。27 次调用均保存提供方诊断，非空 `input_transformations` 为 0；这不证明内部推理复用。

交付使用真实 CSV 解析、日期/时区校验、Decimal 与整数系数聚合、参数解析和 JSON CLI；未使用夹具答案查找表。四个交付模块在工作区、最终副本及独立验收目录的 SHA 完全一致；仅 parser、aggregate、CLI 三个原模块发生变化，原始 SPEC/tests/fixtures 保持不变。[文件清单](file-manifest.json)、[变更](project.diff)、[交付代码](final-project/logstats/parser.py)可查。

## 保留的两条失败收据

- 子 Agent `1.1` 查询不存在的 `tests/fixtures` 目录，产生 `FileNotFoundError`；该只读失败仍为 `status=failed`、`side_effect_status=not_completed`。随后实际读取项目已有夹具并通过必需测试。
- 父 Agent 使用自拟 `deliver-logstats` ID 完成目标，产生 `KeyError: Unknown goal id`；随后使用创建操作实际返回的 UUID 成功完成同一目标。失败收据与后续成功收据均保留。

这些中间失败没有被改写成成功。冻结验收函数依据实际最终生命周期、变更、必需成功测试和独立语义结果判定；用保存的任务对原 `orchestration()` 重新计算，结果与运行器记录完全相同。后验的 16 项字节/收据核对没有再次调用模型或执行测试，也没有改变 R7 原结果。

## 公开证据边界

[ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json)列出每份公开载荷的原始大小/哈希和发布大小/哈希。只替换固定本机绝对路径前缀；原始任务采用确定性 gzip（mtime=0）。路径变换导致公开提示词、部分 JSON 与原始哈希不同，变换前后均有记录；运行器和交付模块内容保留。

白名单包含运行收据、提示词、原运行器、原始夹具、最终项目和后验核对。Core 私有配置、认证数据、SQLite、实时工作目录及依赖目录不进入公开归档。执行所用 API 密钥未读取到报告或日志中。后续发布证据文档的 commit 由上级记录映射，不替换本次实际执行的 source commit/tree。
