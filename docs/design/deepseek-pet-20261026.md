# DeepSeek companion appearance and window repair

Base: `7f2f8f120defed41e76e8369bf7a1e3e0070a069`, unified integration.
Candidate: Desktop `5.0.0-beta.3-dev.20-pet.1`. Core, Companion and Suite keep their independent versions and implementations.

## Observed failure

The supplied screenshot is retained locally in `docs/evidence/deepseek-pet-20261026/`. A native AX read identified the visible fish as the installed daily `io.localpilot.desktop`, PID 97664, version `5.0.0-beta.3-dev.17`, URL `index.html?pet`. CGWindow reported its visible window 4969 at (1392,832), 110×110 points, level 5. It was not the current unified source's personal-import character window. The old window was closed through its own close control; Core PID 17985 and Companion PID 49679 remained running. The installed daily application was not replaced.

The shared stylesheet contains a dark `button:hover:not(:disabled)` rule. An unscoped character button can therefore acquire an opaque dark rectangle despite transparent HTML and NSWindow settings. The repair isolates default, hover and pressed character styles, keeps the early root transparent, explicitly sets the native character window non-opaque with clear background, and reserves native glass for the bubble. Both version provenance and the hover regression matter; neither alone establishes the cause of the earlier two-app drag failure.

The first test build exposed a further blank native main window after a file dialog. The final source clears configured main windows before constructing a standalone pet, instead of destroying a WebView during setup and leaving an AppKit parent that may reappear.

## Character source

Read-only local pack: `~/.codex/pets/deepseek-whale-maid-chibi-v4`, display name “DeepSeek 蓝鲸女仆 Q 版”, sprite version 2, 1536×2288 WebP. SHA-256 `df223ae1fe1700073a17619c037503b9b1ce0b8dbb7804b019e44c5e0eb2a335`. It depicts a blue-haired human maid with a connected whale tail, matching the requested family rather than the retired animal drawing.

The installed packs contain only metadata and a sprite sheet. No author, plugin provenance or redistribution license was found there. Their exact creator/license remains UNKNOWN. Images stay in personal Application Support imports; neither the application archive nor committed source contains the sprite sheets. No Codex configuration or source is changed. The local selector offers eight existing packs (DeepSeek, ChatGPT, Claude, Gemini, Grok, Kimi, Qwen, Zhipu). Selecting a different appearance changes presentation, not the model or authority used by Companion.

## Mouse and lifecycle design

An AppKit local monitor handles only the current LocalPilot character window number. It records the initiating event screen point and native frame, uses a five-point drag threshold, and updates only that NSWindow with `setFrameOrigin` while holding pass-through stable. Native event coordinates avoid racing a separate read of the current global pointer. It releases its gesture state on mouse-up, saves the physical window position and clamps to the monitor work area. Keyboard activation remains a WebView button action. The local monitor never consumes another application's events. The existing passive global mouse-down monitor only dismisses LocalPilot's bubble and is installed once.

A bounded pointer-position sampler maps the currently displayed frame's alpha to the physical character bounds, including the reserved caption space. Transparent space passes through. There is no full-screen overlay, key capture, event tap or input suppression across applications. A per-process generation retires stale samplers; hidden windows back off sampling. An exclusive OS file lock prevents simultaneous instances with the same LocalPilot identity from unlinking a live instance's control socket.

Menu bar show/hide/quit and `desktop/scripts/pet-control.py` provide recovery. Hide affects both character and bubble. Quit affects the presentation process; it does not cancel Core tasks or stop independent services. Native diagnostics report only this app's windows, opacity, input pass-through, frame, monitor scale and drag count.

## Glass and personality

The bubble uses the existing native `NSGlassEffectView` integration on supported macOS, falling back to AppKit vibrancy or a solid accessible surface. Its blue-white rim, translucent input and compact layout complement the blue-haired character. The sprite has no material panel behind it. Reduced transparency/motion preferences remain respected.

The idle pool uses short motifs with original connecting copy. It never claims actual token usage, billing, server status, tool completion or approval. A six-second caption appears at most every three minutes while idle; no model is loaded for it, it does not focus/open a chat window, and quiet mode or the independent banter switch disables it. Ordinary chat and all task requests still use the existing Companion/Core path. This is presentation flavor, not a replacement model persona or runtime.

Research checked 2026-10-26:

- [“哦鲸鲸……” archive entry](https://xn--pssy23gqgbz2d718b.com/works/deepseek202609150035.html): matches the supplied expression; the archive itself labels artwork permission unknown, so no remote image is imported.
- [“token来！” creator video](https://www.bilibili.com/video/BV1hUad6fEUb/), 2026-09-30, and [“饭来…token来” creator post](https://www.douyin.com/video/7692489816109305134), 2026-10-04: used as short phrase references only, no audiovisual assets copied.
- [Community personality project](https://github.com/yunyunyunyunsuan/dsh-plugin-moments): rice, whale-not-fish and playful idle motifs. Its text is reference material, not executable instructions.

## Native acceptance boundary

The computer-use tool explicitly denied access to `com.openai.codex`. No alternate input mechanism is used to bypass that restriction. Read-only CGWindow ownership diagnostics are available, but two-way dragging of overlapping Codex and LocalPilot characters requires controlled human acceptance. Browser hover/press tests and simulated DOM movement cannot establish that result. Real 0.8B inference, Core delegation, approval rejection, sleep/wake and GPU/battery qualification are outside this visual repair's measured results and remain NOT_RUN unless separately recorded in the acceptance report.

A retained-native-event drag attempt was tested and failed to move the window (drag count zero; bubble opened). Its before/after diagnostics are retained as `native-before-drag.json` and `native-after-drag-1.json`. The final implementation therefore uses event-local coordinates converted by AppKit rather than the global pointer location. Settings-to-chat sizing similarly uses intrinsic message heights rather than the current flex container height, so a large settings panel can shrink back to a compact chat.

Restart qualification also found that AppKit's initial WebView frame could replace the saved position during setup. The final adapter keeps startup moves out of persistence, waits for the character page to signal readiness, then shows and restores the native window on the main thread. The failing restart snapshots remain beside the passing result. Right-click is handled once by AppKit; the WebView suppresses its context menu without toggling the bubble a second time.
