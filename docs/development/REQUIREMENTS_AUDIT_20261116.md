# 历次需求独立对照（2026-11-16）

**此前要求尚未全部达到。** 已有可运行的主/子 Agent、来源路由、个人活动来源、Skills、恢复和跨平台服务代码；本轮继续修复真实暴露的产品缺陷。但「已有实现」「脚本协议回归通过」「真实模型任务成功」「目标设备整包验收通过」是不同结论。以下按当前源码核对，不以作者或生成代码所用模型判断质量。

本文件汇总源码与证据对照；本轮包含实际生产修复和回归，原 Qwen 首轮运行目录仍保持冻结。最终提交身份以承载本文件的 Git 提交为准，不能把集成基线 `d846fef` 当成全部修改后的源码 SHA。最终 b26/b31/b7 续作由[最新总证据](../evidence/native-continuation-20261116/RESULTS.md)记录；下表原 b25/b30/b6 批次及其模型分母保留为历史证据。当前提交仅保存在本地；GitHub 推送被自动审批拒绝，待明确推送授权，尚未创建 PR。

## 不同源码和运行证据不能混用

| 来源 | 对应代码 | 可支持的结论 |
| --- | --- | --- |
| 最新续作 | Desktop rc9、Core b26、Suite b31、Companion b7、Channels a3；运行源码 `59fad12` | Core 1475 PASS/90 SKIP、Companion 689 PASS/33 SKIP、Suite 114 PASS/1 SKIP。Skills目录/OpenAI委派/同步child取消补齐，原生A/B及别名7项通过；新2B两项仍0/2。新包与原生短启动见[最新总证据](../evidence/native-continuation-20261116/RESULTS.md)。 |
| 先前 rc8 / 本机 Work | Desktop rc8、Core b23、Suite b28、Companion b5；历史报告各有 SHA | 保留已有 Mac 构建、失败和回归；包括 Session 404、同 Bundle ID 的旧 WebKit 隔离不确定性。不能追认为 rc9 原生通过。 |
| 前阶段集成树 | Desktop rc9、Core b25、Suite b30、Companion **b6**、Channels a3 | Desktop Vitest 74、Rust 50 PASS/3 ignored、Playwright 47 PASS；后者是真实 Chromium + 合成 IPC。Companion 全量 687 PASS/33 SKIP，实际 GTK 8 PASS；再补 7 项真实 tiny CPU 训练/公开 ASR，三组去重为 **695 已通过/25 macOS SKIP**。见[桌面证据](../../desktop/docs/evidence/polish-20261116/RECOVERY.md)和[Companion 证据](../evidence/native-polish-20261116/linux-atspi/RESULTS.md)。 |
| Qwen 实际推理冻结树 | Core b24、Suite b29、Companion **b5**；448 文件清单 SHA `e6f6bf16864dff9c3f7e9dfc6691129cbbbdc2d4c5693357ce023db089a14316` | 官方 Qwen3.5-2B、受控 Q8_0、真实 CPU HTTP 推理。首轮 9 项 **7 PASS/2 FAIL**；固定 MMLU-Pro 32 题 **10 PASS/22 FAIL**。b6 观察接口修改未由这些推理覆盖。见[源码清单](../evidence/qwen35-linux-20261116/SOURCE_FREEZE.json)、[模型身份](../evidence/qwen35-linux-20261116/MODEL_IDENTITY.json)和[协议](../evidence/qwen35-linux-20261116/PROTOCOL.md)。 |
| 修复后的 Qwen 独立诊断 | Core b25、Suite b30、Companion b6；448 文件清单 SHA `d3d866d67ad9cf6f819d8e6786656e4f62265983c15caa3e0a7a8cc4e2333917` | 一次固定四项 **2 PASS/2 FAIL**。自主及规定参数 child 自身读取与父任务完整交付通过；child Shell 未执行，Companion 正确交付文本但任务 `incomplete`，仍失败。预算改变，不能覆盖原批次。见[新诊断](../evidence/qwen35-linux-20261116/CORRECTED_RESULTS.md)。 |

首个 rc9 Linux DEB 也早于 b6 观察修复。最终包必须重新构建并核对 wheel/源码，不能只凭相同 rc9 文件名承接测试结果。早期错误和后续修复后的结果均保留。

前阶段后端回归为 Core **1473 PASS/90 SKIP**、Suite **114 PASS/1 SKIP**，均零失败/错误。原三项规定参数诊断为 **0 PASS/3 FAIL**，同样保留。不同批次、重叠定向测试和重复运行不相加成新的覆盖总数。

## 主 Agent、模型能力和学习

| 用户要求 | 当前实现与源码位置 | 真实依据和未完成部分 |
| --- | --- | --- |
| 参考 DeepSeek SuperAgent，由主 Agent 调用多个子 Agent | [HybridController](../../agent/hybrid.py)、[异步调度](../../agent/async_runtime.py)、[Session](../../agent/session.py)复用原 Runtime 和持久收据；[路由组装](../../localpilot_service/route_backends.py)可注册多个本地/云端 worker。官方原型的设计与许可证另见[来源核验](AIC_OFFICIAL_REQUIREMENTS_20261114.md)。 | 不是完整移植官方原型，也不是任意模型自动成为合格 worker。实际 Qwen 首轮自主分派选了不合法的 `local + LIGHT`，未创建子任务并超时，**FAIL 保留**。合法参数诊断暴露了旧默认子预算首请求即 finalizing 的缺陷；b25 修复并保留旧 Session/UNKNOWN，真实工具与 SQLite 的 138 项定向回归通过，见[预算证据](../evidence/native-polish-20261116/child-budget/RESULTS.md)。前阶段 b25 四项诊断中的自主与规定 child 读取均完成；最新 b26 两项诊断中的 child Shell 仍未执行。这些结果不证明异构本地/云端多模型自主协作质量。 |
| 本地/云端五档与比例 | [来源选择](../../localpilot_service/routing.py)有 local-only、local-first、balanced、cloud-first、cloud-only；[逐步协作](../../agent/cooperative.py)有队列、上下文、失败及停滞升级。当前修正纯云端判断，并将 OpenAI 纳入云端分类。 | 五档是来源约束和偏好，**没有保证 0/25/50/75/100% 固定调用或 token 比例**。默认是宿主优先级和有界启发式；校准默认关闭。缺真实不同模型下质量、延迟、用量与成本的完整五档对照，不能声称已证明最优分工。 |
| 不弱于主流 Agent，使用 AA 等外部榜单 | [Harbor 适配](../../scripts/localpilot_harbor.py)运行实际 Agent；[公开模型评测](../../scripts/public_model_eval.py)复用实际 HTTP backend。已有固定协议、预算和结果来源记录。 | **未证明非劣，也没有 AA 排名。** 本轮 MMLU-Pro 32 题为零样本、每题一次、512 输出 token：10/32，仅此样本 31.25%；22 FAIL 中 16 个 length 截断、6 个完整错误答案，不删除失败。它没有工具、不是完整 MMLU-Pro 或 Agent 对照。旧 534 次仍为 1 PASS/3 FAIL/13 ERROR/517 无最终结果；新正式 Harbor 研究缺 Docker daemon。 |
| DeepSeek 额度不足时可用 OpenAI | [backend 注册](../../localpilot_service/route_backends.py)已有独立 `openai` kind，官方 HTTPS 默认地址、`max_completion_tokens`、私有 key 注入和 usage；Suite、Channels、Desktop 分类同步。见[说明](OPENAI_AND_PUBLIC_EVALUATION_20261116.md)。 | [OpenAI/Harbor 合同证据](../evidence/openai-public-eval-20261116/RESULTS.md)通过，但真实付费 API **NOT_RUN**。用户已授权使用仍不等于已核实其 API 项目、到账额度和 key；当前没有这些账户凭据。不会在已有任务/冻结研究中隐式换 provider。 |
| Skills 赋能、按需加载，不让模型自动自改 | [SkillRegistry](../../localpilot_plugins/skills.py)安装/人工启用精确内容；[Session 注册](../../localpilot_plugins/adapter.py)把稳定目录与说明放进 `load_skill` 的函数描述，正文按需返回，依赖、作用域和版本有检查。默认 Suite PA 的 `full` 工具视图保留简介目录。 | 这是实际实现，不只是文档。已有 [Skills 测试](../../tests/test_pa_skills.py)和[旧格式迁移](../../localpilot_service/restore_migration.py)。续作修复了 [compact 工具视图](../../agent/registry.py)删除 Skill 用途目录的遗漏：full/compact 均向模型提供目录，正文仍按需加载，持久化 schema 保持原合同。[七项回归](../evidence/native-continuation-20261116/skills/RESULTS.md)包含真实 Skill 注册、加载、模型请求及快照恢复。尚无大量真实业务 Skills 的质量/选择准确率验收，不能声称全部达到；Skill 是指导文本，不会改变模型参数，也不自动增加工具权限。 |
| 固定提示与 Skills 永久 KV | [受管 oMLX](../../localpilot_service/cached_omlx.py)、[缓存预算](../../localpilot_service/cache_budget.py)和稳定前缀接入已有实现。受管前缀总预算 50 GiB；需要确切模型、模板与前缀身份。 | 本轮真实 llama.cpp 冷/热、**显式** slot 保存和 provider 重启恢复通过；不是通用外部 HTTP 自动持久 KV。后者**未实现**；Mac oMLX 当前模型冷/热/卸载/重启仍待测。缓存会因模型/模板/Skill 改动、预算或淘汰失效，不能承诺永久不失效。 |
| LoRA、全参后训练或强化学习 | [审阅数据](../../companion/model/reviewed_data.py)、[便携训练](../../companion/model/portable_training.py)、[实际 Torch worker](../../companion/model/torch_training_worker.py)已有入口；CPU/CUDA full 路径确实更新含 embedding/head 的全部参数。MLX 路径的旧 dense/full 只训练指定 Transformer 层，范围不同。 | [训练说明](REVIEWED_TRAINING_20261116.md)已有微型随机 Qwen 的真实 CPU 梯度和重载验证；它不是用户 PA 模型训练。当前缺人工确认样本、独立评估集和真实增益结果；前阶段 b6 的 5 个 tiny CPU 训练用例已单独补验通过，但仍不是个人数据训练。**RL 执行器未实现**。没有自动采集标签、自动训练或自动晋升候选。 |
| 全部重构旧代码、继续打磨 | 已按现有模块修复 Session 恢复、WebView profile、HTTP 云端分类、Harbor cwd 别名、AT-SPI 正文和测试夹具；复用原 Runtime、进程及持久化体系。 | 不能把本轮局部审查写成「全仓库所有代码已全面重构且无问题」。仍有上述真实模型失败及设备覆盖缺口；后续应按具体缺陷和行为证据继续改动，避免无验收目标的全量重写。 |

## Companion、权限和平台

| 用户要求 | 当前实现与源码位置 | 真实依据和未完成部分 |
| --- | --- | --- |
| Companion 轻交互 → 主 Agent，默认本地；即时反馈和完成回传 | [任务控制](../../companion/runtime/tasks.py)、[Core 升级客户端](../../companion/escalation/localpilot.py)接入真实持久 Task/Session、状态和 SSE；自动本地升级受用户开关、实际本地路由与资源控制约束。 | 轻聊真实算术通过；首轮文件任务超时，compact 参数说明缺失也是原因之一，**FAIL 保留**。前阶段 b25 四项诊断中已实际读取并返回完整内容和来源引用，但重复读取耗尽步骤预算，最终 `incomplete`，仍 FAIL。最新 b26 两项诊断中 Companion 误解独立的 `verification=NOT_RUN` 字段并未完成交付，仍 FAIL。accepted/progress/result 已实现，当前原生 APP 多模型完整交互仍未验收。 |
| 尽可能全面的最高只读来源，问 Codex 工作或会议无需再贴内容 | [文件/Codex/会议文字来源](../../companion/observers/sources.py)、[macOS 观察](../../companion/observers/native.py)、[Linux 观察](../../companion/observers/linux.py)和记忆引用/撤销链路存在。 | 有授权、范围与预算的可见来源；**不是整机任意历史或全天候无遗漏监视**。Codex 文字导出不包含隐藏思考、全部工具参数/执行收据；没有进入来源的内容无法回溯。b6 真实 GTK 静态正文、输入/密码排除、暂停已通过，不代表所有应用都暴露可读取文本。 |
| 晨间/晚间、开机和用户动静问好 | [服务问候](../../companion/runtime/service.py)、[观察事件](../../companion/runtime/observations.py)、[通知策略](../../companion/triggers/policy.py)实现时间段、每日去重、静音、勿扰与唤醒触发。 | 历史 Mac 晨间/静音/去重有证据；当前源码真实晚间、锁屏/解锁及系统睡眠唤醒仍 **NOT_RUN**。定时/事件测试不能替代实际系统行为。 |
| 实际会议音轨和本地总结 | [macOS meeting](../../companion/observers/meeting.py)、[Linux meeting](../../companion/observers/linux_meeting.py)具备分段/转写/来源入库；Linux helper 使用实际音频工具。 | 历史 Linux 音频夹具与 whisper.cpp 证据不等于实际声卡会议。Mac 已记录 TCC 拒绝、退出 -6、0 段；当前真实系统/麦克风音轨、中文会议质量和引用尚未通过。Linux Pulse/PipeWire-Pulse 实际采集仍待验。 |
| 完全权限不再遇到 APP 限制 | [桌面权限](../../localpilot_service/desktop_sessions.py)、[权限类型](../../agent/permissions.py)和[四档说明](desktop-permissions-v3.md)：full 使用当前 OS 用户能力，取消普通操作的逐次批准及文件/Shell 沙箱限制；内置凭据保护和任务预算仍有效。 | 实际 Linux Shell 写入读回、UNKNOWN 重启不重放有证据。full 不等于 root，也不能取消 TCC、系统文件授权、服务器能力或有限上下文；内置工具还保护 LocalPilot 凭据目录并执行预算。因此字面上的「任何权限限制都不存在」并未实现。当前 Mac 四档真实模型任务仍待验。 |
| Intel Mac 高优先级 | [首次设置](../../suite/localpilot_suite/desktop_setup.py)分开 Apple Silicon 与 CPU/HTTP 路径；[资源准备](../../desktop/scripts/prepare-bundled-backends.py)、[watchdog 构建](../../desktop/scripts/build-watchdog-wheel.py)、[cryptography 构建](../../desktop/scripts/build-cryptography-wheel.py)有 x86_64 材料路径。 | **代码适配已做，物理 Intel 整包验收 BLOCKED。** 本地 HTTP/GGUF 服务不需要 MPS；MLX/oMLX 权重不能直接拿来当 Intel CPU 模型。需要 macOS 15+、原生 x86_64 Python/依赖和真实 CPU 模型，不能用 M1、Rosetta 或 universal2 切片代替。35B 内存/速度也没有 Intel 结果。见[Intel 指南](../../desktop/docs/development/INTEL_MAC_20261116.md)。 |
| Linux 支持 | [Linux Shell](../../agent/linux_sandbox.py)、[DEB 构建](../../desktop/scripts/build-linux.sh)、[打包](../../desktop/scripts/package-linux.py)、[观察 helper](../../companion/observers/linux_helper.py)、[电源](../../companion/runtime/linux_power.py)存在。 | Debian 13 x86_64 服务、真实 Qwen CPU、文件/Shell、取消/恢复及实际 X11 GTK 只读已验；DEB 构建/提取不等于安装。实际 X11/WebKit 已用只读依赖映射验证首次设置、A/B 草稿/主题/来源偏好隔离、重开和路径别名；Wayland、Pulse、logind、系统安装/升级/回滚未验。通用 Linux GUI 操作型 Computer Use **未实现**，现有 [原生构建](../../computer/build.py)仍是 macOS；Companion 只读不是 Linux GUI 操作替代。其他发行版/架构不自动继承 Debian 结论。 |
| Session、任务、UNKNOWN、独立安装/升级/回滚 | [前端恢复](../../desktop/src/hooks/useSessionRecovery.ts)、[test profile](../../desktop/src-tauri/src/test_profile.rs)、[安装事务](../../suite/localpilot_suite/installation.py)、[APP 安装](../../suite/localpilot_suite/app_install.py)已有实现。 | rc8 基线已复现缓存外来 Session 不恢复，rc9 只有确认 `404 + session_not_found` 才转新草稿；47 项 UI 通过。保留原草稿、服务历史和 UNKNOWN，不重放。真实 Qwen Core 重启/UNKNOWN/SSE409 通过；真实子 Agent 恢复、Mac WebKit A/B 哨兵和当前包反向安装回滚仍需独立验收。旧 Mac 故障回滚通过不追认为新包通过。 |
| 完全 Apache-2.0 开源、README 快装、同步 main | 自有代码见 [LICENSE](../../LICENSE)；第三方边界见 [NOTICE](../../NOTICE)。[README](../../README.md)包含源码、CPU 端点及 Debian Test 包快装。 | 自有源码许可与安装说明已具备；第三方 MIT、模型和数据保留自身许可，不能声称整包所有材料都被改成 Apache。本轮交付目标为独立分支与 Draft PR，尚未合并 main；是否已推送须以远端分支和 PR 回执核对，文档编辑本身不证明交付。未发布 Release；Issue #6/#7 不因局部回归自动视为验收完成。 |
| AIC 评分材料与落地计划 | [官方要求核验](AIC_OFFICIAL_REQUIREMENTS_20261114.md)和现有演示/证据材料可供整理。 | 代码完成功能不等于已经完成答辩录制、比赛材料或微信落地意向表。本轮没有提交表单、对外联系或发布项目；赛事/落地日期和材料须各按对应通知核对。 |

## Linux WebKit 首次失败及后续补验

本次实际失败是首个 rc9 Test 进程启动时找不到：

```text
/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1/WebKitNetworkProcess
```

核查已下载的 Debian 13 `libwebkit2gtk-4.1-0_2.54.0-1~deb13u3_amd64.deb`：包内同时有 Network/Web/GPU helper，它们只被提取到测试 sysroot，当前系统对应目录不存在。候选 DEB 的 `Depends` **已经包含** `libwebkit2gtk-4.1-0`、GTK 和匹配的 Python；不是通过再给清单加同一个依赖就能修好的源码错误。[Debian 官方文件列表](https://packages.debian.org/en/trixie/amd64/libwebkit2gtk-4.1-0/filelist)也列出这些安装路径。

当前执行用户为 UID 1000，`/usr/lib/x86_64-linux-gnu` 不可写、没有 sudo；这不是已按依赖安装好的 Debian 系统。主共享库能由 `LD_LIBRARY_PATH` 找到，不会让其编译时的 helper 路径一起搬家。该下载库含上述固定路径、没有 `WEBKIT_EXEC_PATH` 字符串；上游[相关说明](https://bugs.webkit.org/show_bug.cgi?id=135752)将该变量限于开发构建。因此没有把设置环境变量、修改库字节或禁用 sandbox 作为验收捷径。

续作已把已核验 helper 只读映射到其编译路径，保持 WebKit sandbox，并在正常私有设备和图形会话下启动了真实界面。首次设置、A/B profile 及路径别名已通过，详见[原生证据](../../desktop/docs/evidence/native-continuation-20261116/RESULTS.md)。目录映射期间的 139、X11 认证及别名临时目录失败均保留。**正式系统安装仍需把声明的依赖装入 Debian 桌面，或使用已准备环境。** 不把这次映射启动算作系统安装、升级或回滚。

## 交给 Work 的最小剩余动作

完整可直接转交的提示词见 [WORK_NATIVE_POLISH_20261116.md](WORK_NATIVE_POLISH_20261116.md)。不要求 Work 重做云端普通回归；优先补以下具体缺口：

1. **Debian 13 x86_64 桌面**：取得最终 Core b26／Suite b31／Companion b7 对应 DEB，核对 SHA-256 `4faf7b91de548355aa717800d2f38fc65cccc8a7e87d501f36c1e3312b29a587`，在有管理权限的系统安装；从普通图形用户启动。最小环境核对如下，成功后再按 README 建独立 Test 根目录并做 WebKit A/B 哨兵、Session 和真实任务：

   ```sh
   sudo apt install ./LocalPilot-Test-5.0.1-rc.9-linux-x86_64.deb
   dpkg-query -W local-pilot-test libwebkit2gtk-4.1-0 python3.13
   dpkg-query -L libwebkit2gtk-4.1-0
   test -x /usr/lib/x86_64-linux-gnu/webkit2gtk-4.1/WebKitNetworkProcess
   test -x /usr/lib/x86_64-linux-gnu/webkit2gtk-4.1/WebKitWebProcess
   ```

   没有管理权限时使用预装环境；不在缺运行库的解包目录继续声称完成系统安装。X11/Wayland、音轨、真实睡眠及升级/反向回滚分别记录，不能用 GTK fixture 替代。

2. **现有 Apple Silicon Mac**：先保存本机未提交改动和旧实例状态，使用当前候选及独立 profile；用已有 Qwen3.6-35B 验证实际主/子 Agent、四权限、取消恢复、UNKNOWN/SSE409、安装回滚。分别测试早晚/睡眠和获 TCC 授权 APP 发起的真实会议；不把旧共享 profile 因果写成已确定。oMLX KV 记录冷、热、卸载和服务重启的实际 provider 指标。
3. **物理 Intel Mac**：按现有指南构建原生 Python/依赖/APP，以 CPU GGUF HTTP 模型做上述核心流程，记录硬件、内存及延迟。没有 Intel 设备继续保留 BLOCKED，不能改测试标签补通过。
4. **真实云端和正式研究**：私下核实 API key/组织/赠送额度后做 OpenAI 或 DeepSeek 的实际工具、子 Agent、用量与取消 smoke。准备专用 Docker daemon 和足够磁盘，先 preflight，再创建独立冻结研究；保留旧 534 队列和本轮 32 题所有失败。不得因换 provider、延长 token 或重试而覆盖原协议。
5. **个人后训练**：先由用户确认实际样本和独立测试集，再用现有 LoRA/全参入口训练、评估与候选回退。不要用随机微型训练通过推断个人助理已改善；RL 和通用 HTTP 自动持久 KV 仍是未来代码任务，不能交给 Work 只“补个测试”就算完成。

同步子 Shell 的产品取消/UNKNOWN/重启链路已通过真实进程集成测试；真实 2B 仍没有自主执行到 Shell。当前最影响产品承诺的缺口是：强模型完成子 Shell 任务和 Companion 在预算内完成交付、不同本云模型的质量对照、Mac/Intel/完整 Linux 桌面闭环、实际会议与睡眠，以及个人数据训练效果。这些项目应逐项取得新的执行证据后更新状态，不能用累计自动化 PASS 数替代。
