# Mac 原生验收与 PA 续接：2026-11-14—15

## 身份与结论

- Draft PR #9，仍依赖 PR #1；PR base 保持 `fix/nationals-runtime-ux-20261113`，包含其 `94e0e6ff2c8da974d20530d7a0faa50844d052f4` 基线。
- 接收远端 `ca026d6a62f160153b8da240f92059bde4cd0294`，新建独立 worktree，未重置既有工作树。
- 最后 APP/Core/Companion/Suite 运行快照：`45e52e20ef0a61b055ebc022e2e512158b304c0c`。可选 Harbor adapter 随后增加原生云端接入及容器程序可用性提示，最后源码 `e9c39a7fb875ee60c4a25274f19b9de4a6eea809`；没有更改 APP 内部运行代码。交付证据提交不再改运行源码。
- macOS 27.0.1 / arm64 / 64 GiB；Python 3.14.6。开发 Node 24.20.0；APP 内置 Node 22.23.4 arm64，两者不混称。
- **本机真实文件、权限、模型协作、取消、恢复、同会话换模、原生 SSE、独立安装、失败回滚及真实 Docker 容器执行已取得下述范围的实证。正式榜单、Intel 整包、旧 Skill schema 迁移及全产品 50 GiB 缓存管理仍未完成。保持 Draft。**

原始日志、配置、数据库、故障候选和归档留在本机；本工作树的 `docs/evidence/nationals-20261114-pa-mac/.private/` 为主要索引。公开记录只保留脱敏摘要及字节哈希，不发布凭据、数据库、活动正文或重量文件。

## 回归与构建

| 检查 | 结果 | 实际边界 |
|---|---|---|
| Core 全量 | PASS：1437 项，1367 PASS / 70 SKIP / 0 FAIL、ERROR | `run_core_qualification.py` 文件入口；161.610 秒 |
| Companion 全量 | PASS：581 PASS / 0 SKIP | 36.904 秒；不等于获得系统观察权限 |
| 两套 Python 主回归 | 2018 项，1948 PASS / 70 SKIP | 受控后端回归不是模型成功率 |
| Vitest | PASS：50 项 | 最后草稿修复后重跑 |
| TypeScript / Vite | PASS | 最后草稿修复后重建 |
| Playwright | PASS：27 项 | 浏览器合成桥；包含草稿换模后 reload 断言，不替代原生任务证据 |
| Rust | PASS：40 项，3 ignored | 最终代码 release 测试配置；ignored 不计通过 |
| Swift | PASS | 实际编译并签名 CompanionUI 和 NativeObserver；不是 TCC/全天观察验收 |
| 官方 OpenAI SDK 3.51.0 | PASS：42 项 | 独立 Harbor 环境，真实 loopback HTTP，脚本后端；主环境 42 SKIP 保持原样 |
| Harbor 官方 schema | PASS：20 项 | 固定 0.26.0 / `ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4` |
| Harbor adapter 协议 | PASS：6 项 | 实际 AgentSession、真实 HTTP；environment 为明确的协议 fixture，无 Docker |
| 完整 APP 资源 | PASS | 4 个组件、35 项锁定依赖、Python 和 Node；未使用空后端资源通过打包 |
| ZIP / DMG / 代码签名 | PASS | ZIP 实际解压验签，DMG 校验；ad-hoc、未公证 |

Core 的 70 SKIP：历史 benchmark 缺失 12；可选官方 SDK 42；已安装 Suite 候选 wheel 4；可选 wheel/POSIX 生命周期 2；独立 Harbor adapter 6；Harbor schema 1；未公开费用账本 2；缺失 TimedBackend 1。独立执行结果不篡改主报告 SKIP。全部原始理由见本机 `core-adapter-final.json`。

Core 全量在 `dfc7d78` 执行。最后 `e9c39a7` 只修正可选 adapter 的容器提示，产品 Python/Rust/Swift 输入不变；adapter 的 6 项协议测试及真实模型 Docker 任务另行执行。前端、原生 APP 与 Rust 的 45e52e2 快照单独记录，没有把旧基线报告移植到新构建。

## 真实模型与原生矩阵

| 项目 | 结果 | 证据与限制 |
|---|---|---|
| 本地、云端文本及文件任务 | PASS | Qwen 实际创建并读回 `NATIVE-714`；DeepSeek 在同 Session 读回该文件 |
| 四档权限 | PASS | 只读未写；请求批准前未写、批准后写入；工作区外写要求批准并被拒绝；完全权限实际写入独立外部 fixture，无 APP 二次批准 |
| 五档来源 | PASS，范围为任务入场选路 | local_only/local_first 实际用 Qwen；balanced/cloud_first/cloud_only 实际用 DeepSeek；五档不是固定比例 |
| 本地主 + 两个本地子 Agent | PASS | 真实 read_file 收据、两个标记、父任务收集结果 |
| 云端主 + 两个本地子 Agent | PASS | 实际异步分派、两个只读子任务、wait_children 收集，不把父级 Full 变成子级写权限 |
| 本地主 + 已授权云端子 Agent | PASS | 实际云端读取 fixture，父任务收集；没有私人活动外发 |
| 并发资源控制 | PASS（本次本地串行范围） | Core 本地模型请求上限 1、云端 2；oMLX 本次服务并发 1；子任务生命周期可重叠，物理本地推理排队；未声称两个云请求重叠已验证 |
| Shell 取消 | PASS | 真实 bash/sleep 进程终止，后续完成标记未写；保留可能已有副作用的回执 |
| 子 Agent 取消 | PASS | operator 取消正在推理的真实本地子任务；子任务 cancelled，oMLX 有 `Aborting request` 和 prefill interrupted；父任务如实 incomplete |
| UNKNOWN 不重放 | PASS | 实际 Shell 写入 X 后杀死仅本次 Core，停止该测试 Shell 进程组，再快速重启；原任务为 requires_human / UNKNOWN_BLOCKED，同 key 同 task ID，文件仍只有 X |
| UNKNOWN 换模 | PASS（拒绝） | 真实 409 session_busy，UNKNOWN 状态保留；不将它冒称某个更晚分支的错误码 |
| 任务与 Session 恢复 | PASS | 实际 Core 进程重启；完成收据、消息、历史模型和幂等任务保留；UNKNOWN 不重做 |
| 同 Session 本地→云端→本地 | PASS | Session ID 不变；历史两条 task.model 分别 local-v5/cloud，最终 session_model 为 local-v5；聊天、文件、收据保留 |
| 既有 Session 草稿 | PASS，修复后 | 原生发现重开丢草稿；增加持久化/恢复及 reload 断言。最后 APP 重开实际保留 `PERSISTED-DRAFT-FINAL-714`，换回本地仍保留 |
| 有 child tree 的换模 | PASS（正确拒绝） | 真实 409 model_switch_children_incompatible；此能力仍未实现 |
| 原生 SSE 409 | PASS | 正式包 Core 的测试启动器仅将保留窗口设 32；真实 APP 请求 after=0 收到 409、取快照、after=94 返回 200；同一 task 完成，3993 字符正文中 PREFIX/SUFFIX 各一次 |
| 只读模型健康 | PASS | 实际模型已列出/已加载，inference 与 tool_execution 仍 NOT_PROBED；没有以发现接口冒充推理证明 |
| Companion 立即反馈 | PASS | 真实本地模型；accepted 约 0.009 秒先到，最终约 2.506 秒；算术答复 42；确认文本未合并进答案 |
| Companion 活动与来源 | PASS（授权文件范围） | 实际 FSEvents 索引两份 fixture；今日两项、昨日无记录且不推断没工作；来源撤销后不再读出；真实模型答出 synthetic transcript 的 Ada 并给文件来源 |
| 真实会议、隐藏 Codex 历史、原生晨晚/唤醒全天覆盖 | NOT_RUN | 无本轮授权的真实会议转录/音频或 Companion 原生 AX 观察范围；文件中的 Codex 记录是显式验收记录，不冒称自动感知 |
| 旧 Skill schema / async_policy 迁移 | NOT_RUN | 没有删除旧库、修改历史哈希或放宽恢复指纹；精确迁移仍缺实现 |
| Intel x86_64 APP、依赖、CPU 模型 | NOT_RUN | 本机 arm64，无 Intel 真机；内置 Node/多数扩展 arm64，不能宣传 universal2 |
| LoRA/全参/RL | NOT_RUN | 不让训练阻塞问候、来源和恢复闭环 |

SSE 保留窗口是显式、隔离的资格启动设置，不是新生产配置开关；事件由真实模型任务产生，没有注入合成 token、浏览器桥或第二次任务提交。原生观察到快照前缀和后续完成，HTTP 原始记录在 `native-retention-http.jsonl`。标准 Core 随后已恢复，不留下该小窗口启动器运行。

## 安装、组件与源码身份

独立身份始终为 `io.localpilot.desktop.test` / `LocalPilot Test`，目标是 `~/Applications/LocalPilot Test.app`。独立服务 HOME、SQLite、工作区及端口；日常 `LocalPilot.app` 安装前后树摘要相等。测试身份启动需传入本次受保护的 `LP_INSTALL_TEST_ROOT`；没有将其当作日常双击发行物。

初装、可区分升级候选、最终草稿修复候选均实际安装。最后 APP 构建清单 source 为 `45e52e2`、dirty=false。每次新建版本化 ZIP/DMG；没有向证据/发行目录复制裸候选 APP。

四种真实失败注入均 PASS：复制源不可读、暂存 Info.plist 破坏后真实 codesign 拒绝、替换后的真实 codesign 拒绝、注册命令返回失败。测试槽均恢复原树与有效签名；失败候选留在 Trash 或安装暂存位置，回滚 ZIP 留在测试专用归档目录。相同原树复用既有 archive() 的已验证 ZIP，并每次实际解压核对，避免重复归档占盘。未改验签为恒真。

Core / Companion / Suite 的真实 pip 安装失败回滚各 PASS，包源码和用户 sentinel 均保持；没有把 mock 边界结果当 Mac 安装。Suite 本轮增加 force-reinstall（同版本候选也会更新代码）及安装失败后重装已提供的 previous wheel。成功仍明确要求 doctor，未承诺任意运行期故障自动回滚。

活动模块目录原有名字保留，按独立组件升级；实际 137/79/17/7 个 Python 文件分别与最后 Core/Companion/Suite/Channels wheel 相同。不能仅凭版本号相同推断源码相同。内置 Node 22.23.4 arm64 由固定压缩包核验并实际执行。

watchdog 6.0.0 生产 wheel 的 SHA-256 为 `c1d1d020f564cdec2ea437ff1304e47c182fe19d4310d3eb0923c33158025ab5`，与 PR #1 中官方 sdist + 固定构建输入的来源记录及锁一致；它不是 PyPI 官方 cp314 wheel。本轮初次选到旧的 902f…候选被锁检查拒绝，改用已保留的 c1d…产物重新生成资源。主测试 venv 用 902f…同源码构建候选；最终打包和真实 Companion 文件监听使用锁定 c1d…，两者不混淆。Python 启动器虽含两种架构，不能替代 Intel 完整依赖验证。

## KV、上下文与缓存预算

固定 Qwen revision `38740b847e4cb78f352aba30aa41c76e08e6eb46`、4bit/group64、tokenizer、template、提示摘要，使用隔离 oMLX 0.6.4 和已存在权重，没有下载新模型。13,038 输入 token：

| 请求 | cached token | 客户端 TTFT | 正文 |
|---|---:|---:|---|
| 冷 | 0 | 39.894 秒 | KV-714 |
| 热，同请求哈希 | 12,288 | 3.604 秒 | KV-714 |
| 本次模型卸载/重载 | 12,288 | 14.483 秒 | KV-714 |
| 本次推理服务重启 | 12,288 | 10.419 秒 | KV-714 |
| 改变 Skill 风格的 system 前缀 | 0 | 43.776 秒 | KV-714 |

重载 TTFT 包含模型加载，不能拿 provider 排除加载的数字代替。changed-prefix 是合成 system 前缀失效测试，不是更改真实安装 Skill bundle；模型/模板版本变化的所有组合尚未逐一测试。此结果不证明全后端永久 KV，也不证明 Companion MLX worker 的 fresh_per_request 路径已改变。

另一次预先记录请求哈希、零自动重试的直接 provider 上下文 smoke：58,559 prompt token（产品配置 65,536 的约 89%）、237.873 秒、15 输出 token，正确返回首尾两个 marker。它不是绕过 Task API 的 4096-byte 入场限制，也不是通用长上下文准确率结论。

本次拥有的推理缓存仅 `omlx-test/cache`，实际配置 SSD 1GB / hot 128MB，受后端现有策略约束。外部共享 oMLX/HuggingFace 缓存、权重、活动、SQLite/UNKNOWN、APP 和归档均未纳入删除集合。**全产品统一 50 GiB 所有权台账、淘汰与使用中保护：NOT_RUN / 尚未实现。**

用户提醒内存后，不再加载 35B；此前本轮 oMLX 进程后续退出的原因未独立确证。最后仅恢复轻量 API，确认模型 loaded=false，不把历史加载成功当当前驻留。

本机空闲从约 7.1 GiB 降低后，附件导入真实返回 413（入口保留 2 GiB），没有放宽阈值。经两次明确的具体路径授权，清理本轮 debug 及选定 release 编译缓存；完整源码、日志、APP、回滚包、数据库和权重保留。空间不足时的失败仍在日志内。

## Harbor：真实容器 adapter 与全分母

`scripts.localpilot_harbor:LocalPilotHarborAgent` 复用既有 V5 AgentSession，仅注册经官方 environment.exec 到任务容器的 Shell；没有注册宿主文件/Shell 工具或另写执行循环。已有 Native Messages 云端后端用于节省本机内存，key 仅在宿主通过原私有机制读取，实际检查容器不含该 key。当前禁用子 Agent，拒绝未资格的 MCP/Skills/trajectory import；远端进程取消未确认不冒称已停止。

固定 Harbor 0.26.0 / `ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4`。安装独立测试工具：Colima 0.10.3、Lima 2.2.0、Docker CLI 29.8.1、Compose 5.5.1、Buildx 0.37.1。仅共享公开源码和新的作业目录，无用户主目录挂载；Docker 配置、socket、VM 独立，不启用登录自启动。VM 2 CPU / 4 GiB，未再次加载 35B 本地权重。

官方 hello-world 开发 smoke 全部保留：

- 初始缺 Docker 和错误解析 venv executable symlink 的启动失败：NOT_RUN，不删记录。
- 云端 smoke2：真实容器写入并读回正确内容；官方验证器因 DNS/依赖失败，LocalPilot、Nop 都 FAIL。
- smoke3：原保留预算内 VerifierTimeoutError，按 ERROR 保留。
- smoke4：在新记录中预先冻结 600 秒验证预算，官方两个 pytest 断言通过，但 Agent 在写入后调用缺失的 Python，触发部分副作用/UNKNOWN，Runtime incomplete，因此严格审计仍为 ERROR。没有把 reward=1 当严格成功。
- 最后 smoke5：补充通用环境提示——检查可选程序，写入与可选验证分开；不改 UNKNOWN 规则。真实模型完成容器任务，官方文件存在/内容断言通过。LocalPilot 严格 PASS 1/1，Nop 按预期 FAIL 1/1（0 个成功），审计完整且无异常；只报接入资格，不报 AA 成绩。

网络修复只作用于本轮 VM：缺失的 Ubuntu resolver target 由源 profile provision 生成，使用实际 DHCP DNS；私有 Docker client 采用已有主机代理。未改官方任务、验证器、答案或 Harbor SHA。每次改变代码/环境/预算均新建 study，n_attempts=1、max_retries=0。Mac 项目目录和宿主 registry-identity 没有 hello.txt，实际工具响应带容器执行位置，官方 verifier 独立检查容器状态。

候选官方验证通过后，再冻结 Terminal-Bench 2 官方仓库 commit `2fd12b88aafdd04a52c298e3940bcb189f9766d6` 的全部 89 个任务根：LocalPilot 与固定 Harbor Terminus2，同一 Qwen revision/量化，3 次重复，6 个作业，**534 个计划尝试全部 NOT_RUN**。study SHA-256 `e23dff95ae31b095ac4661f278affad440407e8e82c71f5427ae756b126e9c3f`。它是该 Git 快照，不是 AA 旧版 Hard 子集。

模型、上下文、输出、步骤/turn、官方任务时限倍率与重复次数均存入冻结配置；Terminus 外层重试与 LocalPilot 请求预算不完全等价，**同总请求预算资格尚未建立**，不据此作非劣结论。任务最大要求 4 CPU / 8 GiB / 10 GiB，超过本次 VM 配额及当前可用磁盘的安全运行条件；按用户内存提醒只冻结，不自动执行全量。正式产品对照、τ² Telecom 与所有能力排名仍 NOT_RUN。

## 真实使用量与失败历史

实际模型：本地 `mlx-community--Qwen3.6-35B-A3B-4bit`；云端 `deepseek-flash`，沿用既有私有 key reference。只有本轮合成文件/问题用于云端任务，没有把日常活动外发。统计见 RESULTS.json；所有三份资格数据库中的任务均计入，parent.model_calls 已含子 Agent，不重复相加。直接 provider、Companion 与受控 SDK 测试分别报告。费用未绑定逐请求账单，**实际云费用 UNKNOWN**；失败请求的 token/费用可能未报告，本地电力/设备成本也未知，不能当 0。

保留的失败包括：

1. 初次 Playwright 26/27：测试误用默认 Enter 发送；改按发送按钮后通过。后来原生发现既有 Session 草稿根本没存，新增 reload 断言稳定失败，再修复保存/恢复并重建 APP；最终 27/27。
2. 初次 Rust 缺生成图标；从 SVG 生成后通过，并把生成步骤放入构建源脚本。我在首个 shell 构建运行中编辑该脚本，导致读取偏移后出现 `m: command not found`；该失败保留，之后固定源码重新完整构建。
3. Channels 直接在子目录 build 缺打包输入；改用仓库既有 build_channels_wheel.py。后端资源第一次缺 watchdog、第二次 hash 不匹配，均被拒绝；保留失败暂存与日志，再重新生成。
4. 本地初次任务轮询过快触发 429，停服后已写的文件保留，任务 cancelled。未拿文件存在冒称整条任务成功。复测使用新 fixture 和较低轮询频率。
5. Qwen 若干权限/恢复任务虽写对文件，但额外无效 manage_goal 导致 incomplete；全部保留。权限矩阵用真实文件状态、受控审批与后续云端任务补全，不将这些 incomplete 改标成功。
6. 原生启动若未提供保护根，会被测试身份限制拒绝/可能中止；保留一次 SIGABRT 记录。带正确隔离环境的实际首次设置、重开和升级通过。测试路径的 launchd 曾 EX_CONFIG，使用现有 detached manager，不修改系统防护。
7. 云主/本地子完成后重启暴露 child thinking 误用父设置，整库恢复失败。只改为读取该 child 的已保存 thinking，78 项定向回归通过；原 9 Session / 10 Task / 2 child 恢复，未删库、未改指纹、未推理。之后快速真实 UNKNOWN 重启也通过。
8. 子代理取消首样本由模型给出过小 budget，在推理前被拒绝；另两次验收脚本分别用了错误字段、普通身份而得到错误/403。改用实际 live children 接口与 operator 后，本地推理确实中止。所有尝试保留。
9. Companion 首次活动查询早于实际索引、generic local-http 未关闭该模型 thinking 而截断；第二次 provider profile 的模型路径不匹配而 admission 拒绝。使用 oMLX 正确已加载 profile、等待实际索引后，accepted、真实回答和来源撤销通过；没有扩大轻量预算或编造已读取事实。
10. Core 中间一次 1436 项有 2 ERROR：磁盘低于附件入口 2 GiB 保留值，实际 HTTP 413。经授权清理后完整重跑为 1367 PASS / 69 SKIP。另一次 Companion BM25 本机 mean latency 0.025619 秒、retain=true；上轮 0.111 秒未过线的历史仍保留，未改 benchmark 门槛。
11. Harbor 单 arm spec、缺 Docker、venv 路径误解引用、VM 解压空间不足、DNS/代理、验证器超时及部分 Shell 副作用错误全部保留；旧结果不因最后接入成功而改标。网络/预算改变另立 study，正式任务未运行。

## 剩余具体阻塞与运行状态

- 正式 534 次比较未运行：需要符合任务 CPU/内存/磁盘与架构要求的 Docker 主机，并先资格验证两套 harness 的总请求预算对齐；不能用 hello-world 接入成功代替能力结论。
- 无 Intel 真机：完整 x86_64 依赖、APP、CPU 模型与吞吐仍缺。
- 旧 Skill schema 与 async_policy 的精确升级迁移、保留 child tree 的任意换模仍缺；没有强行绕过。
- 全产品统一 50 GiB 缓存机制仍缺；单个隔离 oMLX 的预算/重启命中不替代它。
- 无真实会议音频/转录与 Companion 原生 AX/TCC 授权数据：不声称全天会议/Codex 全历史感知。问候的时段/静音/去重有软件回归，原生晨晚/唤醒全天仍 NOT_RUN。
- 最后测试 Core/Companion 和仅 API 的 oMLX 保留运行，测试 APP 当前未运行，Docker VM 已停止并删除，公开源与全部 study 已归档；精确 PID/端口保留在本机 final-services.json；只停止和故障注入本轮确认的进程。快速重启时确认为 requires_human / UNKNOWN_BLOCKED；收尾已随原截止时间 timed_out，未决 intent 仍保留，不自动重放。

已复核[官方 11 月 14 日半决赛通知及附件](https://www.aicomp.cn/notice/notice-3/5856.html)：材料截止 **2026-11-19 23:59（中国时间）**；腾讯会议全队持续出镜，PPT+演示总长不超过 6 分钟、无快进无剪辑，以该最新通知为准。未合并、未发 Release、未替换日常 APP、未提交比赛表单。


## 收尾状态（中国时间 2026-11-15）

用户提醒内存后没有再加载 35B：本轮 API 的实际 model loaded=false。Docker VM/辅助网络均回收，原始实验备份为 `.private/harbor-all-studies.tar.gz`，不移动或改写原冻结记录。日常 APP 收尾树摘要仍与开始相同。独立安装可用本机 `.private/open-final-test-app.command` 在保护根环境打开；不是日常 APP，也没有新建桌面别名。
