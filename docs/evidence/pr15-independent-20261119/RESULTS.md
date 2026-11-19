# PR #15 独立复核（2026-11-19）

**NOT_RELEASE_READY。** 远端起点为 `90504749215f058bdcfeee253ad3ccfe83ab4ccf`（tree `62dd402adc8ec8249eb866fcb70b05b5eebe109b`）。从该提交建立独立 worktree。唯一产品改动在插件启动入口，受测本地提交 `1c1d99bb0c41be1ffb82a124ee5528626868bce6`（tree `d6eaf4d424a67b9c5a4e863b6eb9cb16534a90d8`）。公开源码提交 [`04cf5bf`](https://github.com/www080327-glitch/LocalPilot-OpenSource/commit/04cf5bf7dc14c2b67fe08da6d283ac94264fe3ca) 的 tree 与受测本地提交一致。既有 RC21 版本号仅标识候选系列，本次实际执行范围以树和日志为准。

## stdio 初始化

- 对读 RC19、RC20、RC21 归档及其 SHA-256。RC19 r3 日志为 1,636 PASS / 99 SKIP。RC20 r4 在 HTTP 目录帧等待及独立 Schema 子进程路径各有一处错误。第二条旧日志只给出合并错误文本，无法判定为超时还是其他异常。RC21 的原始逐项日志为 **1,620 PASS / 99 SKIP / 24 未执行**。此处的 24 项都在 `PluginTests.setUpClass` 的首帧等待错误后未进入。各轮保留各自结果。
- 本机在同一 RC21 源码上执行一次完整发现和运行，进程退出码 1。unittest 报告启动 1,698 项、111 skip、36 failures、410 errors。错误条目包含类初始化、模块导入及子测试。执行器明确拒绝进程枚举、loopback bind、嵌套 sandbox 等操作，另缺 `reportlab`、`yaml` 测试依赖。本轮全量没有产生可用于关闭门禁的结果。原 RC21 的 24 项在此轮也未执行。当前补丁仅定向复验。
- 现行夹具的早期失败可复现为 `psutil.Process.children()` 的底层 `sysctl` 返回 EPERM。旧版发起 worker，随后 `_receive()` 和 `close()` 都抛 `PermissionError`，清理在回收进程前中断。新入口在启动前检查相同进程枚举能力，返回 `TransportFailure("process_inspection_unavailable")`，未分配临时目录或启动 worker。夹具按资源创建顺序登记类清理。新增回归通过，真实受限执行器再次运行夹具得到预期类别，24 项仍未进入。原 2 秒 SDK / 3 秒父进程等待及内存预算未改。
- 在独立进程中用同一 stdio worker、脚本夹具和同样的超时配置观察协议阶段。此探针各轮直接运行合成夹具的 worker，范围仅到目录帧，生产进程枚举门禁仍如上失败。两个样本都返回目录，无协议错误。历史 Linux 首帧超时的慢段及根因仍未确定。

| 首帧路径阶段 | 基线（ms） | 补丁后（ms） |
|---|---:|---:|
| Popen 返回至子解释器探针 | 83.70 | 70.69 |
| worker 模块导入 | 44.94 | 49.51 |
| SDK 导入至开始读取配置 | 394.75 | 523.73 |
| 打开 stdio transport | 23.31 | 15.74 |
| 初始化握手 | 420.26 | 398.03 |
| 工具、资源及提示目录至帧刷新 | 16.28 | 16.22 |
| Popen 返回至目录帧刷新 | 998.32 | 1,089.59 |
| 独立 Schema 子进程至宿主验证完成 | 139.47 | 156.88 |

Schema 两次均退出 0。父进程超时、非零退出和帧内容仍可在新探针中分辨。旧日志没有这些信号，历史 Schema 错误保留原分类。

## 定时器和增量持久化

- 使用归档的真实 Timer / TaskService / SQLite 复现器。RC20 正常 suspend 后回调获锁，将内存改为 `cancelling`，然后抛 `PersistenceError`，持久审批仍在。RC21 同条件下内存与数据库都保留 `requires_approval`，journal、检查点不变，无工具写入。创建和恢复入口都使用 `_timeout_task`，在原有可重入服务锁内检查 `closed`。显式 `cancel()`、`shutdown()` 和存储异常传播保持原语义。现有恢复超时、显式取消和停服竞争用例通过。
- 查看实际 `TaskService._checkpoint → snapshot_runtime / _task_payload → CheckpointBatch → SQLiteRuntimeStore.save` 路径。消息、工具历史、结果、事件、请求历史和网关审计等通过块引用进检查点，稳定前缀不逐条复制或序列化。父记录引用真实 child 收据列表，父子各块路径可写新后缀，未见每个活动边界重新复制全部子收据。首个基线、结构改动的受影响后缀、任务完成捕获、归档、恢复和旧格式物化仍可能处理完整记录。
- 同一 96 次实际读文件夹具以脚本提供方完成。第 96 个收据保存写 7 个块行，SQL JSON 载荷 73,816 B，观测 20.573 ms。任务完成的状态保存写 388 个块行、2,258,916 B，观测 34.331 ms。停服共 133.858 ms，其中 schema 4→3 物化 124.856 ms。字节数是交给 SQLite 的 JSON 载荷。恢复耗时此次未单独采样。七项现有增量检查通过，合并持久化套件共有 32 项，25 通过、6 失败、1 错误。loopback bind 的 EPERM 可具体定位，失败逐项保留。
- 在同一合成数据库上使用未修改的 RC18 源码（`fe9765c`）继续写，再用当前源码打开。任务数 4→7→8，两个旧原文均可检索，原任务快照和收据、既有执行段逐次比对一致。独立记录 journal 行哈希，30→49→57 行，两个休止点的全部既有行都保持同序原值。正常停服均为 schema 3。这是源码导入往返。历史 RC21 的真实 wheel 替换及原 28 行 journal 保留另见旧归档。

- 原崩溃夹具的真实写文件断言在本机失败，目标文件从未出现，故本轮未复现“实际副作用已发生”。两次失败均保留。用其真实落盘的未收据化 intent 继续验证，当前源码转 schema 4→3 后，RC18 和当前源码都恢复为 `UNKNOWN_BLOCKED`，拒绝继续，模型请求为 0，文件没有被重放创建，journal 前缀保持。补查的首次脚本因错误使用 context manager 失败，第二次因沿用已超过原期限的数据库按规则恢复为终态。第三次在同一次命令内用新库依次运行通过，超时预算未调整。已发生副作用的前后文件检查仍以 RC20 原证据为准。

## Luna 历史证据

| 记录 | 实际类型和结果 |
|---|---|
| R8 | Parser 未交回自测，错误 Python 路径为任务执行问题。广告未注册的 LIGHT/STRONG 为可复现产品路由问题。早期 Core 全量的 runner 缺 `__main__` 与缺依赖属于另一类测试启动故障。 |
| R9 Luna high | 原 R9 工程 PASS，28 次模型调用。途中两次旧 backend 路由错误和一次 subgoals schema 错误有回执。 |
| R10 Luna high | 原 R10 FAIL。Parser provider 在 4,096 输出 token 处报 `finish_reason=length`。此前四项只读工具已完成，截断响应中的工具零派发，替代 child 遇原两 child 限制。随后同 child 原预算恢复的产品修复有独立回归。 |
| R11 6.1 Sol medium | 原 R11 工程 PASS。29 次宿主请求与 provider 模型字段核对。本轮次同时改变源码及 effort，无法从 R10/R11 单对照拆分因果。 |
| RC19 模型配置 | 显式新 worker 模型路由白名单和更正密钥后仍用旧值各有产品修复；原账号密钥文件少一字符出现的 401 是独立配置事件。 |
| R12 Luna medium | 旧 RC17 两次 TLS EOF 失败，在同一冻结协议下第三次 PASS。首个传输失败中 17 unittest / 4 CLI 通过，整体工程仍失败。 |
| Luna medium 安装态长任务 | 旧 RC17 的 7,219.684 秒、240 心跳通过；此前 401 的失败保留。本次无新真实 provider 调用。执行代理身份不是 LocalPilot provider 回执。 |

R9、R10、R11 的原始 `RESULTS.json` 来自 [工程归档](../audit-20261117/root/task-storage-dispatch-b34/SUMMARY.md)。R12 401、三次 TLS/成功尝试和安装态长任务来自 [历史实测](../native-polish-final-20261118/RESULTS.md) 与同目录的结构化用量、来源和收据摘要。

## 保留门禁

- **失败／受阻**：历史 RC21 的 stdio 首帧超时未关闭，本机新的 EPERM 复验另计。当前 Mac Test APP 构建入口被共享构建锁文件写入权限阻断。Playwright 收集 72 项，实际执行在 Vite 绑定 127.0.0.1 时 EPERM，0 页面断言。
- **未运行**：当前树 Test APP 安装/回滚/恢复、当前安装态真实 Luna 工程和长任务、真实新手无终端路线和参与者观察、声轨与中文转写、TCC、休眠唤醒、实际 provider 缓存指标。
- **缺目标设备或素材**：原生 Intel Mac、真实 Debian 13 系统安装及 X11/Wayland、第二物理显示器、私人高级姿态包。≥24 Hz 可见动画、物理拖动与跨屏继续未验收。通用 Linux GUI Computer Use、通用外部持久 KV 与个人训练效果的实现及数据边界仍见需求审计。

[运行记录与散列](EVIDENCE_MANIFEST.json)保留独立运行的日志、退出码、脚本与版本来源。历史归档从原提交读取，未覆盖。PR 保持开放。
