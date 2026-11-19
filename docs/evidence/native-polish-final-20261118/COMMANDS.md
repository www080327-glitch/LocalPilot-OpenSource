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

以下是仓库原 runner 和本轮用户更新的配置；最初的 `gpt-6-luna/high` 尝试因本机密钥文件少一个字符而在推理前 HTTP 401，密钥文件修正后改为 Luna medium。密钥只通过本机私有文件路径传入，不记录其内容。

```sh
LP_SOURCE="$PWD" LP_RUN="$PWD/docs/evidence/native-polish-final-20261118/.private" LP_KEY_FILE="$HOME/.local/share/localpilot-pr15-native-20261117/private/openai-api-key" LP_OUTPUT="$PWD/docs/evidence/native-polish-final-20261118/.private/r12-luna-medium-attempt2"; setopt pipefail; python3 -u scripts/qualify_openai_engineering.py --source-root "$LP_SOURCE" --key-file "$LP_KEY_FILE" --model gpt-6-luna --reasoning medium --output "$LP_OUTPUT" 2>&1 | tee "$LP_RUN/r12-luna-medium-attempt2-console.log"
LP_OUTPUT="$PWD/docs/evidence/native-polish-final-20261118/.private/r12-luna-medium-retry1"; setopt pipefail; python3 -u scripts/qualify_openai_engineering.py --source-root "$LP_SOURCE" --key-file "$LP_KEY_FILE" --model gpt-6-luna --reasoning medium --output "$LP_OUTPUT" 2>&1 | tee "$LP_RUN/r12-luna-medium-retry1-console.log"
LP_OUTPUT="$PWD/docs/evidence/native-polish-final-20261118/.private/r12-luna-medium-direct-tunnel"; setopt pipefail; NO_PROXY=api.openai.com python3 -u scripts/qualify_openai_engineering.py --source-root "$LP_SOURCE" --key-file "$LP_KEY_FILE" --model gpt-6-luna --reasoning medium --output "$LP_OUTPUT" 2>&1 | tee "$LP_RUN/r12-luna-medium-direct-tunnel-console.log"
```

实际第一次执行前预建了输出目录，原 runner 按要求拒绝；该纯本地错误退出码 2，0 API 调用。两条系统代理命令退出 1；指定域名 `NO_PROXY` 的命令退出 0。runner SHA 为 `1878a177ed32600e9d53490ad518a93ece8d729643f2e2681c7b10d11d4724c4`，所有 fixture manifests 与前次一致，源码 SHA 未变。

## installed-runtime Full + extended soak

在只含两个 runner 副本的 `.private/installed-soak-harness/` 中，从 Test APP 下的 Python runtime 执行。实际命令：

```sh
cd "$LP_HARNESS"
NO_PROXY=api.openai.com PYTHONNOUSERSITE=1 "$LP_RUNTIME" scripts/qualify_openai_agent.py --case soak --soak-seconds 7200 --model gpt-6-luna --reasoning medium --key-file "$LP_KEY_FILE" --output "$LP_OUTPUT"
```

`LP_RUNTIME` 指向 `client/modules/bundle-700d64a665f74410627a/runtime/bin/python3.14`；`LP_OUTPUT` 是新的 `.private/installed-soak-luna-medium-direct-tunnel/`。命令退出码 **0**，requested 7200 秒 / elapsed 7219.684 秒，240 心跳，`shell` + `read_file` 收据，marker 为 `LOCALPILOT_SOAK_COMPLETE`，approval interventions 0。runner SHA `a860afd95c17ec86bdd1b738ae7a4223fd3985eadd262c84259e4f396acf3238`；完整结果和散列见 `INSTALLED_SOAK_SUMMARY.json`、`MANIFEST.json` 与 `.private/` 私有 manifest。

## 重启后认证与路由检查（无模型推理）

```text
GET https://api.openai.com/v1/models/gpt-6-luna
GET https://api.openai.com/v1/models/gpt-6.2-sol
Authorization: Bearer <read from the existing local 0600 key file; value not logged>
```

修复本机文件漏掉的一个字符后，从活动隧道路由对两种模型的 GET 均收到 HTTP 200；这是模型目录查询，没有调用 Responses API、生成内容或产生模型 token。结构化结果见 `AUTH_NETWORK_CHECK.json`。
