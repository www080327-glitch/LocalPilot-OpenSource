# PR #1 HEAD 复测与 watchdog 来源调查（2026-11-14）

测试源码基线 `3726d16c625d706b719d2b314cdf79b673b55148`，macOS arm64。原始日志只保留在本机，禁止提交公开仓库。以下自动化不是原生 APP 验收。

- `python -W always::ResourceWarning -m unittest discover -v`：1921 项，1858 PASS、0 FAIL、0 ERROR、63 SKIP；历史 benchmark 缺失等 SKIP 并非通过。`tests.test_runtime_api.APITests.test_expired_sse_reconciles_live_text_and_resumes_new_events_over_http` PASS。运行结束报告一个仍在运行的 subprocess，正在独立追踪，不能凭 PID 推断来源。
- `cd desktop && npm test`：50 PASS、0 FAIL；包含 `reconciledStreamText` 测试。
- `cd desktop && npm run build`：PASS（TypeScript/Vite 构建，无测试项计数）。
- `cd desktop && npm run test:ui`：25 PASS、0 FAIL；浏览器合成桥，非原生 GUI。
- `CARGO_BUILD_JOBS=1 cargo test --manifest-path desktop/src-tauri/Cargo.toml`：40 PASS、0 FAIL、3 ignored；构建时后端资源目录为空，仅限测试编译。
- 新增 `companion.tests.test_file_observer_integration`：现有 Python 环境 1 PASS；下述源码编译 wheel 的独立环境 1 PASS。真实创建、删除文件并等待 Companion `FileObserver` 的系统事件。此测试是在上述全量基线运行后新增，未包含在上述 1921 项内。

## watchdog 审计

`desktop/runtime-dependencies.json` 锁的是 watchdog 6.0.0 的 cp314 universal2 wheel，SHA-256 `df0771e22978c47029f34141bb9aa0a9b868191265d980766949aefc9080ff2c`。旧 APP 中相同文件的散列吻合；wheel 自报 `setuptools (84.2.0)`、cp314 universal2、Apache-2.0，附许可证；35 条 RECORD 中 34 条带哈希且全部吻合，RECORD 自身无哈希。没有 direct_url 来源记录。上述内容不能证明构建者或来源；公开仓库该锁最早随源码快照进入。

官方 PyPI 的 [6.0.0 文件](https://pypi.org/project/watchdog/6.0.0/#files) 不含 cp314 wheel。下载其官方源码分发包并核对 PyPI SHA-256 `9ddf7c82fda3ae8e24decda1338ede66e1c99883db93711d8fb941eaa2d8c282` 后，在独立 Python 3.14.6 venv 使用 setuptools 84.2.0、wheel 0.48.0、packaging 26.3 和 Apple clang 21 构建；生成的 cp314 universal2 wheel SHA-256 `a2f8ef30c58f158d7421a0996e4e2f3c8d9d66b1f731886c1ddbd6d2b3b2f86a`，扩展包含 arm64 和 x86_64。独立环境使用该产物运行上面的真实文件监听测试通过，实际观察者是 macOS FSEvents。构建工具及其下载来源尚未建立完整锁定与可复现证据；此产物不是官方发布的 wheel，尚未写入运行时锁，也不能证明 Intel 实机兼容。

[官方 7.1.0 文件](https://pypi.org/project/watchdog/7.1.0/#files) 包含 cp314 universal2 wheel，SHA-256 `a0fdb62a48b5073ea3bcca29b9910f1cbde1026ab8bffb87a69b112bf6d97d1c`。现有 Companion 声明 `watchdog>=6,<7`，升级还须修改并验证组件依赖、监听和原生兼容；没有改变依赖。

## 未完成

真实非空 bundled-backends 生成与完整校验、独立 APP 构建、首装/模型、四档权限、原生取消与恢复、SSE 409 原生全链路、组件升级回滚均 NOT_RUN。Issue #6/#7 的同会话迁移、真实云本协同、在线健康、统一升级与 50 GiB 受管预算仍未完成。不得把现有测试标成这些验收的 PASS；不发布 Release、不合并 Draft、不替换日常 APP。
