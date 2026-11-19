# Read-only Responses prefix review evidence

This directory records work already performed by the `prefix_followup` agent.
Saving these files did not rerun the probe or tests and did not call a model API.

- Reviewed repository commit: `89c46468995c46f90a73d9c41ea0044d564cd175`.
- Production source snapshot: `c5439659a579b2ee9e74fd53e6d3232fe12fb855`.
- `probe.py` is the exact Python heredoc body previously executed from the repository root. It invokes the real V5 context-transfer and Responses payload/response implementation with synthetic data. Its API-key string is a synthetic fixture, not a credential.
- `probe-tool-output.transcript.txt` transcribes the probe's single printed output line from the execution tool's returned `output` field (chunk `815d26`, exit code 0). It is a tool-output transcript saved after execution, **not a separately captured original process log**. The same tool call first ran `git diff --name-only`; those unrelated changed-document names are not part of this probe transcript.
- `test-command.txt` contains the exact unittest command executed before the root agent requested exclusive use of service/process tests.
- The unittest command completed with `Ran 32 tests in 6.326s`, `OK`, exit code 0. Start output was returned in chunk `56a2a8` (session `36020`); final output was returned by `write_stdin` in chunk `a60deb`.
- **No original unittest log was saved to disk. No replacement or reconstructed unittest log is included.** These counts are transcribed metadata from those tool results, not new test execution. The root agent's full Core run overlaps these modules; do not add the counts together.

The probe establishes a request-prefix mismatch while encrypted reasoning and the paired tool call/result remain in the next payload. It does not establish that OpenAI actually removed reasoning on a paid run, nor measure cost, latency, or quality effects. Existing archived task records omit provider `input_transformations`, so those effects remain unmeasured.

No production files, versions, tests, or historical evidence were modified by this review. All files in this directory are newly saved review material.
