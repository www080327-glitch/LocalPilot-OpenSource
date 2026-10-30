# Host installation

The LocalPilot service must already be configured by its operator. Give this caller only its own ordinary client token, never the operator or model provider token.

Copy the complete `localpilot-agent` directory into the caller project's `.agents/skills/`. The portable adapter scripts require only Python 3.10+. Set LOCALPILOT_URL and LOCALPILOT_TOKEN in the trusted launch/adapter environment; do not put values in prompts or checked-in configuration.

For Codex stdio MCP, configure the command to start the absolute installed `scripts/localpilot_adapter.py --mcp`, and use `env_vars = ["LOCALPILOT_URL", "LOCALPILOT_TOKEN"]`. The host's MCP tool approval rules still apply. This release verified Codex through the supplied HTTP CLI adapter because its noninteractive MCP submission was rejected by host policy. The caller sandbox must allow connection to the service.

For DSH, project `.agents/skills` discovery and the `@deepseek-ai/dsh-mcp-client` stdio bridge were verified. Set serverName=localpilot, command=python3, args=[absolute adapter path, --mcp], and explicitly forward the two environment variables in a project `--patch` overlay. DSH subprocess credential scrubbing otherwise removes token-shaped parent variables. Do not edit another active profile.

If MCP is unavailable, invoke the installed script with `localpilot_submit`, `localpilot_status`, `localpilot_continue` or `localpilot_cancel`, and `--arguments` containing the tool's JSON arguments. Query the same Task ID; retries use the original key and identical body. No adapter accepts a model output as an approval credential.

Service startup, private configuration, operator actions, backups and all client examples are in the separate service distribution's `SERVICE_DEPLOYMENT.md`.


Install into a selected project with `localpilot --home SERVICE_HOME integrations install codex --project PROJECT` (or `dsh`). The installer checks the distinct configured ordinary identity, preserves existing MCP servers and refuses conflicts. Codex uses project `.codex/config.toml`; project trust and host approval remain required. DSH uses an explicit `.localpilot/dsh.patch.json` overlay with its official MCP client. Start it with `dsh headless --patch PROJECT/.localpilot/dsh.patch.json --json "Use LocalPilot ..."`. Both discover project `.agents/skills/localpilot-agent`.

`integrations doctor --project PROJECT` checks credentials, service contract, capability ceilings and stdio schema registration for both hosts. It does not certify a model invocation or host approval. `integrations uninstall HOST --project PROJECT` removes only unchanged installer-owned content; edited content is preserved. User-level installation additionally requires `--scope user --confirm-user`. No global configuration is changed by project installation.


A human can bind an exact folder to one host using the existing operator API through `localpilot --home SERVICE_HOME integrations authorize HOST --project PROJECT --folder EXACT_FOLDER --access read --permission-mode safe --model ROUTE --confirmed`. Use organize/modify only for explicitly authorized mutations. `--cloud-paths-json '[".","public.txt"]'` separately permits directory listing metadata and that exact file's disclosure; default is no file disclosure. The connection then advertises the owned authorized Session ID through capabilities. Parents must submit explicitly into that ID; install never grants a folder. Revoke through GUI for its selected identity or the existing operator workspace-grants API. A closed/cancelled session needs a fresh human authorization/session; never silently replay it.
