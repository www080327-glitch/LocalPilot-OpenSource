# LocalPilot RC20 evidence

Snapshot phase is **FINAL**. Release status remains **NOT_RELEASE_READY**.

`EVIDENCE_MANIFEST.json` records the explicit source selection, archive members, byte counts and SHA-256 hashes. `SHA256SUMS` covers every delivered file except itself. Each gzip archive preserves selected input files byte for byte. `SANITIZATION.json` records screening and transformations.

`PUBLIC_SOURCE_MAP.json` identifies the frozen product tree. The standalone test and fixture maps identify subsequent test-only changes. Individual receipts specify the tested commit, file hashes, command and execution scope. Runtime evidence includes the 96-read fixture, RC18 database round trip and crash compatibility receipts. Install evidence covers recorded Suite tests and package checks when available. The independent review states its source and scope.

`LOG_SUMMARY.json` records framework footers individually. Interrupted logs remain available with their run status. A footer with results only applies to that run, and a missing footer supplies no completed result. Earlier RC19-only UI and native evidence remains in its own published snapshot.

In this directory, run `sha256sum --check SHA256SUMS` before extracting. Unpack the archives to one directory and rerun `python stage_rc20_evidence.py --output <new-snapshot-directory> --phase final` from there to regenerate the snapshot. The script requires a fresh destination.
