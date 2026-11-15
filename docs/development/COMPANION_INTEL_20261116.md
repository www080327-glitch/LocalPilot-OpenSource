# Companion：Intel Mac 与 Linux 服务可移植性

日期：2026-11-16（Asia/Shanghai）。基线：PR #11，`47e39faf3e97fbd13a562a9ec74efa30dfcc7b42`。

## 本轮结论

Companion 已补齐 Intel Mac 使用本地 HTTP 模型服务器时的关键平台、电源适配和 Core 任务委派，并在 Linux x86_64 上完成真实 HTTP、CLI、服务进程和 SQLite 来源/任务恢复测试。测试没有加载真实模型，也没有使用 Intel Mac 硬件，因此不作为 Intel 原生 APP、模型性能或事实回答质量验收。全量 Companion 回归最终为 **654 PASS、25 SKIP、0 FAIL、0 ERROR，共 679 项**。

本轮没有修改 PR #11 的会议 helper 签名修复，也没有改变 TCC 权限或宿主责任进程。此前真实系统音轨因宿主权限被拒的记录继续有效。

## 具体问题与修复

| 问题 | 修复与实际行为 |
| --- | --- |
| Intel/Linux 配置一个存在的模型目录后，MLX 后端会报告可用，再尝试启动不支持的 worker | 在管理器启动 worker 前检查 Apple Silicon macOS；不支持时明确返回 `backend_platform`，`model_called=false`，不计入实际推理、不启动子进程。保留 Apple Silicon 原有 MLX 路径。 |
| 无电池的桌面 Mac，`psutil.sensors_battery()` 返回空值，被当作不能证明交流供电 | 只在 macOS 通过 `pmset -g batt` 确认当前 AC/Battery；报告的电池供电不会被覆盖。资源状态与模型调用共用这项观测。失败/未知仍为未知。 |
| 系统电源解析只支持 `lowpowermode`，漏掉 `powermode` 三态，旧 Intel 也可能没有低功耗选项 | 解析当前供电档的 `powermode` 0/1/2，其中 1 为低功耗；当前档没有该键时，读取同一供电来源的 `pmset -g cap`，仅能力列表明确不含低/高功耗特征时视为不支持。缺失、矛盾、错误输出及读取期间电源变化保持保守结果。 |
| `local-http` 没有向兼容的推理模型发送关闭思考的选项 | 新增显式布尔配置 `http_model_disable_thinking`，缺省 `false`。启用时请求带 `chat_template_kwargs.enable_thinking=false`；oMLX 原有行为不变。不会删除返回思考文本、补造答案或自动重试。 |
| Linux 执行 `launchd install --confirm` 会先创建 plist，再因没有 `launchctl` 失败 | 非 macOS 的 install/uninstall/status 现在直接返回 `macos_required`；保留无副作用的 render 预览，不创建启动项。 |
| 用户手动确认本地任务后，控制器仍按自动升级提交，导致关闭 `localpilot_auto_local` 的配置被拒绝 | 提交沿用实际自动升级偏好；手动帮助和工具确认仍走原控制流程，不暗中开启自动升级。 |
| 本地取消接口返回 `stopping` 且任务仍未静止时，控制器提前展示 `stopped` | 有非终态或非静止任务时保持 `stopping`，收到真实终态且 `quiescent=true` 后才结束；晚到工具调用不执行。 |
| 旧主动提醒测试的时钟仍 patch 重构前模块 | 修正为实际使用时钟的 `companion.runtime.observations.datetime`，继续验证宿主证据与不调用模型。生产夜间静默策略未改。 |

模型状态增加后端、配置可用性、平台支持与是否由 Companion 管理模型进程的字段。对外部 HTTP 服务，退出、空闲卸载或请求失败均不会结束外部服务的进程。

Core 的通用本地 HTTP 路由现在沿用已有共享服务请求取消契约，Companion 复用原 Task API、资源同意和可见控制窗，不新增调度层。外部服务没有受管模型的 load/unload 或失联卸载承诺；注册信息明确 `provider_compute_stop=UNKNOWN`、`heartbeat_lease=false`。收到响应头后的 HTTP 响应可由请求取消关闭；尚未收到响应头时仍需等待响应或请求超时，因此不把客户端取消等同于模型服务器停止计算。

### 电源解析依据

依据 Apple 官方 [PowerManagement `pmset.m`](https://github.com/apple-oss-distributions/PowerManagement/blob/d415e45501842834a280930c3eed9186544a67f0/pmset/pmset.m)，固定源码 commit 为 `d415e45501842834a280930c3eed9186544a67f0`：显示设置的分支选择 `powermode` 或 `lowpowermode`；`show_supported_pm_features()` 对当前来源调用 `IOPMFeatureIsAvailable`，输出 `Capabilities for ...` 及受支持的特征。新增测试使用此公开格式的合成文本，不冒充来自 Intel 真机的采样。

不会把单纯缺少 `lowpowermode`、缺少电池、查询失败或未知平台解释为节能关闭/已接电。`off` 只关闭 Companion 的低功耗策略；默认 `allow_local_on_battery=false` 和操作员禁用开关仍独立生效。

## 支持范围与配置

| 能力 | Apple Silicon macOS | Intel macOS | Linux |
| --- | --- | --- | --- |
| 服务、CLI、文件观察、SQLite 记忆 | 既有实现，云端回归 | 同一 Python 路径；真机待验 | 本轮真实进程/来源恢复通过 |
| 明确选择的 Codex/会议文字来源 | 支持 | 支持 | 本轮通过 |
| 本地 HTTP 推理协议 | 支持 | 主要本地推理入口；真实模型待验 | 协议及 CLI 通过，真实模型待验 |
| 内置 MLX worker/LoRA | 仅 Apple Silicon；真实训练另验 | 不支持，不自动转换权重 | 不支持 |
| 原生窗口 AX、Swift UI、实时会议采集 | 仍需 macOS 权限及实际验收 | 受 OS/硬件/权限限制，真机待验 | 不支持 |
| `low_power_policy=system` | 读取当前系统供电档 | 新增旧硬件能力判断，真机待验 | 尚未适配；保持保守 |
| launchd | macOS 原有路径 | macOS 原有路径 | 明确不可用，可 render 预览 |

使用方式见 [Companion README](../../companion/README.md)。Intel 应明确选择 `backend=local-http`、实际的环回 endpoint/model ID 和 `http_model_host_local_only=true`。默认 `low_power_policy=always` 会阻止未托管 HTTP 后端，应由用户选择 `system` 或 `off`。不会在发现 Intel 时暗中更改现有电池授权、文件观察范围或模型配置。

Linux 新配置可以明确使用 `~/.local/share/localpilot-companion`；没有更改默认路径或迁移已有数据库。当前无系统低功耗适配，需要用户明确配置 `off`；若无法证明交流供电，还需明确选择允许电池/未知电源上的本地推理。外部服务器本身负责 CPU/其他硬件推理，不要求 MPS，也不是内置 MLX 的 CPU 回退实现。

## 测试记录

环境：Linux x86_64，Python 3.12.14。使用现有 `unittest`，没有新增测试框架或运行依赖。

```sh
python -W default -m unittest companion.tests.test_intel_portability companion.tests.test_active_system_power companion.tests.test_suite_contract companion.tests.test_pa_candidate companion.tests.test_omlx_shared -v
python -W default -m unittest companion.tests.test_intel_delegation companion.tests.test_v044_resource_controls -v
python -W default -m unittest discover -s companion/tests -t . -v
```

| 运行 | 结果 | 说明 |
| --- | --- | --- |
| 定向首轮 `focused-r1.log` | 41 PASS | 新平台、电源、HTTP、候选 worker、现有 oMLX 边界 |
| 全量首轮 `full-r1.log` | 645 PASS、25 SKIP、1 ERROR / 671 | 旧测试 patch 错误时钟模块，真实凌晨触发正确夜间静默；原日志保留 |
| 单项复现 `repeated-errors-r1.log` | 1 ERROR | 独立重现同一夹具问题 |
| 修复夹具及 launchd 后定向 `focused-r2.log` | 22 PASS | 含新增 Linux launchd 入口检查 |
| 平台阶段全量 `full-r2.log` | 647 PASS、25 SKIP / 672 | 38.522 秒；0 FAIL、0 ERROR，无 ResourceWarning |
| 委派定向 `delegation-r2.log` | 22 PASS | 6 项真实 Core/HTTP/SQLite 集成及 16 项既有资源控制回归 |
| 最终全量 `full-r3.log` | 654 PASS、25 SKIP / 679 | 42.438 秒；0 FAIL、0 ERROR，无 Warning/ResourceWarning |

新增 `test_intel_portability.py` 共 20 项。重点链路使用真实 loopback HTTP 请求、真实 `model-smoke` CLI、真实 Companion 服务子进程、认证命令、SQLite 与重启后的来源记录。系统供电样本与平台名称在入口替换，因为 Linux 无法执行 macOS `pmset`。候选回执测试仅模拟支持 MLX 的宿主条件，实际 worker 子进程继续在导入 MLX 前验证被改动的文件。

新增 `test_intel_delegation.py` 共 6 项，启动生产 Core HTTP 服务和真实模型协议服务器，经过 Companion 控制器、任务提交和 Core SQLite：手动纯推理在自动升级关闭时成功；自动升级先准备可见控制而不提前提交；标准 Agent 经帮助确认实际读取工作区文件；电池单次同意使用真实资源票据且不改变长期偏好；延迟响应头期间取消保持停止中，晚到的已授权 `read_file` 仍不执行；Companion 关闭重开恢复原 Task/Session 而不重放推理。原生控制窗存活与电源/内存采样在入口替换，Linux 不因此获得原生控制窗支持。没有模拟 Core、请求传输、工具执行或数据库。

HTTP 服务回包是协议夹具；其中返回 `56` 不表示运行了 Qwen 或证明算术能力。`finish_reason=length`、工具调用和缺少有效正文的失败语义保留，服务未提供用量时仍报告 `usage=null`。请求“关闭思考”但服务仍返回思考文本的测试验证原文保留，不能据此把此前真实模型 QA 失败改为通过。

最终日志 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| focused-r1.log | `72429733562481e8edd679d17a956d558ec27fa5673ba4660a809408be7f8def` |
| full-r1.log | `2ff7ca64734e140c235465e80ac3b147f687733599d72044e5f6484db3781307` |
| repeated-errors-r1.log | `868aba7bde76636374c9cba0d6a6098e5701aed0a0909845848028d87403cc83` |
| focused-r2.log | `bc52024f6789104782f665172926a7cbcc1183b9fe34f613dd79345cf084cb2c` |
| full-r2.log | `1702bfd00fe89cd49ed16fd667074270606302340c1954ee18c5349aac41bd50` |
| delegation-r2.log | `9c5931c32face5bbf78d815a54c38a52c0f493f550938d35077ea532a062495c` |
| full-r3.log | `9a8bf7fe436be9859913676694dea9bbc89633e0ce6457b82f66c513dd2de16b` |

## 设备接力范围

还需要 Intel Mac 实机验证 Python/APP 架构、实际 `pmset -g batt/custom/cap` 格式、接电/电池策略、CPU 模型连通与取消、休眠唤醒、原生 helper/权限、实际会议音轨。Apple Silicon 原有 MLX 加载、内存、KV、训练与长时间运行也不由本轮云端测试替代。

这些工作应使用独立测试 APP 和数据目录，保留原失败日志、模型来源/哈希、请求 finish_reason、未知用量、真实功耗未测等限制。不要修改已有日常模型服务的生命周期，也不要为通过验收绕过 TCC 或将模型输出加工成预设答案。
