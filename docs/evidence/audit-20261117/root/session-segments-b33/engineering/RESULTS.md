# Core b33 工程 R8 — 工程资格验收 FAIL

**原协议结果为 Protocol PASS、Orchestration FAIL、Semantic PASS，整体 Engineering FAIL；原运行器退出码 1。** 本轮只运行一次，未改提示词、运行器、夹具、预算或通过标准。原始收据、成功结果和所有中间失败均保留。

代码交付在自有 Core 停止后通过了原始独立验收：**17 项测试与 4 个 CLI 场景全部通过**。但 Parser 子 Agent 没有完成自己必须执行的测试，父 Agent 后来补跑的测试不能替代这个冻结条件。[固定协议](PROTOCOL.json)、[原运行结果](RESULTS.json)、[失败分析](FAILURE_ANALYSIS.json)、[完整任务记录](engineering-task.json.gz)可查。

## 哪一项失败

| 执行者 | 实际请求 / 工具收据 | 修改范围 | 必需的自主测试 | 终态 |
| --- | --- | --- | --- | --- |
| 子 Agent `1.1` | 7 / 12 | 仅 `logstats/parser.py` | `.venv/bin/python` 不存在，Shell exit 127；没有成功的 ParserTests 收据 | completed、async、collected |
| 子 Agent `1.2` | 7 / 17 | 仅 `logstats/aggregate.py` | 相同错误之后改用 `python3`，自己通过 3 项 AggregateTests | completed、async、collected |
| 父 Agent | 17 / 39 | 集成 CLI | 17 项全量测试、指定 CLI、后续 9 项 ParserTests 均通过 | completed、quiescent |

原提示词给出了有效的固定 Python 绝对路径。父 Agent 在派活时改成工作区不存在的 `.venv/bin/python`。两个子 Agent 都收到并执行了这个错误路径。Aggregate 子 Agent自行纠正；Parser 子 Agent结束时明确说明测试没有运行。父 Agent收集后确实补跑了 9 项 ParserTests，但固定 `orchestration()` 要求成功测试收据属于对应子 Agent。因此缺口是本次模型派活和失败恢复未满足工程协议；实际 Shell 正确返回错误，另一子 Agent和父 Agent的 `python3` 均正常运行，当前证据不支持把它归因为 Runtime 或解释器不可用。

两个子任务均已成功被收集，文件范围符合分工，生命周期重叠 **122.728484 秒**。重叠包括模型与工具等待，不表示同时占用 CPU。对保存的任务重新执行原来的纯收据 `orchestration()` 计算，结果逐字段一致，仍为 FAIL。

## 外部语义结果与产品字段

| 层面 | 实际结果 |
| --- | --- |
| 原始独立测试 | 17 / 17，通过 |
| 原始独立 CLI | basic、precision、empty、invalid 全部符合约定；invalid 按约定 exit 2 |
| 真实 CLI `result.json` | 与预期 JSON 一致 |
| 产品生命周期 | `status=completed`、`quiescent=true` |
| 产品验证字段 | `verification_status=not_run`、`engineering_status=unverified` |
| 产品任务判定 | `task_outcome=unverified`、`task_succeeded=false` |
| Completion | `execution=settled`、`delivery=delivered` |

外部语义 PASS 不会覆盖整体工程 FAIL，也不会把产品内建的未验证字段改成通过。验收是在停止自有 Core 后，把四个交付模块复制到新目录，再使用运行器内存中的原始测试和夹具执行；模型修改测试不能改变这一验收。[外部 unittest](external-unittest.json)、[四个 CLI](external-cli.json)、[最终代码和结果](final-project/)、[文件变更](project.diff)完整保留。

## 源码、协议与用量

| 项目 | 值 |
| --- | --- |
| 实际执行源码 commit | `b6f95da47f706581a780d6874382be53d99b33c4` |
| 完整 Git tree | `36d464811bbfd9538274d88bd2c13fbcf80374be` |
| Core 实际服务版本 | `5.0.0b33`，服务日志记录 ready |
| Runtime 源码清单 | 111 个文件，SHA-256 `eb7719c62117b2ff13f30b550e0b3a7139cee342be1b70053fccbdd4c3d8bc81` |
| 原运行器 SHA-256 | `108f948c1b32fa9de95e48a1a84ede4b4b78a3d3ecfabe1c9977e4b7e21cc0fb` |
| 原提示词 SHA-256 | `9c2e3300ef2bff76b38b2c1c645f1bb9d1e112cff853a40779f4aeb8f69e693a` |
| 模型 / 协议 / reasoning | `gpt-6-luna` / Responses / medium |
| 模型与 Core 耗时 | 282.688569 秒 |
| 外层耗时 | 283.355035 秒 |
| 执行次数与状态 | 一次；执行前后 HEAD、tree、源码清单一致，工作树均干净 |
| 停止证据 | 原 runner 完成 Core.stop；停止后只读打开 owner 文件可重新取得并释放独占锁 |

除 source 身份外，整个 PROTOCOL 与 R7 逐字段相同；原运行器、提示词、12 个原始夹具与预算均未变化。唯一外层环境调整是把固定 Python 环境的 `bin` 前置到继承的 PATH。运行器、网络、TLS 和凭据机制未改动。未来证据提交不会替换本次实际执行的源码身份。

整体用量已含两个子 Agent：**31 次模型调用、68 条工具收据、1,261,082 输入 token、15,487 输出 token**；其中缓存输入 1,060,881 token。不能把子 Agent计数再加一次。实际货币成本未知，没有查询余额。31 次调用均保留提供方 response ID，`input_transformations` 都是空数组；这不证明提供方内部推理复用。

## 保留的四条失败工具收据

- 父 Agent首次 delegate 缺少 `backend_preference`，入口校验拒绝，未派发子任务。
- 父 Agent下一次 delegate 使用未注册的 `backend_id`，同样失败；随后按实际路由成功启动两个子 Agent。
- Parser 子 Agent运行不存在的 `.venv/bin/python`，Shell exit 127，没有自主补跑成功测试。
- Aggregate 子 Agent遇到同一 exit 127，随后改用 `python3` 并通过自身 3 项测试。

失败收据没有被删除、重标成功或用父测试替换；原始父/子文本与全部工具结果仍在完整任务记录中。后验核对只比较保存的收据、源码和制品字节，**没有新增模型调用，也没有再运行测试**。

## 公开证据边界

[ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json)逐个记录原始与公开内容的大小和 SHA-256。只替换固定本机绝对路径前缀，完整任务使用确定性 gzip（mtime=0）；原运行器、夹具与交付代码的其余字节不变。Core 私有配置、认证数据、SQLite、实时工作目录和依赖目录被排除。API 密钥本身未写入公开内容，已检查所有明文与 gzip 解压载荷。

首个后验打包检查错误地要求 `changed_paths` 的列表顺序固定，因此停止；实际三项路径集合完全正确。该次检查和校正说明保留在 [postrun-r1](postrun-r1/PACKAGING_NOTES.json)，最终核对仅修正了排序比较，没有改变本次模型运行结果。

这是一次有限的合成工程任务。它揭示了一个明确的子任务执行缺口，同时保留实际语义交付成功的证据；不能据此计算通用 Agent 成功率、AA 排名、小时级稳定性或原生桌面表现。[后验核对](POSTRUN_CHECKS.json)的 review PASS 只代表证据与结论一致，不会把本次资格结果改为 PASS。
