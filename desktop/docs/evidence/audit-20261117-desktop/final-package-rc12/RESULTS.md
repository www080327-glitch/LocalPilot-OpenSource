# RC12 full-source Linux build and partial native startup

**Build: PASS. Native short qualification: PARTIAL_DEFERRED.** The RC12 package was built successfully from the clean published Core b29 source. A fresh profile opened the actual extracted executable in Linux WebKit and prepared its bundled components. The root agent then requested that further RC12 UI qualification stop because a separate b29 engineering run had exposed a completion-accounting failure. The owned RC12 instance was stopped normally. Main-page version display and live service capability verification were not performed, and this record does not claim a complete native smoke pass.

## Exact identity

| Field | Value |
|---|---|
| Published source commit | `8e92deb8b6a0acbba1d139851b1d805246304c61` |
| Source tree | `813a2544f1553d9c6a5e8a01982f2f512eec5e5b` |
| Frozen source dirty | `false` |
| Application | `io.localpilot.desktop.test`, Desktop `5.0.1-rc.12` |
| Modules | Core `5.0.0b29`, Suite `0.2.0b32`, Companion `0.5.7b8`, Channels `0.1.0a4` |
| Artifact | `LocalPilot-Test-5.0.1-rc.12-linux-x86_64.deb` |
| Artifact SHA-256 | `af649f825c5d7096c60a6b42417f3d6bc7d49054cb7360f9a2de79e48706e253` |
| Artifact size | 114637604 bytes |
| Extracted ELF SHA-256 | `b332a1126cbdc038c0e9d7dd4be4ae3f1b1f044b9e44506f9c712f506fca0ebe` |
| Package runtime | Distribution Python 3.13, built with the existing pinned py313 dependency lock |
| Installation | Extracted DEB only; no system-wide package installation |

The delivered file remains at `/workspace/scratch/c0f3ec78c621/validation/package-b29-b8-b32-PDLvOt/build-source/desktop/release/linux-test-v5.0.1-rc.12/20261117-060121-30852/LocalPilot-Test-5.0.1-rc.12-linux-x86_64.deb`. Its size and hash were checked again when collecting this evidence. No old package was overwritten.

## Build and source verification

The existing release workflow ran once in native Terminal tab 17 under the preserved foreground supervisor. `build-native-job.json`, `build-native-launcher.sh`, `build-native-supervisor.py`, `build-rc12-native.log.gz`, and `build-native-exit.json` retain the invocation and return code 0. `build-recipe.sh` records the isolated stage, shared Rust build lock, single worker, fixed dependencies, and preservation of preceding target artifacts.

All four LocalPilot wheels were freshly built from the published source. The source snapshot contains 2517 input-file hashes. Both resource checks are identical and passed: **286 Python/Swift source files**, comprising Core 148, Companion 110, Suite 21, and Channels 7, match the frozen checkout; all **40 wheels** were verified. The frozen source remained clean after the build.

`package-results.json` records the actual bundle self-check, test application identity, component versions, ELF architecture, extracted-runtime imports, `pip check` with no broken requirements, and Node v22.23.4 execution. The packaged runtime is Python 3.13; the native supervisor/build driver uses the separate, fixed Python 3.12.14 environment. Those interpreter roles are not interchangeable.

## Observed native startup and intentional stop

Profile H is `/workspace/scratch/c0f3ec78c621/native-rc12-h`, a new private, marked LocalPilot installation E2E root. No old profile was reused. Native Terminal tab 18 launched the extracted package, and tab 19 performed its verified shutdown.

| Step | Evidence and scope |
|---|---|
| Real WebKit opens RC12 | `01-initial-rc12.png` shows the RC12 welcome page. |
| First setup reaches Agent preparation | `02-prepare-components-rc12.png`. |
| Bundled components are prepared and connected | `03-connected-components-no-model.png`; no model or cloud key was configured. |
| Model download is skipped | `04-paused-before-completing-setup.png` retains the visible skip confirmation. The next setup step was not entered. |
| Owned UI and descendants stop | `native-rc12-h-stop.json`, `05-owned-stop-receipt.png`, and `05-stopped-windows.json`. |

The stop receipt checks the executable hash, wrapper identity, and canonical profile before signaling only the owned UI process. It finishes at `2026-11-16T21:08:30Z` with `STOPPED`, `owned_remaining=[]`, and launcher return code 143. The subsequent window inventory contains no LocalPilot window. The CUA completion summary was recorded after observing this result. The running two-hour job in native Terminal tab 8 and all other validation jobs were left untouched.

The reviewed helper retains WebKit sandboxing, a private `/dev`, and read-only X11 authorization. Only the marked profile is writable. The raw native log is preserved in compressed form. No proxy, TLS, network-policy, or sandbox-disable setting was changed.

## No task or model request from profile H

No task was submitted, model downloaded, API key entered, or account connected. `native-no-model-requests.json` records Companion `backend=disabled`, empty watched directories, observation off, proactive level off, and automatic local/cloud inference off. Read-only inspection after shutdown found Core `checkpoints=0` and `journal=0`, and zero Companion memories, training examples, and observation events.

Live task inventory and capability inspection were **not run**. The evidence deliberately uses `null` for the unobserved live task count; it does not substitute the SQLite counts for a live service reply. Prepared inspection scripts remain in scratch and were never executed. This scope excludes independent benchmark, engineering, grading, and b28 soak jobs.

## Remaining scope and preservation

First setup completion, the main UI's Core b29 label, actual `desktop_execution_budget_v1` readback, the 24-hour UI option, and animation sampling were not qualified for this package. The independent b29 engineering failure remains a failure; successful package construction does not change that result. Final native short qualification is deferred to the subsequent fixed candidate.

This record proves neither a system DEB installation, physical macOS behavior, a completed long task, nor a GitHub binary upload. No production source or version file was changed here.

`desktop-source-continuity.json` records unchanged `desktop/src` and `desktop/src-tauri/src` implementation bytes between the preceding RC11 source and this source. Earlier animation results remain measurements of their original RC10 artifact. `previous-rc11-evidence-integrity.json` verifies all 41 RC11 manifest entries without changes. Build-directory and native desktop timestamps are retained as emitted by their respective environments. The independent manifest covers only this new evidence directory.
