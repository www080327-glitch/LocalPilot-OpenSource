# 本轮原始命令与执行结果

所有命令均在源码 head `97dae142a2deccfb1ed0add0c2cd49b4b02a8fad` 上执行。报告中的 `$LP_RUN` 指本轮新证据目录；原始带机器绝对路径的 Playwright reporter 保存在私有目录中。

## Playwright 原页面用例

```sh
cd desktop
LP_UI_EVIDENCE_DIR="$LP_RUN/browser" npm run test:ui -- tests/ui/model-configuration.spec.ts --output="$LP_RUN/browser/test-results"
```

退出码 **0**；2 passed / 0 skipped / 0 failed。执行时依赖已按 `package-lock.json` 安装，故没有重复执行 `npm ci`。Playwright JSON reporter：`.private/browser/browser-tests.json`。

为保留通过用例的截图帧和 trace，在相同断言上另执行一次：

```sh
cd desktop
LP_UI_EVIDENCE_DIR="$LP_RUN/browser-with-traces" npm run test:ui -- tests/ui/model-configuration.spec.ts --trace on --output="$LP_RUN/browser-with-traces/test-results"
```

退出码 **0**；相同两项再次通过。每项 trace ZIP 和从 trace 导出的首帧截图保存在 `.private/browser-with-traces/` 与 `.private/browser-screenshots/`。

源文件散列：

- `desktop/tests/ui/model-configuration.spec.ts`: `5ce4cb34bf08aa90a3b8d5235a639f940e39e037ac03810d2be127385ecae8cc`
- `desktop/package-lock.json`: `4f5ba378472b1ed574788382fa58bdc775be442f06534dda9bbfeeafae7be0ee`

## 安装与回滚

```sh
python desktop/scripts/install-local-app.py --test-app --help
python desktop/scripts/install-local-app.py --source "$RC17_APP" --test-app --receipt "$LP_RUN/.private/install/rc17-install-plan.json"
python desktop/scripts/install-local-app.py --source "$RC17_APP" --test-app --execute --plan "$LP_RUN/.private/install/rc17-install-plan.json" --receipt "$LP_RUN/.private/install/rc17-install-result.json"
python desktop/scripts/install-local-app.py --source "$RC7_RESTORED_APP" --test-app --receipt "$LP_RUN/.private/install/rc17-to-rc7-plan.json"
python desktop/scripts/install-local-app.py --source "$RC7_RESTORED_APP" --test-app --execute --plan "$LP_RUN/.private/install/rc17-to-rc7-plan.json" --receipt "$LP_RUN/.private/install/rc17-to-rc7-result.json"
python desktop/scripts/install-local-app.py --source "$RC17_APP" --test-app --receipt "$LP_RUN/.private/install/rc7-to-rc17-restore-plan.json"
python desktop/scripts/install-local-app.py --source "$RC17_APP" --test-app --execute --plan "$LP_RUN/.private/install/rc7-to-rc17-restore-plan.json" --receipt "$LP_RUN/.private/install/rc7-to-rc17-restore-result.json"
```

`RC17_APP` 指本轮固定候选 APP，`RC7_RESTORED_APP` 指从首个回滚归档解包验证的 rc.7 APP；二者的实际来源和树 SHA 写入各自私有 dry-run receipt。上面使用变量和相对证据路径规范化机器绝对路径。计划、执行结果、停止/启动日志和完整收据均在 `.private/install/`。三项事务全部执行完成，结果见 `INSTALL_MATRIX.json`。

## Full R12 / 安装态 soak

以下是仓库原 Work 指定入口和实际预算/模型配置；密钥只通过本机私有文件路径传入，不记录其内容：

```sh
python scripts/qualify_openai_engineering.py --source-root "$LP_SOURCE" --key-file "$LP_KEY_FILE" --model gpt-6-luna --reasoning high --output "$LP_RUN/r12-luna-high"
<installed-python> harness/scripts/qualify_openai_agent.py --case soak --soak-seconds 7200 --model gpt-6-luna --reasoning high --key-file "$LP_KEY_FILE" --output "$LP_RUN/full-extended-soak"
```

R12 与安装态 soak 均在模型推理前 HTTP 401；分别为 0 次模型调用/0 子任务和 0 次模型调用/0 心跳。runner 散列、结果散列、进程停止和模块来源见对应 JSON；原始私有日志只留本地。
