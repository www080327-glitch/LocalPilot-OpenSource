# 子 Agent 默认准入预算与旧 Session 兼容修复

日期：2026-11-16。当前修复树为 **Core 5.0.0b25、Suite 0.2.0b30**；集成基线 `d846fef` 不等于受测源码身份，具体文件见 [SOURCE_SHA256.json](SOURCE_SHA256.json)。原 Qwen 运行目录保持冻结，原模型失败没有改标。

## 发现及确定复现

规定合法参数的真实 Qwen 诊断中，child `1.1` 已创建，却在任何模型尝试和工具提案前进入 `FinalizingStarted(reason=token_reserve)`。只读 SQLite 摘录见 [OBSERVED_FAILURE.json](OBSERVED_FAILURE.json)：

| 字段 | 原始结果 |
| --- | ---: |
| 父累计准入上限 | 100000 |
| 子累计准入上限 | 32768 |
| 子输出上限 | 512 |
| 最终答复预留 | 20924 |
| 进入 finalizing 时模型尝试 / 已收费单位 | 0 / 0 |
| 首个请求阶段 | finalizing，工具 schema 为不可用 |
| 实际首请求 UTF-8 字节 / 最终工具收据 | 10293 / 0 |
| 模型终止原因 | length |

这些准入单位是保守字节计量，不是提供方实测 token 或费用。32768 减去 20924 预留只余 11844；512 输出的既有严格字节保护还占 8192，给探索输入留下 3652。现有系统提示、模型交接和工具合同已不能容纳在这个旧默认内。模型尚未获得一次可调用工具的请求，因此此项失败不能全部归因于模型能力。

新增回归直接运行实际 AgentSession、V5、桌面 workspace 权限、真实文件工具和 SQLite；只有模型回复是确定性夹具，没有复制预算公式或绕过 Gateway。修复前目标用例 **FAIL：预期 1 条成功读收据，实际 0 条**，见 `baseline-r1.log.gz`。

## 最小修复

1. 新 Session 的默认 `max_worker_token_units` 从 32768 改为 **131072**；CLI 从同一产品默认取值。
2. 原准入 `min(显式子预算, 宿主子预算, 父剩余预算)`、最终答复预留、步骤数、输出上限、父子累计计账和 UNKNOWN 用量处理均未改。显式 32768 仍可在首次请求进入 finalizing，不会被暗中增额。
3. 当前 qualifier 使用产品默认父上限 **262144**、子上限 **131072**，记录 `resolved-runtime-budgets.json`。仍为 512 输出、父 6 步、子 3 步；这是新协议配置，旧 100000/32768 运行和脚本哈希原样保留。
4. 部署路由只有**没有显式写入子预算**时才有旧缺省兼容资格。旧快照必须为 32768，反投影这个单一字段后仍须完整配置哈希匹配；若同时存在已声明的路径/Skill/async 迁移，则使用原迁移器继续完成原有完整哈希验证。失败或异常会恢复候选 runtime 的预算。
5. 成功恢复的旧 Session 和历史 child 合同继续使用 **32768**；新 Session 使用 **131072**。恢复后换到同样未显式声明预算的模型路由也延续旧值。显式增加预算、其他预算字段或模型身份变化仍按原合同拒绝；未修改历史收据或重放 UNKNOWN。

代码位置：`agent/session_types.py`、`agent/__main__.py`、`localpilot_service/deployment.py`、`restore_migration.py`、`session_migration.py`、`localpilot_api/service.py`、`session_history.py`、`scripts/qualify_linux_model.py`。没有改动 Session 的预算计账循环、最终答复保护或子工具权限。

## 验证结果与首次错误

| 运行 | 结果 | 解释 |
| --- | --- | --- |
| 默认子任务 baseline-r1 | **1 FAIL，预期复现** | 旧默认没有成功读收据，断言未放宽 |
| current-r1 | **4 PASS** | 新默认实际读取；显式宿主/请求小预算保留；父剩余预算裁剪 |
| upgrade-r1 | **1 PASS** | 真实旧源码进程创建 SQLite，当前 build 恢复 UNKNOWN 不重放 |
| current-r2 / current-r3 | **各 5 PASS** | 逐步补历史模型子合同、实际换模及明确预算更改拒绝 |
| combined-baseline-r1 | **1 ERROR，预期复现** | 初版兼容器与已有显式路径迁移同时发生时，被完整配置校验拒绝 |
| current-r4 | **5 PASS，0 SKIP/FAIL/ERROR** | 最终组合修复；旧 SQLite 复制到新私有根后，路径和预算兼容均通过 |
| targeted-r1 | **138 PASS** | 组合缺口被发现前的相关回归，结果保留 |
| targeted-r2 | **138 PASS，0 SKIP/FAIL/ERROR，14.233 秒** | 最终 worker 输出/tier、子工具、持久恢复、async/path/历史 child、换模与 Hybrid 回归 |

138 项已包含新增 5 项，不能把它们重复相加。脚本模型的通过证明执行与恢复逻辑，**不证明 Qwen 自主规划、真实多模型协作或公开榜单能力**。

升级用例实际启动原冻结 checkout 的 Python 进程，经正常 `deployment.build()` 和真实 HTTP 模型夹具生成数据库：一次真实文件写入后主动丢失收据，形成 UNKNOWN；另一个 Session 真正分派 child 后调用模型切换 API，形成历史 child 路由。新 build 连续重开、移到新的私有数据目录、重新换模，都保留旧预算、历史和收据。相同幂等请求返回原任务，没有新增模型请求或文件写入；新建 Session 取得新默认。明确改为 131072、改 worker 步数或改模型身份均被拒绝；显式固定原 32768 正常恢复。

旧数据库、夹具记录及实际子进程命令只保存在本机 `validation/polish-20261116/child-budget/legacy-fixture-r1…r5`。没有把 SQLite 放进 Git；哈希、源文件身份和行数见 [LEGACY_FIXTURES.json](LEGACY_FIXTURES.json)。原始日志没有删除；公开副本只替换工作区前缀，见 [LOG_MANIFEST.json](LOG_MANIFEST.json)。

## 可复跑

[COMMANDS.json](COMMANDS.json)记录每轮完整命令。最终新增回归：

```sh
LOCALPILOT_WORKER_BUDGET_LEGACY_SOURCE=/absolute/path/to/pinned-old-checkout \
  python -m unittest tests.test_worker_admission_budget -v
```

旧源码路径必须确实是旧 32768 默认的 checkout；测试在独立进程中使用它的 AgentSession/build，不用当前实现伪造旧配置。普通全量没有指定该路径时，真实旧进程升级用例会明确 SKIP，不冒充已完成设备验证。

本轮没有进行新的付费推理、Mac/Intel 原生验收或正式 Harbor 研究。后续真实 Qwen 修复候选应以新协议、源码清单和结果单独记录，继续保留原失败。
