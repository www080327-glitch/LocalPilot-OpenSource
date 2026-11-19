# RC14 full-source package and native qualification

**Build: PASS. Native short qualification: PASS. Final-package animation: PASS in one complete 6007 ms sample.** The actual running service, installed package metadata, source constant, and visible main window all identify Core `5.0.0b31`. Both fresh GUI profiles were stopped after verification, with no owned process remaining. No GUI model request or task submission occurred.

## Package and source identity

| Field | Value |
|---|---|
| Published source | `c5439659a579b2ee9e74fd53e6d3232fe12fb855` |
| Source tree | `d0b0b33b036587ef0f0a802ca728419e9a444587` |
| Frozen source dirty | `false`, checked again during collection |
| Application | `io.localpilot.desktop.test`, Desktop `5.0.1-rc.14` |
| Backend versions | Core `5.0.0b31`, Suite `0.2.0b32`, Companion `0.5.7b8`, Channels `0.1.0a4` |
| Artifact | `LocalPilot-Test-5.0.1-rc.14-linux-x86_64.deb` |
| Artifact SHA-256 | `66aed474856ffa958ec07d383dd8f31840bbbdabbd0613e229ce342f9b78ce61` |
| Artifact size | 114637332 bytes |
| Extracted ELF SHA-256 | `75ffa8be30e8a7c73c4cc7806c29cd65d6d9e115bb78e07e5bf097c09dee864c` |

The complete DEB remains at `/workspace/scratch/c0f3ec78c621/validation/package-b31-b8-b32-LtvhM6/build-source/desktop/release/linux-test-v5.0.1-rc.14/20261117-064919-35957/LocalPilot-Test-5.0.1-rc.14-linux-x86_64.deb`. Its size and SHA-256, and the extracted ELF hash, were verified again while collecting this evidence. No system DEB installation or binary upload occurred.

## Build verification

The existing Linux release workflow ran once in native Terminal tab 25, under the existing shared build lock with one Rust worker. Its foreground supervisor records return code 0. The fixed supervisor uses Python 3.12.14; the delivered distribution runtime uses Python 3.13. These are separate, deliberate roles.

All four LocalPilot wheels were freshly built from the published source. Both before-build and after-build resource checks are identical and pass for **286 Python/Swift source files**: Core 148, Companion 110, Suite 21, and Channels 7. All **40 wheel files** were verified. The source snapshot retains individual input hashes. The frozen source checkout remained clean.

`package-results.json` records successful bundled-backend validation, extracted-runtime imports, `pip check`, and Node v22.23.4 execution. `candidate-versions.json` passes the version gate, including the newly checked service constant. `runtime-version-match.json` then connects the source constant and packaged metadata to the version actually returned by the running service. Build recipe, native launcher, supervisor, job, logs, and exit receipt are preserved here.

## Fresh main-window profile K

The new private root was `/workspace/scratch/c0f3ec78c621/native-rc14-k`. Native Terminal tab 27 launched the actual extracted candidate with the existing reviewed read-only helper overlay. WebKit sandboxing remained enabled. The UI was operated through native screenshot coordinates because the accessibility bus is unavailable in this environment.

| Actual observation | Evidence |
|---|---|
| Real WebKit startup displays Desktop RC14 | `01-initial-rc14.png` |
| First setup prepares and connects bundled components | `02-prepare-components-rc14.png`, `03-connected-components-no-model.png` |
| The shared cloud form offers OpenAI and defaults to `gpt-6-luna`; the key remains empty | `04-openai-empty-key.png` |
| The final setup review reports Core ready and Companion running; unconnected channels remain unknown | `05-ready-components-rc14.png` |
| Setup completes and the main page visibly reports Core b31 | `06-main-core-b31.png` |
| The long-task selector offers and selects 24 hours with an empty, unsent composer | `07-long-task-24h-unsent.png` |
| Packaged Python reaches the actual service and reads its capabilities and empty task list | `service-capabilities.json`, `08-live-service-capabilities.png` |

The live service returns `version=5.0.0b31`, `task_count=0`, and `active_task_count=0`. Its compatibility manifest includes `desktop_execution_budget_v1` and `limits.task_timeout_seconds=86400`. Installed metadata reads b31/b32/b8/a4 in the same result. `core-service.log.gz` independently records the b31 ready event.

This confirms the actual service capability and the UI option. No 24-hour task or execution-budget session was submitted in this GUI check. The empty-key cloud form was inspected without saving a credential or making a provider request.

## Fresh desktop-pet profile L

The independent short root was `/workspace/scratch/c0f3ec78c621/native-rc14-l`. Terminal tab 29 launched the same extracted ELF in Companion-pet mode. The synthetic numbered geometric fixture has eight source frames per direction and nine edge poses; optional comic extras are absent. Fixture generation and hashes are preserved. Product artwork and animation source were not edited during this qualification.

The visible body moved from the right screen edge to the left after the physical body click. The first opened conversation window was **320 × 221 pixels**, recorded in `compact-bubble-windows.json` and `12-compact-bubble.png`. Typing immediately after opening it produced `rc14-focus-draft` in the composer, demonstrating automatic input focus without an extra input click. The draft was cleared with Select All and Backspace, without pressing Send or Return. Both states are captured in `13-focused-unsent-draft.png` and `14-cleared-unsent-draft.png`.

### One final-package animation sample

Terminal tab 30 sent the existing `measure_animation` control exactly once, followed by a physical click on the visible pet body. The existing test-profile probe recorded **6007 ms**, including both `RETRACTING` and `PEEKING`. No sample was discarded, repeated, or selected for a better rate. `animation-final-single-run.json` is the unmodified raw sample, including every recorded timestamp; `animation-attempt.json` binds the attempt to this package and source.

| Phase | rAF opportunities/s | Visible changes/s | Full observed phase visible changes/s | Observed phase duration |
|---|---:|---:|---:|---:|
| RETRACTING | 60.3908 | 29.7565 | **29.3073** | 1126 ms |
| PEEKING | 59.3912 | 30.0231 | **28.9532** | 1347 ms |

The conservative full-phase rate is `(visible_change_count - 1) / (last_frame_time - first_frame_time)`. The middle column uses the time from the first to last visible change; the first column counts rAF sampling opportunities. The complete calculations are in `animation-final-summary.json`. Both conservative phase rates exceed 24 changes per second in this single observed run.

This measures actual native WebKit layout-visible geometry, opacity, transform, and sprite background-position changes. It does not measure physical display scanout and does not imply 24 independent drawings: the fixture contains eight source frames per direction. The native window relocation itself is a separate position change after retraction. The observed display scale was DPR 1, with reduced motion disabled. Earlier reduced-motion, Retina/multiple-screen, or hover evidence is not represented as new RC14 measurement.

## No GUI model request and owned shutdown

No model was downloaded, API key entered, messaging account connected, or task submitted. Both profiles retain a disabled Companion backend, no watched directories, and observation/automatic inference disabled. The live Core task inventory was empty. Post-stop, read-only SQLite counts are zero for K's Core checkpoints/journal and both profiles' Companion memories/training examples/observation events. L is a pet-only profile and has no Core database; no invented Core count is assigned to it. `native-no-model-requests.json` records these checks.

The exact candidate hash and each private root were checked before signaling the owned UI process. K stopped at `2026-11-16T21:57:32Z`; L stopped at `2026-11-16T21:59:36Z`. Both stop receipts report `STOPPED`, `owned_remaining=[]`, and launcher return code 143. The K screenshot/window inventory is also preserved. L's final stop receipt was visibly observed in Terminal, followed immediately by the required CUA completion summary. No separate final L desktop screenshot was saved.

The native evidence excludes the independent R6 engineering, grading, and b28 two-hour soak jobs. The ongoing soak's Terminal tab 8 was not operated or signaled. Accessibility/session-bus and read-only Mesa shader-cache warnings remain in the original logs; they were not suppressed or treated as successful OS integration tests.

## Evidence boundaries

This is an extracted-DEB native Linux short qualification using the reviewed helper overlay. It is not a system package-manager installation, physical macOS qualification, high-DPI/multi-screen test, actual 24-hour task run, or authenticated GitHub Release upload. There was no automatic retry after a failure and no production source or version change during this run.

The prior RC13 build PASS/native version FAIL remains unchanged. `previous-rc13-evidence-integrity.json` verifies all 57 previous manifest payload entries by size and SHA-256. Older RC10/RC11/RC12 artifacts and observations keep their original package identities. Timestamps are retained exactly as emitted by their respective native and build environments. The new manifest covers this directory independently.
