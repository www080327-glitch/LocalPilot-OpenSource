# Candidate version gate: stale service VERSION

## Result

The existing candidate checker incorrectly reported a consistent Core b30 / Desktop RC13 candidate while `localpilot_service.VERSION` still contained `5.0.0b28`. The real primary-repository command returned exit 0 and `consistent: true` before this correction. The fixed checker rejects the same b30/b28 input bytes with exit 1. After the release owner synchronized Core b31 / Desktop RC14, the actual primary-repository checker passed with the service constant and package metadata both at b31.

This change is limited to the existing checker and two regression tests. No runtime version source, metadata lookup strategy, build workflow or UI compatibility rule was introduced. Version files were updated separately by the release owner.

## Cause and minimal correction

`scripts/check-candidate-versions.py` already compared `pyproject.toml`, module release metadata, Desktop configuration and README versions, but did not read the service's existing `VERSION` constant. The bundled-backend checks call Suite `--version`; Suite obtains Core's value from installed distribution metadata. They therefore did not expose the stale service constant, even though source/wheel byte identity checks passed.

The correction changes the import line to include `runpy` and adds one assertion immediately after reading the canonical Core project version:

```python
assert runpy.run_path(str(root/'localpilot_service/__init__.py'))['VERSION']==core,'localpilot_service.VERSION differs from pyproject.toml'
```

The explicit source filepath prevents resolution to an older installed module. Both existing Linux and macOS build entrypoints already invoke this checker; no second check or version table was added. The exact two-file change is preserved in [CHANGE.patch](CHANGE.patch), with source identities in [SOURCE_IDENTITY.json](SOURCE_IDENTITY.json).

## Observed controls

| Check | Actual result | Evidence |
| --- | --- | --- |
| Original checker, actual primary source before the owner bump | **Incorrect PASS**, exit 0; metadata b30 / source constant b28 | [BEFORE.json](BEFORE.json), [stdout](BEFORE.stdout.log), [stderr](BEFORE.stderr.log) |
| Fixed checker, exact frozen `1dca93c5` b30 inputs copied to scratch | **Expected rejection**, exit 1 with the service-version diagnostic; only the checker was replaced | [AFTER_MISMATCH.json](AFTER_MISMATCH.json), [stderr](AFTER_MISMATCH.stderr.log) |
| Two actual checker subprocess tests | **2/2 PASS**, no skip, 0.077 seconds | [TESTS_AFTER.log](TESTS_AFTER.log) |
| Fixed checker, actual primary source after owner b31 / RC14 bump | **PASS**, exit 0; metadata and service constant both b31 | [AFTER_CURRENT.json](AFTER_CURRENT.json), [stdout](AFTER_CURRENT.stdout.log) |

The new tests live in the existing `tests/test_release_observability.py`. Each copies the real checker and its existing candidate inputs into a temporary directory. The positive case supplies the matching source constant; the negative case changes only that constant to a stale value. Both invoke the actual checker through `subprocess`, without mocking or duplicating its comparison logic. The before-state mismatch was captured before the owner changed version files; the later rejection used an isolated copy, preserving the frozen b30 checkout.

## UI and validation boundaries

The [RC13 native record](../../../../../desktop/docs/evidence/audit-20261117-desktop/final-package-rc13/RESULTS.md) independently records service health version b28 versus distribution version b30. It also preserves the final screenshot in which the completion button had become enabled. No explicit version-rejection error was observed and the operator did not attempt that final button. Desktop's existing `compatible()` checks readiness, persistence and API capabilities, rather than equality of these prerelease version strings. The observed version defect is therefore not evidence that version comparison permanently blocked first setup.

These are source/build-gate controls, not a new model run, a complete application regression or RC14 native qualification. No API/model request was made. Old package, engineering, benchmark and native receipts were not changed. A successful gate after the owner bump does not retroactively correct the older packages' reported service version.

[ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) records the explicit file allowlist, original and archived byte counts and SHA256 values. Logs are byte-preserving, including empty streams; no credential, raw reference label, private Core configuration or database is included.
