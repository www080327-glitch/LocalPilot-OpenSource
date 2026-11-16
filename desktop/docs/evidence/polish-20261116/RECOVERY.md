# 2026-11-16 Session / Test WebView 修复记录

基线：`d846fef0f4b442d57e6e37f856a59c5a1a1337de`。本轮在 Linux x86_64 云端执行，Desktop 版本由整轮集成更新至 `5.0.1-rc.9`。本文件不把用户本机未提交的工作树或旧 APP 当作本轮受测源码。

## 已有证据

| 项目 | 状态 | 证据与边界 |
| --- | --- | --- |
| Vitest | PASS | 最终 74 通过，覆盖恢复投影、精确 404 错误判别、显式 OpenAI 来源归类等真实函数 |
| TypeScript / Vite | PASS | 最终构建完成 |
| Rust 默认回归 | PASS | 最终 50 通过、3 ignored；单元测试编译时资源目录为空，不代表完整后端包已经验证 |
| Rust → 真实 Core HTTP | PASS | 1 项集成用例显式执行：已知 Session 200、异主体与缺失 Session 结构化 404、关闭 Session 拒绝、丢失 POST 同键恢复不重复；模型为脚本夹具 |
| Playwright r5 | PASS | 47/47 通过，含本轮 6 项恢复场景；已核对 Vite PID、cwd 与服务提供的 rc.9 版本；覆盖最终动态版本文案，仍为合成 IPC 浏览器测试 |
| rc.8 基线目标复现 | FAIL（预期） | 独立确认服务为 rc.8 后，旧缓存 Session 一直保持 `sess_cached`，不会执行经认证 404 后切换新草稿；这不是对用户旧 Mac 现场的追认 |
| 原生 macOS WebKit | NOT_RUN | 存储配置单元测试不能证明 Mac 实例实际隔离，也不能追认上轮共享 profile 未被触及 |

运行日志在本轮受控验证目录 `validation/polish-20261116/desktop/`。本轮修改源码与测试的快照见 [源码 SHA-256 清单](RECOVERY_SOURCE_SHA256.json)，保留日志和各次运行身份见 [日志 SHA-256 清单](RECOVERY_LOG_SHA256.json)。最终整轮集成报告补充 Linux 原生结果。

## 保留的首次错误

- `cargo-test-r1.log`：新 checkout 尚未生成 `src-tauri/icons/32x32.png`，`generate_context!` 宏编译失败。随后按现有流程从 `public/icon.svg` 执行 `npm run tauri -- icon public/icon.svg` 生成图标；没有手改生成物。r2 通过。
- 首次浏览器尝试由整轮主执行者在真实 Cloud 桌面启动，Vite 并未实际监听 1420，浏览器报 `ERR_CONNECTION_REFUSED`。这是环境启动错误，不是目标 Session 缺陷已复现。
- 基线第二次尝试中，新增测试在 App 延迟导入桥接之前读取 `window.recoveryCalls`，因此因 `undefined.some` 退出。等待逻辑改为由 `expect.poll` 等到真实 `submission_history` 调用出现。失败日志保留；这一轮同样不能作为目标缺陷的复现证据。
- r3 的两个 Vite 启动日志都报告 1420 端口已占用；浏览器继续命中了先前的服务。所谓“新版”失败截图仍显示 `5.0.1-rc.8`，而当前源码为 rc.9。因此这轮交叉结果保留为运行指向错误，不作为新旧版本 A/B 结论。
- Linux 本机端点 UI 的既有测试填入 2048，但真实表单要求最少 4096，保存按钮按实现禁用。测试改为先断言 2048 被禁用，再用 4096 完成保存；没有放宽产品门槛。前一次超时保留。
- r4 为 46 PASS / 1 FAIL。最后一项中，新空草稿已正确出现、旧会话容器已被卸载；`not.toContainText` 要求定位到容器，因“元素不存在”仍判失败。测试改为断言旧答案文本数量为 0，并明确断言新输入为空，保留旧作用域草稿原文与无错误附件调用的检查。没有为测试改变产品行为。r5 整套 47 项全部通过。

## 修改的行为

已知缓存 Session 必须由当前服务的任务快照、Session GET 或当前进程创建结果确认，才进入附件面板。只有结构化 `session_not_found` 404 会自动切换到新草稿。外部作用域草稿、历史和 UNKNOWN 原请求保留。服务身份现在包含 Suite home。

Test APP 在创建 WebView 前配置专用持久 store；macOS 使用 `data_store_identifier`，Linux 使用测试根目录内的独立 WebView 数据目录。所有自动与动态主窗口、宠物和气泡入口一致。日常 APP 配置保持原状。实现、官方 API 依据和本机补验步骤见 [开发说明](../../development/SESSION_WEBVIEW_RECOVERY_20261116.md)。
