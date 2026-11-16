# Linux Desktop 原生构建验收 · 2026-11-16

**当前交付为 r5。** r3 / r4 是保留的中间构建，不能作为最终候选交付。

源码候选：Desktop **5.0.1-rc.8**，Core **5.0.0b23**，Suite **0.2.0b28**，Companion **0.5.7b5**，Channels **0.1.0a3**。基线 `0cc99d57990e81302b941b6f5a160093dd298d4b`，构建时工作树含本轮修改；产物记录明确为 `source_dirty:true`，不能把基线 SHA 当成全部受测修改的提交号。

## 已完成

| 项目 | 实际结果 |
| --- | --- |
| 目标环境 | Debian 13 x86_64，系统 CPython 3.13.5；Rust 1.100.0；GTK3 3.24.49 / WebKitGTK 2.54.0 |
| Rust 默认测试 | 45 PASS，0 FAIL，3 项按定义 ignored |
| Rust → 真实 Core HTTP 恢复/身份 | 显式执行默认忽略的用例，1 PASS；脚本模型，无质量结论 |
| Vitest | 72 PASS，13 个文件 |
| TypeScript / Vite | PASS；正式 Linux 打包入口再次构建通过 |
| Playwright | 41 个用例被收集；浏览器启动被环境阻止，没有报为通过 |
| 真实离线资源 | 4 个当前源码组件 wheel + 35 运行依赖 + pip，共 40 个 wheel；源码/安装文件/版本核对通过 |
| 源码一致性 | Core 141 Python + 6 Swift；Companion 99 Python + 11 Swift；Suite 21 Python；Channels 7 Python；合计 268 Python + 17 Swift |
| Linux 原生构建 | PASS：实际 x86_64 ELF + Tauri Test DEB |
| DEB 身份/版本/依赖 | `local-pilot-test`；5.0.1-rc.8；amd64；显式系统 `python3.13` 依赖 |
| DEB 原生自检 | `io.localpilot.desktop.test`，40 wheel 哈希通过，无用户数据打开、无服务启动 |
| DEB 安装源码逐文件核验 | 直接读取最终 DEB 的 data tar，285 个安装源码文件均与受控组件 wheel 一致，含最终 Core 兼容性修复 |
| DEB 真实提取与搬移 | 在含空格的新路径导入四组件及 pydantic_core / Pillow / cryptography 本地扩展，PASS |
| 搬移后运行 | `pip check`、Suite 四组件版本命令、官方 Node 22.23.4 执行，均 PASS |
| Python 打包方式 | 三个 Python 入口恢复为 `/usr/bin/python3.13` 符号链接，不分发系统解释器副本；重新生成 md5sums 和 Installed-Size |
| 文档与差异检查 | 文档链接/历史证据字节检查、候选版本检查、`git diff --check` 通过 |

恢复用例覆盖关闭 Session 的明确拒绝、下次新任务正常提交、POST 回应丢失后使用同一幂等键恢复且不重复建任务、两个认证身份隔离。它实际连接安装资源内的 Core HTTP 服务，模型响应是确定性夹具；不是实际大模型测评，也没有验证原生 WebView 的 SSE 409 全链路。

## 当前候选制品

成功运行槽：`desktop/release/linux-test-v5.0.1-rc.8/20261116-162122-43/`。制品和原始运行日志留在构建环境，未上传公开 Release。

```text
LocalPilot-Test-5.0.1-rc.8-linux-x86_64.deb
bytes: 114593010
sha256: be2a72ea8c79a240b0671e29129fa2b2c40e4cea687ff6b749147945c8f4565b
installed: false
```

包实际依赖：`python3, xdg-utils, zenity, bubblewrap, python3.13, libayatana-appindicator3-1, libwebkit2gtk-4.1-0, libgtk-3-0`。原始 Tauri 包与规范化交付包的哈希、真实自检和提取运行结果见 [PACKAGE_RESULT.json](PACKAGE_RESULT.json)；四组件、依赖和 Node 的哈希见 [VERIFIED_RESOURCES.json](VERIFIED_RESOURCES.json)，最终 DEB 内 285 个源码文件哈希见 [INSTALLED_CODE_SHA256.json](INSTALLED_CODE_SHA256.json)。

Companion wheel 包含最终两处 Linux 修复：PulseAudio JSON 以 `monitor_source` 区分系统音轨来源；SIGTERM 能请求终止仍在转写的子进程。对应安装文件 SHA256 分别为 `d04725aac6af96c38e1025b674e691809df41fb28c2a48b4094eb040790dc86e` 和 `b387295c959db7b08961fbde6eec7880840bd768b52e00297250702b5c7d80f7`。

Core 最终构建保留 PR #9 的原有工具 schema 与固定权限提示词；Linux 平台信息经合格原生 Shell 检查后进入适当的请求视图，兼容无 scope 的子注册表及非 V5 稳定前缀恢复合同。最终安装的 `agent/session_models.py` SHA256 为 `0bb3cc99a0625fa8a0871d513cb85a500d5342c753434f14a924e386a1547590`。真实 Core HTTP 恢复/身份测试又针对 r5 安装资源执行，1 PASS，用时 1.24 秒。

原 r3 / r4 的包校验结果和状态分别保留于 [r3](intermediate-r3/STATUS.json) 和 [r4](intermediate-r4/STATUS.json)；它们只保留对应时刻的构建验证事实，均标记 `INTERMEDIATE_NOT_DELIVERABLE`。

## 保留的失败与修复

1. Linux 配置把 macOSPrivateApi 设为 false，触发 Tauri 的 Cargo feature 与配置一致性检查。保留 macOS 专属配置与原有 feature 一致，实际 AppKit 依赖和调用按目标系统编译。
2. 首次 Linux 编译发现无条件调用 macOS ActivationPolicy，已加目标系统门控。
3. 既有 Rust 扫描测试把 `/Applications` 当成所有主机都有的目录。改为自己创建的外部目录、标记文件和符号链接，真实验证扫描不越界；修正后 45 项通过。
4. 直接从 Channels 子目录调用 build 失败，缺少相对路径的集成文件。改用仓库既有 `scripts/build_channels_wheel.py` 干净暂存流程；没有篡改 wheel 内容。
5. 第一版 DEB 的归档报告误调用 `stat_result.st_size()`，报告生成失败。保留原包与失败记录，修正后使用新的运行槽完成整个流程。
6. 提取实际 DEB 发现 Tauri 把 Python 链接复制为三个解释器文件。打包源码现明确恢复系统解释器链接，重新生成包元数据，并再次提取最终 DEB 执行全部运行检查。
7. 复核发现 Linux ARM 制品名应统一用 `arm64`，已修正打包器与 Release 选择器命名不一致；本轮没有实际 ARM Linux 构建，因此不报该平台通过。
8. Playwright 官方 Chromium 下载返回截断归档；改用已安装 Chromium 后仍因 AF_UNIX `EPERM` 在启动时中止。保存下载日志、启动日志与 JSON 结果；未修改系统沙箱策略。

9. 实际旧源码 Session 兼容性复测发现 Core schema/固定提示词变化，以及随后请求视图对空 scope、自定义 Shell 和非 V5 稳定前缀处理的问题。Core 完成独立复核和完整回归后，重新生成 r5 Core wheel、资源和整个 DEB；旧成功构建全部留存，未冒充最终候选。

最终发布编译仍有两个已有的未使用函数警告：`Sprite::hit` 与 `bubble_origin`。其既有纯函数测试不证明当前原生 GUI 的点击或坐标行为。本轮没有把这两个测试当成 Linux 原生桌面交互通过的证据。

## 仍需设备/环境完成

- Linux 正常桌面会话内首次启动、文件选择器、托盘、拖动、权限提示和实际任务；当前容器不能启动本轮 Chromium/AT-SPI 原生会话。
- DEB 实际安装、跨版本升级/降级、失败恢复和系统注销/睡眠唤醒。当前制品只做提取校验，`installed:false`。
- Linux 实际会议设备、Pulse/PipeWire 来源、原生观察窗口与隐藏历史；AT-SPI 只读观察不等于 macOS Computer Use 控制。
- Intel Mac 物理硬件、macOS 当前源码构建、原生音轨/TCC、真实模型任务及其他原先缺少的产品验收，仍以总计划未完成项为准。
- Debian 12、Ubuntu、Linux arm64、AppImage、RPM 均没有本轮合格产物；当前 DEB 只对应已验证构建基线。

构建与安装命令见 [Linux 指南](../../development/LINUX_20261116.md)。本记录没有发布 Release、安装到系统、合并代码或运行付费云端请求。
