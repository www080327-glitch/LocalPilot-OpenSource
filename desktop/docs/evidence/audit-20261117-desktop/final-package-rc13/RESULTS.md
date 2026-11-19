# RC13 full-source build and failed native version gate

**Build: PASS. Native version gate: FAIL. Overall native qualification: NOT_PASSED. Animation: NOT_RUN.** The delivered RC13 package and installed distribution metadata identify Core b30, but the actual running service reports b28. The frozen source itself still declares `VERSION = "5.0.0b28"` in `localpilot_service/__init__.py`. This is preserved as the first observed native failure; no version constant, package, or frozen source was edited during qualification.

## Package and source identity

| Field | Value |
|---|---|
| Published source | `1dca93c5a6a2d0c557a9507ca020c07458dd92d1` |
| Source tree | `1457ce75f9134196c0c489f69bc4ee5b03467d4b` |
| Frozen source dirty | `false` |
| Application | `io.localpilot.desktop.test`, Desktop `5.0.1-rc.13` |
| Packaged module metadata | Core `5.0.0b30`, Suite `0.2.0b32`, Companion `0.5.7b8`, Channels `0.1.0a4` |
| Actual service version | **`5.0.0b28`** |
| Artifact | `LocalPilot-Test-5.0.1-rc.13-linux-x86_64.deb` |
| Artifact SHA-256 | `de6b7f78628f08b300160c24072684ad3a0d6da6af6f4c47762ca86a39413854` |
| Artifact size | 114638754 bytes |
| Extracted ELF SHA-256 | `8ad9303a963ebf3ce3eb5491d2b50ffa89ce6cfdc72b7244f28d276223a1b49d` |

The complete artifact is preserved at `/workspace/scratch/c0f3ec78c621/validation/package-b30-b8-b32-WdAimn/build-source/desktop/release/linux-test-v5.0.1-rc.13/20261117-063304-33737/LocalPilot-Test-5.0.1-rc.13-linux-x86_64.deb`. Its size and hash were verified again during evidence collection. It was extracted for validation; no system DEB installation or binary upload occurred.

## What the build passed

The existing release workflow ran once in native Terminal tab 21, with the existing shared build lock and one Rust worker. The preserved foreground supervisor receipt records return code 0. Build recipe, supervisor, invocation, output, and exit receipt are included in this directory.

All four LocalPilot wheels were freshly built from the published source. Both source checks are identical and pass for **286 Python/Swift files**: Core 148, Companion 110, Suite 21, and Channels 7. All **40 wheels** were verified. The source snapshot retains individual input hashes; the frozen checkout remained clean.

`package-results.json` records successful bundle metadata validation, extracted-runtime imports, `pip check`, and Node v22.23.4 execution. The installed package runtime is distribution Python 3.13; the native build supervisor uses the separate fixed Python 3.12.14 environment. These successful build checks did not compare the service's runtime version constant with package metadata, so they do not override the failed native gate.

## Actual native observations

The new private profile I was `/workspace/scratch/c0f3ec78c621/native-rc13-i`. It did not exist before this run. Terminal tab 23 launched the actual extracted DEB binary using the existing reviewed read-only helper; WebKit sandboxing remained enabled.

| Observation | Evidence |
|---|---|
| The real WebKit window displays RC13 | `01-initial-rc13.png`. |
| First setup prepares and connects bundled components | `02-prepare-components-rc13.png`, `03-connected-components-no-model.png`. |
| Shared cloud form offers OpenAI and defaults to `gpt-6-luna` with no key entered | `04b-cloud-provider-selection.png`. The earlier `04-openai-empty-key.png` was captured before selection changed and still shows DeepSeek; both captures are preserved. |
| Setup reaches its final component review | `05-ready-components-rc13.png`; Core is displayed as `尚未就绪`, while Companion is running. |
| A later view still shows that Core row, but the completion button is visibly enabled | `07-first-setup-blocked-before-stop.png`. Despite the filename, this final capture does **not** establish a permanently blocked button. The final completion click was not attempted. |
| Read-only inspection reaches the actual service | `service-capabilities.json` and `06-live-service-inspection-first-result.png`: task count 0, active task count 0, `desktop_execution_budget_v1` present, and timeout limit 86400 seconds. |

The independent service inspection reads **health version b28 and distribution metadata b30 in the same result**. `core-service.log.gz` also records b28 at startup. `runtime-version-mismatch.json` links those observations to `frozen-service-version.py`, a verbatim copy of the frozen version declaration.

The version mismatch is proven. No explicit version-rejection exception was observed, and this record does not establish that the mismatch caused the component row or the initial pale completion button. Root directed the run to stop after the mismatch and a separate engineering failure. That engineering run is outside this package/UI evidence scope.

## No GUI model request and owned shutdown

No model was downloaded, task submitted, API key entered, or messaging account connected. Companion remained disabled, with observation and automatic inference off and no watched directories. Read-only post-stop SQLite counts are zero for Core checkpoints/journal and Companion memories/training examples/observation events. The actual live task list was empty. `native-no-model-requests.json` records this narrow scope, excluding independent engineering, grading, and b28 long-soak jobs.

The separate short root J, `/workspace/scratch/c0f3ec78c621/native-rc13-j`, contains only the prepared synthetic geometry fixture. Its launcher was **never executed**, no pet process started, and no animation probe was triggered. Prepared scripts and fixture hashes are retained without being described as execution evidence.

Terminal tab 24 performed the read-only inspection and then the verified owned shutdown. `native-rc13-i-stop.json` checks the exact executable hash and profile identity before signaling the UI. It finishes at `2026-11-16T21:39:54Z` with `STOPPED`, `owned_remaining=[]`, and launcher return code 143. `08-stopped-windows.json` and `08-owned-stop-receipt.png` show that no LocalPilot window remained. The CUA completion summary followed that observation. Terminal tab 8 and other validation jobs were untouched.

## Scope still open

This candidate did not complete the final setup click, main-page Core version check, 24-hour UI selection, or final-package animation sample. No score or timing from an older artifact is transferred to this package. System installation, physical macOS qualification, and authenticated binary upload remain outside this run.

`previous-rc12-evidence-integrity.json` verifies all 40 RC12 manifest payload entries unchanged. Old builds and failure records were preserved. Timestamps remain as emitted by their respective build and native environments; the new manifest covers this directory independently.
