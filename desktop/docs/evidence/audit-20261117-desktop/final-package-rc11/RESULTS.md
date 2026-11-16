# RC11 full-source Linux package and native short verification

**PASS for the package and this limited native verification.** Desktop RC11 was built from the clean published Core b28 source, extracted into a fresh directory, and opened in real Linux WebKit using a new marked profile. First setup, the displayed Core version, actual long-task capability, empty task inventory, and owned-process shutdown were verified. No production source was modified during packaging or verification.

## Package identity

| Field | Value |
|---|---|
| Published source commit | `03535fe943f64f49e9e3d79e7949aca6c9ec9b87` |
| Git tree | `1792d58af7858208db5018a747d78a1c75848edf` |
| Frozen source dirty | `false` |
| Application | `io.localpilot.desktop.test`, Desktop `5.0.1-rc.11` |
| Modules | Core `5.0.0b28`, Suite `0.2.0b32`, Companion `0.5.7b8`, Channels `0.1.0a4` |
| Artifact | `LocalPilot-Test-5.0.1-rc.11-linux-x86_64.deb` |
| Artifact SHA-256 | `aff81df4bdcef0b49ec31582a312a473b6730516e07f902ff08a231f6b99cc5b` |
| Artifact size | 114636308 bytes |
| Extracted ELF SHA-256 | `e81b4c079fc9105f28228096e500520451b624e2317214a7ec634f3b68dc52cd` |
| Package runtime | Distribution Python 3.13 with the existing pinned py313 dependency lock |
| Installation scope | Extracted DEB validation; no system-wide package installation |

The complete DEB is at `/workspace/scratch/c0f3ec78c621/validation/package-b28-b8-b32-DtZ0R2/build-source/desktop/release/linux-test-v5.0.1-rc.11/20261117-050536-74/LocalPilot-Test-5.0.1-rc.11-linux-x86_64.deb`. This record does not claim a GitHub binary upload or macOS qualification.

## Build verification

The build used the repository's existing Linux release workflow, shared build lock, one Rust worker, existing verified frontend dependencies, and fixed offline wheel and Node inputs. `build-recipe.sh` records the scratch orchestration. The source checkout remained clean; `source-snapshot.json` records 2381 input-file hashes.

All four LocalPilot wheels were rebuilt from the published source. No Core b27 wheel was reused. `verified-source-before-build.json` and `verified-source-after-build.json` verify the same **286 Python/Swift source files** against that frozen checkout: Core 148, Companion 110, Suite 21, Channels 7. Both checks verified all **40 wheels**.

`package-results.json` records the native bundle self-check, test application identity, exact component versions, ELF architecture, extracted-runtime imports, `pip check` with no broken requirements, and Node v22.23.4 execution. The native smoke used that delivered DEB's extracted executable and resources, not the mutable shared Rust target.

## Real native UI — fresh profile G

The independent profile was `/workspace/scratch/c0f3ec78c621/native-rc11-g`. Its private `test-owner.json` marks it as LocalPilot installation E2E data. No earlier profile was migrated or reused.

| Check | Observed result and evidence |
|---|---|
| Actual WebKit starts the new build | `01-initial-rc11.png` shows Desktop 5.0.1-rc.11. |
| First setup prepares and connects bundled components | `02b-prepare-components.png`, `03-connected-components-no-model.png`, and `04-ready-components-rc11.png`; model downloads and account connections were skipped. |
| Main UI connects to Core b28 | `05-main-core-b28.png` shows Desktop RC11 and Core 5.0.0b28. |
| Long-task UI gate accepts the real service capability | `06-long-task-24h-unsent.png` shows the selected 24-hour setting with an empty composer. No task was submitted. |
| Actual packaged service advertises the extension | `service-capabilities.json`: `desktop_execution_budget_v1` is present and `compatibility.limits.task_timeout_seconds` is 86400. |
| Live task inventory remains empty | Read-only packaged CLI inspection returns `task_count=0`; `07-live-service-capabilities.png`. |

`02-first-setup-rc11.png` was captured before the first page transition completed; the subsequent `02b` image records the preparation page. Both original captures are retained.

The reviewed helper retains WebKit sandboxing, a private `/dev`, and the existing X11 authorization file read-only. Only the marked profile is writable. The preserved native log contains the expected inaccessible accessibility-bus and read-only Mesa cache warnings from this validation environment; the visible UI and service checks above completed. No network, proxy, TLS, or sandbox-disable configuration was changed.

## No model requests and owned shutdown

`native-no-model-requests.json` records Companion `backend=disabled`, no watched directories, observation off, proactive level off, automatic local/cloud inference off, no entered API key, and no connected account. Core SQLite `checkpoints` and `journal` are both 0. Companion memories, training examples, and observation events are also 0. This scope covers profile G only; separate ongoing benchmark and long-soak jobs are excluded.

`native-rc11-g-stop.json` verifies the exact executable hash and canonical profile root before signaling this UI. It ends with `STOPPED`, `owned_remaining=[]`, and launcher return code 143. `08-stopped-windows.json` and `08-owned-stop-receipt.png` record that no LocalPilot window remained. The native CUA completion summary was recorded after this observation. Other terminal tabs and their ongoing validation jobs were left running.

## Evidence boundaries

This short check verifies RC11 startup, offline first setup, the displayed new Core version, actual service capability, and shutdown. It does not execute a 24-hour task, repeat the full A/B profile matrix, measure RC11 animation, qualify a physical Mac, or prove a binary upload.

`desktop-source-continuity.json` records no changes in `desktop/src` or `desktop/src-tauri/src` between RC10 source `91dd87c6fd4678c103d6383dec1c1385deb38f9a` and this source. The previous animation results remain measurements of the **RC10 artifact**, not measurements of RC11. `previous-rc10-evidence-integrity.json` verifies all 58 original RC10 manifest entries without changes.

Build-directory timestamps and native desktop receipt timestamps are preserved as emitted by their respective environments. They have not been rewritten to imply one shared clock. The new manifest hashes this directory independently; no older evidence or artifact was overwritten.
