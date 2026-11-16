# Desktop audit evidence

Audit decisions and unique category counts: [AUDIT_20261117_DESKTOP.md](../../../../docs/development/AUDIT_20261117_DESKTOP.md).

## Final source checks

- Rust default suite: [rust-tests.log](rust-tests.log), **56 passed / 3 intentionally ignored / 0 failed**.
- Pet-specific production implementation tests: **14 passed**, included in the default suite. They exercise actual atlas decode, animation advance, typed render, alpha geometry and bubble placement.
- TypeScript: `tsc --noEmit` exited 0 after the final UI changes.
- Final UI transport-fixture run: [browser-run-7/output.log](browser-run-7/output.log), [machine result](browser-run-7/browser-tests.json), **7 passed in 10.6 seconds**. The application controls and handlers are the real implementation; native/provider transport is substituted. No model provider is called.
- Actual native WebKit: [native/RESULTS.md](native/RESULTS.md), four animated phase averages **26.79–29.46 fps**, plus explicit same-side placement, reduced app animation, typing focus, reminder and service recovery. This is the mixed candidate with the exact source/ELF identity documented there.

## Preserved first attempts

| Directory | Observed result | Resolution / interpretation |
|---|---|---|
| `browser-run-1` | Seven Chromium launch errors, socket `EPERM`; application was never reached | Run the same repository workflow in the actual desktop terminal environment |
| `browser-run-2` | Exit 127, Node was absent from terminal PATH | Use the existing installed runtime's Node bin directory |
| `browser-run-3` | Three assertions failed against old page content; four skipped when stopped, exit 130 | Default `reuseExistingServer` reused an earlier server. Preserve its evidence, leave that unrelated server running, use a separate port |
| `browser-run-4` | Port availability check reported busy although native listener inventory did not show it | Set loopback `NO_PROXY` for the private test run; no host proxy or network settings changed |
| `browser-run-5` | Six passed, one cloud-form test locator timed out | Nested implicit label included option text; select by actual accessible combobox role/name |
| `browser-run-6` | Seven passed | First complete current-application run |
| `browser-run-7` | Seven passed | Final source plus accurate `already_configured` feedback branch |

The run-specific Playwright configs use the repository's existing configuration and test runner, with only private server port / loopback proxy environment changes. JSON reports originally emitted below the config directory are retained and copied to each run's top level for convenient reading. Logs remain exactly as generated.

The mixed candidate's first package metadata failure and successful retry are documented in `native/RESULTS.md`. Its 38 evidence files are frozen by `native/MANIFEST.json`. A final all-source package must use a separate directory and receipt.
