# RC18 Apple Silicon 原生续验（2026-11-19）

**状态：NOT_RELEASE_READY。** RC18 arm64 Test APP 已构建、安装、回滚并恢复；3 项页面测试通过。原生气泡收起/草稿恢复和滑块改尺寸通过。角色姿态包在允许的本地来源路径中未找到，角色不可见，动画阶段、物理拖动和录屏因此无法验收。

## 源码与产物

- 源码：`3793af90877aef18075c66e0e593c9a8578cbac6`，tree `5c49815729466734c467903246e7a771ec42c98c`；分支 `codex/native-polish-final-20261116`。本次提交只追加验收证据。
- Test APP：`5.0.1-rc.18`，`io.localpilot.desktop.test`，arm64；ad-hoc 签名核验通过，未公证。可执行文件 SHA-256：`ab71e877dec6442942f22ebf8a640327b63559e42d9245063e449a4ab357c00d`。
- APP ZIP SHA-256：`534f9bf2d3965347999c184116d0bd40b452e5bf3f2dc5983ce4041e7418696c`。Core `5.0.0b35`、Companion `0.5.7b12`、Suite `0.2.0b34`、Channels `0.1.0a4` 沿用原版本。
- 本机：Apple M1 Max，macOS 27.0.1 (26A434)，单内建显示器，scale factor 2。Test APP 的 `test-owner.json` 为当前用户私有文件，purpose 为 `LocalPilot installation E2E`。

## 构建和安装切换

| 项目 | 结果 |
|---|---|
| RC18 原生构建、生产前端、arm64 和签名 | PASS |
| RC17 → RC18 Test APP 升级 | PASS |
| RC18 → RC17 回滚 | PASS |
| RC17 → RC18 恢复 | PASS |
| Test APP 最终安装身份/版本/签名 | PASS：`io.localpilot.desktop.test` / `5.0.1-rc.18` / arm64 |

安装器验证了 RC17 回滚归档解包后的签名与原文件树散列。首次回滚执行因同一测试根的 Companion 子进程仍运行而失败；按包内 Suite CLI 正常停止该测试服务后，重新生成计划并完成回滚。失败收据保留在本机私有证据目录。所有事务均使用独立 Test 身份，安装器标记 `user_data_modified=false`。日常 `io.localpilot.desktop` App 未作为目标。

首次构建检查因省略架构专用的已审阅运行时锁而停止；显式指定 `bundled-backends/runtime-dependencies.json` 后锁、组件 wheel/源码、版本和 runtime 检查通过，随后构建成功。初次在工作区解包的签名检查因 `com.apple.FinderInfo` 附加元数据失败；在用户 Cache 新目录解包后，签名、arm64 和可执行文件散列均通过。两个初始失败均保留于私有日志。

## 页面与真实窗口交互

- Playwright 1.64.1：3/3 通过，0 跳过、0 失败。覆盖滑块逻辑、标题栏 X 收起与未发送草稿恢复、已识别角色下的姿态恢复入口。逐项结果见 [`UI_RESULTS.json`](UI_RESULTS.json)。
- Test APP 原生气泡标题栏 X 收起后，原生诊断显示气泡隐藏；重新打开后未发送草稿仍在输入框内。未提交聊天。
- 用真实鼠标把“角色大小”从 1.0 调至 1.2：窗口由 240×220 变为 288×264 逻辑点；再拖回 1.0 后恢复 240×220。诊断分别保存于私有证据。
- 测试时系统“减少动态效果”原本为关闭（`reduceMotion=0`），整个过程未更改；应用“轻柔动画”保持开启。最终 Test 设置中的滑块值为 1.0。

## 桌宠动画与未完成项

允许查找的旧 Test APP `edge-packs/`、本机 `docs/evidence/edge-pet-20261026/private-visuals/` 及独立测试根中均未找到个人姿态包。原生状态是 `character=null`、`PENDING`、opacity `0`，桌宠不可见。动画诊断命令完成 6,011 ms 采样，但没有 `RETRACTING`/`PEEKING` 段，不能计算可见帧率，也不算 0 Hz 或通过。没有公开或复制个人画作。

- 需要本机私人姿态包才能完成角色导入、可见动画 ≥24 Hz、换边录屏和角色上的物理拖动；两台显示器跨屏验收也未运行（当前只有一台显示器）。
- Intel Mac x86_64 和 Debian 13 x86_64 是独立主机门禁，本机不具备这些硬件/系统，本轮未运行。
- Linux 包构建和既有受限验证见本目录父级报告；它们不等同于 dpkg 首装/升级/回滚/恢复或 Linux 桌宠窗口通过。

本轮没有调用模型、合并 PR、发布 Tag/Release，也没有更改日常 App 或系统减少动态效果偏好。PR #15 保持 open。
