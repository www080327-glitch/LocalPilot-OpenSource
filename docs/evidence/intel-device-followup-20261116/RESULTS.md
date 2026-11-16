# LocalPilot Device Acceptance Follow-up

Date: 2026-11-16 (Asia/Shanghai)

Source: `main` at `60ecb84e57471567ecc8234891a14a8528878ee1` (PR #12)

Machine: Apple M1 Max, arm64, macOS 27.0.1, 64 GiB; CPython 3.14.6 arm64; Node 24.20.0; Rust 1.96.0; Command Line Tools SDK 27.2. This is an Apple Silicon run. No Rosetta result is counted as Intel evidence.

## PASS

| Check | Result | Scope |
| --- | --- | --- |
| `npm test` | **72 PASS / 13 files** | Current source; [log](vitest.log) |
| `npm run build` | **PASS** | TypeScript and Vite production build; [log](vite-build.log) |
| `npm run test:ui` | **38 PASS** | Real Chromium 1248; browser UI with a synthetic native bridge. This does not exercise the native APP, TCC, model inference, or Intel hardware; [log](playwright.log) |
| arm64 Rust/Tauri tests | **42 PASS, 3 ignored, 0 failed** | Three ignored cases require explicit live GitHub/Core conditions; [log](cargo-test-arm64.log) |
| Swift meeting helper | **PASS** | Current `MeetingTranscriber.swift` typechecked and compiled to an arm64 macOS 11 target. The binary was not run. The compiler reports `installTap` deprecated on macOS 27; [typecheck log](swift-typecheck.log) |
| Bundled runtime resources | **PASS** | 35 dependency wheels, exact match to the checked-in arm64 hashes; four current component wheels; 257 component Python files matched to source; 2,154 checked-hash bytecode files; Node 22.23.4 archive matched its pinned SHA-256. [checker output](bundled-backends-check-arm64.json) |
| Complete arm64 Test APP build | **PASS** | Built with `src-tauri/tauri.test.conf.json`, one Cargo worker. Bundle ID `io.localpilot.desktop.test`, name `LocalPilot Test`, Desktop `5.0.1-rc.7`; 290.25 MiB. Signature verification passed; ad-hoc signature, no notarization. All 131 Mach-O files in the app include arm64. Build output stayed local; no Release was published. |
| Candidate archives | **PASS** | App ZIP SHA-256 `ceae6208138b2ab51b2460cfdc5bcd60c03062480f27acbd0d1d71bf7cd938c4`; DMG SHA-256 `5f46592e41393d9182a5366006c69a66119b7b9a47e3b6a3bf63620ab4d4a3da`; `hdiutil verify` passed. Main executable SHA-256 `337d07b4c5a6601d6f6b8145694dae0c85198d2753a6ff38f66ca0c9d6bed4b2`. |
| Test install plan | **PASS (plan only)** | The reviewed plan binds the candidate and old app digests; `executed:false`. It was not installed. The current Test APP was running, so replacement would require stopping it and its owned services. [redacted plan](arm64-install-plan.json) |

## NOT_RUN / BLOCKED

| Acceptance item | Result | Reason |
| --- | --- | --- |
| Physical Intel Mac, x86_64 CPython 3.14.6, Intel `watchdog` and `cryptography` source builds | **NOT_RUN** | This machine is arm64. Its universal2 watchdog build and arm64 cryptography wheel do not establish Intel builds. |
| Intel Test APP, actual Intel startup, install/upgrade, injected rollback cases, reverse-install rollback | **NOT_RUN** | No physical Intel Mac was available. The arm64 candidate was not installed over the running older Test APP. |
| Current-source Test APP onboarding, actual CPU GGUF inference, Core/Companion tasks, cancellation and recovery | **NOT_RUN** | The current candidate was built but not launched or installed. The active older Test APP and its Core/Companion processes were left untouched. No model request was sent. |
| System audio, microphone/both meeting capture and TCC responsibility | **NOT_RUN** | No current-source candidate was run under the responsible macOS process. Earlier TCC failure/zero-audio history remains in its prior evidence and was not overwritten. |
| Real sleep/wake, actual multi-model child Agent usage, LoRA effect, cold/hot/restart KV measurements | **NOT_RUN** | These require a current-source app session, actual identified model/provider metrics, and (for LoRA) manually confirmed training examples plus a separate evaluation set. No synthetic response was counted. |
| New public Docker study | **BLOCKED** | Docker client 29.8.1 is present, but `docker info` cannot connect to `/var/run/docker.sock`; no study was created or run. See [preflight](docker-preflight.log). |

The old 534-task queue was not opened or modified. Its recorded result remains 1 PASS, 3 FAIL, 13 ERROR, and 517 without final results. No ranking or non-inferiority claim is made.

## Preserved first-run failures

- The first complete Playwright run was **37 PASS / 1 FAIL**. The new UI fixture returned the same mutable array reference from the synthetic bridge, unlike a serialized native response, so React did not rerender the collaboration choices. Returning `configuredModels.slice()` fixed the fixture; the full suite then passed 38/38. The initial result is preserved in [INITIAL_PLAYWRIGHT_FAILURE.md](INITIAL_PLAYWRIGHT_FAILURE.md).
- The first arm64 Rust test invocation stopped because generated Tauri icons were absent. Running the repository's `tauri icon public/icon.svg` generation entry point and rerunning gave 42 PASS / 3 ignored.
- The first bundled-backend check ran before resources existed. The normal resource-generation workflow then produced the complete arm64 bundle and the final check passed.
- Direct PyPI metadata/download access returned TLS EOF. Artifacts fetched from the configured package mirror were accepted only after the generated lock matched all 35 hashes in the checked-in arm64 lock; the pinned watchdog source build reproduced its checked-in universal2 hash. The resulting arm64 lock and resource manifest are local build material, not a new published lock.

## Build identity and local artifact hashes

- Candidate app canonical tree SHA-256: `69201ed255ca0f045176e7de47117df81315667160eed00b263da1c072529571`.
- Candidate Swift helper SHA-256: `e0ee26299305465f7bc6cb32998ef6554ff3033378288fdf05f447efb33306ae` (arm64 Mach-O; compile only).
- Bundled resource manifest SHA-256: `aeb7a78451a47c2454083a0506dec5800b03f764ad95e3104d34b4d39c98c447`.
- arm64 dependency lock SHA-256: `2f2bc4a2531f0754d3b375061e341166edcb62d5cc55678579ed720b591aa3a9`.
- The unchanged daily APP tree digest at the pre/post check was recorded as `4f746e6dc9fd8b0add14176e2459d6b8df4e8a20823a14fb7f5b938e315a3d93`; the previous Test APP digest remained `3577f8a67e27cc9ff1f631220c9af6694ed2f51e5647b4d39aeb822979e08550`.

No model, external service, daily APP, prior Test APP, user data, or historical queue was deleted, moved, or cleaned to make room. No Release, contest submission, or landing form was published.
