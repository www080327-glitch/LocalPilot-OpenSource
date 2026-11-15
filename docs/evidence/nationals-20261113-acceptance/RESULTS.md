# 国赛整改验收记录（2026-11-13）

基线 PR #1 `992cfb884a9e3486d7eecfad0bc136f56179c731`；macOS arm64，独立 Git worktree，Python 3.14.6、Node 24.20.0、Cargo 1.96.0。以下是本次实际执行，不是发布验收。

| 检查 | 结果 | 说明 |
| --- | --- | --- |
| `npm ci`、`npm test` | PASS | 安装 191 个包；Vitest 9 文件、49 测试通过。 |
| `npm run build` | PASS | TypeScript 和 Vite 构建通过。 |
| 指定 Python 组（除 `test_vllm_cooperative`） | PASS | `tests.test_nationals_runtime tests.test_context_v5 tests.test_harness_context tests.test_v49_context_cache tests.test_cloud_local_partners tests.test_runtime_api`：93 项通过。原上下文溢出测试的长度按新 token 估算调整。 |
| `tests.test_vllm_cooperative` | NOT_RUN | 公开 Git 树缺少导入的 `benchmarks.hybrid_accounting`，模块加载失败；不能声称该组通过。 |
| Shell 实进程与 Session 取消、非零退出专项 | PASS | 真实 bash 写入后关闭输出流并等待；取消终止进程，Session 收据为 unknown 且禁止重放；退出码 3 记录为 failed_process，未变为 UNKNOWN。模型后端为脚本化测试，不是真模型。 |
| `tests.test_host_tools` | FAIL | 16 项中 4 失败、1 错误。旧权限期望与现有实现不一致，包括 Shell 读保护/批准和 full 范围；公网地址解析被环境映射成非公网地址。不能据此断定全部只是测试过期，须按四档产品规则逐项复核。 |
| `npm run test:ui` | FAIL | 25 项中 17 通过、8 失败：4 项渠道旧控件，另有会话、安装、会话偏好、权限控件各一项。会话偏好测试在空白会话点击新建时期望重置，但现有 `newChat` 对空白会话直接返回；是否符合产品预期需连同草稿行为复核。测试为浏览器/合成桥，不是原生验收。 |
| `cargo test --manifest-path src-tauri/Cargo.toml` | PASS（受限） | 40 通过、3 ignored；首次失败因公开检出缺少 `bundled-backends`，随后只为编译创建空资源目录，并用仓库现有 Tauri CLI 从 `public/icon.svg` 生成缺失图标。空资源不是可运行后端，不能证明 APP 打包/安装可用。 |
| SSE 409、加载失败、Auto 路由 | PARTIAL | 运行了现有 Vitest 与服务快照测试；没有贯通原生 GUI、409 重建正文及后续事件的端到端测试，也没有完整实际加载失败与 Auto 路由 UI 测试。 |
| 原生独立 APP、真实模型、双向协同、升级回滚 | NOT_RUN | 未准备经过核验的独立打包资源和测试 APP，未发起真实模型请求；无 token、费用或性能证据。 |

只读盘点：`~/Library/Application Support/io.localpilot.desktop` 约 294 MiB；`~/Library/Caches/io.localpilot.desktop` 约 8 KiB；`~/Library/Caches/LocalPilotDesktop` 约 1.3 MiB；`~/Library/Caches/LocalPilot-Qualification` 约 8.4 GiB。名称与位置不能证明归属或可重建性，不计入已实施的 50 GiB 管理策略；未清理。开工可用空间约 3.3 GiB，构建后约 1.8 GiB，数值随系统变化。

本次没有合并、发布、替换日常 APP 或删除已有数据。后续须先确认资源和剩余空间，再建立独立 Bundle ID 的测试槽；不要把空的编译资源用于发布。
