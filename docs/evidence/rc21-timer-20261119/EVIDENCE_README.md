# LocalPilot RC21 evidence

Snapshot phase is **FINAL**. Release status remains **NOT_RELEASE_READY**.

`EVIDENCE_MANIFEST.json` records the explicit source selection, archive members, byte counts and SHA-256 hashes. `SHA256SUMS` covers every delivered file except itself. Each gzip archive preserves selected input files byte for byte. `SANITIZATION.json` records screening and transformations.

`PUBLIC_SOURCE_MAP.json` identifies the frozen product tree. Individual receipts specify which source revision, command and execution scope apply. The focused timer regression and SQLite probe include runs before and after the fix. The independent review identifies the source it inspected. `FINAL_CORE_RESULTS.json` reconciles the raw unittest runner count with the recorded test methods and class setup error.

`LOG_SUMMARY.json` records framework footers individually. A footer only applies to the corresponding run. RC20 historical regressions, unresolved full-run errors, prior installation checks and the original late-timer reproduction remain in that stage's published evidence.

In this directory, run `sha256sum --check SHA256SUMS` before extracting. Unpack the archives to one directory and rerun `python stage_rc20_evidence.py --output <new-snapshot-directory> --phase final` from there to regenerate the snapshot. The script requires a fresh destination.
