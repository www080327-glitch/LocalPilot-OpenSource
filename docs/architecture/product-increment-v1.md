# LocalPilot 5 product contract v1

This is an additive extension of API / Client Contract 1.0. Desktop remains a client; Core owns AgentSession, TaskService, Gateway and SQLite. Suite owns native installation coordination and the model-manager adapter. Companion retains its decision tree, observations and memory.

## Session authorization

`POST /localpilot/v1/desktop-sessions` requires a separate host control operator authorized for `client_subject` and an `Idempotency-Key`. Exact body: `client_subject`, `model`, `source`, `options: {permission_mode, agent_profile}`. Modes are `ask`, `safe`, `uncertain`, `full`; profiles are `standard`, `minimal`. New sessions persist their options, source-bound authorization identity and negotiated local context. Repeated authorization returns the same session, including after restart. Old sessions are not rewritten. Reducing backend context below a saved session returns `context_changed` before new work.

The four modes reuse the existing Gateway. Deterministic risk classes are SAFE / UNCERTAIN / RISKY. Undeclared extensions require human approval; local-only network access, denied capabilities, protected paths, host-only approvals and UNKNOWN effects remain independent boundaries. LocalSafetyJudge is retained for historical host policies; no new classifier weights or Agent loop are installed.

## Attachments

`POST /localpilot/v1/attachments/import` is operator-mediated, subject-bound host-local file ingestion. Exact fields: `client_subject`, `model`, `paths`. Core checks ordinary-file ownership, protected credentials, symlinks, file identity while copying, aggregate bytes and free space. Original identity, size, SHA256 and permission source are recorded. A model-visible workspace manifest is data; a separate owner-only canonical record is stored outside the workspace in Core's persistence directory.

Budgets: 2 GiB per batch, 2 GiB disk reserve, 8 MiB metadata estimate. The transport's request-body budget also applies. There is no small fixed file-count limit. Native paste uses an 8 MiB IPC budget; picker/drop can use the full batch budget. File thumbnails are lazy, use bounded local decoding and two workers; previews have pixel/file limits. No third-party image processing is involved. Files remain controlled local files, not parsed text or visual model input. The client refuses cloud attachment submission in this candidate; it never treats ordinary cloud-question consent as file-content consent.

## Model manager

Native `product_control` uses a fixed version=1 operation allowlist. Suite authenticates to oMLX locally; admin keys/cookies never enter the WebView. Search, info, download, task progress, cancellation, retry, per-model settings and deletion use official oMLX APIs and negotiated schemas. Unsupported pause, per-model memory/concurrency and per-model cache toggles are not represented as working features. Downloads have a receipt journal; ambiguous submissions are observed/reconciled rather than replayed. Model resource UNKNOWN blocks subsequent mutations.

`verify_model` streams local model hashes and compares them with upstream LFS SHA256 / Git blob metadata. It does not upload file contents or execute model code. Download completion alone is not a checksum claim. Native model load/unload continues through Core ModelResources with separate bounded resource authorization; unloading a model held by active/waiting tasks is rejected.

Hardware recommendations reuse the existing catalog, profiles and recommender, constrained by Core's published local Agent eligibility requirements. Current minimum context is inherited from Core, not guessed by the GUI. Power constraints are shown; no device model is hardcoded. New cloud configuration uses the documented 1M admission range without filling it or increasing output caps. Existing route/session configuration is preserved.

Cache preferences are stored separately from actual provider state. Shared prefix and SSD cache state are observable. Per-model enable/disable and restart durability are not promised. No prewarming is represented as permanent KV cache.

## Installation and pet mode

Desktop carries independent offline Core / Companion / Suite wheels and portable Python, including CA roots. The controlled installer uses pinned official oMLX 0.7.2 DMG size/SHA256 and signature checks. Existing apps/settings are not overwritten. Initial, existing, stopped, upgrade and incomplete-config states are distinct. A model download is optional. Older installations can be discovered without asking for internal directory knowledge. Component upgrades refuse active work and preserve private database/configuration backups. Backups restore only to a new location; old binaries must not be pointed blindly at newer persisted schemas.

Pet mode is a separate native window and Companion consumer. Click opens an anchored reply field; close does not authorize or cancel Core work. Proactive notices require the existing Companion policy/consent and obey quiet hours. Handoff transfers the original question into the main composer for review; it does not silently run the full chain. Standard Desktop chat never enters the pet decision tree.
