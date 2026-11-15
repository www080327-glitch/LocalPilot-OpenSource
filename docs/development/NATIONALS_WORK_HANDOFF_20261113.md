# LocalPilot 国赛前整改：Work 接力任务（2026-11-13）

> 本文是未完成工作及验收操作单，不是已通过测试的结果。以 GitHub 实时 HEAD 与真实运行环境为准，不能将任何 `NOT_RUN` 写成 `PASS`。

## 2026-11-14：最新 1920 项全量通过后，剩余真正阻塞（请先看本节）

最新已在 Mac 运行的测试来自分支 `776061975ab91c1a7cf3d08dd6fd3eeee5b718d6`：Python `unittest discover -v` **1920 项、0 FAIL、0 ERROR、63 SKIP**；其中 12 个历史 benchmark 模块是模块级 NOT_RUN，不能记为 12 个模型评估通过。权限及独立审计指定组 126 PASS；基线 Vitest 49、TS/Vite PASS、Playwright 25（浏览器合成桥）、Rust 40 PASS / 3 ignored（空打包资源）。详细实测记录在 `docs/evidence/nationals-20261114-current-validation/RESULTS.md`。测试退出仍有一项 `subprocess ResourceWarning`，根因未确认。**此记录只适用于相应源码 HEAD，后续提交尚未重新测试。**

此后在 GitHub 上的补充修改：
- `tests/test_runtime_api.py` 增加实际 `TaskService + HTTP + StreamBackend` 的 SSE 保留窗口溢出 409 → 已授权运行中快照完整 `streamed_text` → 以 `last_event_id` 续收新增 TextDelta、模型只执行一次的回归。它不是 Rust/Tauri 原生端到端验收。
- `desktop/src/domain.ts`、`desktop/src/App.tsx` 与 `desktop/tests/domain.test.ts`：只有 `reconciled` 快照的 `last_event_id` 不早于 GUI 已观察 SSE 序号时，才替换流式正文，避免旧 409 快照回退较新文本；新增对应 Vitest 测试。
- 模型菜单说明从“已就绪”修正为“**已配置且声明支持工具；在线状态未验证**”，防止把 Core 的 `operator_configuration_not_live_health` 说成真实 Endpoint 健康。
- **离线打包具体 blocker**：`desktop/runtime-dependencies.json` 锁定 `watchdog-6.0.0-cp314-cp314-macosx_10_15_universal2.whl`、SHA256 `df0771e22978c47029f34141bb9aa0a9b868191265d980766949aefc9080ff2c`。截至本次核查，[官方 PyPI watchdog 6.0.0 文件清单](https://pypi.org/project/watchdog/6.0.0/#files) **没有 CPython 3.14 wheel**（该版本 2024 年发布，官方 macOS 构建仅见到 cp313）。因此镜像/官方索引不可能直接下载这份精确 wheel；旧 APP 的同哈希文件不能证明官方来源。详见 [Issue #8](https://github.com/www080327-glitch/LocalPilot-OpenSource/issues/8)。不能盲改锁定版本/哈希来“通过构建”。
- 产品继续遵守公开 GitHub 单一源码主线：历史发布用**经过核验**的 Tags/Releases，短期本机工作树仅为真实构建和运行，未经审阅不搬迁旧私有仓库全历史。

### Work 现在只处理仍未完成的真实工作

1. 先核对**最新 PR HEAD**、本机 worktree 未提交内容及是否有并行任务。继续复测上述三处新测试和完整 Python/Vitest/TS/Playwright/Rust，记录新的实际结果，不能直接复用 `7760619` 的旧 PASS。
2. **P0 打包来源修复**：按 Issue #8 审计锁文件里 watchdog cp314 轮子的来源/二进制标记。若来自可信的源代码本地构建，则建立源码 SHA、可重复构建命令、wheel 哈希与许可链；若选择升级到官方支持 cp314 的新版，先在实际 macOS 3.14 环境验证全部 Core/Companion 文件观察及原生功能后再调整依赖锁（生成文件走源头）。生成和检查**真实非空** `bundled-backends`，不得拿日常 APP 中来源未核实 wheel 冒充新候选。
3. 在独立 macOS Bundle ID 测试槽验证原生任务/子代理取消和 UNKNOWN 收据、SSE 409 端到端（完整回复 + 新增事件）、重启恢复、四档真实文件与 Shell 边界、模型下载/加载和首次安装。只有真正完成测试的部分标记 PASS。
4. 继续追踪 [Issue #6](https://github.com/www080327-glitch/LocalPilot-OpenSource/issues/6) 的同会话无损模型切换和**真实**本地↔云端双向协同，以及在线模型健康；[Issue #7](https://github.com/www080327-glitch/LocalPilot-OpenSource/issues/7) 的单次升级/回滚、50GiB 仅自有可重建缓存和减法式架构清理。大改另开聚焦 PR。
5. `ResourceWarning` 根因仍未知：先从本机原始 `python-full-current.log` 或最新日志定位具体 Popen/进程及复现场景；必要时针对该测试在独立环境开启 Python 的 ResourceWarning 报错定位，不要猜测 PID 或引入无关子进程管理框架。
6. 明确说明无法核验的每项受哪些真实条件阻塞。保留 Draft、main/Latest/日常 APP 和用户全部数据。不得私自删除 Mac 旧安装包或复制私有历史真值。

## 2026-11-14：公开主线与最后五项权限失败的后续修复（需复跑）

最新 Mac 已记录的完整 `c3c8dc9` 复测为 **1913 项，5 FAIL、13 ERROR、51 SKIP**。这只是旧 HEAD 的实际结果，以下新提交**尚未重新执行真实仓库回归**，绝不将其标成 PASS。

- 五项剩余失败已给出明确的分层修复：`agent/safety.py` 把 `.localpilot/secrets` 作为任何权限模式下的宿主凭据硬边界，同时允许已明确选择 Full 的普通 `.env`/dotfiles 依照 macOS 用户权限读取；`agent/scope_permissions.py` 在工作区外的一次性访问也执行凭据路径拒绝；`PermissionGateway.decide` 对未知 risk 即使 Full 也要求审批。已针对 file_info/search_text/read_file/apply_patch、符号链接、Session、rev3 scope 的真实代码路径补测试。**此限制针对内置文件工具；Full Shell 仍是当前 macOS 用户的 OS 权限，并非独立文件读取沙箱。不要把模型文件工具的拒绝误读为对任意 Shell 命令的沙箱保证。**
- 公开源树缺 `benchmarks`：13 个历史 benchmark 测试模块新增统一的 `tests.optional_benchmarks.require_benchmarks()`，无包时 `unittest` 标记 **SKIP / NOT_RUN** 而不是导入 ERROR；有包时运行原测试，不跳过真实运行失败。已单独在临时 unittest 夹具中验证 `SkipTest` 导入期间会被统计为 skipped，**未运行公开仓库完整 1913 测试**。缺少的 benchmark 本身仍未迁入公开树，见 [Issue #3](https://github.com/www080327-glitch/LocalPilot-OpenSource/issues/3)。
- 公开源码和历史：本仓库实际为 **Public**。新的正式发行只按 GitHub Tags/Releases 追溯。原私有历史仓库只作参考；需先审查凭据、隐藏评测、第三方许可证，不能直接整体公开。GitHub Release 历史回填见 [Issue #4](https://github.com/www080327-glitch/LocalPilot-OpenSource/issues/4)。
- GUI 更新器 `desktop/src-tauri/src/maintenance.rs` 不再请求旧私有 GitHub Release 或信任旧下载域路径；已转到本公开仓库，且预发布和 Draft 仍不可成为稳定自动更新。已同步更新 `VersionManagement.tsx` 文案和 Rust URL/预发布测试。**当前公开 Release 只有 RC 预发布可确认，不应伪造稳定最新版**；旧 `desktop/recommended-release.json` 留作历史 5.0.0 来源证据。
- `README.md`、`.gitignore`、`docs/development/GITHUB_RELEASE_HISTORY_POLICY.md` 已明确：GitHub 保存后续源代码和已验证历史版本；本机仅为实际测试/构建保留短期工作树、依赖缓存与原始日志，严禁未经审批删除历史用户文件。当前无法从本会话检出 GitHub 公开仓库执行真实全套测试，故 **NOT_RETESTED**。

Work 直接在当前独立 Mac 工作树重新获取 PR 的实时 HEAD 后，**第一优先级**运行：

```bash
.venv/bin/python -m unittest -v tests.test_file_info_observation tests.test_runtime_session tests.test_workspace_grants tests.test_desktop_permission_v3 tests.test_scope_escalation tests.test_runtime_permissions
.venv/bin/python -m unittest discover -v
cd desktop && npm test && npm run build && npm run test:ui
CARGO_BUILD_JOBS=1 cargo test --manifest-path src-tauri/Cargo.toml
```

特别核对 `.localpilot/secrets` 的真实工具读取、Full 普通 dotfile、Full 未分类风险必须审批、13 个 benchmark 在公开检出中明确跳过，Rust 公共 Release URL 检查和真实稳定版缺失时的状态。注意 Rust 仍用空 `bundled-backends` 编译仅算受限测试，**不具备打包发行资格**。所有新运行结果独立记录日期、SHA、PASS/FAIL/SKIP 和真实限制。

## 2026-11-14：后续自助修复与 Work 最小待办（最新）

本轮之后又在同一 Draft PR 做了两个可直接确认的源代码修复（但**尚未复测最新 HEAD**）：

1. `scripts/aic_summarize.py` 原来在模块导入时就加载历史 `benchmarks.hybrid_accounting.CostLedger`，这使本可独立运行的 `tests/test_aic_score_audit.py` 也被整体 SKIP。现把 CostLedger 仅在历史报告 CLI 的 `main()` 内导入，删除该评分测试的 SKIP 入口。剩余 **12 个**确实依赖缺失历史 benchmark 的测试模块仍显式 SKIP/NOT_RUN。迁移安全公开历史源码见 [#3](https://github.com/www080327-glitch/LocalPilot-OpenSource/issues/3)。
2. `desktop/src-tauri/src/maintenance.rs` 查询公开 GitHub 成功但无稳定 GUI Release 时，原先返回网络/状态 `UNKNOWN`；现在区分 `NO_STABLE_RELEASE`，公开页面仍可打开，不允许在没有真实正式制品时进行本地安装包校验。前端 `VersionManagement.tsx` 显示“尚无正式版”，不把 RC/Draft 冒充 Latest。这个新状态与 TS/Rust 改动仍须实际运行验证。

剩余有清晰 GitHub 任务跟踪：

- [#5｜P0 全量回归、macOS 独立 APP、SSE 409 / 取消 / 恢复验收](https://github.com/www080327-glitch/LocalPilot-OpenSource/issues/5)
- [#6｜P1 同会话跨模型迁移与真实云本双向协同/在线健康](https://github.com/www080327-glitch/LocalPilot-OpenSource/issues/6)
- [#7｜P1/P2 一次升级回滚、50GiB 真正受管缓存、减法式清理](https://github.com/www080327-glitch/LocalPilot-OpenSource/issues/7)
- [#4｜已核验历史版本迁入公开 GitHub Release](https://github.com/www080327-glitch/LocalPilot-OpenSource/issues/4)

**Work 先做 #5**。最新 HEAD 尚无 CI，不要引用 `c3c8dc9` 的 “1913 项 / 5 FAIL / 13 ERROR” 作为新 HEAD 的复测结果。新 HEAD 应证明 Full 的服务凭据读取边界、Full 未分类风险只能单次批准、12 个 benchmark 模块 SKIP、独立 score-audit 模块真正 PASS、UI/Rust Release 没有稳定版时不误报 UNKNOWN。所有真实运行命令、源码 SHA 和结果保留在 Mac 验收目录，脱敏摘要写到 GitHub PR。

## 仓库与保护边界

- 产品主线：`www080327-glitch/LocalPilot-OpenSource`，目标 PR **#1**，head `fix/nationals-runtime-ux-20261113`，base `main`。
- 开始前核实 PR、实际 HEAD、main、未推送/未提交工作树、运行中 APP/Core/Channels/wheel 版本、当前已有 Work 任务，避免覆盖或交叉修改。
- 私有 `www080327-glitch/LocalPilot` 的 `codex/desktop-rc7-oneclick-20261029` 为历史产品源码来源；`LocalPilot-AIC-20261030-Frozen` 为不可回写的初赛存档。仓库审阅可以跨仓库，修改只进授权的 PR 工作树。
- **不合并 main、不替换 Latest、不覆盖日常 APP、不删除缓存/模型/任务收据/凭据**。仅在 macOS 独立测试槽安装候选。严格执行 `desktop/AGENTS.md` 与现有发布、备份、回滚流程。
- 不创建第二套 Runtime/Router/权限或状态管理框架，不复制已经完成的工具动作，不为了很小概率的竞态引入额外状态机；外部输入只在入口验证一次。

## 已写入 PR #1 的内容（需实际回归）

1. 上下文 token 准入：`agent/context_budget.py`、`context.py`、`context_v5.py`、`session.py`、`hybrid.py`、`vllm.py` 等；旧 turn 字节账本保持独立。中文回退估算已比 UTF-8 每字节一 token 更积极。核对具体本地 tokenizer 支持率及过窗边界。
2. Cooperative 有界本地试用，云端主模型可配本地伙伴，云端/本地双向委派复用已有 HybridController。已新增 cloud-primary route 的返回切换预算逻辑。
3. 偏好保存失败恢复、UNKNOWN 只阻塞原 Session、符号链接与 Full 授权、Shell 长时限/Schema；`dcfe21d` 已将 Session 手动取消信号接入 Shell 进程组停止，原生 GUI/子代理取消及 UNKNOWN 持久验收仍待完成。
4. 显式跨模型切换仍采用明确的新会话，不虚构 canonical history 已迁移；本地模型加载失败不再先丢失当前会话；从显式路由选择 Core Auto 也会新开会话而非继续绑定旧模型。
5. 项目组织/置顶、模型列表只展示 ready+tool_calling+来源允许的注册路由；注意 `ready` 并不是在线健康证明。
6. 底部本地/云端**请求次数**占比与子代理侧栏，运行中统计包含 `SubagentEvent` 嵌套调用，完成后采用服务端持久汇总，不假装是 token/费用占比。
7. SSE 重开 GUI 后支持 `after=0` 重放、事件序号去重；服务端任务快照在运行中暴露 `streamed_text`，过保留窗口的 `reconciled` 快照用于重建全文并续接新事件；工具不重放。

## 2026-11-14 续接进度与下一次 Work 必办项

原生工作区验收见 `docs/evidence/nationals-20261113-acceptance/RESULTS.md`（当时 HEAD 为 `dcfe21d`，不能把旧结果当后续改动通过）。已确认当时：指定 Python 93 PASS；Vitest 49 PASS；TS build PASS；Rust 40 PASS/3 IGNORE（用空资源目录仅证明测试构建）；`test_host_tools` 4 FAIL/1 ERROR；浏览器 UI 17 PASS/8 FAIL；真实 APP、真实模型、SSE 409 原生全链路 NOT_RUN。

本轮在其后修改：`desktop/src/App.tsx` 空白新会话也重置会话偏好；`tests/test_host_tools.py` 对 Full 当前系统用户读写/联网的旧断言与系统临时目录外的写入夹具做针对性更新，并将 Workspace 模式内 Shell 免审批、Request 模式拒绝动作必须审批、Full `http_get` 真实 PermissionGateway 准入分别测试；`tests/test_vllm_cooperative.py` 将未发布的 `benchmarks` 依赖隔离为**显式 SKIP**，其余公开 Runtime/VLLM/Cooperative 测试不再因导入整个套件失败；`desktop/tests/ui/channels.spec.ts` 走新版高级渠道入口；`desktop/tests/ui/installation.spec.ts` 跟随当前安装按钮与高级工作区入口。**全部是新增提交，仍 NOT_RETESTED，不得改写以前的验收结果。**

下一轮执行顺序：

1. 先获取**新 HEAD**并查看本地 Work 测试路径 `/Users/perry_guo/Desktop/aic竞赛/LocalPilot-nationals-acceptance-20261113` 的状态。不要强制重置该工作树。用原始失败日志与新的运行结果逐项比较，分别记录每个失败测试的名字、断言、实际表现、根因和结果。
2. 先在现有项目流程中重跑 `python3 -m unittest tests.test_host_tools tests.test_vllm_cooperative tests.test_nationals_runtime tests.test_runtime_api`，再执行 `cd desktop && npm test && npm run build && npm run test:ui`，补跑 Rust 与全套 Python。**尤其检查**权限 v2/v3 的兼容语义、不同位置的写入夹具、DNS 的环境映射与网络访问实际权限、ChannelSettings 的 4 个高级入口测试、空白新会话、安装新流程、权限 Popover 的 Escape 焦点恢复。
3. 若测试仍失败，按**真实代码/真实 UX**逐项修复，不要仅删除断言。工作区写入 Shell 的临时目录例外须查清：Mac `TMPDIR` 可以用于程序正常临时文件，但不应把任意工作区外用户文件默认为已获全盘授权；先写一个真正位于临时根之外的 OS 写入对照，再决定是否需要最小源码更改。若有行为调整，说明对用户是否增加弹窗。
4. **真实应用构建的阻塞**：先只读确认磁盘剩余（上次约 1.8 GiB）及每个目录归属，检查 `~/Library/Caches/LocalPilot-Qualification` 约 8.4 GiB 的内容、运行进程与引用关系；**不能仅凭目录名称删除**，需要向用户列明明确的可回收内容、影响、大小后取得许可。核验 `bundled-backends` 真实产物和图标来源，空目录绝不可作为发布物。构建独立 Bundle ID 的测试 APP，不覆盖每日使用版本。
5. 原生 GUI 的 SSE 409、模型加载失败、Auto Route、子代理取消、Shell 用户取消/UNKNOWN 幂等，完整验证并记录实际日志。云主→本地子、本地主→云端子、Cooperative Local→Cloud 用**真实模型**评估后再对节费/成功率作声明。
6. 同会话模型迁移、在线模型健康、GUI/Core/Channels 一次升级回滚、50GiB 真正受管可重建缓存预算、Runtime/前端减法式解耦仍待独立实现。优先解决 PR #1 回归阻塞；架构/升级/磁盘等大改不悄悄扩成一个 PR。

## 2026-11-14 最新复测与后续静态修复（需要立即复测）

最新上一轮 macOS 验收实测见 `docs/evidence/nationals-20261114-retest/RESULTS.md`。当时：权限/Shell 和 Cooperative 30 PASS/3 SKIP、指定 Python 107 PASS/3 SKIP；全量 Python **1884 项、20 failures、80 errors、52 skipped**；Vitest 49 PASS、TS/Vite PASS、Rust 40 PASS/3 ignored（空资源目录仅供受限编译）、Playwright 25 PASS（合成浏览器）。真实原生 APP、模型、SSE 409、升级回滚未验收。**此后新增提交尚未重新运行以上任一测试，仍标记 NOT_RETESTED。**

本轮补充的可审计修复：

- `agent/registry.py`：`dispatch_access` 仅在明确的 Full gateway 模式开启，不再因 `scope_revision=3` 就解锁受保护文件检查；否则 Request/Workspace 也可能读取 `.env`。
- `agent/scope_permissions.py`：rev3 工作区外访问提议也继续检查敏感路径和 private roots；原先 `revision!=3` 条件造成跳过。
- `tests/test_desktop_permission_v3.py`：Request/Workspace/Isolated 都不能通过 rev3 在工作区内外读取 `.env`；明确 Full 是不同的主机授权。
- `agent/context_v5.py`：完整 Host state（含原任务、未决义务、历史遗漏哈希）在 token/byte 窗口内时，不再因冗余的独立 compaction checkpoint 不够空间而报过窗；省略 notice 保留在原有受保护状态中，并用边界测试验证。
- `agent/context.py`、`agent/context_v5.py`、`agent/harness_context.py`：在确实使用 backend chat template 做 token 计数时，压缩报告不再错误标成 mixed-text fallback；新增有 tokenizer 的压缩及 optional-state 回归。

**Work 第一优先级：** 从 Mac 工作树读取原始 `docs/evidence/nationals-20261114-retest/python-full-venv.log`，对 20 failures/80 errors **逐项分类实际用例与根因**（文档依赖/未公开 benchmark/权限边界/上下文压缩/恢复/并发及其他）；不要把没有 traceback 的缺陷推断为已修复。先复跑下面的定向组，再完整全量；任何失败先修原因再重跑：

```bash
python3 -m unittest tests.test_desktop_permission_v3 tests.test_scope_escalation tests.test_host_tools tests.test_context_v5 tests.test_v49_context_cache tests.test_harness_context tests.test_computer_runtime tests.test_finalization_recovery tests.test_native_recovery_v3
```

关于 Full：明确区分**主机系统用户文件权限**、`private_roots` 的宿主专用数据（如凭据）、`DataPolicy` 云出站授权和 Shell Seatbelt 仅约束写入的事实。旧 Full 对 `.env` 的允许用例与旧凭据硬边界测试存在产品契约冲突，不能直接删掉全部安全测试或反向更改产品权限。先记录精确失败调用链及可复现的权限影响，再就真正跨越已承诺硬边界的行为做最小修正；不要未经批准添加全新应用沙箱或额外权限确认。

**磁盘与发布仍阻塞：** 上次剩余约 1.3 GiB；`LocalPilot-Qualification` 约 8.4 GiB 暂不能证明每项可安全回收。不要清理、不打包空的 `bundled-backends`、不覆盖日常 APP、保持 PR Draft。

## 第一阶段：先完成静态/构建与测试验收

在**完整 Git 检出**、现有仓库工具链与可明确证明的独立执行环境中，先执行：

```bash
python3 -m unittest tests.test_nationals_runtime tests.test_context_v5 tests.test_harness_context tests.test_v49_context_cache tests.test_vllm_cooperative tests.test_cloud_local_partners tests.test_runtime_api
cd desktop
npm ci
npm test
npm run build
cargo test --manifest-path src-tauri/Cargo.toml
```

如环境可用，再按仓库 Playwright / macOS 测试槽流程执行 `npm run test:ui` 和现有全量测试。任何失败都应定位真实实现最小根因，修修复并重新跑；记录 Python、Vitest、Rust、TypeScript、UI、真实模型的独立结果与日志。尤其检查新加入的 `StreamBackend` 运行快照测试、`replyText` 回退、SSE 409 重建、实时子代理统计与 Auto route 会话边界。若缺环境，标记 `NOT_RUN`，不要推断通过。

## 第二阶段：独立 macOS 测试槽与真实用户路径

遵守 `desktop/AGENTS.md`，先检查当前安装路径/进程/数据/备份，**不覆盖正式 Bundle ID 的日常应用**。重点按以下顺序做端到端：

1. 首装→模型下载/加载→标准 Agent 读取/修改文件；对未装 Core、未加载模型、云 API 不可用分别显示真实状态。
2. 偏好保存失败一次后继续修改与发送；加载本地模型失败时不丢原对话草稿；显式模型↔自动路由切换时历史边界清楚。
3. 一个 UNKNOWN 原提交不会冻结其他 Session 的安全只读任务；旧 UNKNOWN 收据和幂等身份保留。
4. 四档权限、合法软链接、macOS 临时目录别名、工作区外授权、Full 文件工具与 Shell 行为一致。
5. 长 Shell 的正常完成/超时/手动取消，核对部分副作用收据、不自动重试。
6. SSE 正常重连、GUI 完全关闭重开、事件保留窗口溢出后的任务全文、已完成子代理及收据恢复。
7. 同一局部/云端模型组合运行：Local 主→Cloud 子、Cloud 主→Local 子、Local 有界升级到 Cloud；每个真实请求在任务事件和占比里有可核验来源、模型/任务/成本记录。
8. 真实组件升级候选的版本一致性与失败回滚；用户可完成的一次升级流程。

## 第三阶段：尚需实现的关键产品整改

按用户影响与可验证性排序；**不要把此部分全部硬塞进一次高风险 PR**。先在 PR #1 修回归问题，其余拆成可审核的聚焦 PR（或明确说明为何同 PR 更合理）：

- **同会话无损模型迁移**：已有 Session 的 canonical 消息、工具收据、未决任务和工作状态通过既有 Hybrid 交接路径转给新模型，不重演写操作；不能做到之前继续显式新建会话。
- **真实可用模型列表**：配置 ready/文件已下载/进程已加载/Endpoint 活跃/支持工具调用/云端鉴权有效分别展示。在线健康不能假造，避免向用户承诺未探测的云 API；精简不是真正可执行的选项。
- **Shell 手动取消真实体验**：已有 `dcfe21d` 代码与 bash/Session 定向测试；继续验收 GUI、子代理及跨重启 UNKNOWN，避免二次实现。
- **单次组件升级**：GUI/Core/wheels/Channels 各自版本独立，用户只做一次“升级”，更新/兼容检查/失败回滚可见且原有数据安全。
- **50GiB 受管可重建缓存预算**：先在用户 Mac 只读盘点每个目录的归属与可重建性；预算只覆盖 LocalPilot 自己拥有的缓存。优先复用现有淘汰机制，禁止误删模型、收据、备份或外部进程缓存。
- **减法式重构**：App.tsx 的会话提交恢复、服务连接、消息任务事实逐步拆分；Session 初始化多代策略和 desktop_sessions 手工回滚按现有正常路径减法整理，不引入万能配置对象。权限、模型来源与低功耗选择解耦，保持四档体验。
- **独立配对评估**：冻结任务集，DSH 全云/LP 全云/LP 本地优先/同本地模型框架配对，统计成功率、质量、真实主子模型、请求次数、token、成本未知项、重试与耗时；先修工程准入再谈节费。

## 交付格式

每个问题提交：实际根因、最小复现/对应源码、改动范围、删除/合并的重复逻辑、真实跑过的测试命令与结果、仍未解决的具体条件。证据归 `docs/evidence` 新运行目录，修复报告归 `docs/development`，更新 PR 描述；**不合并 main、不发布候选为 Latest、不宣称尚未运行的验收已经 PASS**。
