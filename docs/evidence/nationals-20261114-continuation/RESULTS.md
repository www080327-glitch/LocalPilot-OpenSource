# 国赛整改续接复测（2026-11-14）

基线远端 `c0a63d1805723d398f95c6b3f02d783f8da9c165`；本轮工作建立在其后。原始日志留在本机本目录，含本机路径，未推送到公开仓库。没有把失败、跳过或未运行写成通过。

## 已执行

- `.venv/bin/python -m unittest -v tests.test_native_computer_use tests.test_native_human_recovery tests.test_host_tools tests.test_nationals_runtime`：142 PASS。Full 下明确要求主机批准的窗口聚焦和 UNKNOWN 恢复操作不再绕过批准；普通 Full 扩展行为仍保留。另有权限矩阵和上述关键测试 5 PASS。
- `.venv/bin/python -m unittest -v tests.test_nationals_runtime tests.test_context_v5 tests.test_harness_context tests.test_v49_context_cache tests.test_vllm_cooperative tests.test_cloud_local_partners tests.test_runtime_api`：114 项，111 PASS、3 SKIP（公开树无 benchmark）；包含 rev3 路径、V5 窗口边界、tokenizer 来源和真实 Shell 取消回归。
- 推荐器、选择器与桌面核心门槛：25 PASS；`PYTHONPATH=suite .venv/bin/python -m unittest -v suite.tests.test_active_power_recommendation`：6 PASS，含真实推荐器调用。核心最低 4K 与首个可配置 16K 档不一致造成安装检查异常，现按最低门槛选择首个有效档位。
- Companion 观察测试 11 PASS：原夹具使用固定旧时间，已超过真实保留期；改为当前时间后仍验证队列和 SQLite 的原有断言。
- Hybrid 并发与小窗口拒绝切换 2 PASS；原并发夹具依赖未公开 benchmark，改用真实交接消息；原 12K 窗口已可容纳新的 token 估算，4K 夹具实际触发拒绝。两个 Computer Use 压缩恢复及 Session 压缩测试共 3 PASS，收紧窗口后验证原有恢复与收据断言。子代理 thinking 默认、低功耗以及本地资格定向测试通过。
- `cd desktop && npm test && npm run build`：Vitest 49 PASS；TypeScript/Vite 构建 PASS。不是原生 APP 验收。
- `.venv` 安装文档测试依赖及 `plugins` 已声明依赖；新增 `test` extra 声明文档夹具依赖。`pip install --dry-run '.[test,plugins]'` 停在隔离构建依赖下载阶段，由操作者中断，未记为通过；TOML 解析及已安装版本核对通过。

## 剩余限制

- 全量测试和每个失败的 traceback 见 `python-full-current.log`；每次运行的结果只适用于启动时的代码，后续修改另有定向结果。公开树缺少 `benchmarks` 的测试为 NOT_RUN，unittest 将其计为导入 ERROR，不将其冒充 SKIP 或 PASS。
- Full 凭据和 Git 路径、未知风险等级等测试与当前模式的行为仍有契约冲突，需要按版本和真实授权策略逐项解决；不能通过删除断言宣称解决。剩余失败以最终全量日志为准。
- 开始时磁盘约 8.1 GiB 可用；`~/Applications/LocalPilot.app` 存在；构建目录 `desktop/src-tauri/bundled-backends` 无真实文件；日常 APP 内另有约 281 MiB 的后端资源，但其与当前候选源码的一致性尚未验证，不能直接当作本次候选资源。共享构建槽中还存在旧 APP，未覆盖。没有构建或安装空资源 APP，没有清理、移动或覆盖任何用户数据。真实模型、原生安装/取消/恢复、SSE 409、跨模型会话迁移、模型健康、统一升级回滚和 50 GiB 全局预算均 NOT_RUN 或未实现。
- 全量测试结束有 Python subprocess ResourceWarning，记录在日志中；具体子进程在随后检查时已退出，尚未定位其来源。

### 全量运行结果及逐项状态

`python-full-current.log`：在 `d0b8cc1` 上运行 ` .venv/bin/python -m unittest discover -v`，1911 项、9 failures、13 errors、51 skipped，耗时 180.163 秒。以下是最终失败名称和已知原因；具体 traceback、全部单项输出和跳过理由在该本机日志。

- `test_absent_outside_and_sensitive_paths_still_rejected`、`test_project_credential_namespace_is_not_model_tool_data`、`test_symlink_to_project_credential_namespace_is_denied`、`test_full_permission_preserves_hard_boundaries`：旧测试要求 Full 拒绝敏感路径，而 `ToolRegistry.call` 在 Full 使用 `dispatch_access` 放宽敏感读取；既有 rev3 测试又明确期待 Full 能读取 `.env`。真实产品契约冲突，未消除。
- `test_private_symlink_capability_and_plan_cannot_be_escalated`：失败在 isolated 工作区外读取的预期拒绝；历史提交表明 revision 3 的放宽无意中影响 revision 1/2；现恢复旧版外部读取拒绝，revision 3 原有读取行为保持不变。全量启动后修复，相关 54 项及跨版本定向 13 项通过，不能回填旧全量结果。
- `test_four_modes_and_hard_ceiling`：`PermissionGateway.decide` 在 Full 对未知风险标签返回 allowed，而测试要求 approval_required；需要确定 Full 对无法分类风险的真实契约。
- `test_ineligible_models_never_primary` 的 4B、9B、27B 三个子项：原断言与现行放宽的小模型准入不符；全量启动后修改为同时验证三个可用模型实际请求以及低于 4096 上下文的模型拒绝。新定向测试 2 PASS，未将其回填为该全量运行的 PASS。
- 13 个导入错误均为 `ModuleNotFoundError: benchmarks`：`test_adaptive_benchmark`、`test_aic_score_audit`、`test_aic_terminal_budget`、`test_benchmark`、`test_convergence`、`test_mlx_benchmark`、`test_real_hybrid_accounting`、`test_runtime_stabilization`、`test_selector_mlp`、`test_strict_benchmark`、`test_v48_benchmark`、`test_v48_resource_controls`、`test_v49_accounting`。这些模块 NOT_RUN；并不假装仅包含 13 个实际测试。
- 当前提交的权限、上下文、恢复、路由定向集合 34 PASS，见 `final-targeted.log`。其中真实模型、真实原生 GUI 和端到端升级仍未覆盖。

- `cd desktop && npm run test:ui`：25 PASS，浏览器合成桥，不是原生 GUI 验收。

### 最新源码全量复测

- `c3c8dc9`：`.venv/bin/python -m unittest discover -v`，1913 项、5 failures、13 errors、51 skipped，185.299 秒；原始日志 `python-full-c3c8dc9.log`。5 个失败即上文列出的 4 个 Full 敏感路径/硬边界测试与 1 个 Full 未知风险测试；旧版 isolated 失败已消除。13 个错误仍是上文列出的缺失 benchmark 模块，NOT_RUN。
- 本轮结束时 Python 报告 subprocess ResourceWarning；随后检查对应 PID 已退出，具体来源未确认。
- `cd desktop && CARGO_BUILD_JOBS=1 cargo test --manifest-path src-tauri/Cargo.toml`：40 PASS、3 ignored，见 `rust.log`。使用空的工作树资源目录，只证明测试编译和执行，不是安装包或原生 APP 验收。
- 旧日志逐项索引见 `INITIAL_TRIAGE.md`。完整原始日志保存在本机，未上传至公开 PR。
