# Linux 原生 WebKit Profile 续验（2026-11-16）

## 结论与受测身份

上轮中断的 **A/B 测试目录隔离、关闭重开和 A 的符号链接别名恢复已经完成**。本轮使用真实 X11 桌面上的 Tauri/WebKitGTK 窗口，实际点击首次设置、安装 B 的独立运行组件、保存未发送草稿和来源偏好。没有以 Chromium 或合成 IPC 替代这些原生操作；本轮没有修改 Desktop 生产代码。

受测包为上轮最后一次欢迎页文案修正后的 RC.9 **r4** 候选，精确身份如下。它早于本轮并行进行的后端 b26/b31/b7 修改，不能把这份原生结果写成新后端整包已经验收。

| 项目 | 身份 |
| --- | --- |
| Desktop | 5.0.1-rc.9，`io.localpilot.desktop.test` |
| Core / Suite / Companion / Channels | 5.0.0b25 / 0.2.0b30 / 0.5.7b6 / 0.1.0a3 |
| Git 构建基线 | `d846fef0f4b442d57e6e37f856a59c5a1a1337de`，构建时有未提交修改；基线不是完整受测源码身份 |
| Linux DEB SHA-256 | `bc91d6709645580ec788a4ddc9f995c9c9e9683bbff34215751669b7778a82d6` |
| 实际运行的 ELF SHA-256 | `6cb3172ca81b9a8eeedf22f69d091585d19d1a157682f5ada8ce7bba43d1e11a` |
| 构建目录 | `desktop/release/linux-test-v5.0.1-rc.9/20261116-200711-163/` |
| 实际运行方式 | 提取 DEB，使用上一轮已核验的只读 WebKit helper overlay，保留 WebKit sandbox；没有系统级安装 DEB |

包内 40 个 wheel、自检、组件导入、依赖与 Node 结果见 [原始包结果](PACKAGE_RESULT.json)。新一轮包若替换了后端组件，须使用其自己的包哈希与回归记录。

## 原生验收结果

| 场景 | 结果 | 观察及证据 |
| --- | --- | --- |
| A 重新打开上轮状态 | PASS | `r14-a` 恢复 `LP-RC9-PROFILE-A-20261116-UNSENT`、深色主题、完全本地来源，Core b25 连接；未发送草稿。 |
| B 首次打开 | PASS | 显示独立首次设置、浅色系统主题；没有 A 草稿。欢迎页显示 Linux 说明，未显示原先错误的 macOS 提示。见 [B 首次设置](screenshots/r15-b-first-run.jpg)。 |
| B 独立运行组件与设置 | PASS | 通过实际界面准备并连接独立组件，跳过模型和外部账号连接，选择“平衡”默认来源，完成设置。添加 B 的唯一未发送草稿。见 [B 草稿](screenshots/r15-b-sentinel.jpg)。 |
| 写入 B 后重新打开 A | PASS | 仍是 A 的原草稿、深色主题、完全本地来源；B 没有覆盖 A。见 [A 在 B 之后重开](screenshots/r16-a-after-b.jpg)。 |
| 再次打开 B | PASS | 恢复 B 草稿、系统主题、平衡来源，未出现 A 状态。见 [B 重开](screenshots/r17-b-reopened.jpg)。 |
| A 符号链接路径别名 | PASS（修正验证 wrapper 后） | 保留真实 `LP_INSTALL_TEST_ROOT=.../native-final-profile-a-alias`，仅将 wrapper 的可写挂载、TMPDIR 和 XDG_RUNTIME_DIR 规范为真实 A 路径；恢复 A 草稿、深色主题、完全本地来源和 Core b25。见 [A 别名恢复](screenshots/r20-a-alias-runtime-canonical.jpg)。 |
| 退出与进程归属 | PASS | 六次实际启动均在核对 wrapper PID、ELF 哈希、子进程和测试根目录后停止；所有停止回执均为 `STOPPED`、`owned_remaining=[]`。最后桌面只剩原终端。 |

以上是七项手工原生场景，不加入 Vitest、Rust、Playwright 或后端自动测试的累计计数。

## 文件层交叉核对与零推理边界

最终对两个合格测试根目录只读核对了 WebKit SQLite 中的指定测试键和 Core 表行数，见 [Profile 快照](PROFILE_SNAPSHOT.json)：

| 根目录 | WebKit store | 草稿 / 主题 / 来源 |
| --- | --- | --- |
| A | `06db388f-9cdc-6c6f-c277-58478f46f64c` | A 唯一草稿 / `dark` / `local_only` |
| B | `349c3d85-c3f8-7648-35b0-d985ceb7358d` | B 唯一草稿 / `system` / `balanced` |

两个根目录的 `checkpoints` 和 `journal` 都为 **0 行**，所有模型后端均为 `unavailable`、`not_deployed`。本轮没有提交模型任务、下载权重或连接消息账号。没有将数据库、私钥、客户端 token 或用户数据目录复制到证据中；快照仅含本次测试创建的草稿、可见偏好、目录身份和计数。

别名运行前后 A 始终只有一个 WebKit store，原草稿没有被清除。r19 服务恢复失败时，UI 未投影尚未连接的作用域草稿，但 SQLite 中 A 草稿仍完整保留；r20 服务恢复后原草稿重新可见。

## 保留的首次失败与限制

1. 首次停止 `r14-a` 在 shell 执行器中核对 `/proc`，其 PID namespace 与原生桌面不同，因此在发出任何信号前以 `ABORTED_IDENTITY` 退出。之后在原生终端运行同一身份核对脚本，成功停止自有实例。错误回执仍在 [日志](logs/r14-a-stop-wrong-executor.json)。
2. 首次尝试将 Sky 截图临时路径直接从 shell/原生终端复制时，该临时路径不在相应容器；没有生成那张截图。之后通过 CUA 已返回的截图字节保存证据。此文件传递失败不计作产品失败，也不补造原截图。
3. `r18-a-alias` 的旧 wrapper 将符号链接直接作为 bubblewrap 绑定目标，bubblewrap 在应用启动前拒绝。保留 [原始错误](logs/r18-a-alias.log) 和 [执行回执](logs/r18-a-alias-process.json)。
4. `r19-a-alias` 将挂载目标规范化后已进入同一个 WebKit store，主题与默认来源正确，但带别名的 TMPDIR/XDG_RUNTIME_DIR 下服务恢复未完成。保留 [原生错误截图](screenshots/r19-a-alias-recovery-error.jpg)。`r20` 同时将这两个临时运行路径规范化后恢复正常；没有逐一隔离两个变量，不能声称已确定其中哪一个是唯一原因。`LP_INSTALL_TEST_ROOT` 仍保持别名，因此没有用真实根目录替换别名来跳过目标验证。

所有改动都限于验证 wrapper；没有禁用 WebKit sandbox、改变 X11 认证策略、写入系统依赖目录或修改产品权限。

本轮没有验收系统级 DEB 安装、升级、故障回滚、Wayland、音轨、睡眠唤醒、macOS/Intel 硬件、动态宠物/气泡窗口互动，也没有新增原生 Session 404、SSE 或模型执行场景。这些范围仍以各自原有证据或后续真实设备结果为准。

## 可复核材料

[结构化结论](SUMMARY.json)、[最终 Profile 快照](PROFILE_SNAPSHOT.json)、[包身份](PACKAGE_RESULT.json)、[逐文件 SHA-256](MANIFEST.json) 与 `logs/`、`scripts/`、`screenshots/` 一同保留。原始执行目录是 `validation/polish-20261116/desktop/profile-resume-20261116/`；命令、环境种类、启动时间、真实候选哈希和停止归属均在对应过程记录中。
