# 执行入口

读取 GitHub PR head 后从同一提交建 detached worktree。独立参考树为 RC20 `31644d8` 和 RC18 `fe9765c`。主机 Darwin arm64，Python 3.14.6，pip check 通过。已有缓存中的 35 个 runtime wheel 与 macOS 运行时锁的 SHA-256 一致。执行环境缺可选测试依赖 reportlab、yaml。

下列变量分别指独立临时目录、独立测试解释器和候选源码工作树。

```sh
python3 scripts/check-candidate-versions.py
"$python" -m pip check
PYTHONDONTWRITEBYTECODE=1 "$python" "$scratch/runner.py" --repo "$repo" --output "$scratch/core-baseline" --suite core
PYTHONDONTWRITEBYTECODE=1 "$python" "$scratch/startup_trace.py" "$repo"
PYTHONDONTWRITEBYTECODE=1 "$python" "$scratch/startup_trace_final.py" "$repo"
"$python" -m unittest -v tests.test_plugin_ecosystem.PluginStartupTests
"$python" -m unittest -v tests.test_incremental_checkpoints tests.test_persistent_runtime
LP_GUI_TEST_CONFIG=src-tauri/tauri.test.conf.json desktop/scripts/build-macos.sh
python3 desktop/scripts/install-local-app.py --help
# 在 desktop 下
npm run test:ui -- --list
npm run test:ui -- --output "$scratch/playwright-output"
```

定向复用脚本按源码根配置 PYTHONPATH，使用 PYTHONDONTWRITEBYTECODE=1 与独立 TMPDIR。Timer 复用 RC21 原脚本，旧版加 --expect-old-behavior。存储沿用 RC20 的 measure_long_turn_final.py 与 check_rollback.py；后者依序运行 candidate-create、rc18-write、candidate-reopen，每阶段正常停止后核对 journal 哈希前缀。真实副作用崩溃用原 check_crash_compatibility.py unreceipted-write。未收据 intent 补查复用相同 TaskService 配置，依序调用 materialize、legacy-unknown、candidate-unknown。

原全量 runner 的 passed 公式会把类错误和子测试条目与 started 数混算。原 JSON 保留，本次报告使用逐项日志与 unittest 尾部计数。
