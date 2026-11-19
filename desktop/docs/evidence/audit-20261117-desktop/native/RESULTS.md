# Native Desktop audit candidate D

**PASS for the explicitly measured UI behaviours.** This is a current Desktop / previous verified backend mixed candidate, not the final all-source release. The DEB was extracted and run; it was not installed system-wide.

## Identity

| Field | Value |
|---|---|
| Application identity | `io.localpilot.desktop.test`, Desktop 5.0.1-rc.9 |
| Backend source | `59fad12de6f57006fc7510805af2dfd1718c16ea` |
| Bundled modules | Core 5.0.0b26 / Suite 0.2.0b31 / Companion 0.5.7b7 / Channels 0.1.0a3 |
| Desktop source | 75 individual SHA-256 values in `source-identity.json` |
| DEB SHA-256 | `675d45c81ddd41c5bf7aee4b7595d3aac3e44b303c6e6c19e4d8cdeee89ad45f` |
| DEB bytes | 114619022 |
| Extracted ELF SHA-256 | `c79066b761da62eb9944ab7f0c42f097035b0a669153ecc3e6a7da41703a24d8` |
| Private root | `/workspace/scratch/c0f3ec78c621/validation/native-audit-20261117/profile-d` |
| Helper | Existing reviewed read-only WebKit overlay copied with only `--companion-pet` appended |
| Backend | `disabled`; no task/model submission |
| End state | `STOPPED`, no owned process remaining |

The helper preserves WebKit sandboxing, a standard private `/dev`, and the existing X11 auth file read-only. It makes only this marked private root writable. Personal pet files were absent, so `make-fixture.py` produced simple numbered transparent geometry solely within profile D. No product atlas or user art was edited. The fixture intentionally has a DeepSeek prefix and no optional comic image, exercising the real fallback path.

## Visible results

| Check | Evidence |
|---|---|
| Missing optional comic still renders bottom character | `01-ready.jpg` |
| Real body click retracts, relocates and peeks | `02-relocating.jpg`, `03-after-relocation.jpg`, `animation-click-1.json` |
| Explicit opening accepts typing without another input click | `05-chat-ready.jpg`, `06-focused-unsent-draft.jpg`; draft was cleared and never submitted |
| Top-left → left-edge explicit same-side selection | `07-settings.jpg`, `08-same-side-left.jpg`, `08-same-side-window.json`, `animation-same-side-2.json` |
| Animation preference off takes effect | `09-motion-disabled.jpg`, `settings-motion-disabled.json`, `10-static-relocation.jpg`, `animation-disabled-3.json` |
| One-click 10-minute reminder | `11-quick-reminder.jpg`, `native-no-model-requests.json` (created/due timestamps) |
| Stop independent service, recover from chat button | `12-service-disconnected.jpg`, `13-service-reconnected.jpg` |
| Only owned UI and descendants stopped | `native-audit-d-stop.json`, `14-stopped-windows.json`, `14-stopped.jpg` |

`04-chat-open.jpg` is an immediate pre-paint capture; `05-chat-ready.jpg` shows the completed bubble. Immediate screenshots are kept as captured, not relabeled as completed states.

## Frame measurements

The one-shot diagnostic is accepted only by the existing isolated TestProfile. It samples 6 seconds of real WebKit rAF and laid-out sprite geometry, opacity, transform and background crop. Normal operation never starts the sampler.

| Run | Phase | Observed layout-change fps | Qualification |
|---|---|---:|---|
| Body click 1 | retract | 29.10 | ≥24 phase average |
| Body click 1 | peek | 29.46 | ≥24 phase average |
| Same-side button 2 | retract | 26.79 | ≥24 phase average |
| Same-side button 2 | peek | 29.25 | ≥24 phase average |
| Animation off | all 6 seconds | no animated phase | direct reposition observed |

See `animation-summary.json` for separate rAF opportunity rates and exact values. This measures the actual WebKit presentation state, not physical display photons, and does not promise constant inter-frame spacing. Window relocation occurs once after retraction; the continuous sprite transformation is inside the small window. There are eight source atlas frames per direction, not 24 unique drawings. The measured host DPR is 1; 2× geometry was tested separately in the real Rust helper, not on a claimed Retina host.

## Follow-up boundaries

The first native run revealed an initially oversized hidden composer and dark-on-dark hover inherited from the main app. Their screenshots remain here. Source fixes add expansion/focus and connection changes to measurement triggers and keep the main hover rule outside pet pages. Accurate existing-cloud-configuration feedback and provider-neutral Swift text were also finalized afterward. The final all-source candidate must cover those last UI bytes; this candidate is not claimed to contain them.

The build archive initially lacked `.git`, so packaging completed binary/resource checks but could not write commit metadata. `build.log` preserves the failure. A local stage identity at the actual backend commit was created and `package-retry.log` / `mixed-candidate-package-results.json` record the successful retry without changing the compiled ELF.

Host clock strings are preserved exactly as reported by their environments. The audit label is 2026-11-17; native process UTC receipts and build-host logs can have different clock values. No fabricated normalized timestamps replace those records.
