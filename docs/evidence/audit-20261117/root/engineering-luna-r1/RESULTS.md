# GPT-6 Luna 单任务工程验收：独立复核

## 结论

**本次预先声明的 protocol、orchestration、semantic 三项判据均通过，已有原始记录支持。** 模型完成一个公开、合成的标准库 Python 项目：两个异步子任务分别实现 CSV parser 和聚合模块，父任务实现 CLI 并完成整体验证。Core 停止后，外部验收在独立目录中使用原始固定测试和交付的四个模块，再次得到 **17 项测试通过、4 个 CLI 场景通过**。这不是依据模型的完成声明评分。

本次记录的运行时长为 **336.939722906 秒，约 336.94 秒**，包含 runner 初始化 Core、模型任务和停止 Core；独立外部验收发生在此后。任务 deadline 为 1,200 秒。该结果只证明本次固定合成工程的执行和验收，不代表通用软件工程能力、真实项目成功率、两小时持续工程工作、AA / ITBench 成绩或最终 RC10 桌面二进制的模型实测。

独立复核没有再次调用模型、运行项目测试或修改生成代码。它读取已归档记录，校验文件哈希、固定验收原件和源码身份，并调用冻结 runner 的真实 `orchestration()` 对原始 task JSON 重算统计；重算结果与 [RESULTS.json](RESULTS.json) 完全相同。

## 运行与验收身份

| 项目 | 已核对的身份 |
| --- | --- |
| Core 源码提交 | `91dd87c6fd4678c103d6383dec1c1385deb38f9a` |
| Core Git tree | `c19b18071de42ed42feb25519671a559f38dec18` |
| 源码目录 | `/workspace/scratch/c0f3ec78c621/validation/audit-20261117/final-source-91dd87c` |
| 运行源码清单 | 110 个文件；manifest SHA-256 `21350877c16f1a9d77e95f9a1e781cf7854478310c3d879bd5e6bd7318e33f7a` |
| 工程 runner SHA-256 | `108f948c1b32fa9de95e48a1a84ede4b4b78a3d3ecfabe1c9977e4b7e21cc0fb` |
| 模型与协议 | 配置为 `gpt-6-luna`、Responses、`medium` reasoning；36 条聚合调用的 `reported_model` 均为 `gpt-6-luna` |
| Task ID | `resp_99758f62efdd4bf9ab1ca750268b06ec` |
| 权限与预算 | Full；standard execution budget；父 steps 100 / tools 200；每子任务请求 steps 20 / tools 40 |

Core 与验收 runner 分别绑定身份：Core 从上述固定 checkout 启动，新增工程 runner 以自己的 SHA 固定，不能因为 Core 的提交号相同，就把新增 runner 也描述成该提交已有的文件。调用前的 [PROTOCOL.json](PROTOCOL.json) 已保存源码、runner、公开提示词、验收原件哈希及计数要求。

此次复核确认：

- 110 个记录的源码文件逐一匹配固定 checkout；3 个 qualification helper 的哈希也匹配。
- 记录的 `source`、`source_after` 与 `PROTOCOL.source` 完全相等，manifest 摘要可独立重算。
- 固定 checkout 的 HEAD 仍为 `91dd87c…`，Git 工作树干净。
- 当前[工程 runner](../../../../../scripts/qualify_openai_engineering.py) 的字节哈希与运行记录一致，未在执行后调整判据。
- [prompt.txt](prompt.txt) 的哈希匹配预声明协议。

这 110 文件清单是所记录 Runtime 范围；额外三个 helper 和 runner 另有独立哈希。它不等于把整个桌面安装包或所有外部依赖都纳入同一份文件清单。

## 实际工程任务

公开规格为 [SPEC.md](final-project/SPEC.md)：解析带时区的 CSV 事件，处理 CSV 引号和空行，将时间归一化为 UTC，以 `Decimal` 表示数值，按类别精确汇总并输出 JSON。CLI 还必须处理文件输出、Unicode、非法输入和文件错误。

交付保持四个包模块。实际修改了三个实现文件，包初始化文件保持原样：

| 模块 | 实施角色 | 最终 SHA-256 |
| --- | --- | --- |
| [parser.py](final-project/logstats/parser.py) | 子任务 `1.1` | `deb84df5eacb352a988febc58c3b2d368a6ba765a9a26b3ee8e00501d1a4e776` |
| [aggregate.py](final-project/logstats/aggregate.py) | 子任务 `1.2` | `b7784e3860d26e25e2494618f9a2d9f9012e71dc3a5be1ff74d9d04b8102d0be` |
| [__main__.py](final-project/logstats/__main__.py) | 父任务 | `979a14d250ea2b3b98832736111e3a2a21ef4bb5016286c799d0fd3661f7f2d5` |
| [__init__.py](final-project/logstats/__init__.py) | 保留初始文件 | `ae8f92d8e600d6dc9ad8d3ac5063b4ee18d5ef365e259d9323608625b76ef7de` |

这些归档文件的哈希同时匹配最终文件清单、外部验收的 delivered 哈希，以及各实现最后一次 `apply_patch` 的结果。生成代码使用实际 CSV、日期、Decimal 与 CLI 逻辑；此次通过不是把模型的答复文本当作项目输出。具体修改保留在 [project.diff](project.diff)。

## 异步分工与父任务验证

| 角色 | 已记录模型调用 | 实际修改范围 | 成功测试回执 | 最终状态 |
| --- | ---: | --- | --- | --- |
| Parser 子任务 `1.1` | 6 | 仅 `logstats/parser.py` | `ParserTests`，9 项，exit 0 | completed、async、collected |
| Aggregate 子任务 `1.2` | 10 | 仅 `logstats/aggregate.py` | `AggregateTests`，3 项，exit 0 | completed、async、collected |
| 父任务 | 包含在下述聚合总数中 | `logstats/__main__.py` | 完整 17 项，exit 0；随后 CLI exit 0 | completed、quiescent |

聚合模型调用总数是 **36**，已经包含两个子任务的 **6 + 10** 次，不能再相加成 52 次。工具回执共 **57** 条：父任务 28 条，两个子任务分别 10 和 19 条；其中 3 条失败、54 条完成，失败过程见后文。

子任务生命周期分别为：

- `1.1`：start `1794851950.1339335`，completed `1794852054.5930588`。
- `1.2`：start `1794851957.5277445`，completed `1794852115.0789258`。

两者 start 到 completed 的交集为 **97.065314293 秒**。这是包括模型等待和工具操作的异步生命周期重叠；它不等于同时占用 CPU 的时间，也不证明底层提供商同时执行了每一个请求。

父任务在两个子任务仍运行时先实现了独立的 CLI，之后完成收集和整体验证。预声明评分要求实际分工、各自修改与测试、收集、重叠和父任务验收，没有要求 CLI patch 一定晚于两个子任务 completed。因此该记录支持已冻结的编排判据，但不能把执行过程写成严格的“子任务全部结束后才开始实现 CLI”。

父任务实际 Shell 回执为：

```sh
python3 -S -m unittest discover -s tests -p test_acceptance.py -v
python3 -S -m logstats fixtures/basic.csv --output result.json
```

完整测试回执为 `Ran 17 tests in 0.218s / OK`。CLI exit 0，stdout、stderr 均为空，符合文件输出模式。`result.json` 与 basic 的固定期望匹配，其实际文件哈希也匹配 [file-manifest.json](file-manifest.json)。

上述统计来自 [engineering-task.json.gz](engineering-task.json.gz) 中的原始工具回执和子任务记录；不是从模型结尾的总结反推。

## 停止后独立可执行验收

[冻结 runner](../../../../../scripts/qualify_openai_engineering.py) 在 `core.stop()` 返回后，才创建独立验收目录，复制四个交付模块，并从 runner 内存中的原始常量恢复测试和 fixtures。它使用 `-S` 与受控子进程环境执行测试，不沿用工作区中可能被修改的测试。

此次复核将原 scratch 中 `acceptance-original` 的 12 个文件逐一与 runner 常量、[acceptance-manifest.json](acceptance-manifest.json) 和协议中的哈希比较，全部一致。工作区仅三个实现模块发生变化，其余九个原始路径保持不变；没有通过修改公开测试或 fixtures 降低本次验收要求。

### 固定单元测试

[external-unittest.json](external-unittest.json) 保存完整 argv、stdout、stderr 和退出码：

- 固定解释器：`/workspace/scratch/2a488f6eabf5/LocalPilot-OpenSource/.venv/bin/python`。
- `17` 项全部通过，无跳过；exit `0`。
- 测试框架报告 `0.164s`；包括子进程启动的外部计时为约 `0.243s`。
- 构成为 Parser 9 项、Aggregate 3 项、CLI 5 项。

覆盖范围包括 CSV 引号 / 空行 / 多行字段、字段和 header 校验、物理行号、UTC 归一化、非法数值与日期、精确汇总和排序、输入不变、Unicode 文件输出、非法输入不截断已有输出及缺失输入文件。

### 四个外部 CLI 场景

| 场景 | 实际退出码 | 实际结果 |
| --- | ---: | --- |
| `basic.csv` | 0 | 3 条记录、2 个组；包含引号 / 逗号类别、时区归一化与小数汇总；JSON 与固定期望相同。 |
| `precision.csv` | 0 | 5 条记录；精确保留 `9007199254740993.10`、零和、Unicode 类别与排序；JSON 与固定期望相同。 |
| `empty.csv` | 0 | `record_count=0`、空 groups，与固定期望相同。 |
| `invalid.csv` | 2 | stdout 为空；stderr 为 `error: row 2: invalid decimal value`；无 traceback。 |

原始记录见 [external-cli.json](external-cli.json)。这些是实际运行交付 CLI 的观测；模型声称“已通过”的文字不参与这四项判断。固定有限测试通过也不意味着规格所有可能输入都已穷尽验证。

## 失败、恢复与结论边界

本轮包含真实失败，不能描述为一次无错误的直线执行：

1. **第一次委派因夹具缺少档位映射而失败。** 父任务用 `backend_preference=cloud`、`tier=STRONG`，没有指定 `backend_id`；这是 schema 合法的请求。该工程夹具注册了 `route:worker`，但没有提供 `cloud_worker_backends` 的 STRONG 映射，解析时得不到对应 backend，返回了不够准确的 `Unregistered hybrid backend_id`。随后请求明确选择 `backend_id=route:worker`、`model=gpt-6-luna`，两个 async 委派成功。显式 `backend_id` 优先于 `tier`，因此后续成功证明已注册路由上的委派恢复，**不证明 STRONG 档位映射配置或档位选择已经通过验收**；也不能把第一次失败归因于模型提交了非法参数或显式的未注册 backend ID。
2. **一次状态查询字段错误。** 父任务向 `child_status` 发送了 `worker_id`，schema 返回 unexpected field；之后通过有效的 `wait_children` 完成收集。
3. **聚合子任务发生真实实现错误并自行修复。** 子任务改写精确累加 helper 后，`summarize()` 一度仍调用已删除的 `_as_cents`。首次三项 AggregateTests 中两项抛出 `NameError`，exit 1。子任务根据错误再次 patch，更新调用、组内存储和格式化，再运行相同三项得到全部通过。之后父任务 17 项与外部 17 项也通过。父任务没有代替该子任务修改 aggregate。

这些失败及后续 patch 都保留在原始 task 归档，未删除失败回执，也未在运行中修改固定测试或评分协议。

模型最终自述称指定解释器不在其工作区，并说明改用 `python3 -S`。回执能证明父任务确实用了 `python3` 并通过；外部验收确实用了固定 `.venv/bin/python` 并通过。本复核不把模型关于解释器不可用的解释当作宿主文件不存在的独立证据。

Core 自身的最终 `verification_summary` 仍为 `verification_status=not_run`、`engineering_status=unverified`、`task_outcome=unverified`；文件操作汇总也是 `NOT_RUN`。**本文件的 semantic / engineering PASS 来自停止后的外部工程验收，不回写或升级 Core 自身的状态字段。** Runtime 记录确认任务 completed、quiescent，无 unfinished workers、pending approval 或 unknown receipts。

`owned_core_stopped=true` 在 [RESULTS.json](RESULTS.json) 中已记录；对应固定 helper 的 `stop()` 会 terminate 并 wait，超时则 kill 再 wait，之后 runner 才执行外部验收。此处只评价这次 runner 自有 Core 的正常停止路径，不声称执行过机器范围的进程清理或系统安装。

## 归档完整性与复核范围

[ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) 列出的 **18 个归档文件**全部通过字节数和 SHA-256 核对。有 original 字段的 13 项同时核对原始字节；其中压缩 task 解压后的长度和哈希也匹配清单记录。四个交付模块及 SPEC 另以归档哈希核对。

| 关键文件 | SHA-256 |
| --- | --- |
| `ARTIFACT_MANIFEST.json` | `8625cdbf81c4acb17911ad69ab2ec5e5707f825f2854ba78e802db3c61cdae7d` |
| `RESULTS.json` | `a9bf147721edeb211f65058883e9145b2bf22715522b7b927caf3961b468e6d1` |
| `engineering-task.json.gz` | `ff93f1e7e3b835dcbd60ce3c5f0290c09419cb93bd9487ddab33a384aa01f2a9` |
| `external-unittest.json` | `2c341d3103de0c37f124399ba749a856c483efdbe654a10243bbc13215016e7b` |
| `external-cli.json` | `7634481993d0dc01c7fb0830e5baafc16158f36ff4b060a847a12f6b20843b2f` |

本 Markdown 是验收完成后新增的独立说明，不在原 18 项 artifact 清单中；原 JSON、压缩 task、生成代码、Core 和 runner 均未修改。复核没有读取 `private-core`、API key、活跃 ITBench 任务、答案或 GT，也没有重跑业务测试。此次结果应与先前源码快照的模型试验、长时间运行验收和公开评估分别报告。
