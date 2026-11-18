# Desktop 5.0.1-rc.18 原生续验

**发布状态为 NOT_RELEASE_READY。** 本轮更改 Desktop。Core 5.0.0b35、Companion 0.5.7b12、Suite 0.2.0b34 与 Channels 0.1.0a4 沿用上轮版本。本轮没有发起新的外部模型调用。

## Apple Silicon 上的 0 Hz

逐字核对了本轮收到的 RC17 报告与已提交版本，逐项验证公开清单中的 17 份文件。6.009 秒的原始记录中，缩回阶段有 34 次回调，探头阶段有 41 次，两段都没有可见变化。验收时所选角色缺少边缘姿态包，原生诊断记录为 `pending`，透明度为 0。要得到完整角色下的帧率，需要在原机选定角色、导入与身份匹配的私人姿态包，然后同时采集画面和两个阶段的诊断。[Mac 原始报告](../native-polish-final-20261118/RESULTS.md) · [采样复核](mac-record-readback.json) · [素材核查](audit/asset-audit.json)

RC17 在 Apple Silicon 已通过独立 Test APP 升级、回滚和恢复，两项模型设置页面测试、原夹具 Luna medium 的 R12 Full，以及安装态 7,219.684 秒、240 心跳的 Full + extended soak。系统代理上的两次 TLS EOF 仍保留在原记录。RC18 本轮未在 Mac 上构建或实测。

## 桌宠修复

旧导入流程先覆盖已安装的 `poses.png`，之后才验证清单声明的补充图。如果新包缺图，原包也会失效。另一路径允许 PNG 格式正确但某个必需姿态完全透明的包通过。RC18 先解码候选文件、校验角色身份、版本、散列与姿态框。九个必需姿态和声明的补充姿态都须含有超过原生点击阈值的像素，再替换程序管理的文件。原目录里的许可和其他用户文件保留。已装姿态损坏时，设置页保留基础角色身份并提供重新导入入口。[独立复核](audit/pose-import-review.json)

`pet-control.py` 新增 `--test-root`，选择与 Test APP 相同的独立数据根，并在 `inspect` 与 `measure_animation` 时等待这次调用产生的新报告。测量时由已启动的独立桌宠采样六秒。原生诊断与真实录屏须对应到同一次操作。[脚本复核](audit/pet-control-review.json)

## 桌面回归

| 项目 | 冻结源码上的结果 |
|---|---|
| Vitest | 13 个测试文件，75 项通过，0 跳过 |
| 生产前端构建 | TypeScript 与 Vite 通过，转换 1,896 个模块，输出 9 个文件 |
| 桌面 Python | 11 项通过，覆盖隔离测试根和旧报告识别 |
| 版本与桌面文档检查 | 通过。118 份受测输入前后散列一致 |
| 新增 Playwright 页面用例 | 滑块、标题栏 X、姿态恢复共 3 项，均阻断于 Chromium 启动，页面断言执行数为 0 |

Chromium 的进程单例 socket 遭环境拒绝（`EPERM`）。允许其在受限环境外运行的请求被自动审批拒绝，本环境禁用沙箱权限升级。共享桌面只报告一个虚拟输出。页面测试使用仓库现有的 Tauri 桥，即使在其他机器通过，真实窗口的尺寸、收起与物理拖动仍须分别观察。[桌面回归](audit/desktop-regressions.json) · [页面测试记录](audit/ui-controls.json) · [原始日志索引](audit/EVIDENCE_MANIFEST.json)

## Debian 13 x86_64 构建与实际运行

在 Debian 13 / x86_64 / 系统 Python 3.13.5 上，由仓库既有脚本对两个干净提交分别执行 Test 身份原生构建。Rust 1.100.0，单编译 worker，GTK/WebKit 使用 Debian 包提供的共享库。RC17 提供本次实机升级与回滚所需的对照。可下载测试包随本次交付单独提供。

| Desktop 版本 | 最终 DEB 字节数 | SHA-256 |
|---|---:|---|
| [5.0.1-rc.17](linux/RC17_PACKAGE.json) | 114,690,242 | `d7c425f50d7fc2e1c9599fbbcd95867e4c3d0ec9c43d730a8fa80711efb9f604` |
| [5.0.1-rc.18](linux/RC18_PACKAGE.json) | 114,689,644 | `ed8bc890b477d54cd12e588853791796bd7c6dfbe3b484c06cf84b7c76a10a43` |

- 两个最终 DEB 分别在新建的含空格目录解包，实际运行 x86_64 ELF 的 `--bundle-self-check`。两个包都报告 `io.localpilot.desktop.test`、正确版本及 40 个已验证 wheel。四个产品模块和三个二进制扩展均从包内 runtime 导入，`pip check`、Suite 版本命令和内置 Node 22.23.4 检查通过。包结构检查覆盖 288 份组件源文件。两份打包报告的 `installed` 均为 `false`。[RC17 收据](linux/RC17_PACKAGE.json) · [RC18 收据](linux/RC18_PACKAGE.json)
- RC18 Rust 默认测试 57 项通过，0 失败，3 项按仓库定义忽略。其中新增姿态回归另行单跑也通过。该用例使用实际 PNG 和临时磁盘目录，拒绝缺尾图、坏 PNG、散列错误和必需姿态透明的候选后，重新打开原包并核对原始内容。有效替换后也核对用户许可文件。[默认 Rust 全量](linux/RUST_SUITE.json) · [原始日志索引](linux/ARCHIVE_INDEX.json)
- 另行显式运行了默认忽略的 `real_core_recovery_and_identity`，使用 RC18 DEB 内的 Python、真实 Core HTTP 服务和本机脚本模型。会话拒绝、一次响应丢失后的同键恢复、两套测试身份隔离通过。[Core 恢复验证](linux/CORE_RECOVERY.json)
- 用 RC18 DEB 内的 Python 以隔离模式运行现有的 12 项任务存储和 7 项桌宠历史测试，19 项全部通过。覆盖 SQLite 迁移、失败回滚、历史分页、重启恢复等行为。运行时记录的全部 56 个 Companion 模块来自解包后的 `site-packages`。[包内 Companion 验证](linux/PACKAGED_COMPANION.json)

## 剩余原生门禁

| 门禁 | 实际结果和继续条件 |
|---|---|
| Debian 首装、升级、回滚、恢复 | **BLOCKED**。RC17 首装使用全新的私有包数据库。普通安装要求管理员权限，官方非 root 模式在设置首个目录的 `0:0` 属主时失败。真实事务从 `half-installed` 回退到 `not-installed`，独立测试数据标记散列一致。其余三个切换步骤未到达。需保留两个上述 DEB，在有包安装权限的独立 Debian 13 机器继续。[dpkg 收据](linux/DPKG_LIFECYCLE.json) |
| Linux 桌宠窗口 | 实际以带用途标记的独立根运行 RC18 包内程序的 `--companion-pet`。构建进程没有 X11/Wayland 图形会话，GTK 初始化失败，退出码 101，观测到 0 帧。[真实启动输出](linux/GUI_LAUNCH.json) |
| Mac 原生 RC18 | Apple Silicon 需要补 RC18 Test APP 的升级、回滚与恢复，并导入原有角色姿态。真实 Intel Mac 的 x86_64 构建、安装与交互仍待验收。 |
| 可见动画与物理交互 | RC17 最后实测仍为 0 Hz。RC18 的缩回与探头阶段均需真实可见变化 ≥24 Hz，保留同步录屏。角色大小滑块、标题栏 X、物理拖动与跨两台显示器的工作区/缩放仍需真实窗口证据。 |

[对应源码与 Git 树](SOURCE.json) · [直接交给目标电脑的 Work 提示词](../../development/WORK_RC18_NATIVE.md) · [本目录文件散列](SHA256SUMS)
