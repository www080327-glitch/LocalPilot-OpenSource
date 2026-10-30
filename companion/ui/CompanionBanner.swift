import AppKit

/// A transient app-owned panel; never calls activate or becomes a key window.
private final class PassiveCompanionPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

final class CompanionBanner: NSObject {
    private var panel: NSPanel?
    private var expiry: Timer?
    private var openAction: (() -> Void)?
    private var helpAction: (() -> Void)?
    private(set) var lastPresentation: JSONObject = [:]

    func show(_ text: String, help: (() -> Void)? = nil, open: @escaping () -> Void) -> Bool {
        dismiss()
        let foregroundBefore = NSWorkspace.shared.frontmostApplication?.processIdentifier ?? 0
        let frame = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1024, height: 768)
        let rect = NSRect(x: frame.maxX - 400, y: frame.maxY - 172, width: 380, height: 150)
        let window = PassiveCompanionPanel(contentRect: rect, styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: false)
        window.level = .normal
        window.hidesOnDeactivate = false
        window.isReleasedWhenClosed = false
        window.backgroundColor = .windowBackgroundColor
        window.hasShadow = true
        window.title = "Companion 提醒"
        let view = NSView(frame: NSRect(x: 0, y: 0, width: 380, height: 150))
        let title = NSTextField(labelWithString: help == nil ? "Companion · 有一条新反馈" : "Companion · 需要我帮忙吗？")
        title.font = .boldSystemFont(ofSize: 13)
        title.frame = NSRect(x: 14, y: 118, width: 330, height: 20)
        view.addSubview(title)
        let label = NSTextField(wrappingLabelWithString: String(text.prefix(300)))
        label.frame = NSRect(x: 14, y: 44, width: 352, height: 68)
        view.addSubview(label)
        let detail = NSButton(title: "查看", target: self, action: #selector(openDetails))
        detail.frame = NSRect(x: 265, y: 8, width: 95, height: 28)
        view.addSubview(detail)
        if help != nil {
            let button = NSButton(title: "需要帮助", target: self, action: #selector(acceptHelp))
            button.frame = NSRect(x: 14, y: 8, width: 120, height: 28); view.addSubview(button)
        }
        let close = NSButton(title: "收起", target: self, action: #selector(closeClicked))
        close.frame = NSRect(x: 170, y: 8, width: 90, height: 28)
        view.addSubview(close)
        if #available(macOS 26.0, *) {
            let glass = NSGlassEffectView(frame: view.frame); glass.cornerRadius = 18; glass.contentView = view
            window.isOpaque = false; window.backgroundColor = .clear; window.contentView = glass
        } else { window.contentView = view }
        panel = window
        openAction = open; helpAction = help
        window.orderFrontRegardless()
        lastPresentation = ["visible":window.isVisible, "key_window":window.isKeyWindow,
            "window_number":window.windowNumber, "pid":ProcessInfo.processInfo.processIdentifier,
            "foreground_before":foregroundBefore,
            "foreground_after":NSWorkspace.shared.frontmostApplication?.processIdentifier ?? 0,
            "activation_requested":false]
        expiry = Timer.scheduledTimer(withTimeInterval: 15, repeats: false) { [weak self] _ in self?.dismiss() }
        return window.isVisible
    }

    @objc private func acceptHelp() { let action = helpAction; dismiss(); action?() }
    @objc private func openDetails() { let action = openAction; dismiss(); action?() }
    @objc private func closeClicked() { dismiss() }
    func dismiss() {
        expiry?.invalidate(); expiry = nil
        panel?.orderOut(nil); panel = nil
        openAction = nil; helpAction = nil
    }
}
