# LocalPilot Suite CLI

The Suite exposes `localpilot`; Core independently exposes `localpilot-core`, `localpilot-service` and `localpilot-adapter`; Companion independently exposes `companion`. Global `--home DIR` and `--json` precede the command. No command downloads model weights during initialization. Default data directory is `~/.local/share/localpilot`, separate from the virtual environment and installed source.

```sh
localpilot --version
localpilot --home "$LP_DATA" init --workspace "$LP_WORKSPACE" --model Qwen3.6-35B-A3B-4bit --base-url http://127.0.0.1:1234/v1
localpilot --home "$LP_DATA" doctor
localpilot --home "$LP_DATA" start
localpilot --home "$LP_DATA" companion start
localpilot --home "$LP_DATA" companion ask "你好"
localpilot --home "$LP_DATA" ask "你好"
localpilot --home "$LP_DATA" chat
localpilot --home "$LP_DATA" agent "读取工作目录中的说明文件"
localpilot --home "$LP_DATA" tasks
localpilot --home "$LP_DATA" task show TASK_ID
localpilot --home "$LP_DATA" task watch TASK_ID
localpilot --home "$LP_DATA" task cancel TASK_ID
localpilot --home "$LP_DATA" logs
localpilot --home "$LP_DATA" config
localpilot --home "$LP_DATA" models
localpilot --home "$LP_DATA" companion status
localpilot --home "$LP_DATA" companion stop
localpilot --home "$LP_DATA" stop
```

`LP_DATA` and `LP_WORKSPACE` above are paths chosen by the user; private data must be outside the tool workspace. `init` prompts for missing workspace/model on an interactive terminal, or requires flags for scripts. `init --connect URL --token-env NAME` binds an existing service without copying its credentials. Generated credentials use private files and never appear in stdout. Existing files are preserved; repeating init fails clearly. Load the needed client environment in a trusted shell when independently using Companion; Suite forwards ordinary client credentials and removes operator/provider credential variables.

The generated Companion starts in a conservative rules-only configuration: model backend disabled, no watched directories or native observation permissions, automatic local escalation disabled. This is an installation baseline, not proof of configured Qwen behavior. Explicitly configure the 0.8B path, LocalPilot managed model route/resource control, observation permissions and native UI before full Companion inference use. Battery or unknown power blocks real lightweight inference by default. `LOCALPILOT_DISABLE_LOCAL_MODELS=1` blocks Companion models and Core CLI local inference even on AC. It is an operator testing override, not a service-wide authorization policy for every external API consumer.

`companion ask` uses light Companion interaction; deterministic greetings require no model. Top-level `ask/chat` use a Core reasoning_only route; `agent` requires a standard execution route. The generated HTTP identity can access both routes. No command infers that an unavailable local model authorizes cloud use. Configure DeepSeek through the documented host-only credential resolver and explicit egress policy.

## Streaming and persistent work

Human mode displays text deltas and task events. JSON mode emits newline-delimited `type=event` objects followed by one authoritative final task object. Persisted event cursors suppress history on reconnect. `task show` retrieves the complete current result even if events were previously printed. Reconnect attempts are bounded; snapshots reconcile expired cursors. Reconnection never submits a mutation.

The CLI saves the request/key privately before sending. Human output prints the key and Task ID. `--key KEY` permits an identical retry after uncertain submission; changed input under the same key is rejected. `--detach` submits and returns. A terminal close or Ctrl-C detaches and leaves an authorized task running; use `tasks` or `task watch ID`. `/quit` ends interactive chat. `task cancel ID` requests cancellation explicitly. Stop/restart refuses active tasks, including tasks owned by other service clients; it does not silently cancel them.

## Trusted control

Ordinary CLI and Companion tokens cannot approve. Read the required_action preview and current action ID; an independently authorized operator can explicitly use:

```sh
localpilot --home "$LP_DATA" task approve TASK_ID --action-id CURRENT_ACTION_ID --operator-token-env LOCALPILOT_OPERATOR_TOKEN
localpilot --home "$LP_DATA" task reject TASK_ID --action-id CURRENT_ACTION_ID --operator-token-env LOCALPILOT_OPERATOR_TOKEN
localpilot --home "$LP_DATA" task resume TASK_ID --action-id CURRENT_ACTION_ID --operator-token-env LOCALPILOT_OPERATOR_TOKEN
```

Operator tokens stay in the trusted terminal environment, never prompts. These calls remain subject to server owner binding, stale-ticket checks and UNKNOWN quarantine. A help confirmation authorizes task submission only; it never authorizes tool effects.

| Exit | Meaning |
| --- | --- |
| 0 | Command succeeded, submitted detached task, or Runtime completed; inspect verification separately |
| 1 | Transport/startup/general failure or doctor cannot reach service |
| 2 | Invalid configuration, power policy, unavailable route or local validation |
| 3 | HTTP authorization denied |
| 4 | HTTP conflict or Suite detects missing compatible Core CLI |
| 5 | Task requires approval/human action |
| 6 | Task failed, incomplete, cancelled or timed out |
| 7 | HTTP 429 |
| 130 | CLI detached by interrupt |

Core task success exit 0 is not a universal semantic verification certificate. Inspect verification_summary and receipt_summary. An unavailable backend or missing metric is never printed as successful inference. Companion preserves its own documented exit codes behind the subcommand. Argument-parser usage errors may be plain stderr even in JSON mode.

## Current managed installation profile

`localpilot init --workspace /your/workspace --managed-qwen35` uses the exact approved cached Qwen3.6-35B revision and the installed `/Applications/oMLX.app` launcher. Install oMLX separately before using this preset; the wheel does not bundle it or weights. The vendor model interpreter is isolated from the CLI environment. `doctor` checks cached files, executable and credential references without running inference; static readiness is not model health. External local-openai services remain a supported alternative.

Suite detects the approved existing 0.8B cache and enables its Companion backend for on-demand interaction; use the Companion `[mlx]` optional extra. `--companion-model-path` supplies another explicitly chosen existing directory. The default remains no automatic inference on battery and no automatic cloud. Optional `--cloud-key-file` references an existing private DeepSeek credential file, never its value. `allow_automatic_cloud` remains false.

Managed task CLI defaults to a bounded 600-second deadline; use `--timeout` to select up to 3600 seconds. Detach leaves an ordinary-token API heartbeat controller; it cannot approve, execute tools or invoke models. Cursor-based watch and task show recover progress after terminal exit. Task input JSON UTF-8 limit is published in health compatibility; oversized original questions fail before submission, while optional context omissions remain explicit.

## Opt-in proactive help

Opening the UI does not grant observation access. The generated config starts with observation/proactive delivery off. Choose `watch_dirs`, native observation and app scope in your own `companion.json`; inspect `localpilot companion privacy`; explicitly use `localpilot companion authorize-observation --confirm` when you accept that scope. `localpilot companion proactive --level normal --delivery enabled` enables delivery policy. OS accessibility/notification permissions remain a user decision. Help confirmation still does not grant tool approval, and natural proactive-help recall has not been certified.
