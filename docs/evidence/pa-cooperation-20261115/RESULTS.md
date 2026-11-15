# PA 协作、来源延续与最后一轮代码检查（2026-11-15）

本轮分支为 `codex/pa-cooperation-20261115`，基线为 [Draft PR #10](https://github.com/www080327-glitch/LocalPilot-OpenSource/pull/10) 的 `92ad9a30b9fda43bc185d96c99e5cb0a8ce8ec02`。受测源码由本目录 `SOURCE_FILES.json` 逐文件绑定；发布时在本段补充受测代码提交和新 PR 引用。旧 PR #1、#9、#10 与全部旧 evidence 保持原样。

开发与执行环境为 **Linux x86_64、Python 3.12.14**。本轮完成代码、协议、真实文件/SQLite/子进程和独立 wheel 安装验证；没有 macOS SDK、真实音轨、Intel Mac 或正式模型/Docker 评测环境。

## 当前最终结果

| 范围 | 结果 | 范围与限制 |
|---|---|---|
| Core 全量 | **1401 PASS / 110 SKIP / 0 FAIL / 0 ERROR，共 1511**，189.008 秒 | 包含真实 PR #1 / PR #9 历史源码兼容检查 |
| Companion 全量 | **627 PASS / 25 SKIP / 0 FAIL / 0 ERROR，共 652**，37.443 秒 | 25 项需要 macOS Swift；音频使用协议夹具 |
| Suite 全量 | **101 PASS / 1 SKIP / 0 FAIL / 0 ERROR，共 102**，39.441 秒 | 1 项为 macOS 系统路径别名；含真实 pip/venv 维护事务 |
| Desktop | **Vitest 68 PASS / 12 文件；TypeScript / Vite PASS** | 真实 React SSR 和前端逻辑，不是原生交互 |
| TypeScript 未使用符号检查 | **PASS** | `--noUnusedLocals --noUnusedParameters` |
| 官方 OpenAI SDK 3.51.0 | **42 PASS**，3.661 秒 | 真实本地 HTTP/SSE 与产品 Runtime |
| 固定 Harbor 0.26.0 | **72 PASS / 4 SKIP，共 76**，24.191 秒 | 4 个真实模型资格测试尚未运行；其余包含真实官方工厂/类型、HTTP、Shell 与 tokenizer 协议进程 |
| 四组件真实 wheel | **PASS：257 个包内 Python 文件 + 3 个脚本资源** | 逐字节对应源码，唯一包归属，许可证与 Swift 资源在包内 |
| 新 venv 安装与入口 | **PASS** | 仓库外 `-I` 导入、全部安装文件、实际文件读写、五个 CLI 和 Channels 版本 |
| 安装后渠道生命周期 | **12 PASS / 0 FAIL / 0 ERROR / 0 SKIP**，8.579 秒 | 全新 venv、真实四组件 wheel、仓库外运行；包含 SIGINT 后重开及启动身份缺陷回归 |
| Playwright | **34 项收集 / 0 项实际运行** | Chromium 在页面启动前被环境的 socket 限制阻止；不是 34 项产品 FAIL，也不是交互 PASS |
| Rust / Swift / 新原生 APP | **NOT_RUN** | 缺 cargo/macOS SDK；需本机 Work |
| 真模型质量、正式对照、真实训练 | **NOT_RUN** | 没有用脚本应答替代实际模型成绩 |

定向测试、SDK、Harbor 与安装补测和全量存在重叠，不能相加为独立测试总数。Core 原始 110 SKIP 分类为：历史 benchmark/账本/TimedBackend 15、原生 macOS 20、官方 SDK 42、独立 Suite/渠道 12、固定 Harbor 环境 17、真实模型资格 4。独立环境补测不会改写主环境原始 SKIP。

最终 Core、Companion、Suite 日志未出现 `ResourceWarning` 或 `RuntimeWarning`。可取得的原始日志、精确命令与失败历史收入归档；未单独落盘的首次 Harbor 夹具输出在下文注明，不以成功日志补作原始失败证据。

## 本轮完成的实现

### 1. 多 Agent 进入公开评测的实际路径

宿主通过显式 `child_registry_factory` 与 JSON 契约为 Worker 构造工具。新建、异步和恢复使用同一路径，父级权限上限、数据策略和动态授权检查保留；工厂自身授权也必须通过。配置摘要只在显式启用时增加，旧默认指纹保持。

Harbor 新模式的父子注册表只含指向同一任务环境的 Shell，共用同一模型、一个推理槽、一个预算账本及 tokenizer。默认 Worker 的内部额度针对多步任务改为 6 步、8 次工具提案、131072 admission units、1024 输出 token，仍受父上限和唯一真实模型总预算约束。

新增协议测试实际让两个子会话分别写入、追加、读取并汇总：6 次 Shell、11 次 HTTP。总请求额度设为 3 时，父子只能合计发送 3 次。模型文本来自受控应答器，不能据此声称完成真实模型任务或获得公开榜单分数。

新 study 冻结调度/预算契约，并对实际父子请求、usage 和工具域进行审计。正常预算耗尽仍是失败；tokenizer/内存条件不成立、usage 不明、取消缺少结算等不取得比较资格。单 Agent 默认及旧 534 队列未改动。

### 2. PA 来源延续、会议与样本

观察的类别、定位、版本和证据身份保留到正式主 Agent 请求。来源变更或撤销后，自动会话改用新 Session，派生结果退出检索；旧任务、真实收据和 UNKNOWN 保留。无法重建原来源关系的旧结果只留在管理历史。

会议自身采集改为不可变片段、增量同步。80 段真实子进程协议夹具最终是 80 条观察、80 个版本；这不是 80 段真实音频验收。终态和进程退出码不一致时明确失败。

GUI 与 Pet 的样本审阅接入实际显示的回答和来源。保存需要人工编辑/确认，并再次核对来源；没有自动把模型答案当训练真值。候选 adapter 的检查与显式 `model_adapter_path` 加载入口已接到固定 MLX-LM 0.31.3 接口，实际 tensor 加载、训练和质量提高仍未验证。

本轮采用人工审阅后的 LoRA。既有 `full` 入口只训练受支持的 Transformer 层，不包含 embedding/head，不能代表全模型所有参数训练；强化学习执行器为 NOT_IMPLEMENTED。

### 3. 桌面与 Core 代码整理

| 文件 | PR #10 基线 | 本轮 | 职责调整 |
|---|---:|---:|---|
| `agent/session.py` | 1564 行 | 1240 行 | 工具执行、资源指纹与收据的九个方法集中到 `session_tools.py` |
| `desktop/src/App.tsx` | 3866 行 | 2737 行 | 任务详情、设置、模型选择与共有展示组件分离；清除不可达旧委派流程 |

九个 Core 方法移动前后 AST 一致，额外修复原脚本审批缺少 `Path` 导入的问题。真实脚本用例覆盖批准后执行一次、脚本变更后原批准失效；原消息、配置、收据和恢复语义保留。

会议控制通过独立 Companion 通道工作，Core 离线不阻断停止入口。轮询或停止收到无快照的 busy/stopping/error/UNKNOWN 时，保留原状态和停止入口；服务返回“正在停止”并不表示 helper 已退出。维护返回展示本次助手错误及原安装收据，Channels 版本由 Suite 实际 metadata 提供。

## 失败历史与修复依据

- 新 child registry 最早 6 项测试中 4 FAIL：受控模型夹具误把宿主 working-state 消息当用户任务，并使用并不存在的 tool `name`；改为实际用户消息及 `tool_call_id` 后 6 项通过。
- 脚本审批新增 2 项先复现真实 `Path` 导入遗漏；补导入后通过，随后工具/持久组 108 项通过。
- 首轮 Core 全量为 1502 项、1399 PASS / 103 SKIP。独立审阅随后发现新自定义工厂漏继承父动态授权；新增 2 项先复现，再修复。最终含工厂、审批、持久化的定向组 110 PASS，最终 Core 全量如上。
- Harbor 首轮新增夹具为 5 PASS / 1 ERROR，原因是 tool 消息关联字段错误。该次只有工具对话输出，没有单独保存原始日志文件，临时目录已被测试清理；不以之后的成功日志代替。之后先完成 75 项，再实证发现默认 Worker 预算只能完成极短任务，补三步 Shell 用例并调整仅新模式的额度；最终 76 项结果如上。原 75 项和最终 76 项日志均保留。
- Companion 初次 90 项聚焦中 1 FAIL / 2 ERROR，均为新增测试的插入位置、无效保留期及真实请求消息选择问题。初次 650 项全量另有 1 FAIL，合成 worker 被 Linux 未知电源状态下的既有策略挡住；仅为该隔离测试明确电源选项，未放宽产品。最终 652 项通过。
- Desktop 先完成 61 PASS。交叉核对发现实际 busy/stopping 回包没有 meeting 快照，旧 hook 会清掉停止条；最小修复和新回归后最终为 68 PASS。此前日志保留。
- 四个 wheel 首次均成功构建；第一次审计脚本把 `.data/data` 中的示例 Python 脚本错误当作顶层包路径。修正审计映射后复核原四个 wheel，257 个包文件及 3 个脚本资源均与源码相同；没有修改产品来迁就审计。
- 安装后渠道最初 6 项为 5 PASS / 1 FAIL：第一次启动、SIGINT 与 stopped 状态均成功，第二次启动在身份记录阶段失败。原 wheel 单例 1 PASS、附诊断 trace 的 10 次 PASS、原始完整组 6 PASS、最后不带 trace 的 3 次 PASS，均未复现，因此当时保持根因未定。补私有诊断后的独立安装 9 项再次出现 1 FAIL / 2 ERROR，证实保存身份前已经失败；这次日志捕获 `ValueError`。
- 随后纯真实子进程探测在第 5 次启动捕获：进程仍存活、`psutil.cmdline()` 暂时为空，同一 PID 后续命令行完全匹配。已将初次空观测延后至既有就绪检查，未增加等待或重启。新增安装用例只注入该系统观测，仍执行真实 CLI、子进程及 HTTP；非空不同、最终仍空或改变、保存失败均拒绝并收割子进程。原诊断夹具改为实际可存活 bridge 子进程，避免使用没有 HTTP 就绪端点的 adapter 假进程。旧 wheel 的同一新增用例确定性 1 FAIL；新 Suite 的安装副本 12 PASS，随后重新构建四组件并装入全新 venv，最终 12 PASS。渠道首次失败、复跑和根因探测均保留；没有进一步断言底层内核为何短暂返回空内容。
- 后续 Core 1508 项出现 1 FAIL / 107 SKIP：既有超时夹具只给 Python 启动、导入、读配置和打印共 100 毫秒，却无条件要求输出已经出现。实际加 0.2 秒启动延迟后，旧时限会在任何输出前终止；改测试时限为 2 秒可保留部分 stdout 和 `TimeoutExpired`。只改夹具时限，产品探测/清理的 30/120 秒与全部原断言不变，定向 6 项通过；最后全量结果见表。
- Chromium 单次启动在 `process_singleton_posix.cc:297` 报 `socket() failed: Operation not permitted`。未启动页面，后续仅收集用例，没有反复尝试或把 SSR 标成原生 PASS。

## 关键执行方式

```sh
LOCALPILOT_PR9_SOURCE=/absolute/pr9-baseline \
LOCALPILOT_LEGACY_SOURCE=/absolute/pr1-legacy \
.venv/bin/python -W default scripts/run_core_qualification.py --report /absolute/core-report.json

.venv/bin/python -W default -m unittest discover -s companion/tests -t . -v
PYTHONPATH=suite .venv/bin/python -W default -m unittest discover -s suite/tests -v

cd desktop
npm test
npm run build
./node_modules/.bin/tsc --noEmit --noUnusedLocals --noUnusedParameters
npm run check:docs
```

四个 wheel 从单独源码快照按已有 `python -m build --wheel --no-isolation` 和 `scripts/build_channels_wheel.py` 流程产生。在另一全新 venv 中安装，仓库外执行 `-I` 检查与 CLI。具体版本/哈希和安装路径见 `component-wheel-audit.json`、`component-installed-proof.json`。

SDK 与固定 Harbor 的独立命令见日志及[公开评测续作](../../development/EVALUATION_CONTINUATION_20261115.md)。本轮未新增产品依赖或测试框架。

## 尚需真实验收

旧 534 项对照仍是 **1 PASS / 3 FAIL / 13 ERROR / 517 无最终结果**，冻结源码 `1c06e97` 未变。本轮没有启动旧队列或新真实模型/Docker study，没有官方 AA 排名或“不弱于主流 Agent”的结论。

新候选的 Rust/Swift、独立 APP 安装与升级退出/重开、真实五档模型任务、Shell/子 Agent 取消、UNKNOWN/Session/SSE 409、会议音轨、原生样本审阅、晚间及系统睡眠唤醒、KV 冷热/重载、Intel 和实际 LoRA 仍按[统一 Work 提示词](../../development/WORK_PA_COOPERATION_20261115.md)执行。历史 benchmark 原件和旧 Release 来源依旧需要真实材料。

本轮未合并、发布 Release、替换日常 APP、提交比赛/落地表单或发送对外消息。自有代码继续 Apache-2.0，实际第三方许可保留。

## 可核对材料

- `RESULTS.json`：最终机器可读计数、原始 SKIP 与证据边界。
- `GITHUB_BASELINE.json`：只读核对的 PR #1/#9/#10 SHA 与 Issue #6/#7/#8 状态。
- `SOURCE_FILES.json`：本轮源码全量 SHA-256 清单。
- `LOG_MANIFEST.json` 与 `verification-logs-redacted.tar.gz`：本轮各阶段日志、原始/脱敏摘要及失败保留。
- `component-wheel-audit.json` / `component-installed-proof.json`：真实制品、归属、源码与独立安装核对。
