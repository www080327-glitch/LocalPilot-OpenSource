import AppKit

private final class InferenceGlassPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

/// A native popover, anchored to the menu bar. Dismissal never means refusal.
/// AppKit supplies the current macOS glass material and accessibility settings.
final class InferenceControlWindow: NSObject, NSPopoverDelegate, NSWindowDelegate {
    var onPresented: ((String) -> Void)?
    var onStart: ((String, Bool) -> Void)?
    var onStop: ((String) -> Void)?
    var onCloud: (() -> Void)?
    weak var anchor: NSView?
    var control: JSONObject = [:]
    var seen = Set<String>()
    var presentedTickets = Set<String>()
    let popover = NSPopover()
    let titleText = NSTextField(labelWithString: "推理控制")
    let detail = NSTextField(wrappingLabelWithString: "")
    let output = NSTextField(wrappingLabelWithString: "")
    let stopButton = NSButton()
    let confirmButton = NSButton()
    let cloudButton = NSButton()
    var built = false
    var toast: NSPanel?
    let toastLabel = NSTextField(wrappingLabelWithString: "")
    let toastConfirm = NSButton()
    var outsideMonitor: Any?
    var localMonitor: Any?

    var active: Bool {
        ["prepared", "starting", "running", "stopping", "draining", "recovery_required", "stop_unconfirmed", "cleanup_required"].contains(control["phase"] as? String ?? "")
    }
    var ticket: String? { control["id"] as? String }

    func build() {
        let view = NSView(frame: NSRect(x: 0, y: 0, width: 390, height: 300))
        let controller = NSViewController(); controller.view = view
        popover.contentViewController = controller; popover.contentSize = view.frame.size
        popover.behavior = .applicationDefined; popover.animates = false; popover.delegate = self
        // Native popovers already use Liquid Glass on supported systems. Adding
        // another visual-effect layer would obscure the system material.
        titleText.frame = NSRect(x: 16, y: 260, width: 300, height: 25)
        let dismiss = NSButton(title: "收起", target: self, action: #selector(collapse))
        dismiss.frame = NSRect(x: 320, y: 259, width: 56, height: 27); view.addSubview(dismiss)
        titleText.font = .boldSystemFont(ofSize: 15); view.addSubview(titleText)
        detail.frame = NSRect(x: 16, y: 151, width: 358, height: 105)
        detail.font = .systemFont(ofSize: 11); view.addSubview(detail)
        output.frame = NSRect(x: 16, y: 75, width: 358, height: 72)
        output.font = .systemFont(ofSize: 11); view.addSubview(output)
        stopButton.frame = NSRect(x: 16, y: 14, width: 174, height: 28)
        stopButton.target = self; stopButton.action = #selector(stop); view.addSubview(stopButton)
        confirmButton.frame = NSRect(x: 200, y: 14, width: 174, height: 28)
        confirmButton.target = self; confirmButton.action = #selector(confirm); view.addSubview(confirmButton)
        cloudButton.frame = NSRect(x: 200, y: 45, width: 174, height: 25)
        cloudButton.title = "改用云端处理本次问题…"
        cloudButton.target = self; cloudButton.action = #selector(cloud); view.addSubview(cloudButton)
        built = true
    }

    func reveal() {
        guard let anchor = anchor else { return }
        if !built { build() }
        popover.show(relativeTo: anchor.bounds, of: anchor, preferredEdge: .minY)
        // Programmatic background presentation must survive app inactivity;
        // dismiss explicitly on outside clicks, without activating other apps.
        if outsideMonitor == nil {
            outsideMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in self?.collapse() }
            localMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] event in
                if let self = self, let frame = self.popover.contentViewController?.view.window?.frame, !frame.contains(NSEvent.mouseLocation) { self.collapse() }
                return event
            }
        }
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            if !self.popover.isShown { self.showToast() } else { self.acknowledgePresentation() }
        }
    }
    func showToast() {
        uiControlTrace("toast_build")
        if toast == nil {
            let frame = NSRect(x: 0, y: 0, width: 390, height: 230)
            let window = InferenceGlassPanel(contentRect: frame, styleMask: [.titled, .closable, .nonactivatingPanel, .fullSizeContentView], backing: .buffered, defer: false)
            window.title = "Companion"; window.titleVisibility = .hidden; window.titlebarAppearsTransparent = true
            window.level = .normal; window.hidesOnDeactivate = false; window.isReleasedWhenClosed = false
            window.isOpaque = false; window.backgroundColor = .clear; window.delegate = self
            let view = NSView(frame: frame)
            if #available(macOS 26.0, *) {
                let glass = NSGlassEffectView(frame: frame); glass.cornerRadius = 20; glass.contentView = view
                window.contentView = glass
            } else {
                let material = NSVisualEffectView(frame: frame); material.material = .popover; material.addSubview(view)
                window.contentView = material
            }
            toastLabel.frame = NSRect(x: 16, y: 57, width: 358, height: 136); toastLabel.font = .systemFont(ofSize: 12)
            view.addSubview(toastLabel)
            let stop = NSButton(title: "停止本次调用", target: self, action: #selector(stop))
            stop.frame = NSRect(x: 16, y: 15, width: 174, height: 28); view.addSubview(stop)
            toastConfirm.frame = NSRect(x: 200, y: 15, width: 174, height: 28)
            toastConfirm.target = self; toastConfirm.action = #selector(confirm); view.addSubview(toastConfirm)
            let dismiss = NSButton(title: "收起", target: self, action: #selector(collapse))
            dismiss.frame = NSRect(x: 320, y: 199, width: 55, height: 26); view.addSubview(dismiss)
            if let visible = NSScreen.main?.visibleFrame { window.setFrameOrigin(NSPoint(x: visible.maxX-frame.width-20, y: visible.minY+24)) }
            toast = window
        }
        updateToast(); toast?.orderFrontRegardless(); toast?.displayIfNeeded()
        if outsideMonitor == nil {
            outsideMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in self?.collapse() }
            localMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] event in
                if let self = self, let frame = self.toast?.frame, !frame.contains(NSEvent.mouseLocation) { self.collapse() }
                return event
            }
        }
        uiControlTrace("toast_visible " + String(toast?.isVisible == true))
        if toast?.isVisible == true { acknowledgePresentation() }
    }
    func updateToast() {
        toastLabel.stringValue = titleText.stringValue + "\n" + detail.stringValue + "\n" + output.stringValue.components(separatedBy: "\n")[0]
        toastConfirm.title = confirmButton.title; toastConfirm.isHidden = confirmButton.isHidden
        toastConfirm.isEnabled = confirmButton.isEnabled
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool { collapse(); return false }
    func toggle() { if popover.isShown || toast?.isVisible == true { collapse() } else { reveal() } }

    func show(_ value: JSONObject) {
        guard let id = value["id"] as? String else { return }
        control = value
        if !built { build() }
        let phase = value["phase"] as? String ?? "UNKNOWN"
        let local = value["kind"] as? String == "local"
        let agent = value["mode"] as? String == "execution"
        titleText.stringValue = agent ? "LocalPilot · 标准 Agent 协助" : local ? "LocalPilot · 极简理解" : "DeepSeek · 极简咨询"
        let resources = value["resources"] as? JSONObject ?? [:]
        let ac = resources["on_ac_power"] as? Bool
        let power = ac == true ? "已接电源" : ac == false ? "电池供电" : "电源状态未知"
        let available = (resources["memory_available_bytes"] as? Double ?? 0) / 1_073_741_824
        let required = value["required_confirmations"] as? [String] ?? []
        var reasons: [String] = []
        if required.contains("agent_help") { reasons.append("是否需要帮助？确认后才启用标准 Agent；工具审批另行进行。") }
        if value["fallback"] is JSONObject { reasons.append("本地未能解答，建议咨询 DeepSeek；只发送原问题，不重放操作。") }
        if required.contains("battery_or_unknown_power") { reasons.append("电池／未知供电：需要本次确认。") }
        if required.contains("memory_wall") { reasons.append("可用内存低于内存墙：需要本次确认。") }
        if required.contains("cloud_question_egress") { reasons.append("仅问题文字发往云端：需要本次确认。") }
        detail.stringValue = "\(value["model"] as? String ?? "模型待核验")\n\(power) · 可用内存 \(String(format: "%.1f", available)) GiB\n\(reasons.joined(separator: "\n"))\n点外部即可收起；从菜单栏可随时停止。"
        let labels = ["prepared":"等待确认" ,"starting":"正在提交／按需加载", "running":"正在推理",
                      "stopping":"正在停止并释放", "draining":"接收本轮回复后停止", "finished":"推理已结束",
                      "stopped":"已停止或未开始", "blocked":"本次未能开始", "recovery_required":"提交状态待恢复", "stop_unconfirmed":"停止尚未确认，可重试", "cleanup_required":"模型释放尚未确认，请点击停止重试"]
        let last = value["last_status"] as? JSONObject ?? [:]
        let resource = last["model_resource"] as? JSONObject ?? [:]
        let released = resource["managed"] as? Bool == true && resource["model_process_alive"] as? Bool == false
        output.stringValue = "\(labels[phase] ?? phase)\(released ? " · 模型已释放" : "")\n" + String((last["agent_response"] as? String ?? (last["error"] as? JSONObject)?["code"] as? String ?? last["reason"] as? String ?? "").prefix(180))
        stopButton.title = phase == "prepared" ? (agent && required.contains("agent_help") ? "暂不需要帮助" : "本次不调用") : active ? (local ? "停止并释放模型" : "接收本轮后停止") : "收起"
        confirmButton.title = agent ? (required.contains("agent_help") ? "需要帮助，开始任务" : "允许本次资源使用") : local ? "允许本次调用" : "同意本次云端咨询"
        confirmButton.isEnabled = phase == "prepared"
        confirmButton.isHidden = phase != "prepared" || required.isEmpty
        cloudButton.isHidden = !local || phase != "prepared" || value["mode"] as? String != "reasoning"
        if phase == "prepared" && !seen.contains(id) {
            seen.insert(id)
            // Automatic presentation uses a nonactivating native glass card.
            // A menu-bar popover is expanded only by an explicit menu action.
            showToast()
            if required.isEmpty {
                DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
                    guard self?.ticket == id else { return }; self?.collapse()
                }
            }
        }
        updateToast()
        // Updates never reopen a dismissed popover. The menu-bar stop item and
        // heartbeat remain available even while the popover is hidden.
    }
    @objc func collapse() {
        popover.performClose(nil); toast?.orderOut(nil)
        if let monitor = outsideMonitor { NSEvent.removeMonitor(monitor) }; outsideMonitor = nil
        if let monitor = localMonitor { NSEvent.removeMonitor(monitor) }; localMonitor = nil
    }
    func acknowledgePresentation() {
        guard control["phase"] as? String == "prepared", let id = ticket, !presentedTickets.contains(id) else { return }
        uiControlTrace("surface_ack_callback")
        presentedTickets.insert(id); onPresented?(id)
    }
    func popoverDidShow(_ notification: Notification) { acknowledgePresentation() }
    func popoverDidClose(_ notification: Notification) {
        if let monitor = outsideMonitor { NSEvent.removeMonitor(monitor) }; outsideMonitor = nil
        if let monitor = localMonitor { NSEvent.removeMonitor(monitor) }; localMonitor = nil
    }
    @objc func confirm() { if let id = ticket { confirmButton.isEnabled = false; onStart?(id, true) } }
    @objc func cloud() { collapse(); onCloud?() }
    @objc func stop() { if active, let id = ticket { onStop?(id) } else { collapse() } }
}

final class ResourceAlertWindow: NSObject {
    weak var anchor: NSView?
    let popover = NSPopover()
    var fallback: NSPanel?
    var seen = Set<String>()
    func show(_ alert: JSONObject) {
        let key = "\(alert["kind"] ?? ""):\(alert["at"] ?? "")"
        if seen.contains(key) { return }; seen.insert(key)
        guard let anchor = anchor else { return }
        let controller = NSViewController(); controller.view = NSView(frame: NSRect(x: 0, y: 0, width: 340, height: 110))
        let label = NSTextField(wrappingLabelWithString: alert["message"] as? String ?? "资源状态需要留意。")
        label.frame = NSRect(x: 16, y: 18, width: 308, height: 76); controller.view.addSubview(label)
        popover.contentViewController = controller; popover.behavior = .transient; popover.animates = false
        popover.show(relativeTo: anchor.bounds, of: anchor, preferredEdge: .minY)
        DispatchQueue.main.async { [weak self] in
            guard let self = self, !self.popover.isShown else { return }
            if self.fallback == nil {
                let frame = NSRect(x: 0, y: 0, width: 350, height: 140)
                let window = InferenceGlassPanel(contentRect: frame, styleMask: [.titled, .closable, .nonactivatingPanel, .fullSizeContentView], backing: .buffered, defer: false)
                window.title = "Companion · 系统资源提醒"; window.level = .normal
                window.titlebarAppearsTransparent = true; window.isOpaque = false; window.backgroundColor = .clear
                window.hidesOnDeactivate = false; window.isReleasedWhenClosed = false
                if #available(macOS 26.0, *) {
                    let glass = NSGlassEffectView(frame: frame); glass.cornerRadius = 18
                    glass.contentView = NSView(frame: frame); window.contentView = glass
                }
                if let visible = NSScreen.main?.visibleFrame { window.setFrameOrigin(NSPoint(x: visible.maxX-370, y: visible.minY+280)) }
                self.fallback = window
            }
            let label = NSTextField(wrappingLabelWithString: alert["message"] as? String ?? "资源状态需要留意。")
            label.frame = NSRect(x: 16, y: 18, width: 318, height: 88)
            let container: NSView?
            if #available(macOS 26.0, *), let glass = self.fallback?.contentView as? NSGlassEffectView { container = glass.contentView }
            else { container = self.fallback?.contentView }
            container?.subviews.forEach { $0.removeFromSuperview() }; container?.addSubview(label)
            self.fallback?.orderFrontRegardless()
        }
        DispatchQueue.main.asyncAfter(deadline: .now()+6) { [weak self] in self?.popover.performClose(nil); self?.fallback?.orderOut(nil) }
    }
}
