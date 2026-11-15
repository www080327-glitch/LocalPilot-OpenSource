# PA 补齐、重构与最终云端验证（2026-11-15）

**受测代码提交：`907dbce1b1aed1752badd74cab8604839057b119`。** 新交付为 [Draft PR #10](https://github.com/www080327-glitch/LocalPilot-OpenSource/pull/10)，此后仅追加本段推送引用，未改变受测运行代码。 本记录对应分支 `codex/pa-completion-20261115`，基线为 Draft PR #9 的 `0a7fdff36f45a471130293b508b5d008f40cecf9`。PR #1 `94e0e6ff2c8da974d20530d7a0faa50844d052f4`、PR #9 与原生受测 APP `d2b2fae` 的记录保持原样。本轮没有合并、Release、日常 APP 替换或对外表单提交。

本环境为 **Linux x86_64 / Python 3.12.14**。代码、真实协议、文件、SQLite、子进程和打包检查已经完成；macOS 新 APP、Swift/TCC、真实音轨、Intel 和实际模型质量仍须独立验收。

## 最终结果

| 范围 | 最终结果 | 证据边界 |
|---|---|---|
| Core 全量 | **1388 PASS / 97 SKIP / 0 FAIL / 0 ERROR，共 1485**，205.298 s | 启用真实 PR #1 / PR #9 旧源码兼容检查；含 HTTP、TLS、SQLite、真实工具与子进程 |
| Companion 全量 | **605 PASS / 25 SKIP / 0 FAIL / 0 ERROR，共 630**，36.310 s | 25 SKIP 都需要 macOS Swift；会议测试是实际子进程的合成协议，不是音频 |
| Suite 全量 | **101 PASS / 1 SKIP / 0 FAIL / 0 ERROR，共 102**，46.508 s | 1 SKIP 为 macOS 固定系统路径别名；含 12 个实际 pip/venv 升级事务 |
| Desktop TypeScript / Vite | **PASS** | 编译与生产前端构建 |
| Desktop Vitest | **54 PASS** | 新会话恢复、来源比例与既有界面状态 |
| 官方 OpenAI SDK 3.51.0 | **42 PASS**，4.066 s | 两个 SDK 契约模块，真实本地 HTTP/SSE；不是云模型调用 |
| 固定 Harbor 0.26.0 契约 | **62 PASS / 4 SKIP，共 66**，18.741 s | 官方 schema/BaseAgent/Terminus2 与产品 transport；4 项需要真实模型 |
| 全新 wheel 环境的渠道生命周期 | **6 PASS**，4.852 s | 仓库外仅复制测试；真实 Core/渠道进程、SQLite、SIGTERM/SIGINT、幂等重开与卸载保留数据 |
| APP 目录交换 | **11 PASS** | codesign/LaunchServices 为受控边界；不能当作 Mac 签名成功 |
| 目标架构依赖锁 | **3 PASS** | 实际 ZIP/metadata/hash 夹具；不声称已获得 Intel 依赖 |
| 四组件实际 wheel | **PASS：255 个唯一 Python 文件** | 源码逐字节一致、归属唯一、许可证和 Swift 资源在包内 |
| 四组件独立安装 | **PASS** | 新 venv、实际 pip、`-I` 导入、255 个安装文件一致、真实文件工具、5 个 CLI 入口和 Suite 版本 |
| 文档、diff、Python/Shell 语法 | **PASS** | 本轮链接和旧 evidence 字节保留 |
| Rust / Swift / 新原生 APP | **NOT_RUN** | 本环境无 cargo 和 macOS SDK；保留为 Work 必跑项 |
| 新候选 Playwright | **NOT_RUN / 环境阻塞** | 本会话较早两次 Chromium 启动失败，25 项失败日志保留；不能冒充已执行的新原生或浏览器交互 |
| 真实会议 / 晚间及睡眠唤醒 / Intel | **NOT_RUN** | 没有相应 Mac、授权来源或设备 |
| 本轮真实模型质量、LoRA、完整公开对照 | **NOT_RUN** | 未下载模型、训练或调用付费 API；不报排名或能力提升 |

**不要相加当作独立测试总数。** SDK、Harbor、安装环境补测覆盖了 Core 中因环境缺少而跳过的用例；定向回归也与全量重叠。Core 的 97 SKIP 原样记录在 [RESULTS.json](RESULTS.json)：历史 benchmark/账本/TimedBackend 15、原生 macOS 20、官方 SDK 42、独立 Suite/渠道安装 6、Harbor 环境 10、真实模型资格 4。其中 SDK 42、渠道 6、Harbor 环境契约已在相应独立环境补跑，主环境的原始 SKIP 计数不改写。

旧 `test_scope_escalation.py` 把另一个 TestCase 类暴露为模块级 `Base`，导致 13 个 AgentService 测试被重复收集。本轮改为模块引用，**没有删除测试方法或断言**。因此全量从同阶段 1498 个收集项变为 1485 个唯一项；不能把这次减少解释成删掉难测项目。

## 关键实现和实际验证

### 多模型、子 Agent 与会话恢复

多个已注册本地/云端模型共用原 AgentSession 与调度器，保留五档策略；新路由可 async，旧同步 route 不必改指纹。新建与恢复 Worker 共用工厂，继承已审阅的 Skills/工具与权限上限。来源占比按实际分派调用与 usage 计算，缺 usage 时不伪造 token 或费用。

完成 child 后，主模型可以在兼容的空闲边界切换；历史 child 保留原后端、配置、消息、收据和已完成调用。换权限、同步/异步及声明的私有路径迁移组合均覆盖 SQLite 重启，要求完整配置指纹精确匹配，UNKNOWN 不重放。删除历史模型 route 或改变历史工具契约仍明确拒绝。

测试使用真实 HTTP/TLS 服务、两个模型端点的脚本响应、实际文件、SQLite 与子线程/子进程；它证明调用和恢复契约，不证明真实模型任务质量。另从精确旧 PR #9 checkout 比较五档配置在 Service/Desktop 下的完整指纹，并从真正 PR #1 代码创建旧 Skill 库进行迁移。

### Companion 与会议

来源连接、持续同步、停用、撤销和覆盖报告已接 CLI、认证命令与 GUI。Codex 只读取用户明确选择的可见消息；模型旧回答保持未核验报告身份。会议转录有来源、轨道和时间，未经授权的来源不参与检索。

新增 Swift helper 和 Python 生命周期控制，支持显式 mic/system/both、本地 Speech、最终片段、停止与失败回执，UI 关闭设置后仍保留停止入口。停止不会等待模型请求返回。人工审阅样本按来源连通组切分，固定 mlx-lm 0.31.3 的计划/显式执行接口已实现；没有自动训练、融合或替换产品模型。

### 维护与包装

GUI 与 Core、Companion、Suite、Channels 统一到可审阅计划和回执；组件安装成功但新进程导入失败仍回滚，Channels 代码目录也纳入。历史 APP 计划核对 Test/Daily 身份；helper 在 GUI 已退出时的失败同样可见。

新 Core 不再与 Channels 重复拥有 Python 包、console script 或渠道资产；遇旧 Core 重复归属时要求准确的 Channels 材料并最后恢复它。12 个事务测试使用真实临时 venv、pip、wheel 和文件内容；另外四个完整真实新 wheel 在新环境安装、检查并执行渠道生命周期。

自有源码保持 Apache-2.0，Core/Channels 实际包含的 MIT 适配继续保留署名，分发元数据如实列出两者。Companion/Suite 独立 wheel 现在携带完整 Apache 许可证。Linux 安装环境的 psutil/Pillow/pypdf/watchdog 等版本单独记录，不替代 Mac 的 39-wheel 资源资格或受控 watchdog 构建来源。

### 重构范围

| 主干 | 基线行数 | 当前行数 | 责任分离 |
|---|---:|---:|---|
| `agent/session.py` | 2769 | 1564 | 模型请求、Computer、Worker、公开类型；统一 child 构造 |
| `companion/runtime/service.py` | 1706 | 542 | 观察、对话、任务、命令采用组合组件 |
| `desktop/src/App.tsx` | 4245 | 3866 | 连接、任务/SSE、Session 恢复、会议生命周期 hooks；维护与配置组件 |

旧公开入口保留，复用原 Runtime、Tool Gateway、SQLite、维护机制与测试工具。行数只是拆分位置的说明，不能当作正确性或维护性分数。

## 真实失败历史

本轮最终结果不是首次执行全部通过。归档中保留了全部已有工作区日志，包含更早源码阶段的尝试；**只有上表明确的最终日志被用于当前候选结论**。

- 第一轮集成 Core 为 1464 项，1 FAIL、95 SKIP：旧测试要求的 legacy 合作路由错误文案发生变化。恢复旧兼容文案后相关契约通过。
- 后续全量为 1498 项，1 ERROR、97 SKIP：并发修改测试在创建 Session 前收集了空的 factory 列表，双 barrier 从未安装。输家可能被正常的 approval-expired 检查挡住，而不是走测试预期的锁内 conflict 结构。单独第 2 次即复现。只修夹具时序并断言有两个 Session，保留所有文件冲突、重读和重新批准断言；随后单例连续 100 次、整文件 25 项及最终全量通过。
- child 迁移早期出现与新功能不一致的旧预期，以及夹具 worker 预算过小；修改实际夹具预算后以真实文件成果验证。async 迁移测试曾使用不存在的查询方法和错误的原调用计数，失败日志保留。
- 来源测试最早有 2 个夹具错误；会议控制器首轮真实暴露 helper 已退出时的 `BrokenPipeError`，修复拥有进程的 stdin 关闭后通过。保留全部失败。
- 官方 Harbor 独立环境曾缺 psutil；LiteLLM 导入的在线价格表路径在本环境缺 socksio。补齐前者并使用官方本地价格表开关后通过，没有修改产品依赖或添加推理重试。
- 本轮一次 SDK 命令使用了不存在的模块名，记录为 import ERROR；正确两个模块最终 42 PASS。
- Companion 首次 wheel 构建提示 `shared_ax` 缺 packages 声明。修改 pyproject 源头并重建后警告消失，首次日志及产物仍留在工作区。
- 历史 Chromium 启动限制及此前源码阶段的失败没有覆盖或删除；它们不计作新版本原生验证。最终 Core、Companion 以 `-W default` 执行，日志没有 ResourceWarning 或 RuntimeWarning。

## 关键命令

路径变量分别指两个真实旧 checkout，不是重新实现的兼容夹具。

```sh
LOCALPILOT_PR9_SOURCE=/absolute/pr9-baseline \
LOCALPILOT_LEGACY_SOURCE=/absolute/pr1-legacy \
.venv/bin/python -W default -m unittest discover -s tests -v

.venv/bin/python -W default -m unittest discover -s companion/tests -t . -v

# Suite 使用实际包目录和既有 unittest 流程；日志包含逐项结果。
PYTHONPATH=suite .venv/bin/python -m unittest discover -s suite/tests -v

cd desktop
npm run build
npm test
npm run check:docs
```

四个 wheel 从单独源码快照构建，使用 `python -m build --wheel --no-isolation`，Channels 使用 `scripts/build_channels_wheel.py --out ... --no-isolation`。构建环境实际为 build 1.6.1 / setuptools 84.2.1。快照与安装文件的结果在 [component-wheel-audit.json](component-wheel-audit.json) 和 [component-installed-proof.json](component-installed-proof.json)。

官方 SDK 独立环境运行 `tests.test_openai_compatibility_audit tests.test_runtime_api_sdk`。渠道生命周期从仓库之外仅含 `tests/` 的目录运行，设置实际 `LP_TEST_CHANNEL_WHEEL`，清除 PYTHONPATH，运行 `tests.test_channel_suite_diagnostics tests.test_channel_suite_integration`。Harbor 固定来源、精确环境开关和命令见 [评估补齐说明](../../development/EVALUATION_COMPLETION_20261115.md)。

## 尚未完成的产品结论

旧 534 队列仍是 **1 PASS、3 FAIL、13 ERROR、517 无最终结果**，冻结源码 `1c06e97`；本轮没有启动、修改或重试它。原资源阻塞与已失败分母保留。新源码需要新的 study，现有 Harbor adapter 测的是容器 Shell 主 Agent，不是完整 Super Agent/Companion；没有 AA 官方成绩、排名或非劣结论。

新 APP 的 Rust/Swift、签名/安装/升级重开、真实模型五档任务、原生 SSE 409、会议音轨、晚间睡眠唤醒、Intel、KV 冷热/重载和实际 LoRA 仍依 [Work 提示词](../../development/WORK_PA_COMPLETION_20261115.md)执行。历史 benchmark 原件、数据授权与旧 Release 来源需要真实材料，不能靠写空实现消除门控。

## 可核对材料

- [机器可读结果及跳过原因](RESULTS.json)
- [日志原件与脱敏副本摘要](LOG_MANIFEST.json)
- [完整脱敏日志归档](verification-logs-redacted.tar.gz)
- [源码文件清单及摘要](SOURCE_FILES.json)
- [wheel 源码、归属和许可证检查](component-wheel-audit.json)
- [全新环境的真实安装证明](component-installed-proof.json)
- [mlx-lm 0.31.3 接口核验记录](companion-mlx0313-interface.json)

日志只替换了本工作区绝对根路径并移除 ANSI 颜色，结果、失败与堆栈保持。`LOG_MANIFEST.json` 同时保留原件和公开副本的 SHA256。历史日志可能来自较早源码；不能通过累计日志测试数量制造当前候选的通过总数。
