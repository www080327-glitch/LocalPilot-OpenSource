# PR #1 当前源码回归（2026-11-14）

基线为 `eb12bbb7846ce741a12237acfc06f070aad54033`，修复是本记录所在提交的源码。原始日志留在本机，不提交公开仓库。

## 回归及根因

- 基线 `.venv/bin/python -m unittest discover -v`：1919 项，2 FAIL、63 SKIP，无 ERROR。`test_full_reads_dotfiles_and_tool_body_reaches_cloud` 的 Session 预检在工具分派上下文之外调用 `sensitive_path`，因而 Full 普通 dotfile 在预检阶段被拒绝；工具直接调用的 Full 行为不同。现在预检使用网关的实际权限模式，仍始终阻止 `.localpilot/secrets`。另一个失败 `test_full_permission_preserves_hard_boundaries` 旧测试期待 Full 下禁止 `rm`，但现有 `command_decision` 明确赋予 Full 系统用户权限；文件边界断言保留，命令语义改为独立测试并验证实际文件结果。Shell/命令不是文件工具沙箱。
- 修复后相同全量命令：1920 项，0 FAIL、0 ERROR、63 SKIP，181.881 秒。12 个缺失历史 benchmark 的模块以 SKIP/NOT_RUN 报告；各模块中的测试并未运行。其他跳过项也不能视作 PASS。退出时出现 `subprocess ResourceWarning`，原因未定位。
- `.venv/bin/python -m unittest -v tests.test_file_info_observation tests.test_runtime_session tests.test_workspace_grants tests.test_desktop_permission_v3 tests.test_scope_escalation tests.test_runtime_permissions tests.test_aic_score_audit`：修复后 126 PASS。
- 在基线运行 `cd desktop && npm test`：49 PASS；`npm run build`：PASS；`npm run test:ui`：25 PASS，浏览器合成桥，不是原生 GUI。修复仅涉及 Python 权限预检和其测试。
- 在基线运行 `cd desktop && CARGO_BUILD_JOBS=1 cargo test --manifest-path src-tauri/Cargo.toml`：40 PASS、3 ignored；编译时资源目录为空，不能证明 APP 打包或可运行。

## 资源与未验收项

工作树 `bundled-backends` 为空。只读检查日常 APP 的 wheel：Core `5.0.0b21+channels.3` SHA-256 `a4ecc036d3a00389ca3a2c67f9b13ed2753d6b76fbaab084529e9ceb4cd51c21`；其 135 个 Python 文件中仅 120 个与本次工作树对应路径逐字节一致，不能用作当前 Core。该 APP 内 35 个锁定的第三方 wheel 哈希与当前锁文件匹配，不代表完整后端已重建或来源链全部核实。没有复制它的资源或打包空资源 APP。

在独立工作树以修复提交为源码，使用 `python -m build --wheel` 构建 Core、Companion、Suite，并通过 `scripts/build_channels_wheel.py` 构建 Channels。wheel 内 Python 文件分别为 136、78、17、7 个，均与源码逐字节一致；Core SHA-256 为 `a3cf63c4ec3244d51bd9f2180685f50e5e70434c84f944c1dc3e4f0f0b13c56e`。图标由仓库 `desktop/public/icon.svg` 经现有 Tauri CLI 生成。Node 22.23.4 从官方 Node 发布站获取，SHA-256 `c9e1dbc748b33ed2d14f42445191ecaf14c56259c7a9a26d0042c49ec2b66428` 与打包脚本固定值一致。第三方 wheel 从配置镜像重建时，`watchdog==6.0.0` 对当前环境没有匹配分发；尝试官方索引时 TLS 连接失败。日常 APP 同哈希 wheel 的原始来源尚未证实，因此没有把它作为已核验构建来源。完整资源准备和原生构建仍 NOT_RUN。

独立原生 APP、首次安装、真实模型、GUI 关闭重开、Shell/子代理取消与 UNKNOWN 防重、SSE 409 原生恢复、真实四档权限、组件一次升级及回滚均为 NOT_RUN。Issue #6/#7 的同会话迁移、真实双向协同、在线健康、统一升级、缓存预算及架构清理未完成；历史 benchmark 与发行资产仍需按 #3/#4 逐项审计。未合并、发布 Latest、覆盖 APP 或清理用户数据。
