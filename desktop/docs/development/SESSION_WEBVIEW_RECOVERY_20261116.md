# 测试 APP 的 WebView 作用域与 Session 恢复

## 本轮修复边界

用户报告 RC.8 候选在新的 `LP_INSTALL_TEST_ROOT` 下首次设置出现 `HTTP 404: Session not found`，同时旧 Test APP 仍在运行。没有取得当时 WebKit profile 的完整快照，因此不能把本轮源码缺陷直接断言为那次现场错误的唯一原因，也不能追认旧两个实例已经隔离。

源码存在独立可检查的错误路径：`App` 从 `lp.currentChat` 读出旧 `sess_*`，只要新服务报告 `attachments_v2`，就把这个尚未确认归属的 ID 交给 `DocumentPanel`。这条请求早于首次设置完成和当前服务的任务恢复。原生 `data()` 的测试根目录并未设置 WebKit 网站存储，单独更换后端目录不能证明 `localStorage` 已隔离。

## Session 只读确认

附件面板现在只接收当前服务任务列表中的 Session、当前进程刚创建成功的 Session，或经认证 `GET /localpilot/v1/sessions/{id}` 确认的缓存 Session。首次设置未完成时，旧缓存 ID 不触发附件查询。

启动恢复仍先读当前服务的任务列表、提交历史和待确认提交。缓存任务不在列表中时，还会寻找同一 Session 的已知任务；仍没有任务时才查询 Session。Session 的 `active_task_id` / `last_task_id` 能继续指向实际任务快照；一个尚未提交任务但已有附件的 Session 也能保留附件入口。

只有原生传回的 HTTP 404 **且** JSON 错误码为 `session_not_found`，才把当前选择切换到新草稿。403、503、连接中断、非 JSON 404 及 `task_not_found` 都保留原选择并展示错误。一次后续刷新可重新确认。不会通过猜测任务列表缺项来删除历史，也不因恢复界面而调用提交或重放 UNKNOWN 原请求。

旧作用域草稿保留原文；当前作用域中未发送的输入可进入新草稿。服务身份包括 Suite home、origin、client subject 与 client generation。即使地址和 client subject 相同，更换 home 也会重新恢复选择。日常回执、原请求和 Core SQLite 历史不由这些前端恢复逻辑修改。

## Test APP 的原生浏览器存储

`src-tauri/src/test_profile.rs` 在 Tauri 创建任何 WebView 前校验测试目录。只对既有 `io.localpilot.desktop.test` 和 `io.localpilot.desktop.channels.test` 应用身份生效。目录仍需绝对路径和当前用户所有、权限为 600、purpose 为 `LocalPilot installation E2E` 的 `test-owner.json`。

确定性存储身份由规范化后的测试根目录和 Bundle ID 生成。符号链接路径以及 macOS `/var`、`/private/var` 等指向同一目录的别名得到同一身份；不同根目录或不同 Bundle ID 得到不同身份。关闭并重新打开同一根目录不会更换身份。

| 平台 | 原生实现 | 当前限制 |
| --- | --- | --- |
| macOS 15+ | Tauri `data_store_identifier`，指定持久 WKWebsiteDataStore | 实际存储位置由 WebKit 管理；不能声称所有前端文件都在测试根目录下 |
| Linux | Tauri `app_directories_override.local_data`，自动窗口及动态窗口使用 `<root>/client/webview/<store UUID>` | 必须在实际 WebKitGTK 桌面会话验收持久性和窗口间共享 |
| 日常 APP | 保留原配置和原存储 | 本轮不迁移或清空日常 profile |

自动主窗口、宠物窗口、气泡窗口，以及宠物首次设置、任务审核、交回主窗口的动态创建入口均应用同一 Test profile。没有额外创建 Runtime，也没有复制、删除或修复旧 WebKit 默认 profile。修复前的测试 APP 若使用默认 WebKit store，升级后该测试根目录首次进入新的专用前端 store；native `client` 内已保存的设置和后端历史仍保留，旧前端 store 留存。

实现依据锁文件中的 Tauri 2.12.5。其 [WebviewWindowBuilder 文档](https://docs.rs/tauri/2.12.5/tauri/webview/struct.WebviewWindowBuilder.html#method.data_store_identifier)说明 WKWebView 的 `data_directory` 不适用，命名 store 需要 macOS 14+；本项目最低 macOS 为 15。Linux 默认 WebView 目录遵循 Tauri 的 [appDirectoriesOverride](https://docs.rs/tauri-utils/2.10.2/tauri_utils/config/struct.AppDirectoryOverrides.html) 中 `local_data`。仅配置 Bundle ID 或 native 数据目录不足以证明浏览器隔离。

## 自动化与真机验证

Rust 单元测试直接验证实际 Tauri 配置，包括同根重复启动、不同根、不同 Bundle ID、规范化路径别名、无效标记拒绝、日常配置不变。真实 Core HTTP 集成测试读同一主体的 Session 成功，另一主体和不存在 Session 返回结构化 404，并保留既有关闭 Session 拒绝、丢失 POST 后同键恢复、任务不重复的断言。模型是确定性的测试夹具，只用于验证 HTTP/恢复契约。

Playwright 的六个新增用例运行真实 App 和恢复 hook，桥接为合成 IPC；覆盖首次设置、确认 404、既有历史、503 后刷新、无任务的附件 Session、更换同源 Suite home。它们不是 WebKit、真实模型或多实例原生验收。具体通过和失败记录见 [本轮恢复记录](../evidence/polish-20261116/RECOVERY.md)。

### 给本机 Work 的补充验收

1. 读取最终 main SHA、`AGENTS.md` 与本文件，先记录旧 Test APP / 日常 APP 的运行状态、路径、bundle 哈希、旧客户端 profile 摘要和未决任务。不要把旧 Mac 未提交修改当成已经进入 main。
2. 从当前源码使用现有 `scripts/build-macos.sh` 和 `LP_GUI_TEST_CONFIG=src-tauri/tauri.test.conf.json` 构建新候选；先完成资源、架构、签名与 `--bundle-self-check`。Apple Silicon 与物理 Intel 分别记录，Rosetta 不计 Intel 验收。
3. 建立两个本轮独占且有合格所有者标记的绝对测试根目录 A、B。使用候选实际可执行文件与各自 `LP_INSTALL_TEST_ROOT` 启动，核对新 PID、路径和根目录。不要只用 `open -a` 推断启动了第二实例，因为 LaunchServices 可能复用已运行的同 Bundle ID APP。
4. 在 A 完成首次设置后，保留未发送的唯一草稿 `PROFILE-A-<本轮随机标识>` 并设置一项可见偏好；完全退出 A 的 GUI 后重开 A，确认草稿和偏好仍在。在 B 检查首次设置与草稿没有继承 A，再用不同的 `PROFILE-B-...` 检查 B 的持久性。回到 A，确认 B 未覆盖 A。再从指向 A 的路径别名打开，确认恢复的是 A。不要向模型发送这些哨兵草稿。
5. 检查宠物和气泡窗口从同一个 A 进入首次设置/审核主窗口时仍采用 A；B 的窗口不得读取 A 草稿。将旧默认 profile 未迁移、WebKit 实际存储与前后摘要分别记录，不要用 bundle 哈希代替 profile 证据。
6. 当前服务注入一条合法、仅用于测试的旧缓存 Session 选择；经过确认的 `session_not_found` 404 应转到新草稿。再检查有效 Session 恢复、真实未决 UNKNOWN 原请求未自动重放。对停服、403 或 503 不应自动新建替代任务。保留每次错误的原始日志。
7. 继续用户指定的 Qwen3.6 35B 真实任务、取消、恢复、升级及回滚验收。该步骤另记 provider usage/耗时；前述无模型 UI 存储测试不能替代它。TCC、系统音轨、睡眠唤醒及物理 Intel 仍需相应设备独立验收。

本次明确云端 `openai` adapter 同时进入前端模型图标/五档来源选择及 native 提交校验。云端优先/仅云端选择不会因额度不足自行改 provider；本地模型仅具有云传出许可也不再被 native `cloud_only` 误当成云端主模型。
