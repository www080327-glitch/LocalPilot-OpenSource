# Commands run for this acceptance

Paths are normalized so the public record does not expose a local username or workspace path. Full raw shell logs and the install dry-run receipt remain locally under `.private/` and are excluded from Git.

```sh
python3 scripts/check-candidate-versions.py
(cd desktop && npm ci)
(cd desktop && LP_UI_EVIDENCE_DIR="$LP_RUN/browser" npm run test:ui -- tests/ui/model-configuration.spec.ts --output="$LP_RUN/browser/test-results")
(cd desktop && LP_UI_EVIDENCE_DIR="$LP_RUN/browser-traced" npm run test:ui -- tests/ui/model-configuration.spec.ts --output="$LP_RUN/browser-traced/test-results" --trace on)
python3 desktop/scripts/lock-runtime-dependencies.py --arch arm64 --wheels "$LP_CACHE/dependencies" --out "$LP_CACHE/runtime-dependencies-arm64.json"
python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir "$LP_CACHE/components" .
python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir "$LP_CACHE/components" ./companion
python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir "$LP_CACHE/components" ./suite
python3 scripts/build_channels_wheel.py --out "$LP_CACHE/components" --no-isolation
python3 desktop/scripts/prepare-bundled-backends.py --arch arm64 --wheels "$LP_CACHE/components" --dependencies "$LP_CACHE/dependencies" --dependency-lock "$LP_CACHE/runtime-dependencies-arm64.json"
python3 desktop/scripts/check-bundled-backends.py --arch arm64 --dependency-lock "$LP_CACHE/runtime-dependencies-arm64.json"
(cd desktop && LP_GUI_DEPENDENCY_LOCK="$LP_CACHE/runtime-dependencies-arm64.json" LP_GUI_USE_INSTALLED_DEPS=1 LP_GUI_TEST_CONFIG=src-tauri/tauri.test.conf.json scripts/build-macos.sh)
python3 scripts/qualify_openai_engineering.py --source-root "$LP_SOURCE" --key-file "$LP_KEY_FILE" --model gpt-6-luna --reasoning high --output "$LP_RUN/engineering-luna-high-r12-followup"
python3 desktop/scripts/install-local-app.py --source "$LP_CANDIDATE" --test-app --receipt "$LP_RUN/.private/install/rc17-install-plan.json"
```

Exit results and logs are in this directory. R12 preserved the runner's original synthetic fixture, two-child cap and 4096 worker output cap. The command failed before any model call because the OpenAI API TLS connection was interrupted. The install command above is the dry-run only; no `--execute` command was issued because the fixed target was actively occupied by another acceptance.
