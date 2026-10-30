# Local thinking controls

The existing effort slider is retained. Models whose oMLX `/v1/models/status` metadata declares a boolean `thinking_default` expose two positions: `none` (关闭) and `high` (开启). These are the existing session effort identifiers; local payloads map them only to `chat_template_kwargs.enable_thinking=false/true`, never an unsupported provider-native reasoning-effort value.

A Desktop session stores the host-observed model/default declaration in `thinking_toggle`. Capabilities are enabled on that owned session at an idle boundary; historical sessions without this declaration retain their checkpoint identities until an explicit host settings update. No global oMLX setting or weight is modified.

The current route's explicit template default remains authoritative until the user selects another position. Provider default and LocalPilot route override can differ; the UI must not infer that thinking is enabled solely from the provider's default.

The composer remembers effort per provider/model identity. A model change restores that model's own value, and submission normalizes a legacy/restored incompatible value before passing it to native code. Returning from DeepSeek to a local model cannot forward an unsupported cloud effort. Existing local route aliases share a model preference.

Focused verification: provider-payload mapping, read-only capability discovery, session persistence across restart with a scripted local backend, UI effort normalization, and a headless round trip from multi-level cloud controls to two-level local controls and back. No model inference, download or training is required by these checks.
