# RC19 public evidence snapshot

Snapshot phase: **FINAL**. This archive is evidence, not a release-readiness assertion.

`EVIDENCE_MANIFEST.json` enumerates every raw member and archive with byte count and SHA256. `SHA256SUMS` covers every delivered file except itself. Original text bytes are preserved; `SANITIZATION.json` records screening and any transformations. No transformation was applied in this snapshot.

The five deterministic gzip archives group provenance, runtime, desktop UI, native/install and independent reviews. Archive member names are relative to the validation directory. `PUBLIC_SOURCE_MAP.json` identifies the tested local commits and matching public source trees. Earlier failures and results for older source snapshots remain present and must not be described as final-source passes.

`LOG_SUMMARY.json` extracts recorded test footers without summing different runs. `UI_RESULTS.json` distinguishes unit tests/build/collection/typecheck from blocked page execution. `NATIVE_PACKAGE_RESULTS.json` records package tests; `NATIVE_GUI_RESULTS.json` separately records the actual window launch. A log with no parsed footer, including a successful but empty typecheck log, needs its producer's result receipt. Browser launch failure does not count as a page assertion. Source review does not establish physical animation, dragging, device acceptance or novice usability.

The staging program is in `provenance.tar.gz` as `stage_rc19_evidence.py`. Given the original validation directory, rerun `python stage_rc19_evidence.py --root <validation-directory> --output <new-snapshot-directory> --phase final`. It deliberately refuses to overwrite a snapshot. Use `sha256sum --check SHA256SUMS` in this directory before extracting.

Excluded: source clone contents; environments and toolchains; runtime databases and generated bulk fixtures; downloaded packages/models; built binaries; personal artwork and its metadata; unlisted helper scripts. Root-owned RESULTS, requirements and Work handoff documents are maintained separately.
