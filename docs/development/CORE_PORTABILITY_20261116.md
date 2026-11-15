# Core portability checks — 2026-11-16

Base: `47e39faf3e97fbd13a562a9ec74efa30dfcc7b42` (PR #11). These changes address the portable Core entry points and a configured OpenAI-compatible local server. They do not qualify an Intel APP, Linux desktop integration, or model quality.

## Problems reproduced and fixed

1. `python main.py` returned before invoking the Agent on every host outside the bundled Apple Silicon MLX recommender's scope. Explicit `--local-base-url` and `--local-model` arguments never reached inference. The launcher now enters the existing Agent CLI on these hosts without asking the inapplicable MLX questionnaire. It also returns the Agent's process exit status, so an unavailable model no longer appears successful.
2. Hardware discovery reported Linux as `Unknown`. It now preserves the actual operating system name, while keeping MLX recommendation support and MPS availability separate. Neither an Intel architecture nor a Linux name establishes provider acceleration.
3. Core CLI treated `psutil.sensors_battery() is None` as a mandatory rejection. That includes batteryless Intel desktops. On macOS, the CLI now falls back to the observed power source from `/usr/bin/pmset -g batt`. An observed battery source stays a battery source; failed or unrecognized observations stay unknown.
4. Generic local endpoint initialization exposed no context or HTTP timeout controls even though the backend supported them. CPU users can now pass their server's actual context configuration and a suitable timeout without editing private JSON. Existing configurations and omitted-option defaults are unchanged.
5. Companion's controlled local inference path could not use a generic CPU endpoint because only managed models and oMLX advertised the required request controls. The existing oMLX/vLLM response-disconnect implementation now lives once in `LocalHTTPBackend`. Generic local-openai routes advertise shared external request controls, without entering oMLX's load/unload implementation. Core CLI distinguishes shared services from owned models and does not start a managed-model heartbeat controller for them.

The first four source-entry/hardware regression tests failed on the unchanged base and passed after the fixes. Baseline failures remain in the external validation log.

## CLI options

Both `localpilot-core init` and `python -m localpilot_service.configure` accept:

| Option | Meaning |
| --- | --- |
| `--context-budget TOKENS` | Positive configured context estimate. Match the server's loaded context; this is not a measured capacity claim. |
| `--model-timeout SECONDS` | Positive finite model HTTP timeout, including waiting for the first token. It is distinct from the whole task's `--timeout`. |
| `--stream-usage` | Request streamed usage from a provider that implements this option. Missing usage remains unknown. |

`localpilot-core ask`, `agent`, and `chat` accept `--allow-local-on-battery`. This explicitly allows that foreground command's local-openai requests when power is battery or unknown. It does not persist a background preference or change system settings. `LOCALPILOT_DISABLE_LOCAL_MODELS=1` still blocks these requests. In interactive `chat`, the choice applies to the turns submitted by that command until it exits. Managed oMLX resource grants keep their own existing policy.

For example, after installing Core and starting a compatible local server separately:

```bash
mkdir -p "$HOME/LocalPilotWorkspace"
localpilot-core --home "$HOME/.local/share/localpilot-portable" init \
  --workspace "$HOME/LocalPilotWorkspace" \
  --model YOUR_EXISTING_MODEL_ID \
  --base-url http://127.0.0.1:1234/v1 \
  --context-budget 8192 \
  --model-timeout 120
localpilot-core --home "$HOME/.local/share/localpilot-portable" start
localpilot-core --home "$HOME/.local/share/localpilot-portable" models
localpilot-core --home "$HOME/.local/share/localpilot-portable" ask \
  --allow-local-on-battery 'Reply with a short greeting.'
```

The example's explicit power override is useful on Linux servers or containers with no readable power source. On a Mac with observed AC power, omit it. Replace the model ID and context with the server's configuration. The command neither installs a model nor checks model quality. Use `agent` for tool tasks; `ask` uses the isolated reasoning-only route. Mutations continue through the configured approval flow.

## What the tests execute

`tests/test_core_portability.py` exercises the production paths with temporary workspaces, a real loopback HTTP/SSE server, and actual Core subprocesses:

- Linux source launcher → HTTP tool call → real `apply_patch` → real `read_file` → final response, including file evidence in the next provider request.
- Source launcher failure exit status when the configured model is absent.
- Simulated Intel identity → the same real HTTP Agent path, without an MLX questionnaire. The platform identity alone is simulated; this is not physical Intel testing.
- `init` → configured 8,192-token/120-second backend → real Core startup without inference.
- File mutation waits for a separate operator approval, then executes and reads back the written file.
- Task SSE events have ordered unique sequence IDs, reconnect from the last cursor, and return HTTP 409 for an impossible future cursor.
- SIGTERM shutdown → SQLite `integrity_check` → new Core process → retained completed task/receipts → duplicate idempotency key returns the original task without another model call.
- Cancellation during an approval wait prevents a file write and remains cancelled after process restart.
- Cancellation while a model HTTP response is pending acknowledges stop intent without waiting for the provider; when the late response arrives, its proposed file tool is not dispatched.
- Active buffered and streaming HTTP responses are disconnected through the common transport for local-openai, oMLX and vLLM. Partial streaming evidence is retained without replay. The real Core process stops an active stream through `/inference/stop`, leaves the provider available to a new request, and retains the cancelled task across restart without repeating its model call or late file proposal.
- Unknown power blocks a default CLI request, an explicit power override permits it, and the operator disable environment variable still blocks it. No persistent power preference is written.
- Invalid context/timeout options fail before creating provider credentials.

`tests/test_local_http_backend.py` also checks both buffered and streamed replies containing visible `<think>` text and absent usage. The adapter preserves the provider's output and leaves usage unknown; it does not manufacture a clean answer or zero token cost.

These HTTP replies are scripted protocol fixtures. They establish behavior of the actual transport, runtime, tools, permissions, cancellation boundary, and persistence. They do not establish the ability of any language model to choose tools or answer accurately.

## Commands and logs

Validation logs are separate from old Mac evidence:

`/workspace/scratch/2a488f6eabf5/validation/intel-20261116/core/`

| Validation | Result | Duration | Log |
| --- | --- | --- | --- |
| Initial focused Core portability, HTTP, health, hardware, recommender and CLI | 81 PASS, 0 FAIL, 0 ERROR | 34.474 s | `targeted-portability-final.log` |
| Initial full Core discovery, before shared HTTP cancellation extension | 1,413 PASS, 110 SKIP, 0 FAIL, 0 ERROR (1,523 tests) | 211.057 s | `full-core.log` / `full-core.json` |
| Shared HTTP cancellation, portability, oMLX/vLLM and CLI regression | 69 PASS, 3 SKIP, 0 FAIL, 0 ERROR (72 tests) | 37.625 s | `shared-http-targeted-final.log` |
| Final full Core discovery, including shared HTTP cancellation | 1,416 PASS, 110 SKIP, 0 FAIL, 0 ERROR (1,526 tests) | 218.368 s | `full-core-final.log` / `full-core-final.json` |
| Existing independent OpenAI SDK 3.51.0 environment, after shared HTTP change | 42 PASS, 0 FAIL, 0 ERROR | 4.058 s | `sdk-contracts-final.log` |
| Existing Harbor 0.26.0 contract environment, after shared HTTP change | 72 PASS, 4 SKIP, 0 FAIL, 0 ERROR | 27.714 s | `harbor-contracts-final.log` |

The Harbor checkout remains clean at `ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4`. The four skips require real local model/tokenizer qualification. SDK and Harbor groups reuse some tests from general discovery and should not be added to a single unique-test total. They use actual SDK/schema classes, protocol subprocesses and controlled HTTP/Shell fixtures, without a real Docker daemon or model weights. Environment versions and hashes of changed Core source/test files are retained alongside the logs. No product dependencies were added.

Final full discovery used the existing file-backed entry point with `-W default` and the actual prior-source fixtures:

```bash
LOCALPILOT_PR9_SOURCE=/workspace/scratch/2a488f6eabf5/validation/pr9-baseline \
LOCALPILOT_LEGACY_SOURCE=/workspace/scratch/2a488f6eabf5/validation/pr1-legacy \
.venv/bin/python -W default scripts/run_core_qualification.py \
  --report /workspace/scratch/2a488f6eabf5/validation/intel-20261116/core/full-core-final.json
```

The 110 general-discovery skips consist of 42 optional SDK cases and 17 pinned Harbor cases (both groups passed separately above), 12 installed Suite/Channels cases (requiring the separate installation qualification), 20 native macOS cases, four real-model cases, and 15 unavailable historical research cases. No ResourceWarning, RuntimeWarning or traceback appeared in the final Core, cancellation, SDK or Harbor logs. Installed Suite results belong to their own report and must not be inferred from this source-only Core run.

```bash
.venv/bin/python -m unittest \
  tests.test_core_portability \
  tests.test_local_http_backend \
  tests.test_pa_model_health \
  tests.test_pa_macos_hardware \
  tests.test_recommender \
  tests.test_suite_cli -v
```

Intermediate history is retained: the first process test expected exit code 1 for a CLI validation error, while the established CLI contract returns 2; the assertion was corrected. A named-test invocation including `tests.test_selector_mlp` stopped at its module-level `SkipTest` because historical benchmark fixtures are absent from this public source tree. The focused invocation above excludes that historical module; full unittest discovery should retain its skip classification.

The first active-cancellation pair had one PASS and one FAIL. A real buffered response reproduced a race in the previous oMLX/vLLM implementation: the cancellation thread closed `HTTPResponse` while its reader was closing the same `fp` after socket shutdown, causing `AttributeError`. The common transport now shuts down the socket in the cancelling thread and leaves response closure to the existing reader's context manager. No extra manager, retry, polling process or speculative locking was added. The failing log `shared-http-cancel-new.log` remains; the immediate five-test correction and later complete adapter groups passed.

## Remaining limits

| Area | Current evidence / remaining work |
| --- | --- |
| Intel Mac | Portable code path and simulated Intel branch covered; physical Intel CPU model, x86_64 packaging, native permissions, install/upgrade and performance still require an Intel Mac. |
| Linux | Actual Core subprocess, HTTP, workspace tools, SSE and SQLite behavior covered. Linux native desktop capture, meetings, notifications and APP packaging are not qualified here. |
| Inference acceleration | Local HTTP backend has no MLX or MPS dependency. CPU/Metal/CUDA selection belongs to the explicitly configured provider and is not inferred from the OS. |
| Model quality / speed | No real model weights or paid APIs were used in these tests. They do not change the previous benchmark outcome or establish parity with mainstream agents. |
| Provider interruption | Active client HTTP responses can be disconnected. Before response headers arrive, stop intent is retained and the pending HTTP open still waits for a response or timeout. Disconnecting a client does not prove the provider has stopped computing or released model memory. Registry metadata states `request_cancel_scope=client_http_response`, `provider_compute_stop=UNKNOWN`, `release_after_task=false`, and `heartbeat_lease=false`; no automatic model unload or lost-heartbeat lease is claimed. |
| Shell | Existing host Shell still requires macOS Seatbelt; this work does not substitute unrestricted Linux Shell execution or claim equivalent sandboxing. |
| Usage and reasoning text | Unknown usage remains unknown. Visible provider reasoning remains visible; the selected model/template must be qualified separately. |

