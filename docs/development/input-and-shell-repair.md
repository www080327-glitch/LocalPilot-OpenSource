# Input and Shell repair

The composer and pet chat share Enter behavior. The default is newline; settings can select Enter-to-send. Command/Ctrl+Enter sends and Shift+Enter inserts a newline. Composition state, native `isComposing`, WebKit keyCode 229, and a short composition-end guard prevent IME candidate confirmation from submitting. The setting persists as `lp.enterBehavior` and does not modify backend preferences.

The send path also respects the same active/UNKNOWN-task block as the disabled send button, so keyboard shortcuts cannot bypass it and trigger an irrelevant profile-switch request.

A trusted Shell process that returns a normal nonzero exit now records a settled `failed_process` attempt, with `partial_effects_possible` retained. Earlier parts of a compound command may have run. The error and stderr remain visible; the Agent can inspect the filesystem and use a corrected command. This failure is not promoted to success or erased. Overall task verification remains independent of command exit status.

Timeouts, signals, lost process outcomes and in-flight intents retain UNKNOWN quarantine and no automatic replay. Existing quarantined tasks are not rewritten or automatically retried by this update.

Focused checks: IME/keyboard unit controls, headless UI composition and setting persistence, and an actual temporary-filesystem macOS `touch -n` failure followed by inspection, correction, file creation and readback. The backend is scripted; no real cloud model is used for these checks. A separate timeout check confirms UNKNOWN is preserved.
