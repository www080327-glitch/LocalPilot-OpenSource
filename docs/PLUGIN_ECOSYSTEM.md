# LocalPilot 5 plugin ecosystem (opt-in beta)

LocalPilot is the **MCP client** in this module. This does not replace the
existing LocalPilot MCP server / Codex Skill / DSH integration. External
capabilities enter the existing ToolRegistry, PermissionGateway, AgentSession
and TaskService. There is no second Agent runtime.

## Installation and review

Install the reviewed Core wheel with its `plugins` extra and the matching Suite
wheel. The extra pins `mcp==1.26.0`, `jsonschema==4.26.0`, `packaging==26.0`.
Core without the extra retains its existing tools. No servers connect at import,
route construction, or Skill discovery.

The protocol is pinned to the official MCP **2025-11-25** specification. Other
negotiated versions are rejected. Official SDK transports implement stdio and
Streamable HTTP, including JSON/SSE responses and session headers. Sampling,
elicitation, roots, and experimental task capabilities are not advertised.

Review the actual server source, dependency lock, license, startup behavior,
filesystem access and downstream networking before running it. Install its
reviewed, pinned package in a dedicated environment; `plugins add` registers a
manifest and never invokes pip/npm, downloads code, or grants permissions.

Generate a manifest for the included MIT public-notes example:

```python
import sys
from pathlib import Path
from localpilot_plugins.sdk import StdioPlugin, write_manifest

source = Path("examples/plugins/public_notes/server.py").resolve()
write_manifest(StdioPlugin("public-notes", sys.executable,
                          (str(source),), (str(source),)), "public-notes.json")
```

Use a separate native home outside every Agent workspace. No existing files are
overwritten by `add`. Read the source before attesting `--source-reviewed`:

```text
localpilot --home /private/tmp/localpilot-plugin-demo plugins add public-notes.json
localpilot --home /private/tmp/localpilot-plugin-demo plugins discover public-notes --source-reviewed --license MIT
localpilot --home /private/tmp/localpilot-plugin-demo plugins tools public-notes
localpilot --home /private/tmp/localpilot-plugin-demo plugins review public-notes --catalog-sha256 DIGEST_FROM_DISCOVERY --policy examples/plugins/public_notes/review.json
localpilot --home /private/tmp/localpilot-plugin-demo plugins enable public-notes
localpilot --home /private/tmp/localpilot-plugin-demo plugins doctor public-notes
localpilot --home /private/tmp/localpilot-plugin-demo plugins list
```

`discover` executes reviewed startup code and returns an **untrusted catalog**.
It disables the installation and revokes any previous review. `review` binds the
exact catalog, executable/source identity, allowed tools, concrete resource URIs,
prompts, host-authored summaries, effect classifications and argument constraints.
`enable` remains a separate action. External `readOnlyHint`, descriptions and
server instructions cannot create host metadata or permissions. Raw schema prose
is omitted from the model's tool definitions; structural constraints remain.

Names include the server, capability kind and a digest. Duplicate names inside
one server, repeated pagination cursors and excessive catalogs fail discovery.
Capabilities are inspected independently: a resource-only or prompt-only server
does not receive tools/list. Unsupported resource-template listing is optional.

## HTTP and credentials

```json
{
  "id": "public-remote",
  "transport": "streamable-http",
  "url": "https://reviewed.example/mcp",
  "bearer_credential": "public-remote-key",
  "timeout": 15
}
```

The endpoint must be HTTPS or a numeric loopback HTTP address. URL credentials,
queries, fragments, redirects and inherited HTTP proxies are refused. Specify
the exact endpoint, including a trailing slash if its server requires one.
Remote TLS uses the HTTP library's certificate verification.

```text
localpilot --home /private/tmp/localpilot-plugin-demo plugins credential public-remote-key --private-file /private/operator/token.txt
```

Alternatively read the credential from standard input with `--stdin`. Do not put
credentials in prompts, arguments, URLs or shell history. Stdio manifests can
bind `credential_env: {"SERVER_API_KEY": "public-remote-key"}`. Arbitrary
environment, shell startup variables and provider/operator environment inheritance
are disabled. Each server resolves only its own credential references.

Credentials use the existing native service's owner-only storage convention:
private directory, regular owner-only file, no symlinks, native code access.
They are not an encrypted OS Keychain implementation. Exact credential values
are redacted before external output reaches the model or receipts; this is not
a general detector for encoded/transformed secrets from compromised code.
Removing a server removes its unshared credential references and preserves
historical receipts. Credential rotation rebuilds transport identity.

## Authorization, effects and isolation

Every discovered capability is adapted into ToolRegistry and goes through its
Gateway. Even full-permission mode requires per-call approval for MCP tools.
Approvals show server/tool identity, arguments, reviewed resource scope, network
classification, Plugin Egress, effect classification and the verification boundary.
They bind the authorization generation and catalog; an old approval cannot grant
an updated, disabled or removed plugin authority.

Cloud Egress controls model disclosure. Plugin Egress separately controls
transmission to the plugin process/endpoint. Ordinary local file permissions do
not grant either. The existing hard `local_only` data policy still forbids
network-classified plugins even when Plugin Egress is allowed. `allow_agent`
separately controls whether an enabled server is exposed to AgentSession.

For an observation, `status=ok` means a response was received and validated;
verification is `response_only`. For a tool reviewed as producing external
effects, even `isError=false` yields **UNKNOWN** with
`verification=external_effect_unobservable`, `action_may_have_applied=true` and
`replay_allowed=false`. A server's success prose cannot certify an external
effect. Failed external calls can also have effects. The TaskService and existing
UNKNOWN recovery controls retain these obligations.

Each stable host operation identity is journaled before dispatch, with redacted
parameters and their digest, server/tool/catalog identity, resource scope,
reviewed network/egress settings and outcome. A crash after intent cannot replay
the call. Reusing an identity with changed parameters/policy is rejected. Reused
receipts are explicitly historical observations. No exactly-once claim is made.

Source/executable hashes and catalog identity are rechecked. Source files named
in the manifest, direct executable and absolute file arguments are hashed;
transitive dependencies must also be pinned/reviewed by the operator. TLS endpoint
and serverInfo/catalog identify remote servers; this is not a cryptographic
attestation of their implementation or behavior.

One disposable SDK worker per active server isolates protocol parsing, plugin
crashes and oversized replies from Core. Requests have 1–60 second bounds; only
two connection attempts are allowed before invocation. Tool calls are never
retried automatically. Worker+descendant RSS is monitored against 512 MiB;
messages are bounded at 1 MiB, catalogs at 256 KiB, individual schemas/arguments
at 32 KiB, and model results are further bounded by the existing Registry.
JSON Schema validation also runs in a disposable process with CPU and wall limits.
Remote/recursive schema references and regex schemas fail closed.

Cancellation attempts `notifications/cancelled`, then terminates the worker tree
within a bound. Remote cancellation delivery/acknowledgement and rollback remain
unknown. Disable/remove is checked during active requests and before every new
dispatch; it cannot undo an already sent effect. Idle shutdown closes the SDK
session; Core suspend/shutdown closes workers. A later invocation negotiates a
fresh session and rechecks the catalog. HTTP event replay after a lost response
is not used to clear UNKNOWN or resubmit a tool.

**These process controls are not an OS filesystem/network sandbox.** A reviewed
stdio server runs as the native user and can perform startup actions; downstream
network access and arbitrary remote effects are unobservable. Scope prose is a
review/approval description; enforceable argument restrictions belong in each
tool's host `argument_schema`. Only reviewed servers are eligible for this beta.
The security acceptance is the measured Gateway/credential/no-replay boundary,
not permission to install arbitrary hostile code.

## Agent and service opt-in

Add an explicit block to a tool-enabled route in a **new test** service
configuration; no migration rewrites user configurations:

```json
{
  "plugins": {
    "home": "/private/tmp/localpilot-plugin-demo/plugins",
    "skill_home": "/private/tmp/localpilot-plugin-demo/skills",
    "skills": [{"id": "public-notes", "scope": "user"}]
  }
}
```

This block uses the existing AgentSession route. It does not alter model
routing, GUI structure, Computer Use, attachments, Codex or DSH configuration.
Workspace changes rebind adapters and protect native plugin/Skill storage from
ordinary file scope escalation. Private stores may not overlap any tool workspace.
Children do not automatically inherit plugin tools; no recursive delegation or
plugin-requested model calls are enabled.

For a native host embedding Core, call
`localpilot_plugins.adapter.configure_session(runtime, home, skill_home=..., skills=...)`
before persistence restore. Existing TaskService approvals, receipts and stable
operation namespaces survive restart. Old action tickets expire on restart.

`plugins call` is an operator diagnostic using the same Registry/Gateway:

```text
localpilot --home /private/tmp/localpilot-plugin-demo plugins call public-notes --kind tool --tool lookup_public_note --arguments public-arguments.json --workspace /path/to/public-workspace --request-id stable-public-operation
```

Review its approval preview, then repeat with `--approve` and the same identity
to authorize exactly those arguments. Never generate a replacement identity to
evade UNKNOWN. Management/review/credential operations are not model tools.

## Skills

A Skill bundle contains **only explicit `skill.json` and `SKILL.md`** as registry
inputs. See `examples/skills/public-notes`. Markdown elsewhere is never scanned
as a trusted instruction. Metadata specifies version, LocalPilot compatibility,
dependencies and their version constraints, required tools, inputs and outputs.
Installation never executes scripts or installs dependencies.

```text
localpilot --home /private/tmp/localpilot-plugin-demo skills add examples/skills/public-notes --scope user
localpilot --home /private/tmp/localpilot-plugin-demo skills show public-notes --scope user
localpilot --home /private/tmp/localpilot-plugin-demo skills enable public-notes --scope user --reviewed-sha256 BUNDLE_DIGEST
localpilot --home /private/tmp/localpilot-plugin-demo skills doctor public-notes --scope user --tools read_file
localpilot --home /private/tmp/localpilot-plugin-demo skills --project /path/to/public-workspace add examples/skills/public-notes --scope project
```

Project installation data lives in `.localpilot/skills`. Its native review record
is stored outside the project, so workspace file edits cannot forge approval.
Scope must be explicit; project and user Skills never silently shadow each other.
Dependencies resolve in the selected scope, with bounded depth and cycle checks.
Missing/disabled dependencies, wrong versions, missing tools, incompatibility or
tampering block loading. Updating disables the Skill and revokes the review.

Host-selected Skills are read through `load_skill` and returned as reviewed **user
guidance below host policy**. They are not inserted as system instructions and
grant no tool, credential, cloud, network or plugin permissions. Requirements
describe needed tools; they do not install or authorize them. Input/output
schemas document the Skill contract; a Skill is not a second executable runtime.

## Update, disable, remove and diagnostics

```text
localpilot --home /private/tmp/localpilot-plugin-demo plugins disable public-notes
localpilot --home /private/tmp/localpilot-plugin-demo plugins update reviewed-new-manifest.json
localpilot --home /private/tmp/localpilot-plugin-demo plugins remove public-notes
localpilot --home /private/tmp/localpilot-plugin-demo skills disable public-notes --scope user
localpilot --home /private/tmp/localpilot-plugin-demo skills remove public-notes --scope user
```

Updates reset discovery, review and enabled state. Refresh a Session's registry
by creating a new session after changing its plugin catalog; stale adapters fail
closed. Doctor checks identity, negotiated capability catalog and ping without
executing tools. Errors are bounded and exclude raw HTTP error bodies/stderr.
Corrupt individual installation records are quarantined in discovery diagnostics.

This delivery provides the Suite CLI management surface. GUI management,
OAuth browser/PKCE/DCR flows, OS Keychain migration, advanced RFC6570 template
expansion, resource subscriptions, and HTTP event replay qualification are
**NOT_RUN/unsupported** in this beta. Concrete resource URI review supports
advertised resources and simple `{variable}` template expansions.

## Sources and reproducibility

- [Pinned MCP specification](https://modelcontextprotocol.io/specification/2025-11-25)
- [Official lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
- [Official transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [Pinned Python SDK source and MIT license](https://github.com/modelcontextprotocol/python-sdk/tree/3d9d34552a9ab8988acf8d06e4a705bd799fc32b)

Review evidence is in `docs/evidence/plugin-ecosystem-20261025`. Public E2E uses
the pinned SDK's simple-tool, simple-resource, simple-prompt and
simple-streamablehttp packages, installed only inside this checkout's environment.
`python -m scripts.plugin_public_e2e REPORT.json` reproduces the transport tests.
`python -m scripts.plugin_model_e2e EXISTING_NATIVE_HOME REPORT.json` performs a
bounded, public-data local-model selection test via existing native credentials
and resource control. It preserves user configuration and does not download weights.
