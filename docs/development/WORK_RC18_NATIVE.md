# LocalPilot RC18 桌宠与原生安装验收

把下面这段交给连接目标电脑的 Work。

> 继续验收 `www080327-glitch/LocalPilot-OpenSource` 的 PR #15，分支 `codex/native-polish-final-20261116`。先读 `desktop/AGENTS.md` 和本轮[验收记录](../evidence/rc18-native-followup/RESULTS.md)。记录实际使用的 Git SHA、Test APP 版本、可执行文件散列和系统架构。优先完成这台机器能做的实际交互，并将证据追加到原 PR。
>
> Desktop `5.0.1-rc.17` 在 Apple Silicon 上已通过安装升级回滚、两个模型设置页面用例、Luna medium R12 和安装态两小时任务。[Mac 原始报告](../evidence/native-polish-final-20261118/RESULTS.md)给出了这些结果和此前的 0 Hz 样本。本轮桌宠改动对应 `5.0.1-rc.18`，Core、Companion、Suite 和 Channels 延用同一版本。日常 APP 和日常数据继续使用原有身份。所有操作使用 `io.localpilot.desktop.test` 与独立的 `LP_INSTALL_TEST_ROOT`。

## 在 Apple Silicon Mac 恢复个人角色并实测

1. 用 `desktop/scripts/build-macos.sh` 及 `src-tauri/tauri.test.conf.json` 构建 RC18 Test APP。在 `desktop/` 下按 `scripts/install-local-app.py --test-app` 的 plan、execute、receipt 流程，从可核对的 RC17 Test APP 升级，验证签名、回滚和恢复。为本次结果建新目录 `LP_RUN`，记录测试程序的实际可执行路径 `LP_TEST_EXECUTABLE`。测试根须是绝对路径，标记文件为当前用户拥有的私有 `test-owner.json`，purpose 为 `LocalPilot installation E2E`。
2. 用同一测试根启动独立桌宠。先确认该根的测试实例状态，复用已经运行的匹配实例。需要启动时，从终端执行 `LP_INSTALL_TEST_ROOT="$LP_INSTALL_TEST_ROOT" "$LP_TEST_EXECUTABLE" --companion-pet`。等待 `client/pet-control.sock` 出现。日常主窗口与独立桌宠使用不同启动方式。
3. 打开气泡的**宠物设置 → 换个形象**，选择本机已有个人图集的角色。在“导入当前角色探头姿态包”中选择同一身份的文件夹。原先记录的私有来源位于旧 Test APP 的 `edge-packs/<角色 id>/` 或原机的 `docs/evidence/edge-pet-20261026/private-visuals/`。文件夹应含 `pack.json`、`poses.png` 和清单引用的补充图片。可用的具体身份与姿态规范见[角色原始设计](../design/edge-pet-20261026.md)。个人原画留在本机，仅记录角色 ID、来源散列和必要诊断；截图若涉及额外的私人素材，按该次授权范围处理。
4. 用下方命令保存 `before.json`。在气泡中输入草稿，点标题栏 X，用原生窗口状态确认收起，再打开并核对草稿。用鼠标操作设置中的“角色大小”滑块，把 1.0 改到 1.2，记录实际窗口尺寸，再拖回 1.0。默认窗口为 240×220 逻辑点，1.2 倍时为 288×264。在角色可见处真实按下并拖动，用原生诊断的 `input_counts`、`drag_count`、方向记录、松手位置和屏幕录像对应这一次手势。若有两台显示器，实际跨屏拖动并核对显示器工作区、缩放、气泡跟随和松手后的边缘位置。
5. 确认角色已显示，缩回和探头两个阶段都可见。关闭减少动态效果进行动态采样，记下初始设置，验收后恢复。运行第二条命令后立即单击可见角色触发换边，六秒内保持窗口可见，同时保存可见过程的证据。检查 JSON 中完整的 `RETRACTING` 和 `PEEKING` 两段；按实际可见变化的时间戳复算频率，并同时报告按整个阶段时长计算的保守值。两段都须达到 24 次可见变化/秒，保留未达到或缺少阶段的样本。命令返回新 JSON 表示采样完成，零变化仍记录 0 Hz。最后复核应用与系统的减少动态效果设置。

从仓库根目录执行，`LP_RUN` 为本次新建的证据目录。

```sh
python3 desktop/scripts/pet-control.py inspect --test-root "$LP_INSTALL_TEST_ROOT" > "$LP_RUN/before.json"
python3 desktop/scripts/pet-control.py measure_animation --test-root "$LP_INSTALL_TEST_ROOT" > "$LP_RUN/animation.json"
python3 desktop/scripts/pet-control.py inspect --test-root "$LP_INSTALL_TEST_ROOT" > "$LP_RUN/after.json"
```

工作区里的两条新增页面用例可在 `desktop/` 目录运行。页面点击覆盖滑块和 X 的实际前端逻辑，原生窗口和指针效果按上面的真实 Test APP 步骤验收。

```sh
LP_UI_EVIDENCE_DIR="$LP_RUN/page" npm run test:ui -- tests/ui/pet-controls.spec.ts --output="$LP_RUN/page/results"
```

## 在 Debian 与 Intel Mac 完成各自的安装和交互

- 在独立 Debian 13 x86_64 / 系统 Python 3.13 环境，使用与要测源码对应的 **LocalPilot Test DEB**。先验 `SHA256SUMS`、架构、版本、依赖、Test 身份，按[仓库 Linux 流程](../../desktop/docs/development/LINUX_20261116.md)通过系统包管理器实测安装、升级、回滚、恢复。每一步核对实际安装版本、数据标记和退出状态。启动 `localpilot-desktop-test --companion-pet` 时传入同一 `LP_INSTALL_TEST_ROOT`，用真实 WebKit 窗口验证角色、滑块、X、拖动与动画。Linux 原生诊断的窗口大小为物理像素，记录屏幕配置和缩放后再与逻辑尺寸对照。
- 在真实 Intel Mac 上按[Intel 原生指南](../../desktop/docs/development/INTEL_MAC_20261116.md)构建匹配目标的依赖和 Test APP，验证 x86_64 产物、实际安装导入、打开/退出、升级回滚及桌面交互。记录这台机器的 `uname -m`、macOS/SDK 与 Python 版本。缺某一设备或缺角色原材料时写明实际缺项，继续其他能做的步骤。

保留初次失败、实际通过的范围和每份公开证据的散列。完成后更新 PR #15 并读回核对。维持 open，直到用户明确安排合并或发布。
