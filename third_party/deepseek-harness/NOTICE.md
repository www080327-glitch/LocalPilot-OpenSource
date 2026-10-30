# DeepSeek Harness attribution and dependency scope

Reference: https://github.com/deepseek-ai/deepseek-harness
Pinned source: 687f282e8625c6b8d11ff58211a90524be2e4317 (0.2.1-rc.2)
Copyright (c) 2026 DeepSeek. Upstream license: MIT, reproduced in LICENSE.

V5 production adaptation: agent/deepseek_native.py ports the text/tool subset
of serialize.ts, replay.ts and translate.ts (same llm-deepseek/src directory)
and sse.ts lifecycle policy into Python. Canonical Message/SQLite, offset-only
replay metadata, host egress provenance and all Gateway execution remain
LocalPilot-owned. It implements public Messages, without Files, account
identity, session-log or plugin-inventory extensions. V5 context/policy code
is an independent implementation informed by session surface and balanced
compaction design. No upstream npm dependency is bundled in the product.

Production adaptation: agent/deepseek_optimized.py adapts the history pairing checks
from packages/llm/llm-deepseek/src/serialize.ts and the terminated SSE-frame policy
from packages/llm/llm-deepseek/src/sse.ts. It targets Chat Completions, not the
upstream Messages wire format. Tool ordering follows the deterministic ordering
in packages/core/system-prompt/src/index.ts. agent/deepseek_context.py applies the
upstream event-derived request projection idea to LocalPilot receipt references;
it is an independent implementation, not a DSH Session-format implementation.

LocalPilot does not vendor or import Cordis, eventsource-parser, DSH Agent Loop,
DSH Session persistence, DSH tools, account authentication, or telemetry plugins
in its production Python runtime. No new Python or Node runtime dependency is
introduced. The isolated native benchmark runs the actual upstream checkout,
including its own packages, MIT licenses and third-party dependency closure.

UPSTREAM_THIRD_PARTY_NOTICES.md is an unmodified reference copy of the upstream
notice inventory, not a representation that every listed dependency is bundled
with LocalPilot. The reference closure audit contains non-MIT and unknown-license
entries; its permissions must be reviewed before any future redistribution of
those packages. This change distributes no such dependency implementation.
