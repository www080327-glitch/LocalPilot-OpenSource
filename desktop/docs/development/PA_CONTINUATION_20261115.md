# Desktop 产品入口续作与职责整理 · 2026-11-15

## 基线与范围

本轮从 PR #10 的 `92ad9a30b9fda43bc185d96c99e5cb0a8ce8ec02` 继续，工作分支为 `codex/pa-cooperation-20261115`。保留 PR #1、#9、#10 及本机上一轮验收目录；本记录不覆盖此前证据。本轮桌面改动没有安装 APP、运行模型、录音、训练、清理用户文件或修改任何日常服务。

桌面工作仅修改 `desktop/**`。Companion 的回答来源核验与样本接口、Suite 的 Channels 版本字段由对应模块负责人维护；界面复用既有原生 IPC 和命令接口。

## 已完成的职责拆分

`src/App.tsx` 从 **3866 行降至 2737 行**，减少 1129 行。这里没有通过压缩格式减少行数；提取后保留任务状态、持久会话恢复、显式模型切换和提交逻辑的原有归属。

| 文件 | 本轮职责 | 行数 |
|---|---|---:|
| `src/components/TaskInspector.tsx` | 任务计划、工具、审批、时间线、子代理、实际调用比例、证据与 Diff | 609 |
| `src/components/SettingsDialog.tsx` | 默认偏好、连接表单、服务管理、云端范围、外观设置 | 415 |
| `src/components/ModelPicker.tsx` | 模型菜单与键盘/焦点交互，调用主界面的既有切换处理器 | 134 |
| `src/components/TaskStatus.tsx` | 主对话与任务详情共用的任务状态 | — |
| `src/components/JsonView.tsx` | 多个面板共用的 JSON 收据展示 | — |
| `src/components/BrandMark.tsx` | 主窗口与设置共用的标识 | — |

设置中的云端路径草稿继续跨关闭/重开保留；Suite 初始化结果仍由主窗口保存并显示到设置。模型菜单不负责重建 Session，不拼接旧对话；原来的 `selectModel`、`desktop_model` 调用和失败保留草稿行为不变。

编译器检查确认旧 `prepareDelegation` 没有任何调用者。它是主窗口 `delegation` 状态的唯一有效入口，两个委派状态都初始化为 `null`，所以其旧票据对话框、心跳和活动条不可达。本轮移除了这条死路径。宠物窗口当前的 `pet_agent` 委派入口以及主窗口的显式云端确认继续保留。

## 修复的具体产品流程

### 维护升级与回执

- `--maintenance-return` 返回主窗口后，自动打开“软件更新”并展开升级记录，只进行读取，不自动执行升级、回滚或恢复任务。
- 原界面使用 `row.receipt || row.handoff_error`。如果某计划已有成功安装收据，随后独立助手在回滚前置检查失败，新错误会被旧收据遮住。本轮将安装收据和助手错误分开显示，保留各自时间；历史条目也提示有助手错误记录。
- 刷新升级记录会更新当前选中计划的收据。读取失败现在可见，不再静默吞掉。
- 已安装模块列表补齐 Channels。旧 Suite 未返回该字段时仍显示 UNKNOWN；本轮 Suite 源头同时增加该字段。
- 设置版本徽标移除硬写的 `arm64`。页面没有观测架构时只显示真实软件版本，不推断 Intel/Apple Silicon。

### 会议采集状态与停止入口

- 会议状态直接通过已配置 Suite 的 Companion 通道查询。此前依赖 Core 健康刷新才能得到 `compHealth`，Core 停止时会挡住独立 Companion 的状态查询。
- HTTP 请求成功但返回 `status: error` 时，也会将已活动采集标为“状态待确认”，保留停止入口。异常不会触发再次启动。
- `starting`、`recording`、`stopping`、`interrupted` 等状态分别显示；尚在启动时不再声称已经采集音频。
- 麦克风与系统音轨各自状态可见，原始覆盖结果仍可展开查看；开始按钮等待 Companion 连接，活动期间保留全局停止条。
- 用户切换到另一个 Suite 数据目录前，若当前采集仍活动或状态未确认，需先明确停止并确认结果，避免界面切走后失去原采集的停止入口。相同目录的连接检查不受此限制。

这只完成了产品接线与状态处理。当前 Linux 环境不能证明 macOS TCC、Speech、本机语音模型或系统音轨可用。

随后交叉核对实际认证命令，发现服务入口还有两个真实返回：服务停止中返回 `{status: "stopping"}`，2048 项队列满时返回 `{status: "busy"}`；两者不携带会议快照。仅排除 `error` 会把它们误当成新状态，使旧活动状态及全局停止条消失。已在 `meetingStatus.ts` 添加共享的响应分类，轮询和控制两条入口均在更新状态前使用：只接受 `ok/active/stopped/unavailable` 且包含已知 `meeting.state` 的快照。`busy/stopping/error/UNKNOWN` 或缺失快照保留旧结果并进入状态待确认，停止入口保留；没有增加自动重试或新状态框架。这里的服务回包 `status: stopping` 与有效快照中的 `meeting.state: stopping` 分别处理。

交叉核对还确认：实际保存命令名为 `training_example_add`；问答的 `answer_id` 经 `/pet-stream` final 和原生转发保留，主窗口 `args` 与宠物 `payload` 都正确展平到认证 `/command`；样本返回非 `ok` 时不会显示保存成功。Suite 的 `localpilot-channels` 字段与版本页面读取键一致。

### 人工审阅训练样本

新增 `src/components/TrainingSamples.tsx`，复用 Companion 提供的下列契约：

| 操作 | 界面行为 |
|---|---|
| `training_candidates` | 用户点击后读取最近可审阅的已显示回答，不保存样本 |
| `training_review` | 读取候选问题、回答、用途与当前可用来源；可编辑问题和回答 |
| `training_example_add` | 用户明确点击保存后，提交 `answer_id`、用途和编辑后的问答；不由页面拼造来源 ID |
| `training_examples` | 显示已明确保存的样本；来源不可用时不展示原文 |
| `training_example_delete` | 用户点击删除后移除该样本，影响后续导出 |
| `training_export` | 用户明确点击后导出；展示本机路径及结果，不启动训练 |

主设置的“Companion 独立设置”包含完整候选、审阅、列表、删除和导出入口。宠物每条带 `answer_id` 的完成回复可以直接打开同一审阅表单；没有该 ID 的回答不会出现该入口。

宠物使用原 `pet_service`，保留其独立的 `companion_profile`。主设置使用原 `companion` 命令。两条原生白名单分别补齐实际需要的命令，未新增 Tauri 命令或手改生成权限文件。

保存失败会保留人工编辑文本并显示错误，不能把来源失效当成保存成功。导出前不会自动生成标签、写样本或启动训练。导出包含已审阅私人文本；撤销来源、删除样本不会追删此前生成的独立文件，界面明确说明这一实际行为。

## 本轮验证

执行位置为仓库的 `desktop/`。

| 验证 | 命令或范围 | 结果 |
|---|---|---|
| 前端回归 | `npm test` | **68 PASS，12 个文件**；此前 61 项通过记录保留 |
| 新增真实组件渲染断言 | `tests/task-panels.test.tsx` | **7 PASS**，包含 UNKNOWN 不提供批准/恢复、真实批准仍可见、缺失证据不变成验证通过、缺失来源不编造比例、轻量模型禁用、启动状态不冒称录音、四组件版本入口 |
| 会议响应及停止入口 | `tests/meeting-status.test.tsx` | **7 PASS**，覆盖实际回包字段、非快照拒绝、原生可用性替身下的真实组件停止按钮；不代表实际录音 |
| 类型与生产构建 | `npm run build` | **PASS**，TypeScript 与 Vite |
| 未使用符号检查 | `./node_modules/.bin/tsc --noEmit --noUnusedLocals --noUnusedParameters` | **PASS** |
| 改动前端格式 / 文档 | `prettier --check` / `npm run check:docs` | **PASS**；文档检查同时核对历史证据字节未变 |
| Playwright 用例收集 | `npm run test:ui -- --list` | **34 条，14 个文件**；收集成功不等于执行通过 |
| 浏览器实际执行 | 一次系统 Chromium 启动探针 | **BLOCKED / NOT_RUN**，页面未启动 |
| Rust 编译/格式 | 当前 PATH 与常用工具链目录无 cargo/rustfmt | **NOT_RUN** |
| macOS 原生 APP、维护退出重开、TCC、麦克风/系统音轨 | 无 Mac 环境 | **NOT_RUN** |
| 真模型推理、训练、能力榜单 | 未发起 | **NOT_RUN** |

浏览器错误与上一轮一致：`process_singleton_posix.cc:297`，`socket() failed: Operation not permitted`。只试一次后停止，没有通过重复参数或替换浏览器绕过环境限制，也没有把启动错误计成 34 条产品断言失败。

新增 `tests/ui/companion-review.spec.ts` 使用明确的合成原生桥，前四条覆盖：Core 停止时的会议查询与停止、审阅后显式保存与删除、来源撤销后保留编辑文本、维护返回时旧成功收据不能遮住后续助手错误。交叉核对后再加入 `busy/stopping/UNKNOWN` 三种轮询与停止回包的入口保留断言，共七条。即使在本机执行通过，它们也只能证明浏览器交互，不能替代原生 IPC、录音或模型验收。

原有版本管理浏览器测试的一条旧断言仍在寻找已移除的手工更新文案，已改为核对现有“执行前需停止服务”说明；没有弱化其浏览器不能写本机文件的断言。

本轮日志位于：

```text
/workspace/scratch/2a488f6eabf5/validation/desktop-pa-continuation-20261115/
  vitest.log
  build.log
  vitest-final.log
  build-final.log
  typescript-unused.log
  ui-list.log
  chromium-probe.log
  docs-check.log
  format-check.log
  vitest-meeting-response-final.log
  build-meeting-response-final.log
  ui-list-meeting-response.log
  typescript-meeting-response.log
  docs-check-meeting-response.log
```

第一轮通过日志、61 项回归通过日志和 Chromium 失败日志均保留。交叉核对修复后的 68 项回归、构建及 34 条 UI 收集使用独立日志；历史证据目录未改。

## 给本机 Work 的续测提示词

```text
继续验收 LocalPilot 的 codex/pa-cooperation-20261115 最新提交。先读仓库与 desktop/AGENTS.md，以及 desktop/docs/development/PA_CONTINUATION_20261115.md。读取 GitHub 最新 PR/HEAD，在新的独立 worktree 工作，不覆盖正在验收 PR #10 的目录，不合并 PR 或发布 Release。

先执行 desktop 的 npm test、npm run build 和 npm run test:ui。浏览器用例是合成桥，只记录浏览器验收结果；重点核对新 companion-review.spec.ts、已有 pa-model-switch.spec.ts、permission-parity.spec.ts、onboarding/installation/version-management 流程。本轮云端 Linux 只收集到34条用例，Chromium在创建socket时被环境阻止，没有执行产品断言。

使用本机现有 Rust/macOS 工具链完成 cargo fmt --check、有意义的Rust测试与Tauri编译。检查本轮 companion/pet_service 新白名单是否可调用；不要手改生成权限文件。若已有格式问题，保留失败记录，修实际新增问题，不做无关的大面积格式变更。

按现有 scripts/build-macos.sh 流程构建新版本运行目录中的独立测试APP，身份 io.localpilot.desktop.test。使用已审阅的测试身份安装计划，不覆盖日常APP。沿用旧验收中已证明的安装/失败回滚材料，只补本轮真正变化的交互，不重复下载大模型。

1. 原生打开设置、模型菜单、任务详情四个tab；确认已持久对话/草稿、思考设置、任务收据及UNKNOWN隔离保持。切换模型失败仍保留原会话。任务执行、未知副作用与完整权限语义均以Core真实返回为准。
2. 在独立测试Suite执行受控GUI维护并重开，确认自动出现“软件更新”、历史记录展开、未自动恢复Core任务。分别展示安装收据和助手失败记录，核对时间；不要把历史成功收据当成新一轮回滚成功。确认Core/Companion/Suite/Channels版本均可读取。
3. 在隔离Companion中显式开始一个受控测试音轨，观察starting/recording/denied/unavailable各状态，确认全局停止按钮可用。只停止本次测试所属Core，验证会议状态和停止仍由Companion独立工作。通过真实系统授权完成TCC验证，不绕过系统设置。停止后核对helper退出及source/segment收据。重启不得自动恢复采集。
4. 给Companion连接明确的测试文本来源，提问并获得一个带answer_id的已显示回答。从来源设置和宠物单条回复分别进入审阅，核对来源，修改问答，再明确点击保存。确认此前没有样本写入、只保存一次、未启动训练；读取列表、删除样本、显式导出并核对本机结果。
5. 另开一条审阅，在保存前停用或撤销其来源；确认后端拒绝保存，界面保留编辑稿并显示失败，之后列表/导出不复用已撤销来源。若独立宠物与主Suite使用不同Companion目录，确认两边审阅命令没有串到另一目录。

逐项记录 PASS/FAIL/NOT_RUN。保留原始失败与UNKNOWN，不用模拟模型、浏览器合成桥、静态渲染或编译通过替代真实模型、原生音轨或任务执行验收。无可用模型/语音资源时记录限制和具体阻塞项，完成其余可执行检查。不要自动训练、付费推理、清理真实数据或启动日常服务。
```
