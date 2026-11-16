# Initial Playwright Failure (Preserved)

- Command: `npm run test:ui`
- Source: `60ecb84e57471567ecc8234891a14a8528878ee1` before the test fixture correction.
- Result: 37 PASS, 1 FAIL of 38.
- Failing case: `tests/ui/intel-setup.spec.ts` — “saving a local route refreshes the cooperation model choices”.
- Failure: expected option `local-cpu · fixture-gguf · local-openai` was absent.
- Cause: the synthetic bridge returned the same mutable `configuredModels` array on every JSON response. The fixture mutated that array in place, so React saw the same array reference and correctly skipped a rerender. Production returns a deserialized response snapshot.
- Correction: return `configuredModels.slice()` from the fixture catalog. The same test then passed, followed by the full 38-test suite.

This first failure was retained as a distinct run; it is not overwritten by the later passing run.
