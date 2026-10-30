# Installation, independent upgrades and rollback

This candidate is qualified on macOS arm64 / Python 3.14.6. The wheels contain Python and existing helper source; they do not contain model weights, caches, user memory, credentials or runtime databases. Native Computer Use admission is unchanged. No new native helper was built in battery qualification.

## Install once

Create an isolated environment and install the reviewed wheels from the same release directory. Dependencies can be resolved normally, or supplied in a wheelhouse for offline installation. The local qualification used a fresh environment and an explicit dependency directory; it did not change user environments.

```sh
python3 -m venv "$LP_ENV"
"$LP_ENV/bin/python" -m pip install --find-links "$LP_ARTIFACTS" 'localpilot-suite==0.1.0rc2'
"$LP_ENV/bin/localpilot" --version
```

Suite dependencies bind Core >=4.9.2rc2,<5 and Companion >=0.5.5rc2,<0.6. Distribution names differ from command names. This does not imply publication on PyPI; local wheels/source archives are the delivered artifacts.

Standalone alternatives:

```sh
"$LP_ENV/bin/python" -m pip install "$LP_ARTIFACTS/localpilot_agent_service-4.9.2rc2-py3-none-any.whl"
"$LP_ENV/bin/localpilot-core" --help
"$LP_ENV/bin/python" -m pip install "$LP_ARTIFACTS/localpilot_companion-0.5.5rc2-py3-none-any.whl"
"$LP_ENV/bin/companion" --help
```

Core has its own service, SDK, adapter and CLI; it never requires Companion. Companion dependencies do not include Core; configured delegation uses HTTP. `companion --config FILE ...` requires its own explicit configuration. Suite supplies a conservative starter Companion configuration after Core init. A separately installed Companion can target the same public API from another environment.

Use init, doctor, start and the examples in SUITE_CLI.md. Place data outside both code installation and task workspace. `doctor` reads service configuration/contract without contacting inference backends; unavailable service returns nonzero and model health remains NOT_PROBED. Initial model paths/endpoints reference existing deployment; startup never downloads weights.

## Independent upgrade

Keep the previous wheel and a SQLite backup before changes. Explicitly resolve active tasks, then stop the affected service. A client terminal closing is not a service stop. Core CLI refuses to stop a service with active tasks of any owner. The upgrade manager refuses to replace a live managed Core or Companion. It does not auto-approve or cancel work.

```sh
localpilot --home "$LP_DATA" companion stop
localpilot --home "$LP_DATA" upgrade companion --wheel "$NEW_COMPANION_WHEEL" --previous-wheel "$OLD_COMPANION_WHEEL"
localpilot --home "$LP_DATA" upgrade companion --wheel "$NEW_COMPANION_WHEEL" --previous-wheel "$OLD_COMPANION_WHEEL" --execute
localpilot --home "$LP_DATA" companion start

localpilot --home "$LP_DATA" stop
localpilot --home "$LP_DATA" upgrade core --wheel "$NEW_CORE_WHEEL" --previous-wheel "$OLD_CORE_WHEEL" --execute
localpilot --home "$LP_DATA" start
localpilot --home "$LP_DATA" doctor
```

Without --execute, upgrade prints the exact installation plan. Execution requires a previous-wheel path so recovery is concrete, validates distribution metadata, records the rollback plan in private data, and uses pip --no-deps to replace only the selected module. No package upgrade overwrites user data directories or provider credentials. Dependency compatibility still needs doctor and pip check. Do not run simultaneous upgrades in one environment. Installer failure may require restoring the previous wheel manually; this candidate does not claim transactional pip installation.

For the initial 0.5.4 -> 0.5.5rc2 / 4.9.1rc2 -> 4.9.2rc2 migration, upgrade Companion first. Old Companion rejects the new Core version. A rollback to Core 4.9.1rc2 preserves data but removes the new Core CLI; Suite reports its missing minimum CLI clearly and the thin `upgrade core ...` path can restore the candidate. This is an explicit compatibility limitation, not full functionality on every historical combination.

## Rollback

Stop the affected service, then reverse the wheel arguments. Restore database snapshots only to a new private destination with matching original backend/workspace/verification configuration; do not force schema changes or overwrite live SQLite files. Core's existing conservative snapshot tool is:

```sh
"$LP_ENV/bin/python" -m localpilot_service.backup backup "$LP_DATA/data/runtime.sqlite3" "$LP_BACKUP"
```

Rollback of an existing authorized task must preserve original route/backend fingerprint and UNKNOWN obligations. This phase tested real package downgrade/upgrade and idle/history SQLite recovery, not a real-model in-flight database schema migration. No schema migration was added.

## Uninstall and reinstall

Stop each service explicitly after task reconciliation. Remove distributions using pip uninstall; retain LP_DATA. Reinstall reviewed wheels and point to the same data/config. Do not delete user data as an uninstall side effect. An explicit user decision is required before deleting memory, credentials, databases or backups. Qualification confirmed five protected configuration/user files retained exact SHA256 through independent upgrades, rollback and Companion uninstall/reinstall.

## Diagnostics and limits

A token failure is 401/403; no token is printed. Port conflicts fail without signalling the existing port owner. Process stop validates PID creation time, owner and exact CLI/home identity; stale or mismatched records do not authorize signalling another process. The service uses its existing SQLite ownership locks. SSE detach/reconnect does not replay work. Persistent submission keys must be reused after uncertain delivery.

Resource and test evidence are in the release report. Rules-only startup, scripted provider testing and short idle runs do not certify real-model quality, long-duration stability, model switching or cache performance. Qwen, Qwen -> DeepSeek, live cross-model Agent handoff and UI notification delivery remain separate admission gates.

## Current managed installation profile

`localpilot init --workspace /your/workspace --managed-qwen35` uses the exact approved cached Qwen3.6-35B revision and the installed `/Applications/oMLX.app` launcher. Install oMLX separately before using this preset; the wheel does not bundle it or weights. The vendor model interpreter is isolated from the CLI environment. `doctor` checks cached files, executable and credential references without running inference; static readiness is not model health. External local-openai services remain a supported alternative.

Suite detects the approved existing 0.8B cache and enables its Companion backend for on-demand interaction; use the Companion `[mlx]` optional extra. `--companion-model-path` supplies another explicitly chosen existing directory. The default remains no automatic inference on battery and no automatic cloud. Optional `--cloud-key-file` references an existing private DeepSeek credential file, never its value. `allow_automatic_cloud` remains false.

Managed task CLI defaults to a bounded 600-second deadline; use `--timeout` to select up to 3600 seconds. Detach leaves an ordinary-token API heartbeat controller; it cannot approve, execute tools or invoke models. Cursor-based watch and task show recover progress after terminal exit. Task input JSON UTF-8 limit is published in health compatibility; oversized original questions fail before submission, while optional context omissions remain explicit.
