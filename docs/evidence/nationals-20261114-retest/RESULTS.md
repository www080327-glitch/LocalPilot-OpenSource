# 国赛整改复测（2026-11-14）

基线 PR #1 `46c2bc242e9cff1e8c8ada000ff3894b4cd14d39`，macOS arm64；浏览器测试修正提交 `94efd51`。此记录不是发布验收。原始日志保存在本目录，完整 Python 失败名称和 traceback 见 `python-full-venv.log`。

- Shell / 权限和 Cooperative 专项：33 项，30 通过、3 跳过；未公开 benchmark 包相关测试明确 SKIP。包括 Workspace 内 Shell、Request 拒绝、Full 系统权限和 HTTP 准入，但不等于原生 GUI 验收。
- 指定 Python：110 项，107 通过、3 跳过。
- Python 全量：1884 项，20 failures、80 errors、52 skipped；失败。使用现有 `.venv` 并从本机 pip 缓存安装声明的 watchdog 6.0.0。部分错误来自缺失文档测试依赖（如 `docx`）与未公开的 benchmark 包；其余失败尚未逐项判定，不得全归因环境。系统 Python 首次全量运行因缺 watchdog 且中途停止，日志保留，非完整结果。
- Vitest：49 通过；TypeScript/Vite 构建通过。
- Rust：40 通过、3 ignored；本机 `bundled-backends` 是空目录，仅证明受限测试编译，不证明可运行应用。
- Playwright：原始运行 21 通过、4 失败；修正测试夹具和过时选择器后 25 通过。浏览器合成桥不是原生验收。首次及中间失败日志保留。
- 磁盘：测试前约 1.7 GiB，测试后约 1.4 GiB。`~/Library/Caches/LocalPilot-Qualification` 约 8.4 GiB，含多个 APP、验收与真实模型目录；未证明各目录引用和可重建性，未删除或移动。`lsof` 扫描未发现打开文件，但不证明无其他引用。候选包括 20261028 多个约 252 MiB 的 `*-artifact` APP、390 MiB 的 `*-native*`、425–566 MiB 的 `real-qwen35-*`，均需进一步核验备份、挂载及历史用途后逐路径审批。
- 真实模型协同、同会话迁移、模型在线健康、统一升级回滚、原生取消和恢复、SSE 409 原生端到端、50 GiB 预算、架构清理、独立 APP 安装验收：NOT_RUN 或未完成。未构建独立应用；空资源不可用于打包。

全量失败中，Full 模式对凭据路径、系统用户权限和既有硬边界测试之间存在契约冲突；电脑控制恢复/上下文压缩和并发等测试亦失败。需要逐项复现和核对，不能仅修改旧断言。日志仅留本机，可能包含本机路径；发布前须审阅。
