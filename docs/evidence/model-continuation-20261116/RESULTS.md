# 模型、OpenAI 委派与子 Shell 取消续验 — 2026-11-16

## 结论与源码边界

本轮修复了两个实际产品缺口：Companion 拒绝新注册的显式 OpenAI 路由，以及父任务取消未及时传到正在执行 Shell 的同步子 Agent。OpenAI 身份和委派相关 **62 项回归通过**；取消、HTTP、SQLite 恢复及异步生命周期相关 **65 项回归通过**。这些组内包含定向用例，不将之前的单项复跑重复加总。

独立的真实 Qwen3.5-2B 两项诊断为 **0 PASS / 2 FAIL / 0 ERROR**。保留原来的九项产品测试、规定参数诊断、四项修复后诊断和公开题库结果，没有覆盖或重算旧分母。新结果也不计入 AA 或任何正式 Agent 排名。

最终生产源码提交为 `59fad12de6f57006fc7510805af2dfd1718c16ea`。**真实模型运行使用的快照早于本轮随后定位的子 Shell 取消修复**：模型快照包含 449 个文件，清单 SHA-256 为 `e895e8094ef31f088dd09691552d6309e1133d1c665fc36092826a43e3f1027e`，运行前后完全一致。组件标识为 Core b26、Suite b31、Companion b7、Desktop rc9；相同组件标识不代表两份源码相同。

[FINAL_SOURCE_DIFFERENCE.json](FINAL_SOURCE_DIFFERENCE.json) 列出模型快照与最终提交的差异：一个运行时代码文件 `agent/session.py` 的取消传播修复，以及 Companion README 文本。模型诊断没有执行 Shell，不能用它声称验证了晚发现的取消补丁；该补丁由真实子 Shell 集成测试独立验证。

## OpenAI 接入补全

此前 Core 已注册 `openai`，但 Companion 的提交预检与云咨询控制窗只接受 DeepSeek，导致明确选择 OpenAI 仍无法进入已有链路。现有两个白名单均加入显式 `openai`；控制窗按实际提供商显示 OpenAI 或 DeepSeek。`local_only` 仍拒绝 OpenAI，泛化的 `remote-openai` 仍不能冒充已资格验证的云咨询后端，原来的明确云端确认及上下文裁剪规则保留。

新 OpenAI 后端同时补齐 `provider="openai"`。此前该属性缺失会让持久身份及子任务用量记录把提供商记为 unknown。旧兼容端点的身份没有改变。

使用仓库已有的真实 HTTP/SQLite/TLS 测试框架验证，没有外部 API 调用：

| 检查 | 结果 |
| --- | --- |
| 已配置 OpenAI 云咨询显示实际身份；确认前不调用；确认后只传允许的问题 | PASS |
| 本地专用会话拒绝显式 OpenAI，未创建任务或发模型请求 | PASS |
| 未资格验证的 `remote-openai` 仍被拒绝 | PASS |
| OpenAI 持久 backend identity 记录 `provider=openai` | PASS |
| 原有自动本地策略、委派、TLS、流式 usage、代理与恢复合同 | PASS |

组合命令为：

```bash
python -m unittest companion.tests.test_v044_service companion.tests.test_v044_help_and_collaboration companion.tests.test_v044_automatic_local tests.test_openai_cloud_backend -v
```

在已有完整依赖的组件 Python 环境下为 **62/62 PASS**，见 [openai-companion-r3.log](openai-companion-r3.log)。模型响应在这些测试中是脚本化的协议夹具，不是 OpenAI 实际推理或付费账户验收。

首轮默认 Python 缺少 watchdog 的两项 ERROR 保留在 `openai-companion-targeted.log`。第二轮新测试错误地把已有单步云咨询夹具的最终验收状态要求为 completed；该夹具实际的模型请求和答复均完成，但独立验收未运行，因此保持 incomplete。测试改为验证本项真正目的：确认、传输内容、实际答复、quiescent 与 runtime_status。原失败保留于 `openai-companion-targeted-r2.log`。**真实 Qwen 任务的 completed 判据没有因此放宽。**

## 真实子 Shell 取消缺陷与修复

新增集成测试在生产 Core 子进程、真实 HTTP 和 SQLite 上运行真实 Linux 受限 Shell；仅父/子模型的推理响应由现有协议夹具提供。子 Agent 执行一次 `printf ... >> child-partial.txt; sleep 60`，确认实际文件出现后取消父任务。

旧实现中，父任务的取消事件没有立即传给同步子 Agent。子 Shell 只检查自己的取消事件，而子 Agent 只有在工具返回后才会检查父事件。因此子进程继续睡眠，任务保持 cancelling，Core 停机也被拖住。

首次验证因旧高频轮询触发 HTTP 429，保留于 [child-shell-runtime-r1.log](child-shell-runtime-r1.log)。改为每 0.2 秒检查一次后，旧代码仍在五秒边界保持 cancelling；Core 收到 SIGTERM 十秒后仍未退出，见 [child-shell-runtime-r2.log](child-shell-runtime-r2.log)。这排除了限流是根因的解释。

修复只在既有 `AgentSession.request_cancel` 中向当前未结束的子 Agent 传递取消意图，沿用已有事件、原生停止和收据处理。没有引入新调度器、取消队列或恢复协议，也没有把未知副作用改判为未发生。

同一测试在修复后完整通过，总用时 1.36 秒，见 [child-shell-runtime-r3.log](child-shell-runtime-r3.log)。其判据同时要求：

- 真正执行 Shell 的是子 Agent；父 Agent 没有代执行。
- 取消后父/子任务终止并 quiescent，子 Shell 收据保留 `side_effect_status=unknown`。
- 退出并重启 Core 后，SQLite 中的子任务与收据完整保留。
- 使用同一幂等键再次提交返回原任务；文件只追加一次，模型服务器没有收到新的执行请求。

相关回归命令：

```bash
python -m unittest tests.test_core_portability tests.test_async_runtime tests.test_v2_p0_reliability -v
```

结果为 **65/65 PASS**，见 [cancel-regression-r4.log](cancel-regression-r4.log)。其中既有异步子任务、等待批准、已完成动作和共享原生控制等行为也通过。该结果证明运行时取消与恢复链路，不证明模型会自主正确选择 Shell。

## 预先固定的真实模型诊断

[PROTOCOL.json](PROTOCOL.json) 在推理开始前于 `2026-11-16T13:30:01Z` 保存；固定脚本为 [model_diagnostic.py](model_diagnostic.py)，源码清单为 [SOURCE_FREEZE.json](SOURCE_FREEZE.json)。复用已经完整核验的官方 Qwen3.5-2B revision `15852e8c16360a2fea060d615a32b45270f8a8fc` 的受控 Q8_0 转换，未下载另一套权重、调用付费模型或换模型重试。

| 参数 | 实际设置 |
| --- | --- |
| 模型与服务 | 官方 Qwen3.5-2B 受控 Q8_0；固定 llama.cpp `b1b770d90d94cad9e9ea5b993bdbc383a522fb28` |
| 推理资源 | CPU 2 线程、单 slot、8192 token 上下文、每请求最多 512 输出 token、非思考模式 |
| 采样 | temperature=1、top_p=1、top_k=20、min_p=0、presence_penalty=2、repeat_penalty=1、seed=42 |
| 父任务预算 | 6 步、8 个工具提议、262144 个宿主准入单位；包含子任务实际消耗及收尾预留 |
| 宿主 worker 上限 | 3 步、4 个工具提议、131072 个宿主准入单位 |
| Shell 提示显式请求的 child 预算 | **3 步、2 个工具提议**，省略 tokens 字段以使用宿主上限；仍受父任务剩余预算限制 |
| 任务期限 | 每项 600 秒；Shell marker 最多等待 450 秒，若任务提前终止则立即按结果结束 |
| 运行次数 | 每项一次；无模型输出后的提示调整或重跑 |

宿主准入单位用于保守记账，不等于 provider 实测 token。与上轮相比，本协议延长了 wall-clock 期限，并明确要求 Companion 只读一次后直接答复；原步骤和输出 token 上限保持。它是链路诊断，不是相同条件下的模型质量对照。

| 任务 | 结果 | 秒 | 实际依据 |
| --- | --- | ---: | --- |
| 真实 child Shell → 取消 → 重启 → 不重放 | FAIL | 321.00 | 父模型创建了实际 child；child 连续调用两次 list_entries 后进入收尾，没有 Shell 收据或 marker。父任务提前以 incomplete 结束，因此未进入 Shell 取消/重启分支 |
| Companion 明确一次读取并完整交付 | FAIL | 316.38 | 一次完整物理读取加三次缓存读取，违反一次读取要求；随后 step_reserve 收尾且状态 incomplete。最终文本把独立 verification=NOT_RUN 误解为工具没有执行或没有读取授权，没有按要求交付 |

第一项的 child 运行状态虽然为 completed，但其收据只有两次目录读取，不能当成 Shell 任务完成。第二项虽然在最终文本中提到了真实 marker，也不能替代完整交付和 completed 的既定判据。两项都不是请求错误、漏跑或 600 秒超时；它们反映该 2B 模型在本次有限预算、工具选择和证据解释条件下的实际失败。没有据此推断所有更强模型的表现。

完整结果见 [SUMMARY.json](SUMMARY.json)、[child-cancel-task.json](child-cancel-task.json) 和 [companion-final.json](companion-final.json)。provider 实际运行 638.97 秒，最高观察 RSS 为 2,589,932 KiB（约 2.47 GiB，仅 provider），正常退出码 0；Core 和 provider 均已停止。脚本以退出码 1 保留两项 FAIL。外部云端调用为 0，API 支出为 $0，能耗未测。共享宿主期间还运行了轻量回归，不将耗时作为专机吞吐基准。

## 证据保留

[LOG_MANIFEST.json](LOG_MANIFEST.json) 对公开日志/任务快照同时记录原始和公开文本 SHA-256；公开副本只替换运行目录、源码目录、Python 环境和临时目录前缀，原结果、任务内容及失败仍保留。源码清单使用仓库相对路径。

原始脱敏前的合成任务、日志、协议、冻结脚本和取消修复前的 Session 源码另外归档，身份见 [PRIVATE_ARCHIVE_IDENTITY.json](PRIVATE_ARCHIVE_IDENTITY.json)。归档明确排除权重、KV 二进制缓存、SQLite、服务配置、客户端凭据和依赖环境。公开证据不是私有配置的副本。

剩余的真实模型 Shell 与 Companion 质量验收，应按既有 Work 计划使用已授权的 Mac Qwen3.6-35B 或明确配置的合格云模型分别完成。真实 API 余额、异构多模型/五档质量、Intel 原生硬件、Mac 原生权限与个人训练数据仍需要对应环境或数据；本报告不将合同测试替代这些验收。
