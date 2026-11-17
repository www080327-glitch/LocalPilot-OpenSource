# Runtime audit — 2026-11-17 work batch

Baseline: `b420b97f18e452dc983c49e81cf7cfb87e7e82bb`. This audit changes the existing runtime, tool gateway, plugin adapter, and public service controls. It does not add another agent engine. Previous model failures and frozen evidence are unchanged.

## Scope and accounting

The runtime contribution contains **16 independent items: 6 bugs, 3 maintainability changes, 3 user-operation improvements, and 4 removals of unnecessary defensive work**. Each item belongs to one category only. The deadline, execution-budget, and long-Shell changes are counted together as one user-operation improvement. Supporting tests, compatibility handling, schema documentation, and capability negotiation are not counted as separate items.

The reviewed paths include `agent/`, the runtime-facing parts of `localpilot_service/`, `localpilot_plugins/`, and their interactions with `computer/`. The OpenAI Responses adapter, provider credentials, Desktop presentation, Suite forwarding, and actual API evaluation have separate owners. `localpilot_api/service.py` was explicitly added to this scope for task deadlines and truthful task snapshots.

## Bugs

| ID | Concrete failure path | Correction | Verification | Remaining boundary |
| --- | --- | --- | --- | --- |
| R-B01 | `SkillRegistry.load()` defaulted to `5.0.0b16`. A reviewed bundle requiring the installed `5.0.0b26` was rejected as incompatible. | Resolve the default from `localpilot_service.VERSION`; retain explicit version overrides. Normalize the version and available tools once at entry. | Real bundle install, digest review, enable, and load in `test_skill_compatibility_uses_installed_core_version`. The baseline loader was also executed against a real bundle and reproduced the incompatibility error. | This verifies compatibility selection, not the quality of a Skill's instructions. Disabled/tampered bundle checks remain. |
| R-B02 | Model retry backoff used `time.sleep()`. Cancellation during a configured one-second backoff still waited that whole second and charged another attempt before observing the stop event. Longer configured backoffs delayed cancellation further. | Wait on the existing cancellation event; check cancellation before retry accounting and request dispatch. | A scripted transient model failure triggers cancellation at `ModelRetry`; the real session returns cancelled within 0.5 seconds, sends one request, and records one attempt. | The model transport must still implement cancellation of an already running request. This change covers backoff, not a remote provider's compute lifecycle. |
| R-B03 | `_child_registry()` silently constructed a Standard tool profile for a Minimal parent. Delegation expanded the child's schema without the parent's selected profile. | Inherit the parent registry profile and tool profile for new children. Persist child tool-contract revision 2. Restore revision 1/no-contract children with their historical Standard profile. | Real parent/child session execution, current snapshot/restore equality, and a revision-1 compatibility fixture in `test_runtime_audit`. Existing selected-Skill child restore tests also pass. | Child construction by an explicitly configured host factory keeps that factory's contract. The change does not introduce recursive delegation. |
| R-B04 | `desktop_sessions.apply_options()` validated `context_length`, scope revision, and thinking declarations after modifying permissions, tools, or prompts. Invalid options could leave a partially modified runtime. | Validate the complete option shape and scalar values before mutation; resolve thinking targets before applying settings. | Invalid negotiated context leaves permission mode, prompt, messages, and registered tools unchanged. | A real checkpoint/write failure is handled by the existing switch transaction; R-M01 makes that rollback inspectable. |
| R-B05 | Switching an existing revision-3 Full session to Ask, Safe, or Uncertain kept revision 3 but passed a mode rejected by `scope_permissions.configure()`. The switch raised `Unknown file permission mode`. | Accept all seven supported Desktop modes in file-scope configuration, retaining their gateway decisions. Only the existing Full/read modes receive automatic outside-scope handling. | Exercise Full → Ask → Safe → Uncertain → Workspace → Isolated → Request on a real registry. Ask still requires approval for a read. Desktop permission and scope suites pass. | This does not grant OS access or automatically authorize outside-scope actions in Ask/Safe/Uncertain. |
| R-B06 | `tool_protocol.validate_arguments()` returned early for extension names. Shell is an extension backed by `partial(shell, mode=...)`; an unadvertised model argument `mode='full'` could override the host's isolated mode. | Apply the existing advertised-schema validator to extensions too. Owning MCP/native validators continue to handle their additional protocol rules. Reject host-only Shell arguments before intent/dispatch. | With the baseline validator, an isolated registry returned `sandbox_mode='full'` and created a real test file. The fixed gateway rejects `mode`, `private_roots`, and `max_timeout`; no file is created. Native Computer and host-tool regressions pass. | This is argument isolation at the tool boundary. Full Shell intentionally retains the current OS user's rights when the host has selected it. |

### Baseline receipts for R-B01 and R-B06

The baseline module sources were read from `git show b420b97:<path>` and executed in a temporary module against real temporary files. Only the old validator/loader was substituted; this was a focused reproduction, not a claim that the entire old checkout was rerun.

```json
{"baseline_validator":"b420b97:agent/tool_protocol.py","permission_mode":"isolated","injected_host_parameter":"mode=full","returned_status":"ok","actual_sandbox_mode":"full","file_created":true}
{"baseline_loader":"b420b97:localpilot_plugins/skills.py","running_core":"5.0.0b26","requires_localpilot":"==5.0.0b26","rejected":"Skill is incompatible with this LocalPilot version"}
```

## Maintainability

| ID | Existing maintenance problem | Change | Verification | Remaining boundary |
| --- | --- | --- | --- | --- |
| R-M01 | Profile switching saved/restored long positional tuples of runtime, registry, gateway, backend, and task state. Adding a field required matching two distant tuple orders, and backend context/root attributes were difficult to inspect. | `_profile_state()` records named attributes grouped by their actual owner. Rollback iterates these names. The switch's normal flow remains authorization → update → checkpoint. | A controlled checkpoint failure exercises the real permission/profile/budget mutation and verifies the complete configuration, messages, and session options are restored. Existing HTTP/SQLite profile and history tests pass. | The test injects a storage exception; it does not simulate every possible filesystem failure. Durable-store fencing remains the persistence layer's responsibility. |
| R-M02 | Skill dependency traversal loaded a dependency record once to check its version and again inside `visit()`. Shared dependencies also incurred redundant reads. | `visit()` returns its already reviewed, loaded node. Version constraints use that returned node; dependency ordering, cycle detection, and digest checks stay in one traversal. | Existing real Skill install/load, dependency version, cycle, tamper, selected-catalog, and child-restore tests pass. | Installed records and review receipts remain independently checked; this is not a cache across separate load operations. |
| R-M03 | CLI `follow()` interleaved SSE reconnect/cursor logic with nested human/JSON event rendering. Output changes required editing the transport loop. | Move the existing rendering decisions into `_print_follow_event()`. The main loop retains event ordering, durable cursors, resync, and reconnect behavior. | Real HTTP/SSE tests verify JSON reconnect without replay and human streaming without printing the final answer twice. | The helper is terminal presentation only; it does not infer task completion from display text. |

## User-operation improvements

| ID | Previous interruption or manual work | Change | Verification | Remaining boundary |
| --- | --- | --- | --- | --- |
| R-U01 | Task submission and CLI heartbeat were capped at one hour, Desktop sessions kept tiny default step/tool budgets, and Shell had a one-hour ceiling. Extending only one layer still terminated a long task early. | Add an explicitly selected `execution_budget='extended'`, a common 24-hour maximum task deadline, truthful persisted `timeout_seconds`/`deadline` snapshots, and a 24-hour Shell ceiling only for Full + Extended. Expose `desktop_execution_budget_v1`; native/Suite owners connect the existing controls to 4-hour/24-hour choices. | Real HTTP/SQLite 24-hour request admission, over-limit rejection, idle budget switching, restoration after restart, task-history preservation, CLI submission, child Shell ceiling inheritance, and an actual 65-second Shell command. | A 24-hour admitted deadline is not proof of 24 hours of successful autonomous work. The separate two-hour soak and real API evaluation belong to the root audit. Explicit cancellation, finite budgets, UNKNOWN receipts, and OS permissions remain active. |
| R-U02 | Every MCP call asked again even after exact source/catalog review, enablement, and Full permission. | The existing PluginTool host-approval callback requires per-call approval outside Full. Full reuses the enabled review. Permission-mode changes take effect immediately. | Real MCP stdio process: Full calls succeed without another approval; switching to Approve Mutations asks; revocation blocks dispatch. Existing local-only, credential redaction, cancellation, and UNKNOWN/no-replay tests pass. | Source identity, catalog/generation, egress, host argument scope, credential isolation, and external-effect uncertainty remain enforced. Server text does not become host policy. |
| R-U03 | A non-Hybrid Full session already configured as Cloud Only still paused to authorize a cloud child on its configured backend. | Reuse that existing Cloud Only authorization when the hard data policy permits cloud. Local-first → cloud still requires its separate authorization; local-only still blocks cloud. | Real parent/child runtime with scripted model replies completes three cloud requests without another approval. Existing local-first and local-only denial tests pass. | Full alone does not create cloud authority. Hybrid sessions still require their declared `CLOUD_ALLOWED` egress policy. |

### Explicit long-task contract

Standard sessions retain their configured route budgets. Selecting Full alone does not select Extended.

| Setting | Standard | Extended |
| --- | --- | --- |
| API task deadline default | 120 seconds | Still 120 unless the client explicitly sends a longer deadline |
| API/CLI allowed task deadline | Up to 86,400 seconds | Up to 86,400 seconds |
| Desktop default deadline | Existing 600 seconds | Native owner provides explicit 4-hour/24-hour choices |
| Parent model attempts | Existing route value, normally 8 | 2,048 |
| Tool proposals | Existing route value, normally 12 | 4,096 |
| Cumulative admission units | Existing route value, normally 262,144 | 64 MiB |
| Parent output limit | Existing route value, normally 2,048 tokens | 4,096 tokens |
| Child count per turn | Existing route value, normally 2 | 64 |
| Child request/tool ceilings | Existing route values | 64 requests / 128 tool proposals |
| Child admission/output ceilings | Existing route values | 2 MiB / 2,048 output tokens |
| Model switches per turn | Existing route value | 8 |
| Shell timeout default | 120 seconds | Still 120 seconds unless the tool requests more |
| Shell timeout maximum | 3,600 seconds | 86,400 only with Full; other modes retain 3,600 |

Admission units are the existing conservative UTF-8 accounting units, not measured provider token usage or billing. Child budgets remain bounded by the parent's remaining budget. No timer, counter, receipt, or permission is reset to extend an in-flight task. Budget/profile changes require an idle session and expected-current-value fields.

The observed real Shell command was `sleep 65; printf long-shell-complete`, with requested timeout 7,200 seconds and host ceiling 86,400 seconds. It returned after **65.005 seconds** with `status='ok'`, exit code `0`, matching stdout, `process_completed=true`, and `verification='NOT_RUN'`. This proves the command was not cut off by the legacy 60-second execution limit; it does not claim semantic task verification.

## Removed unnecessary defensive work

| ID | Unnecessary restriction or repeated work | Change | Verification | Retained constraint |
| --- | --- | --- | --- | --- |
| R-D01 | `safe_files.transfer()` rejected any source with more than one hard link, even though copy reads the source and move renames one directory entry. | Remove the source link-count restriction. | Real hard-linked source is copied to a different inode and moved while its alias remains intact with the same bytes. | Expected content digest, descriptor-relative access, no overwrite, and before/after identity/content checks remain. Content-modifying patch rules are unchanged. |
| R-D02 | `file_info` used the hashing inspection path to return only type/size. Metadata lookup read the full file and rejected files above 64 MiB. | Allow metadata-only descriptor inspection; `file_info` does not request a content hash. | A real 65 MiB sparse file returns correct metadata; explicit content-hash inspection still rejects above its 64 MiB bound. | Metadata is not content coverage or verification. Credential and workspace path checks remain. |
| R-D03 | The gateway reconstructed an already validated, frozen `RiskAssessment` solely to defend against a host subclass bypassing its constructor. A second Full branch was unreachable after the caller's Full decision. | Remove the duplicate reconstruction and unreachable branch. | Existing permission thresholds, invalid/failing judge, capability, approval, and read-only tests pass. | The owning `RiskAssessment` constructor and the gateway's type check still validate the external judge result. |
| R-D04 | A plugin proposal was validated in AgentSession, again in ToolRegistry, and again in PluginManager, repeatedly launching schema validation subprocesses for the same arguments. Prompt-specific validation was delayed until after dispatch intent. | Keep validation at the entry before intent; use a private prevalidated registry dispatch internally; pass the validated plugin arguments onward. Move prompt argument validation to PluginTool's entry validator. | Real MCP invocation observes one owning argument-validation call and one receipt. Invalid prompt arguments fail before any receipt/process dispatch. Existing cancellation-during-validation and invalid-schema tests pass. | Authorization, revocation, resource versions, and cancellation can change during a call and are still checked at their relevant dispatch boundaries. Direct public `registry.call()` still validates input. |

## Validation record

Tests use the existing `unittest` workflow. Scripted replies simulate only model behavior; HTTP, SSE, SQLite, filesystem operations, child sessions, Shell processes, and MCP stdio transport run their actual implementations.

The pinned component runtime has Python 3.13.5, MCP 1.26.0, and packaging 26.0. An early attempt with the generic Python failed the pinned MCP-version check (generic environment had MCP 1.29.0); another preserved component environment lacked packaging. These were environment-selection failures, not passes or product defects. No new model or dependency download was used.

| Command / check | Result |
| --- | --- |
| `python -m unittest tests.test_runtime_audit tests.test_desktop_product tests.test_suite_cli tests.test_plugin_ecosystem -q` using pinned component Python | 80 tests, PASS, 41.226 seconds |
| `python -m unittest tests.test_pa_full_permission tests.test_runtime_audit -q` | 17 tests, PASS, 0.083 seconds |
| `python -m unittest tests.test_runtime_audit tests.test_runtime_session tests.test_persistent_runtime tests.test_core_portability tests.test_async_runtime tests.test_desktop_permission_v3 tests.test_scope_escalation tests.test_file_info_observation tests.test_host_tools -q` using pinned component Python | 187 tests, 185 passed / 2 skipped, 17.830 seconds |
| `git diff --check` | PASS |
| Real 65-second Full + Extended Shell | PASS; receipt summarized above |

The 187-test group skipped the two explicitly macOS-only Seatbelt tests (`test_full_shell_runs_and_writes_a_real_file` and `test_read_only_shell_can_read_but_os_denies_writes`). Linux scoped Shell and cancellation ran. An earlier command referenced `test_runtime_stabilization`, whose historical benchmark dependency is absent from the public tree; its module raised `SkipTest` during explicit loading. That command is **NOT_RUN**, not included in the passing counts.

These historical test groups overlap; their counts must not be added as distinct test coverage. The root owner subsequently completed [Core regression R2](../evidence/audit-20261117/root/core-regression-r2.log): 1,616 tests, 1,525 passed and 91 skipped, with no failures. Source was published at `91dd87c`; [the final Linux package report](../../desktop/docs/evidence/audit-20261117-desktop/final-package/RESULTS.md) binds the clean build and extracted-package native checks to that source. [Actual model results](../evidence/audit-20261117/root/RESULTS.md) and the [finite engineering acceptance](../evidence/audit-20261117/root/engineering-luna-r1/RESULTS.md) remain separate, source-identified evidence. These additions do not change the identities or counts of the historical groups above.

### Full-regression fixture alignment

The first Core-wide run reported 2 failures and 8 errors. The affected fixtures
still expected an intermediate cloud-child approval in Full + Cloud Only, or a
Python `TypeError` after an injected host-only argument reached the tool. The
corrected product behavior enters the child immediately and rejects the extra
argument at schema validation.

The four affected test modules now install child fault/takeover fixtures before
task creation, wait for the actual in-flight action before cancellation, and
assert the specific `ToolArgumentsError` for `allow_frontmost`. Child usage,
interrupted-output accounting, UNKNOWN obligations, receipt uniqueness, immutable
past snapshots, no repeated effect, and zero native dispatch on invalid arguments
retain their original assertions. No production code changed for this alignment,
and these are not additional audit items.

`python -m unittest tests.test_finalization_recovery tests.test_v2_p0_reliability
tests.test_computer_runtime tests.test_local_native_backend -v` completed with
**169 tests passed in 2.287 seconds**. The first full-regression log remains
unchanged; the completed Core R2 rerun is linked above.

## Limitations: reasoning state and request prefixes

OpenAI Responses retains encrypted reasoning items with model, endpoint, message,
and egress-scope binding. This does not establish uninterrupted reasoning reuse.
The V5 request view appends a temporary current host-state message; canonical
history does not retain that message before the next model response. Replaying
the response therefore changes the prefix that originally produced it.

A synthetic run through the real `context_v5.transfer()` and Responses payload
functions observed three input items in the first request, but only two items
before its replayed reasoning on the next request. The previous host-state item
was absent even though encrypted reasoning remained in the payload. No model API
was called for this check.

[OpenAI's prefix guidance](https://developers.openai.com/api/docs/guides/preserved-reasoning)
states that prefix changes cause subsequent reasoning items to be dropped. This
can require repeated reasoning; the size of any cost, latency, or quality effect
has not been measured here. Addressing it requires a separate context-history
change. This is an **unresolved limitation**, not a fixed defect or an additional
completed audit item; the running benchmark snapshot is unchanged.

The [b31 continuation review](../evidence/audit-20261117/root/continuation-b31/RESULTS.md#请求前缀限制复核) reproduces the same structure with the real request functions and no network calls, preserving its probe and clearly labeled tool-output transcript. The next payload still contains encrypted reasoning and the paired function call/result; no tool-protocol failure is established by that probe. Archived actual-model receipts lack provider `input_transformations`, so actual reasoning removal and its impact remain unmeasured. The same continuation adds a full b31 Core regression and a separate installed-wheel lifecycle check without changing this implementation.

## Follow-up: corrected Shell proposals and Full child projection

The current Core b28 source is published at `03535fe943f64f49e9e3d79e7949aca6c9ec9b87`. Two additional concrete defects were reproduced and fixed without changing the main forty-item counts: a fresh successful host Shell call can now settle the identical never-dispatched proposal when only timeout changed; child repair references gain the same worker prefix as their projected receipts. `_finish`, tool schemas, prompts and budgets are unchanged.

[The independent before/after report](../evidence/audit-20261117/root/shell-timeout-repair/RESULTS.md) records 73 tests, 72 passed and one existing macOS-only skip, with real Shell/file/Full parent-child paths and scripted model responses. No-execution, different-command, reused-receipt and UNKNOWN controls retain their earlier behavior. The frozen R2 case-020 remains an original incomplete result; it was not rerun or reclassified. Case-019 used different commands and is outside the narrow association. RC11 packaging and actual-model long-running checks are reported separately.
