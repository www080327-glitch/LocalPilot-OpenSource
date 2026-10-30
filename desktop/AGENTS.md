# LocalPilot Desktop engineering rules

- Keep the root limited to README, AGENTS, LICENSE (if supplied), build/configuration entrypoints and source directories.
- Put architecture in docs/architecture, design in docs/design, development guidance in docs/development, acceptance in docs/acceptance, raw evidence in docs/evidence, and UI images in docs/screenshots.
- Never create root-level reports. Retain failed and UNKNOWN evidence. Existing docs/archive records are immutable historical context.
- New test screenshots and evidence must use a new run directory rather than overwrite published evidence.
- Core, Companion and Suite have independent lifecycles and versions. Do not implement a second Runtime or modify their worktrees during GUI maintenance.
- Treat local APPs, archives and build outputs as protected until identity, references and running state are checked. Cleanup is dry-run unless the human explicitly confirms exact paths. Use Trash only; no permanent deletion or background cleanup.
- Keep published release outputs immutable. Build into a fresh versioned run directory. Never package credentials, Application Support, SQLite or model data.
- Use a single build worker for low-power work. Do not start model inference for GUI checks.

- Use scripts/build-macos.sh for the shared build slot and archive-only delivery. Never copy candidate APPs into evidence or release directories. Keep the daily Bundle ID io.localpilot.desktop; use an explicit test override and LocalPilot Test display name for isolated GUI runs.
- Install/upgrade through scripts/install-local-app.py with a reviewed plan. Verify the rollback ZIP by extraction; the retired installed APP goes to Trash. Never generate new Desktop aliases or APP backup folders.
- Use Suite maintenance apps --dry-run and inspect active processes/references before --cleanup --plan. Keep test fixtures and unknown ownership. Record scan, archive, restoration and Trash receipts in a dated docs/evidence directory.
