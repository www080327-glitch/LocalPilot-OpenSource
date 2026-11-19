# Final full-source RC10 package and native validation

**PASS for the verified package, main UI, service capability and pet interactions.** The first pet launch from the long profile E path failed with the documented Linux Unix-socket path limit. That failure is retained; the independent short profile F completed the pet checks. No production source was changed during this validation.

## Package identity

| Field | Value |
|---|---|
| Published source commit | `91dd87c6fd4678c103d6383dec1c1385deb38f9a` |
| Git tree | `c19b18071de42ed42feb25519671a559f38dec18` |
| Source dirty | `false` |
| Test application | `io.localpilot.desktop.test`, Desktop `5.0.1-rc.10` |
| Modules | Core `5.0.0b27`, Suite `0.2.0b32`, Companion `0.5.7b8`, Channels `0.1.0a4` |
| DEB | `LocalPilot-Test-5.0.1-rc.10-linux-x86_64.deb` |
| DEB SHA-256 | `cd6b7c33baf93e352c0f6f84b56ea32deddd0804425c5110d4bb6b6da27cb73f` |
| DEB size | 114633328 bytes |
| Extracted ELF SHA-256 | `4dd57426eec47489828d18bb6f2ce8a200a7018435144d649cfbad2d44668c84` |
| Installation claim | Extracted DEB validation only; **not installed system-wide** |

The complete artifact is at `/workspace/scratch/c0f3ec78c621/validation/package-b27-b8-b32-Azb7vG/build-source/desktop/release/linux-test-v5.0.1-rc.10/20261117-023617-73/LocalPilot-Test-5.0.1-rc.10-linux-x86_64.deb`. This evidence does not claim a GitHub binary upload.

`package-results.json` records the successful bundle self-check, all 40 verified wheels, packaged-runtime imports, `pip check`, and Node v22.23.4. All four LocalPilot wheels were rebuilt from the clean published source. `verified-source-before-build.json` and `verified-source-after-build.json` verify 286 Python/Swift source files byte-for-byte against that frozen checkout: Core 148, Companion 110, Suite 21, Channels 7. No old backend wheels were substituted. `source-snapshot.json` records individual input hashes. The build used one worker, the repository's Linux release workflow, offline wheel inputs, and the existing installed frontend dependencies after checking their lock file against the frozen source.

## Main UI and actual service — fresh profile E

| Verification | Evidence |
|---|---|
| Actual WebKit starts RC10 | `01-initial-rc10.jpg`, `02-setup-rc10.jpg` |
| First setup prepares bundled components; model downloads and accounts skipped | `04-ready-core-b27.jpg` shows ready components; version itself is visible in `05-main-core-b27.jpg` |
| Shared cloud form offers OpenAI with default `gpt-6-luna`; key remains empty | `03-openai-setup-empty-key.jpg` |
| Connected main UI displays Core 5.0.0b27 | `05-main-core-b27.jpg` |
| Real service enables long-task choices; 24-hour draft selection is visible | `06-long-task-24h-unsent.jpg` |
| Service actually advertises the extension and limit | `service-capabilities.json`: `desktop_execution_budget_v1`, `compatibility.limits.task_timeout_seconds=86400` |
| No model/task submission | Live task list count 0 and active task count 0; `native-no-model-requests.json` |

The native run verifies the real package's capability response and UI gate, not a completed 24-hour task. Actual budget switching/submission arguments are covered by the existing implementation tests and the runtime audit. Cloud `already_configured` feedback is covered by final browser run 7; this native run deliberately does not save an API key or call a cloud provider.

### Preserved first pet-start failure

Profile E's socket path was **115 UTF-8 bytes**, and the real pet process exited with `path must be shorter than SUN_LEN`. `native-final-e.log.gz` and `long-path-failure.json` retain the failure. The main UI checks above remained valid. We stopped all owned E processes and created the independent, marked `/workspace/scratch/c0f3ec78c621/native-rc10-f` root. Its socket path is 69 bytes. No earlier profile was migrated, no original snapshot was overwritten, and no socket workaround was added to production code.

## Final pet — independent profile F

Both E and F use the same extracted final ELF. The existing reviewed validation helper preserves WebKit sandboxing, a private `/dev`, and the single existing X11 auth file read-only; only the corresponding marked profile is writable. F appends `--companion-pet` to the same helper. The fixture is numbered transparent geometry with eight source atlas frames per direction and nine edge poses. It intentionally omits the optional comic extension. No personal character or product artwork was edited.

| Verification | Evidence |
|---|---|
| Final package displays the fallback pet without optional comic | `07-pet-ready.jpg` |
| Real body click retracts and peeks at the opposite edge | `08-pet-after-single-animation.jpg`, `animation-final-single-run.json` |
| First manual opening has a compact 320×221 bubble | `09-first-expanded-compact.jpg`, `09-first-expanded-windows.json` |
| Direct typing after opening uses input focus | `10-focused-unsent-draft.jpg`; `rc10-focus-draft` was cleared, never sent |
| Button hover remains readable | `11-button-hover-readable.jpg`, `12-advanced-hover-readable.jpg` |
| Returning from settings restores the compact chat height | `13-return-chat-compact.jpg` |

### One final-package animation sample

The existing TestProfile-only diagnostic sampled **6015 ms**. We kept the first completed sample; no repeated runs were used to select a higher result.

| Phase | rAF opportunities/s | Probe visual changes/s | Conservative full observed phase changes/s |
|---|---:|---:|---:|
| RETRACTING | 57.0410 | **28.5205** | **28.5205** |
| PEEKING | 60.3577 | **29.3890** | **28.3160** |

Both measures of visual changes exceed 24/s in both observed phases. The probe rate is `(changed samples − 1) / (last changed time − first changed time)`; the conservative column uses the complete observed phase duration instead. Raw arrays and exact values are in `animation-final-single-run.json` and `animation-final-summary.json`.

These are actual WebKit rAF observations of laid-out sprite geometry, opacity, transform and crop, not physical-display photometry. The measured DPR is 1. They do not promise a constant interval between every frame or 24 unique drawings. Native window relocation occurs after retraction; continuous sprite motion takes place within the window. The previous D run separately covers same-side anchors, app animation off and service recovery; its immutable evidence remains under `../native/`.

## No provider requests and owned-process shutdown

`native-no-model-requests.json` records both profiles with Companion `backend=disabled`, no watched directories, native observation off, proactive level off and automatic cloud off. Profile E's live Core task count, SQLite `checkpoints` and `journal` are all 0. Both Companion databases have 0 memories, training examples and observation events. Schema and FTS metadata rows are reported by their actual names and are not described as user tasks. No task was submitted from the main window or pet, and no API key, model download or account connection was used.

`native-final-e-stop.json` and `native-final-f-stop.json` verify the executable hash and canonical profile root before signaling only the owned UI. Both end with `STOPPED`, `owned_remaining=[]` and launcher exit 143. The private process namespace then has no surviving owned service. `14-stopped-windows.json` / `14-stopped.jpg` show no LocalPilot windows remaining. The CUA completion summary was recorded after that observation.

Host clock strings are preserved verbatim: native desktop receipts and build-host timestamps differ. They have not been rewritten to imply a shared clock. Build logs, first failure, screenshots, scripts and result metadata are hashed in `MANIFEST.json`; this directory does not alter the earlier D or A/B manifests.
