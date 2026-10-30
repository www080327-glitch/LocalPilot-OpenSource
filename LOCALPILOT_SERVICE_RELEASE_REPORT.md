# LocalPilot V4.9 Agent Service Packaging & API Integration

2026-10-13，Asia/Shanghai。基线 HEAD `ad886b598b3ab0da4ca0849f1ae9b52e3170de28`，分支 v2-computer-use。**SERVICE_PACKAGING_SCOPED_GO = YES；RELEASE_CANDIDATE_ADMISSION = SCOPED_RC_GO（以下已公开 Agent Service 契约范围）。** 未 push，未创建或移动任何 tag。候选发行包 `localpilot-agent-service 4.9.1rc2` / 建议 Git tag `v4.9.1-service-rc2`；没有创建 tag。原rc1归档保留。

Implementation / 修复 commit：`b47a4953`；之前的权限修复 `628bec4a4c0aa478f1eb8b89fd8b57808185f572` 保留。详情在 `docs/evidence/agent-service-20261013/release-metadata.json`。最终归档与报告提交独立于代码修复提交，避免用自引用 hash 冒充实现版本。

## 实际交付

独立、认证、默认 loopback 的 service 入口和私有配置向导；现有 Responses/Chat 文本 facade；原生 Task/Session/事件/审批/接管/恢复/取消；按客户端命名空间的持久幂等；随 Session 原子持久化的 owner subject；认证 scopes、operator approval_for 绑定、客户端速率/活动任务/连接限制和全局 bounded handlers；不保存 credential/prompt 的审计；沿原 Hybrid Cloud Egress Policy。

南向继续使用已有 Chat Completions Backend，增加受校验的 host generation 参数及恢复 fingerprint；选择 explicit/preference/automatic、不可用/能力不足/未部署分开记录，无静默 fallback。Model Manager 独立合同、默认拒绝下载的 ResourceGrant 与受控 job adapter、认证 HTTP transport 已交付；没有安装 vLLM、下载权重或运行不可信代码。

可独立分发的 localpilot-agent Skill + portable HTTP/MCP Adapter；Python SDK、TypeScript/JavaScript 示例、Tk GUI、Companion 示例与独立 operator terminal。Companion 仅调用契约，不合并监听/消息路由/轻量模型。OpenAPI 3.1、配置模板、启动/停止/health/诊断/backup/restore 与 host 安装说明已完成。

所有 Runtime 工具仍由原 AgentSession/Registry/Gateway 执行。没有重做调度、推荐器或 Computer Use。原核心改动只在 service record/lifecycle 与 HTTP projection：owner/元数据 additive fields、scope-aware handler seam、Backend service_contract fingerprint 和已配置 verifier 的失败/未知状态投影。既有 Backend 无新字段时配置 hash 保持原形，旧单身份 API 行为保留。

## 架构审查

读取 V4.9 最新报告、docs/RUNTIME_API_V2.md、OPENAI_API_COMPATIBILITY.md 与 TaskService/Session/Gateway/Router/Backend/SQLite/Hybrid owning source。请求中 RUNTIME_API_V2.md 实际位于 docs/；EXTERNAL_AGENT_SKILL_V2.md 当前仓库不存在，经定向搜索确认，改为交付新的独立 Skill。

当前已有：persisted Tasks/Sessions、dispatch 前 intent、effect/read receipts、epoch-bound approvals、UNKNOWN quarantine、safe resume、cancel、native cursor SSE、部分 OpenAI 文本兼容和 Hybrid Egress。旧兼容报告中“幂等/持久化 unsupported”落后于当前源码；没有重新实现这些机制。仍未宣称完整 OpenAI schema/tool-calling/Conversations/reconnect 兼容，保持未知 usage=null 与原扩展状态。

V4.9 Cloud collaboration 的实验 NO 结论保持；此轮 service packaging GO 不代表多 Agent、更快推理或平台安全结论。

## 真实 E2E

| 客户端/路径 | 实测结果 |
|---|---|
| 普通 curl、Python、JavaScript | 真实 HTTP → DeepSeek cloud → read_file → 当前内容/收据，PASS；多轮、native events、原键重试有原始记录 |
| GUI | 真 Tk button driver → 同一 API/cloud，PASS；未做长期视觉/交互认证 |
| Companion | 独立示例进程 + cloud/events，PASS；Companion identity 的审批交还和12文件恢复；不代表 QQ/微信集成 |
| Codex | 实际加载 Skill，HTTP CLI Adapter → LocalPilot → cloud/read_file → trusted host verifier → Codex，PASS |
| DSH | 实际 headless Agent 加载 Skill，MCP → 同服务/cloud/read_file/verifier → DSH，PASS |
| service process recovery | 原 Task/Session/SQLite，由新 PID 恢复审批，旧 ticket409，12个精确文件、12写收据/24工具收据，verification passed |

最终 Harness 证据为 `harness-authority-sealed/`；两个 outer Agent exit0、状态 quiescent/completed、文件标记真实返回、verification/engineering passed。源码与 Skill source-before/source-after 相同。最后另补齐非默认 Session 的 model 省略亲和性，以及未部署模型创建 Session 的409拒绝，均由新控制和源码绑定全量回归验证。Host verifier 仅认证公开 fixture 的当前 SHA/最终文本，不扩展为通用需求认证。普通客户端初期 verifier 未启用，engineering=unverified，严格区分。

Codex **MCP submit 本身没有通过真实 E2E**：非交互宿主审批拒绝，两个原始失败保留。HTTP readonly sandbox 随后又因网络禁止未提交。最后在独立临时 caller workspace 开启该宿主的网络许可，通过既有 Skill HTTP adapter；服务端 route/token 仍为 read-only，不能 write/execute/operator approval。没有修改用户已有 Codex 配置/进程或将 ordinary token 变成 operator。

真实 Responses background + 持久 Chat SSE 另在 `protocol-cloud-actual/` 验证。LocalPilot 通过现有本地 Chat API 的真实 loopback/scripted model 合同通过，真正关闭 endpoint 的 connection failure 也保持 failed/fallback=false。真实本地资格已在22:31/22:38补齐，见下文。支持的local/cloud选择在同一服务的独立Session中实测；运行中跨Backend handoff和真实vLLM仍 NOT_RUN。模拟合同不替代真实模型证据。

## 发现、修复与全部失败

独立长任务首轮模型只返回计划：非文件工具 body 被 egress policy withheld，模型索要额外确认，文件未交付；API 还把 completed model turn 与 verifier unknown 一起呈现为 completed。这条原始失败保留，service 现在将已配置 verifier 的 unknown/failed/blocked 映射 incomplete，并继续保留 result.runtime_status。新增 unknown/failed/blocked 三种控制覆盖 OpenAI retrieve 与原生 Task，未改变旧单身份 API。

第二轮真实重启成功后，driver 200ms polling 触发既有120/min限流429；不是 service 取消保障失败。最终低频查询，不提高限制、不自动重放写入，完成12文件。其成功只限 bounded planned SIGTERM，在审批 yield 边界，不是断电、数小时任务或 distributed exactly-once。

最后的配置校验补丁拒绝 truthy 字符串 operator/工具能力与非有限、负值资源预算，避免无效配置变成授权；正常已验路径不变。

初次 UNKNOWN fixture 的 wrapper 在实际 mutation 前错误抛异常，测试 driver 修正后通过，原 tests-first.txt 保留。Verifier 开发期 import error 已修正。Codex 上述 MCP/network 拒绝全部保留。早期 codex-network-verified derived matrix 的 MCP 分类是元数据错误，原 transcript 为 HTTP；最终矩阵正确分类，原文件未覆写。

## 回归与省电范围

| 检查 | 结果 |
|---|---|
| sealed all-source-bound regression，官方 SDK 2.29.0 environment | 938 tests，0 fail/0 error，1 optional JSON Schema validator skip；source unchanged=true（full-local-qualified） |
| 新 service/security/Backend/manager/backup/deploy/verifier 控制 | 23/23，在宿主环境包含该 JSON Schema 验证；与 SDK 环境的 skip 互补 |
| strict | 11/11 scripted controls |
| V1.4 stabilization | 51/51 controls，36 ablations |
| Skill validation | PASS |
| real external Harness final | Codex HTTP + DSH MCP 两项 PASS，fixed file verifier scope |

全量最终 runner 单进程，100ms idle/test，elapsed190.53s，own CPU23.98s，own peak RSS249,741,312 bytes。这只是本进程指标，不是整机电量/功耗测量。前期928/933/936项日志也保留，不替换最终938项分母。strict/stabilization/scripted model API 均非模型能力成绩。

21:00 前没有本地大模型推理、GPU/Metal高负载、大规模编译、压力测试或大规模并行 campaign。未修改 Clash Verge/代理/TUN/系统电源设置；仅停止由本轮自行启动的 LocalPilot test service PIDs，没有停止用户模型或 Companion 服务。Cloud/API 用已有受保护 credential resolver，没有读取到工具输出、复制或移动 provider key。模型输出不能自批准。

## 剩余准入项与发布方案

G与支持的I选择资格已补齐。RC准入限于文档中可部署的Agent Service接口：真实客户端/外部Harness→服务→既有Gateway/Runtime→本地或云端Backend；选择新的route需新Session，持久Session不允许换route。未开展同一运行中Session的Hybrid handoff、真实vLLM、压力/小时级本地运行、QQ/微信集成或GUI长期UX认证；这些仍NOT_RUN，不作为已交付API的支持声明。V4.9多Agent实验NO结论不变。

一次heartbeat后续任务已执行；用户随后指出未运行本地模型，按原21:00后本地验收授权，核查已缓存且已支持的Qwen模型/已安装oMLX，创建独立认证验收服务。没有安装、下载、替换用户模型或调整系统设置。此次补验完成，不重复自动执行。

4.9.1rc2新增一个host配置连接，将既有Backend的include_stream_usage选项透传并纳入恢复fingerprint，默认false保留旧行为。新归档使用独立rc2文件名；原rc1不覆盖。建议版本/tag仅是发布方案，不push、不创建/移动tag。归档仍按显式whitelist制作，不含credentials、权重、运行DB或历史evidence副本。

完整矩阵：[AGENT_SERVICE_E2E_MATRIX.md](AGENT_SERVICE_E2E_MATRIX.md)。部署：[SERVICE_DEPLOYMENT.md](SERVICE_DEPLOYMENT.md)。API：[AGENT_SERVICE_API.md](AGENT_SERVICE_API.md)。Backend：[MODEL_BACKEND_API.md](MODEL_BACKEND_API.md)。Manager：[MODEL_MANAGER_CONTRACT.md](MODEL_MANAGER_CONTRACT.md)。Companion：[COMPANION_CLIENT_CONTRACT.md](COMPANION_CLIENT_CONTRACT.md)。原始证据、private state 指针和 archive SHA 见 release-metadata/evidence manifest。

## 21:00 后补验（2026-10-13 21:45，Asia/Shanghai）

交付源码与修复 commit 628bec4a 的封存散列全部一致，tracked 工作区未有后续产品改动，stable tag 引用未改变。当前不存在 serving-profile.json；已知历史 host 配置的8020和8048各两次TCP检查及一次GET /v1/models均拒绝连接（errno61）。这只证明两个已知端点当前不可达，不能推断所有其它端点或磁盘上的模型不存在。认证、实际部署/加载模型、tool/streaming/usage 本地资格无法完成，明确 NOT_RUN；没有启动、加载、下载、切换或停止用户模型。

利用上述真实预检结果将测试 Registry 的本地 route 标记 unavailable。显式本地提交返回409 model_unavailable，Task 数为0；偏好[local,cloud]记录local/model_unavailable → cloud/selected，backend_fallback=false，并由真实DeepSeek执行一次只读fixture读取，trusted verifier passed。这里验证的是北向 admission/选择与显式追踪，不是本地推理、已运行Task的跨Backend handoff或真实vLLM。

21:45这一步的完整RC仍为PENDING_REAL_LOCAL_BACKEND_E2E，当时需要ready endpoint/实际model ID/认证引用。该预检只增加driver和证据，未修改产品。之后用户继续本地验收，22:31起的独立服务补验取代当前阻塞状态；本段及原始preflight保留为历史事实。原rc1归档保持原字节及散列。

原始检查与任务/事件/Provider usage：docs/evidence/agent-service-20261013/post-window-20261013T214544+0800/。

## 本地真实模型补验（22:31–22:39，Asia/Shanghai）

模型为已缓存的Qwen3.6-35B-A3B-4bit，snapshot `38740b847e4cb78f352aba30aa41c76e08e6eb46`，权重20,402,204,271字节；已安装oMLX 0.6.4。静态检查缓存/模型卡声明/本地架构支持和磁盘、64GiB主机内存，再以独立base-path和单模型symlink启动本轮拥有的loopback8048服务。离线环境阻止Hub下载，认证token只在进程环境内，配置/日志不保存值。最大并发1、模型内存guard26GB，swap增长超过1GiB即只停止自有进程；未使用历史prepare/restore helper或用户全局model settings。

先确认未认证/v1/models返回401，精确model ID在catalog且/api/status loaded_models为ready；然后经LocalPilot服务提交固定fixture只读任务。服务器端read权限/Gateway/LOCAL_ONLY egress执行，只有1次read_file，无写入、命令、子Agent或UNKNOWN效果。当前fixture SHA、read receipt和最终标记由trusted host verifier与独立artifact audit确认；Task completed、verification/engineering passed。

首次真实本地任务PASS，但流式provider usage为null，保留为UNKNOWN。发现packaging配置未透传既有LocalHTTPBackend.include_stream_usage；最小修复后再跑同类固定只读任务，仍为1次read_file、2次模型请求，native SSE 30事件。Provider报告input/output tokens分别3533/25和4406/32，oMLX独立status的total_requests=2、total_prompt_tokens=7939、total_completion_tokens=57，与Task usage一致。缓存统计仍UNKNOWN/null，不据此估算费用或推广吞吐。

同一Agent服务通过显式cloud route在独立Session中执行相同fixture只读任务，真实DeepSeek+trusted verifier PASS，route selected=cloud、fallback=false。此前真实本地端点不可用时的409拒绝/偏好cloud证据仍有效。持久Session换route按既有契约返回409 route_conflict，无新Task/推理；这是admission控制，不是运行中Hybrid handoff。

原综合driver结果FAIL原样保留：内部previous_task_id字段收到正确400；随后检查已停止的原Session收到正确409 session_closed；新Session确实收到409 route_conflict，但driver原先预期错误码字符串不同。最终按既有TaskService契约和原生session_id完成独立无推理控制，PASS。没有重评或重跑已完成的本地/云端Task，原Task的trusted verification早已passed；独立qualification-audit分项核对当前文件/收据/usage/选择，PASS_SCOPED。新增unit fixture首次直接传text而非TaskRequest的driver错误也保留，修正后相关43项控制PASS。

两次验收仅停止本轮创建的模型服务PID42796/42958；没有停止用户模型或Companion。第二轮vmmap physical footprint ready19.6G、结束20.1G、peak22.8G；整个监控期间swap固定1,708,916,736字节，增长0。oMLX预填充max_bytes警告保留，无资源abort、未执行日志建议的sysctl调整。最终active_requests/waiting_requests为0，拥有的模型进程已退出，8048 listener关闭。

证据：`local-real-20261013/`保留原usage未知结果；`local-real-usage-20261013/`保留模型部署/ready状态、完整Task、SSE、usage、vmmap/swap、原driver失败及最终qualification-audit。此次补丁相关控制已PASS，最终源码绑定全量回归见full-local-qualified；strict/stabilization owning Runtime源码未改变，沿用原11/11、51/51+36证据，不为文档/证据重复运行模型。
