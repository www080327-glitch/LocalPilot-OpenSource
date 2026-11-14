# PR #1 HEAD 复测与 watchdog 来源调查（2026-11-14）

测试源码基线 `3726d16c625d706b719d2b314cdf79b673b55148`，macOS arm64。原始日志只保留在本机，禁止提交公开仓库。以下自动化不是原生 APP 验收。

- `python -W always::ResourceWarning -m unittest discover -v`：1921 项，1858 PASS、0 FAIL、0 ERROR、63 SKIP；历史 benchmark 缺失等 SKIP 并非通过。`tests.test_runtime_api.APITests.test_expired_sse_reconciles_live_text_and_resumes_new_events_over_http` PASS。运行结束报告 subprocess ResourceWarning；后续追踪找到具体来源，见下文。
- `cd desktop && npm test`：50 PASS、0 FAIL；包含 `reconciledStreamText` 测试。
- `cd desktop && npm run build`：PASS（TypeScript/Vite 构建，无测试项计数）。
- `cd desktop && npm run test:ui`：25 PASS、0 FAIL；浏览器合成桥，非原生 GUI。
- `CARGO_BUILD_JOBS=1 cargo test --manifest-path desktop/src-tauri/Cargo.toml`：40 PASS、0 FAIL、3 ignored；构建时后端资源目录为空，仅限测试编译。
- 新增 `companion.tests.test_file_observer_integration`：现有 Python 环境 1 PASS；下述源码编译 wheel 的独立环境 1 PASS。真实创建、删除文件并等待 Companion `FileObserver` 的系统事件。此测试是在上述全量基线运行后新增，未包含在上述 1921 项内。

## subprocess ResourceWarning

对 1922 项测试的独立追踪运行记录每个真实 `Popen` 的创建位置并将警告 PID 对照：来自 `tests.test_suite_cli.SuiteCLITests.test_managed_task_controller_survives_cli_return_and_retry_does_not_duplicate` 经 `localpilot_service.cli.ensure_controller` 启动的 `localpilot_service.task_control`。测试使用 `psutil.Process.wait` 等待控制器退出，但模块保存的 `Popen` 对象没有同步等待，解释器关闭时其 `returncode` 仍为空，从而发出警告；该次追踪结束后该 PID 已不存在。最小修复仅改测试，用同一个真实 `Popen` 对象等待并核对 PID 与退出码，继续检查真实心跳和幂等。定向运行 `python -W always::ResourceWarning -m unittest -v tests.test_suite_cli.SuiteCLITests.test_managed_task_controller_survives_cli_return_and_retry_does_not_duplicate`：1 PASS、0 FAIL、0 ERROR、0 SKIP，未出现该警告。修复后完整回归 1922 项中 1859 PASS、0 FAIL、0 ERROR、63 SKIP，未再出现该 subprocess 警告。

## watchdog 审计

基线 `3726d16` 的 `desktop/runtime-dependencies.json` 锁的是 watchdog 6.0.0 的 cp314 universal2 wheel，SHA-256 `df0771e22978c47029f34141bb9aa0a9b868191265d980766949aefc9080ff2c`。旧 APP 中相同文件的散列吻合；wheel 自报 `setuptools (84.2.0)`、cp314 universal2、Apache-2.0，附许可证；35 条 RECORD 中 34 条带哈希且全部吻合，RECORD 自身无哈希。没有 direct_url 来源记录。上述内容不能证明构建者或来源；公开仓库该锁最早随源码快照进入。35 项锁定第三方依赖中，34 项的文件名和哈希与 PyPI 官方清单一致，且已从官方文件服务下载并核对实际文件；唯一未能取得官方同名文件的是 watchdog。

官方 PyPI 的 [6.0.0 文件](https://pypi.org/project/watchdog/6.0.0/#files) 不含 cp314 wheel。下载其官方源码分发包并核对 PyPI SHA-256 `9ddf7c82fda3ae8e24decda1338ede66e1c99883db93711d8fb941eaa2d8c282` 后，在独立 Python 3.14.6 venv 使用 setuptools 84.2.0、wheel 0.48.0、packaging 26.3 和 Apple clang 21 构建；生成的 cp314 universal2 wheel SHA-256 `a2f8ef30c58f158d7421a0996e4e2f3c8d9d66b1f731886c1ddbd6d2b3b2f86a`，扩展包含 arm64 和 x86_64。独立环境使用该产物运行上面的真实文件监听测试通过，实际观察者是 macOS FSEvents。随后将 setuptools、wheel、packaging 的官方 wheel 分别按 PyPI 哈希校验，另建环境再次编译，所得 wheel SHA-256 `902f22636a059b65b4192ffbbcaa8e8324565d13c358ec22fe7419332c2b9c3d`，同样通过真实文件创建与删除监听；两次产物的原生扩展字节不同，尚未证明位级可重复。构建输入和日志留在本机。此产物不是官方发布的 wheel，也不能证明 Intel 实机兼容。

候选 wheel 独立环境安装 34 项已校验依赖后，运行 `python -m unittest -v companion.tests.test_v01 companion.tests.test_file_observer_integration tests.test_runtime_api`：首次 80 项中 77 PASS、3 ERROR（测试夹具缺少 openpyxl 和 python-docx）；补充这些测试依赖后 79 PASS、1 ERROR（缺 reportlab）；再补充 reportlab 后 80 PASS、0 FAIL、0 ERROR、0 SKIP。安装测试夹具后核对 35 项运行时依赖版本均与现有锁一致。该定向结果不是原生 APP 验收。

[官方 7.1.0 文件](https://pypi.org/project/watchdog/7.1.0/#files) 包含 cp314 universal2 wheel，SHA-256 `a0fdb62a48b5073ea3bcca29b9910f1cbde1026ab8bffb87a69b112bf6d97d1c`。现有 Companion 声明 `watchdog>=6,<7`，升级还须修改并验证组件依赖、监听和原生兼容；没有改变依赖。

固定构建环境 `SOURCE_DATE_EPOCH=1730419200`、`PYTHONHASHSEED=0`、`CFLAGS=-g0` 后，在不同源码目录从头编译得到相同 wheel SHA-256 `c1d1d020f564cdec2ea437ff1304e47c182fe19d4310d3eb0923c33158025ab5`，对应源码构建脚本与依赖锁的候选改动；它在独立环境完成相同 80 项定向测试。构建脚本将来源和产物哈希作为必要条件，并拒绝覆盖已有 wheel。该复现仅在同一 Mac 工具链进行，不证明跨机器位级一致。

## 后端资源

四个组件 wheel 重新从当前源码构建，Core、Companion、Suite、Channels 的 136、78、17、7 个 Python 文件分别与源码一致。使用 34 项官方下载并核验的第三方 wheel 和本地构建的 watchdog，加 Python 3.14.6 和固定 Node 22.23.4，运行现有 prepare 与 check 脚本：PASS；39 个 wheel、组件版本、2128 个可移植字节码文件通过检查。资源复制到独立路径后，实际启动 Suite 版本命令、导入四组件、watchdog FSEvents 和运行 Node --version 均 PASS。Node 固定压缩包 SHA-256 `c9e1dbc748b33ed2d14f42445191ecaf14c56259c7a9a26d0042c49ec2b66428`。这些结果仍不等于原生产品验收。

## 未完成

独立 APP 构建、首装/模型、四档权限、原生取消与恢复、SSE 409 原生全链路、组件升级回滚均 NOT_RUN。Issue #6/#7 的同会话迁移、真实云本协同、在线健康、统一升级与 50 GiB 受管预算仍未完成。不得把现有测试标成这些验收的 PASS；不发布 Release、不合并 Draft、不替换日常 APP。
