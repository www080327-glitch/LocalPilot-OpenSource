# PR #15 remaining acceptance — 2026-11-17

## Identity and source

- PR #15 is OPEN, base `main`, head branch `codex/native-polish-final-20261116`. The requested delivery head and remote PR head were both `97dae142a2deccfb1ed0add0c2cd49b4b02a8fad` at the start of this run; no newer commit was present.
- Current source tree SHA is recorded in [SOURCE.json](SOURCE.json). Candidate versions: Desktop 5.0.1-rc.17, Core 5.0.0b35, Companion 0.5.7b12, Suite 0.2.0b34, Channels 0.1.0a4. Version gate passed.
- The b35 source regression, install payload and workspace-scoped read-only role evidence are reused as documented in `docs/evidence/audit-20261117/root/rc17-followup-b35/RESULTS.md`; they are not relabelled as native or Full acceptance.

## Completed

Original commands are listed in [COMMANDS.md](COMMANDS.md); raw logs and private receipts are kept locally and excluded from Git.

| Check | Result | Evidence |
|---|---|---|
| Existing Playwright page tests | PASS, 2/2 in Chromium | The requested `npm ci` and `LP_UI_EVIDENCE_DIR=... npm run test:ui -- tests/ui/model-configuration.spec.ts --output=...` flow passed both original cases. The first records the coordinator/role settings and save payload; the second verifies removing a partner or promoting it to primary clears the optional roles. Reporter JSON and raw log are under `browser/`. |
| Playwright screenshots and traces | PASS, 2 traces | A trace-enabled second run also passed 2/2; each `trace.zip` contains screencast frames. Representative final frames are `screenshots/roles-save.jpg` and `screenshots/roles-clear.jpg`. |
| Candidate version gate | PASS | `version-gate.log`; all five component versions are consistent. |
| Four current component wheels and arm64 dependencies | PASS | Core b35, Companion b12, Suite b34 and Channels a4 wheels built from this source. All 35 dependency wheels in the source lock were found locally with exact SHA-256 matches; the lock and bundled backend checks passed. The initial direct PyPI downloader and first missing build-tool attempts failed and are retained in private raw logs; no lock or dependency was altered. |
| Apple Silicon Test APP build | PASS, build/package only | `scripts/build-macos.sh` used the test Tauri config and single-worker build lock. APP identity `io.localpilot.desktop.test`, display name `LocalPilot Test`, version 5.0.1-rc.17; arm64 binary and `codesign --verify --deep --strict` passed. The app ZIP passed `unzip -t`; the DMG passed `hdiutil verify`. Fresh app ZIP and DMG SHA-256 are in [macos-artifact-hashes.txt](macos-artifact-hashes.txt). The APP candidate itself remains in the repository's generated release/build locations, not copied into this evidence folder. Ad-hoc signing is not notarization. |
| Installer dry-run plan | PASS, plan only | [install-plan-summary.json](install-plan-summary.json) records an rc.7 → rc.17 Test APP upgrade plan, source/installed tree hashes, `executed=false` and unchanged user data. The actual plan receipt is preserved locally under `.private/` and excluded from Git. |

The initial attempt to add an unsupported Playwright `--screenshot` flag failed; it is retained in `browser/invalid-extra-screenshot-option.log`. The prescribed test command was then run unchanged and passed. An initial component wheel attempt also failed because the system Python lacked setuptools, and the first Channels attempt lacked the `build` module. Both failures are retained; the isolated build environment was then prepared using the repository-documented build tools and all four current wheels built.

## Failed / blocked / not run

| Gate | Result | Concrete condition |
|---|---|---|
| Full engineering R12, Luna high | FAIL before model inference; gate NOT PASSED | The same frozen runner SHA and original synthetic fixture were used after your limited authorization. Luna/high was configured, the two-child limit and 4096 per-child output-token cap were preserved. The task became quiescent/failed after 12.5s with `SSL: UNEXPECTED_EOF_WHILE_READING` connecting to `https://api.openai.com/v1`; unauthenticated curl to the same host returned `SSL_ERROR_SYSCALL`. It recorded no model calls or children, and provider usage is UNKNOWN. This is transport failure, not model-capability failure; Sol was not attempted. The original complete runner output and raw logs remain locally under `.private/`, excluded from Git; [R12_RESULT_SUMMARY.json](R12_RESULT_SUMMARY.json) binds their hashes. No alternate endpoint or entry was used. |
| Install / upgrade / rollback / restore | NOT_RUN beyond dry-run | The fixed `~/Applications/LocalPilot Test.app` is running version rc.7 (PID and executable hash in [app-slot-state.json](app-slot-state.json)). Its `LP_INSTALL_TEST_ROOT` belongs to another still-active acceptance. Replacing or stopping it would disrupt that task and would reuse its private data root, so it was left untouched. No install execute, rollback archive, restore, or failure injection was run. The only restore artifact is a reviewed plan, not a completion receipt. |
| Current candidate native GUI interaction | NOT_RUN | Candidate built but not installed. No cold-start/restart, focus, pet bubble, drag poses, resize, multi-display or Reduce Motion interaction on this candidate. |
| Visible animation sampling ≥24 Hz | NOT_RUN | No installed candidate; only one built-in display is attached. No rAF-only substitute or animation result is claimed. |
| Physical Intel Mac | NOT_RUN | This host is arm64; no actual x86_64 Mac was available. |
| Linux native install and GUI | NOT_RUN | No supported Linux desktop/system package environment was attached. Historical Linux packages refer to older commits and were not reused as this candidate's result. |
| Installed Full + extended two-hour soak | NOT_RUN | Current candidate is not installed, and no source-tree substitute was used. The required 240 heartbeats, completion receipt, installed import-source proof and process-exit check are absent. |

The build host inventory is summarized in [macos-host-summary.txt](macos-host-summary.txt). Only Command Line Tools were selected and `xcodebuild -version` was unavailable, but the repository's current Tauri/arm64 build completed.

## Release state

**NOT_RELEASE_READY.** Browser tests and Apple Silicon build/package checks passed. The Full R12 inference, installed Test upgrade/rollback/restore, current-candidate GUI/animation, physical Intel, Linux and installed two-hour soak gates remain open. This report preserves the R12 network failure and the active Test slot as blockers; it does not merge, tag, release or replace the daily APP.
