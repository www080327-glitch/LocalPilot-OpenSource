# LocalPilot 原生门禁 Work 续接提示词

下面整段可交给连接实际电脑的 Work。源码和脚本测试已经完成的内容以本轮 [RESULTS](../evidence/audit-20261117/root/rc17-followup-b35/RESULTS.md) 为准；先读记录，再补真正缺失的机器验收。

---

继续完成 LocalPilot PR #15 的剩余原生验收和交付。请直接执行，不停在计划。仓库是 `www080327-glitch/LocalPilot-OpenSource`，PR 为 `https://github.com/www080327-glitch/LocalPilot-OpenSource/pull/15`，分支是 `codex/native-polish-final-20261116`。

## 一、先恢复准确基线

找到现有 LocalPilot checkout，核对 remote、远端 PR head、未提交改动及正在运行的 LocalPilot/Test APP。基线已包含 `6c923a95c749d1db2c6d2548e2109cd79b02d938` 的 RC17，以及本轮后续提交。建立独立 worktree，保留日常工作目录。

先读这些文件：

- `desktop/AGENTS.md`
- `docs/development/RC17_FOLLOWUP_20261117.md`
- `docs/evidence/audit-20261117/root/rc17-followup-b35/RESULTS.md`、`SOURCE.json`
- `docs/development/TASK_STORAGE_SCHEDULING_20261117.md`
- `desktop/docs/development/INTEL_MAC_20261116.md`
- `docs/development/PLATFORM_SUPPORT_20261116.md`

本轮组件组合为 Desktop `5.0.1-rc.17`、Core `5.0.0b35`、Companion `0.5.7b12`、Suite `0.2.0b34`、Channels `0.1.0a4`。先执行 `python scripts/check-candidate-versions.py` 并检查本轮来源清单。若远端有更新，基于最新源码增量验收，记录实际 SHA；不要把旧报告的成功标记直接套在新提交上。

已经修复：逐任务 SQLite 存储；同会话来源依赖投影及旧 writer 失效/回填；只读 search/review 模型角色；未注册 tier 广告；伙伴 thinking 被父任务覆盖；V5 子任务第一次输出截断后的原预算恢复。保留原 R9/R10/R11 与本轮所有失败，先读当前真实模型结果，不盲目重复同一任务。

## 二、先补浏览器实际页面验收

云端两次续验都在 Chromium 进程单例 socket 创建阶段遇到 `Operation not permitted`，0 页面断言。请在这台可正常启动浏览器的电脑运行仓库原 Playwright 用例：

```sh
cd desktop
npm ci
LP_UI_EVIDENCE_DIR="$LP_RUN/browser" npm run test:ui -- tests/ui/model-configuration.spec.ts --output="$LP_RUN/browser/test-results"
```

`LP_RUN` 使用新的带日期证据目录。若已有依赖与锁文件一致，可复用；需要系统 Chromium 时使用仓库已有的 `LP_UI_CHROMIUM_EXECUTABLE`。保留原断言，保存 reporter JSON、日志、截图和 trace。两项必须实际完成页面断言，启动成功不等于测试通过。然后验证配置的保存、重启、同一伙伴兼任探索/审阅、取消伙伴及把伙伴改为主模型时清理失效角色。

## 三、构建与安装当前候选

先记录 `uname -m`、系统版本、Python、Node、Rust、Xcode/SDK（适用时）。使用仓库已有脚本和依赖锁，不引入第二套打包流程。

Apple Silicon Mac 优先完成。按 `desktop/README.md` 与 `docs/development/MAC_PORTABILITY_20261114.md` 准备匹配本轮 Core/Companion 的四组件 wheel 和架构资源，再从 desktop 目录使用：

```sh
LP_GUI_TEST_CONFIG=src-tauri/tauri.test.conf.json scripts/build-macos.sh
```

仅在确认已有依赖与锁一致时使用 `LP_GUI_USE_INSTALLED_DEPS=1`。构建使用现有单 worker 约定。核对归档、签名、架构、组件版本、实际导入来源与源码散列。用 `scripts/install-local-app.py --test-app` 的现有 plan/execute/receipt 流程在独立 `LocalPilot Test` 身份和测试数据根中进行安装、升级、回滚与恢复，不覆盖日常 APP 或用户数据。先读脚本 `--help` 获取当前完整参数，不能猜参数。

Intel Mac 必须用实际 x86_64 Mac，遵循 `INTEL_MAC_20261116.md` 的固定原生依赖与独立锁。arm64 上通过或交叉构建不算 Intel 真机通过。没有这台机器就保留明确的 NOT_RUN，并列出缺少的机器条件。

Linux 使用匹配发行版、架构和系统 Python 的 Rust/GTK/WebKitGTK 开发环境，按 `desktop/docs/development/LINUX_20261116.md` 使用 `linux_backends.py prepare/check` 和 `scripts/build-linux.sh`。本轮云端没有 cargo/rustc、相应开发库及受支持的系统包安装 helper，附加桌面也没有当前候选；不要搬用 RC14 的 DEB/GUI 结果。

## 四、实际原生交互和动画

在本轮新 Test APP 上完成：冷启动和重启；Super Agent 主会话；只读探索/审阅配置及恢复；Companion 气泡输入、焦点、退出；桌宠拖动和六边缘姿态；缩放；多显示器；减少动态效果。必要时修复具体复现问题并补对应回归，不改已经通过的实现来凑新工作。

用现有 `measure_animation` / `pet-animation-probe.json` 入口记录实际变化帧，并保存可见动画录屏/截图与采样。验收要求是可见动态段至少 24 Hz；仅统计 requestAnimationFrame 回调不足以证明。减少动态效果模式按其预期检查，不强行把刻意静态表现判成帧率失败。没有的硬件条件分别标 NOT_RUN。

## 五、安装态来源检查、模型和长时任务

使用本轮安装态服务验证：一万条历史下查询旧任务、翻页和更新；同一会话来源依赖去重；撤销来源或更改文件后仍按当前状态阻止旧内容；迁移前后 task ID/完整 payload 不变；旧 b11 写入或更新后，新版查询会刷新依赖投影。完整 JSON 旧版本降级仍须按文档恢复迁移前备份。

模型遵循现有授权配置，不自作主张更换为昂贵型号。工程门禁先用 Luna high；如果存在实际能力瓶颈，再用 6.1 Sol medium，保存两次结果。对应现有命令为：

```sh
python scripts/qualify_openai_engineering.py --source-root "$LP_SOURCE" --key-file "$LP_KEY_FILE" --model gpt-6-luna --reasoning high --output "$LP_RUN/engineering-luna-high"
```

只有确需复验时才重新调用；当前源码已有结果可核对引用。保留原 fixture、prompt、最多两个子任务和子任务 4096 单次输出上限。确认真实调用中的模型/effort，两个子任务各自实现并自测，外部 17 项 unittest 与 4 个 CLI 场景通过。若发生 length，检查同一 child 的 `WorkerOutputRecovery` 和预算计数；不因模型自述完成就改写验证等级。角色真实模型的小型续验使用 `scripts/qualify_openai_worker_roles.py --help` 指定本机已授权密钥文件和新目录。

长时测试需要在新安装组合上检查 Full 一次授权及显式 extended 预算。注意 `qualify_openai_agent.py` 默认把脚本所在仓库加入 Python 路径，直接在源码树运行只证明源码服务。做安装态验收时，将它和 `qualify_linux_model.py` 原样复制到一个只含这两个脚本的独立 `harness/scripts/`，该目录不含 `agent`、`localpilot_service` 等产品源码；从新安装环境的 Python 执行，检查父进程和实际 Core 子进程均从安装目录加载模块，并记录脚本散列、模块来源及版本。然后在该 harness 下使用现有入口和实际私有 key 路径：

```sh
python scripts/qualify_openai_agent.py --case soak --soak-seconds 7200 --model gpt-6-luna --reasoning high --key-file "$LP_KEY_FILE" --output "$LP_RUN/full-extended-soak"
```

仅更换解释器、不排除源码覆盖不能算安装态验收。任务正常持续两小时，核对至少 240 条心跳、完成文件、后续 read_file 收据、最终文本及进程退出；不能把 213 秒工程任务或旧版本两小时记录当作此项通过。已有运行中的同类任务先确认状态，不重复开跑。

## 六、交付

把本轮新证据放在新的 dated evidence 目录，包含实际源码 SHA、OS/架构、构建/安装身份、原始命令、退出码、失败与复验、截图/动画采样、逐文件 SHA-256 和升级/回滚收据。密钥、用户数据、模型权重和 runtime SQLite 不上传。

继续更新 PR #15 并从远端读回核对，不合并、不创建 Tag 或正式 Release。所有必需原生门禁仍有缺口时，保留 NOT_RELEASE_READY。最后明确列出本机已完成、失败、跳过与因缺设备确实未执行的项，并给其他机器一个精确续接步骤。

## 另行跟踪的架构后续

Core archived-canonical 通用检索、Computer/Adaptive/精确云授权路由的执行段轮换，以及单个超长运行 turn 的块式持久化，仍是源码实现后续。它们与上面的环境受阻验收不同，不能写成“已有实现，只待真机测试”。本次先完成上述原生交付门禁；如果继续这些架构工作，先读 `PERSISTENT_CONTEXT_20261117.md` 和 `PERSISTENT_SESSION_SEGMENTS_20261117.md`，明确具体负载和最小修改范围，不能直接删除现有路由 guard 或另建平行 Runtime。
