import AppKit
import Foundation

private final class CompanionPanelView: NSView {
    override func draw(_ dirtyRect: NSRect) {
        NSColor.windowBackgroundColor.setFill()
        dirtyRect.fill()
    }
}

/// UI has no observer handles, file tools, shell tools, or LocalPilot transport.
/// Every action is a serialized Host command over CompanionClient.
final class MenuBarController: NSObject, NSApplicationDelegate {
    let client: CompanionClient
    let banner = CompanionBanner()
    let inferenceWindow = InferenceControlWindow()
    let resourceWindow = ResourceAlertWindow()
    lazy var systemNotifications = SystemNotifications()
    let batteryAutomation = NSButton(checkboxWithTitle: "未接电源时允许自动调用本地模型", target: nil, action: nil)
    let cloudAutomation = NSButton(checkboxWithTitle: "必要时允许自动调用 LocalPilot 云端 API", target: nil, action: nil)
    let resourceText = NSTextField(wrappingLabelWithString: "资源状态待采样")
    var controlPoll = false
    var inferenceMenuItem: NSMenuItem?
    var stopMenuItem: NSMenuItem?
    var presentedIDs: Set<String> = []
    let reminderInput = NSTextField()
    let reminderDate = NSDatePicker()
    let reminderOutput = NSTextView()
    var showOnLaunch = false
    var statusItem: NSStatusItem?
    var panel: NSPanel?
    var timer: Timer?
    var pollingInterval: TimeInterval = 0
    var snapshot: JSONObject = [:]
    var busy = false
    var pausePending = false
    var lastRefresh = Date.distantPast
    var pollCount = 0
    var connectionText = "连接服务中…"
    let statusLabel = NSTextField(wrappingLabelWithString: "连接服务中…")
    let activityLabel = NSTextField(labelWithString: "观察随时可暂停，委派任务提交前会请你确认。")
    let chatOutput = NSTextView()
    let chatInput = NSTextField()
    let taskInput = NSTextField()
    let cloudGrant = NSButton(checkboxWithTitle: "允许本次问题交给云端（不携带本地观察和记忆）", target: nil, action: nil)
    let memoryOutput = NSTextView()
    let memoryInput = NSTextField()
    let noticeOutput = NSTextView()
    let privacyOutput = NSTextView()
    let taskOutput = NSTextView()
    let noticePicker = NSPopUpButton()
    let taskPicker = NSPopUpButton()
    let exclusionInput = NSTextField()
    let pauseButton = NSButton()
    let dndButton = NSButton()
    let levelPicker = NSPopUpButton()
    let deliveryPicker = NSPopUpButton()
    let tabs = NSTabView()
    var pageButtons: [NSButton] = []

    init(client: CompanionClient) {
        self.client = client
        self.presentedIDs = client.presentedIDs()
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        uiControlTrace("app_did_finish")
        buildPanel()
        inferenceWindow.onPresented = { [weak self] id in self?.acknowledgeControl(id) }
        inferenceWindow.onStart = { [weak self] id, confirmed in self?.startInference(id, confirmed: confirmed) }
        inferenceWindow.onStop = { [weak self] id in self?.stopInference(id) }
        inferenceWindow.onCloud = { [weak self] in
            self?.request(["command":"prepare_cloud"]) { _ in }
        }
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem?.button?.image = NSImage(systemSymbolName: "brain", accessibilityDescription: "Companion")
        statusItem?.button?.image?.isTemplate = true
        statusItem?.button?.toolTip = "Companion"
        systemNotifications.onStop = { [weak self] id in self?.stopInference(id) }
        systemNotifications.onOpen = { [weak self] in self?.inferenceWindow.reveal() }
        let menu = NSMenu(); menu.autoenablesItems = false
        let items: [(String, Selector?)] = [("打开 Companion", #selector(togglePanel)),
            ("暂停 / 恢复观察", #selector(togglePause)), ("勿扰开关", #selector(toggleDND)),
            ("刷新状态", #selector(refreshClicked)), ("退出界面", #selector(quitUI))]
        for (title, action) in items {
            let item = NSMenuItem(title: title, action: action, keyEquivalent: "")
            item.target = self
            menu.addItem(item)
        }
        let inferenceItem = NSMenuItem(title: "当前推理…", action: #selector(showInferenceControl), keyEquivalent: "")
        inferenceItem.target = self; inferenceMenuItem = inferenceItem
        let stopItem = NSMenuItem(title: "停止当前推理", action: #selector(stopCurrentInference), keyEquivalent: "")
        stopItem.target = self; stopItem.isEnabled = false; stopMenuItem = stopItem
        menu.insertItem(stopItem, at: 0); menu.insertItem(inferenceItem, at: 0)
        statusItem?.menu = menu
        inferenceWindow.anchor = statusItem?.button
        resourceWindow.anchor = statusItem?.button
        refresh()
        if showOnLaunch { togglePanel() }
        schedulePolling()
    }
    func schedulePolling() {
        let interval: TimeInterval = inferenceWindow.active ? (inferenceWindow.control["phase"] as? String == "prepared" ? 5 : 2) : (panel?.isVisible == true ? 30 : 60)
        if timer?.isValid == true && interval == pollingInterval { return }
        timer?.invalidate(); pollingInterval = interval
        timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            if !self.client.runtimeMatches() { NSApp.terminate(nil); return }
            if self.inferenceWindow.active, let id = self.inferenceWindow.ticket {
                self.client.command(["command":"inference_heartbeat", "ticket_id":id]) { _ in }
                if !self.controlPoll {
                    self.controlPoll = true
                    self.client.command(["command":"ui_snapshot"]) { result in
                        DispatchQueue.main.async { self.controlPoll = false; self.applySnapshot(result) }
                    }
                }
            } else if Date().timeIntervalSince(self.lastRefresh) >= (self.panel?.isVisible == true ? 30 : 60) { self.refresh() }
        }
    }

    func buildPanel() {
        let view = CompanionPanelView(frame: NSRect(x: 0, y: 0, width: 760, height: 640))
        let window = NSPanel(contentRect: view.frame, styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "AI Companion"
        window.isReleasedWhenClosed = false
        window.hidesOnDeactivate = false
        window.level = .normal
        window.contentView = view
        statusLabel.frame = NSRect(x: 20, y: 568, width: 720, height: 54)
        statusLabel.font = .systemFont(ofSize: 13)
        view.addSubview(statusLabel)
        tabs.frame = NSRect(x: 16, y: 62, width: 728, height: 450)
        tabs.tabViewType = .noTabsNoBorder
        view.addSubview(tabs)
        for (index, title) in ["聊天", "最近记忆", "主动建议", "隐私", "委派任务", "提醒待办", "资源"].enumerated() {
            let pageButton = NSButton(title: title, target: self, action: #selector(selectPage(_:)))
            pageButton.setButtonType(.pushOnPushOff)
            pageButton.tag = index
            pageButton.state = index == 0 ? .on : .off
            pageButton.frame = NSRect(x: 20 + index * 103, y: 526, width: 96, height: 28)
            pageButtons.append(pageButton); view.addSubview(pageButton)
        }
        let chat = page("聊天")
        scroll(chatOutput, in: chat, rect: NSRect(x: 12, y: 114, width: 680, height: 306))
        button("看看最近观察", #selector(showContext), in: chat, rect: NSRect(x: 12, y: 78, width: 160, height: 28))
        button("整理窗口要点", #selector(reviewContext), in: chat, rect: NSRect(x: 186, y: 78, width: 160, height: 28))
        chatOutput.string = "你好，我会根据你授权的观察与记忆提供帮助。信息不足时会明确说明；复杂任务可以交给 LocalPilot 处理。"
        chatInput.frame = NSRect(x: 12, y: 36, width: 570, height: 30)
        chatInput.placeholderString = "聊一聊，或描述需要协助的事"
        chatInput.target = self; chatInput.action = #selector(sendChat)
        chat.addSubview(chatInput)
        button("发送", #selector(sendChat), in: chat, rect: NSRect(x: 594, y: 36, width: 98, height: 30))
        let memory = page("最近记忆")
        scroll(memoryOutput, in: memory, rect: NSRect(x: 12, y: 98, width: 680, height: 322))
        memoryInput.frame = NSRect(x: 12, y: 58, width: 548, height: 30)
        memoryInput.placeholderString = "明确希望我记住的偏好，例如：建议先给结论"
        memory.addSubview(memoryInput)
        button("记住偏好", #selector(savePreference), in: memory, rect: NSRect(x: 572, y: 58, width: 120, height: 30))
        button("刷新记忆", #selector(refreshClicked), in: memory, rect: NSRect(x: 12, y: 16, width: 120, height: 30))
        let memoryHint = NSTextField(labelWithString: "显示当前授权范围内的来源与证据类型。提问和模型推断不视为已确认事实。")
        memoryHint.frame = NSRect(x: 140, y: 22, width: 545, height: 22); memoryHint.font = .systemFont(ofSize: 11); memory.addSubview(memoryHint)
        let notices = page("主动建议")
        noticePicker.frame = NSRect(x: 12, y: 392, width: 680, height: 28)
        noticePicker.target = self; noticePicker.action = #selector(selectNotice); notices.addSubview(noticePicker)
        scroll(noticeOutput, in: notices, rect: NSRect(x: 12, y: 112, width: 680, height: 264))
        button("有帮助", #selector(useful), in: notices, rect: NSRect(x: 12, y: 70, width: 100, height: 30))
        button("没帮助", #selector(notUseful), in: notices, rect: NSRect(x: 120, y: 70, width: 100, height: 30))
        button("不再提醒类似事情", #selector(muteNotice), in: notices, rect: NSRect(x: 228, y: 70, width: 172, height: 30))
        button("需要帮助…", #selector(acceptNoticeHelp), in: notices, rect: NSRect(x: 418, y: 70, width: 140, height: 30))
        levelPicker.frame = NSRect(x: 12, y: 20, width: 150, height: 28)
        for (title, value) in [("主动程度：关闭", "off"), ("主动程度：低", "low"), ("主动程度：正常", "normal")] {
            levelPicker.addItem(withTitle: title); levelPicker.lastItem?.representedObject = value
        }
        notices.addSubview(levelPicker)
        deliveryPicker.frame = NSRect(x: 174, y: 20, width: 150, height: 28)
        for (title, value) in [("静默评估", "silent"), ("允许提醒", "enabled")] {
            deliveryPicker.addItem(withTitle: title); deliveryPicker.lastItem?.representedObject = value
        }
        notices.addSubview(deliveryPicker)
        button("应用设置", #selector(setProactive), in: notices, rect: NSRect(x: 338, y: 20, width: 115, height: 28))
        button("检查反馈链路", #selector(checkFeedback), in: notices, rect: NSRect(x: 468, y: 20, width: 180, height: 28))
        let privacy = page("隐私")
        scroll(privacyOutput, in: privacy, rect: NSRect(x: 12, y: 142, width: 680, height: 278))
        pauseButton.title = "暂停观察"; pauseButton.target = self; pauseButton.action = #selector(togglePause)
        pauseButton.frame = NSRect(x: 12, y: 98, width: 130, height: 30); privacy.addSubview(pauseButton)
        button("查看范围并授权", #selector(authorize), in: privacy, rect: NSRect(x: 154, y: 98, width: 160, height: 30))
        dndButton.title = "开启勿扰"; dndButton.target = self; dndButton.action = #selector(toggleDND)
        dndButton.frame = NSRect(x: 326, y: 98, width: 130, height: 30); privacy.addSubview(dndButton)
        let excludeLabel = NSTextField(labelWithString: "排除应用（bundle ID，逗号分隔）：")
        excludeLabel.frame = NSRect(x: 12, y: 62, width: 680, height: 22); privacy.addSubview(excludeLabel)
        exclusionInput.frame = NSRect(x: 12, y: 20, width: 548, height: 30)
        exclusionInput.placeholderString = "例如 com.apple.Safari, com.microsoft.VSCode"
        privacy.addSubview(exclusionInput)
        button("保存排除", #selector(setExclusions), in: privacy, rect: NSRect(x: 572, y: 20, width: 120, height: 30))
        let tasks = page("委派任务")
        taskPicker.frame = NSRect(x: 12, y: 392, width: 680, height: 28)
        taskPicker.target = self; taskPicker.action = #selector(selectTask); tasks.addSubview(taskPicker)
        scroll(taskOutput, in: tasks, rect: NSRect(x: 12, y: 134, width: 680, height: 244))
        taskInput.frame = NSRect(x: 12, y: 96, width: 680, height: 28)
        taskInput.placeholderString = "描述要委派的任务；准备后会显示待核对的上下文"
        tasks.addSubview(taskInput)
        button("准备任务", #selector(prepareTask), in: tasks, rect: NSRect(x: 12, y: 56, width: 190, height: 30))
        button("核对并提交", #selector(submitTask), in: tasks, rect: NSRect(x: 214, y: 56, width: 128, height: 30))
        button("查询任务", #selector(checkTask), in: tasks, rect: NSRect(x: 354, y: 56, width: 100, height: 30))
        button("取消任务", #selector(cancelTask), in: tasks, rect: NSRect(x: 466, y: 56, width: 100, height: 30))
        button("检测连接", #selector(checkConnection), in: tasks, rect: NSRect(x: 578, y: 56, width: 114, height: 30))
        cloudGrant.frame = NSRect(x: 12, y: 30, width: 680, height: 22)
        tasks.addSubview(cloudGrant)
        let taskHint = NSTextField(wrappingLabelWithString: "提交不代表完成。工具审批与恢复在 LocalPilot 中完成；此界面不会自动批准工具或云端外传。")
        taskHint.font = .systemFont(ofSize: 11); taskHint.frame = NSRect(x: 12, y: 4, width: 680, height: 24); tasks.addSubview(taskHint)
        let reminders = page("提醒待办")
        scroll(reminderOutput, in: reminders, rect: NSRect(x: 12, y: 138, width: 680, height: 282))
        reminderInput.frame = NSRect(x: 12, y: 96, width: 680, height: 30)
        reminderInput.placeholderString = "明确告诉我需要提醒的事项"
        reminders.addSubview(reminderInput)
        reminderDate.datePickerStyle = .textFieldAndStepper
        reminderDate.datePickerElements = [.yearMonthDay, .hourMinute]
        reminderDate.dateValue = Date().addingTimeInterval(3600)
        reminderDate.frame = NSRect(x: 12, y: 52, width: 300, height: 30)
        reminders.addSubview(reminderDate)
        button("保存提醒", #selector(saveReminder), in: reminders, rect: NSRect(x: 326, y: 52, width: 130, height: 30))
        let reminderHint = NSTextField(labelWithString: "仅保存你明确设置的事项；提醒遵守勿扰、夜间与每日限额。")
        reminderHint.frame = NSRect(x: 12, y: 14, width: 680, height: 24)
        reminders.addSubview(reminderHint)
        let resources = page("资源")
        batteryAutomation.frame = NSRect(x: 12, y: 380, width: 680, height: 28)
        cloudAutomation.frame = NSRect(x: 12, y: 336, width: 680, height: 28)
        for toggle in [batteryAutomation, cloudAutomation] {
            toggle.target = self; toggle.action = #selector(setInferenceOptions); resources.addSubview(toggle)
        }
        let hint = NSTextField(wrappingLabelWithString: "两项默认关闭。接电源且内存充足时，本地调用可自动开始；电池供电、内存不足或云端调用会先请求确认。每次调用都显示停止控制，任务结束后释放本地大模型。云端停止会接收已经发出的本轮回复。")
        hint.frame = NSRect(x: 12, y: 222, width: 680, height: 100); resources.addSubview(hint)
        button("允许系统通知…", #selector(enableSystemNotifications), in: resources, rect: NSRect(x: 12, y: 10, width: 180, height: 28))
        resourceText.frame = NSRect(x: 12, y: 44, width: 680, height: 166)
        resources.addSubview(resourceText)
        activityLabel.frame = NSRect(x: 20, y: 28, width: 620, height: 22)
        activityLabel.font = .systemFont(ofSize: 11); view.addSubview(activityLabel)
        button("刷新", #selector(refreshClicked), in: view, rect: NSRect(x: 646, y: 22, width: 92, height: 30))
        panel = window
        // Construction deliberately does not order a window, activate the app,
        // move the pointer, read AX, or alter any other application's state.
    }

    private func page(_ title: String) -> NSView {
        let item = NSTabViewItem(identifier: title)
        item.label = title
        let view = NSView(frame: NSRect(x: 0, y: 0, width: 704, height: 440))
        item.view = view; tabs.addTabViewItem(item); return view
    }
    private func scroll(_ text: NSTextView, in view: NSView, rect: NSRect) {
        let scroll = NSScrollView(frame: rect)
        scroll.hasVerticalScroller = true; scroll.borderType = .bezelBorder
        text.isEditable = false; text.isSelectable = true
        text.font = .systemFont(ofSize: 13)
        text.textContainerInset = NSSize(width: 9, height: 9)
        text.isVerticallyResizable = true
        text.isHorizontallyResizable = false
        text.autoresizingMask = [.width]
        text.textContainer?.widthTracksTextView = true
        scroll.documentView = text; view.addSubview(scroll)
    }
    private func button(_ title: String, _ action: Selector, in view: NSView, rect: NSRect) {
        let button = NSButton(title: title, target: self, action: action)
        button.frame = rect; view.addSubview(button)
    }

    @objc func togglePanel() {
        if panel?.isVisible == true { panel?.orderOut(nil); schedulePolling(); return }
        panel?.center(); panel?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        schedulePolling(); refresh()
    }
    @objc func selectPage(_ sender: NSButton) {
        guard tabs.tabViewItems.indices.contains(sender.tag) else { return }
        tabs.selectTabViewItem(at: sender.tag)
        for button in pageButtons { button.state = button.tag == sender.tag ? .on : .off }
    }

    func request(_ body: JSONObject, done: @escaping (JSONObject) -> Void) {
        guard !busy else { activityLabel.stringValue = "正在处理上一条请求，请稍候。"; return }
        busy = true; activityLabel.stringValue = "正在处理…"
        client.command(body) { [weak self] result in
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.busy = false
                let state = CompanionPresentation.value(result, "status", fallback: "ok")
                self.activityLabel.stringValue = ["error", "forbidden", "unavailable"].contains(state)
                    ? (result["text"] as? String ?? CompanionPresentation.readableState(state)) : "已更新 · 观察随时可暂停，任务提交前会请你确认。"
                self.showInference(result)
                done(result)
            }
        }
    }
    func refresh() {
        guard !busy else { return }
        lastRefresh = Date(); pollCount += 1
        request(["command": "ui_snapshot"]) { [weak self] value in self?.applySnapshot(value) }
    }
    @objc func refreshClicked() { refresh() }

    @objc func showContext() {
        request(["command":"current_context"]) { [weak self] result in
            self?.chatOutput.string += "\n\nCompanion：\n" + (result["text"] as? String ?? "无法取得近期观察")
            self?.chatOutput.scrollToEndOfDocument(nil)
        }
    }
    @objc func reviewContext() {
        activityLabel.stringValue = "正在整理已读到的窗口文字…"
        request(["command":"review_context"]) { [weak self] result in
            self?.chatOutput.string += "\n\nCompanion：\n" + (result["text"] as? String ?? "无法整理当前内容")
            if let sources = result["observation_sources"] as? [JSONObject], !sources.isEmpty {
                self?.chatOutput.string += "\n\n本次读取来源：\n" + sources.map(CompanionPresentation.memoryText).joined(separator: "\n\n")
            }
            self?.chatOutput.scrollToEndOfDocument(nil)
        }
    }
    @objc func savePreference() {
        let text = memoryInput.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        request(["command":"remember", "type":"preference", "text":text]) { [weak self] result in
            if result["status"] as? String == "ok" { self?.memoryInput.stringValue = ""; self?.refresh() }
        }
    }

    func applySnapshot(_ value: JSONObject) {
        guard value["status"] as? String == "ok", let runtime = value["runtime"] as? JSONObject else {
            statusLabel.stringValue = "Companion 服务不可用。\n请先启动服务，再重新打开界面。"; return
        }
        snapshot = value
        showInference(value)
        let options = value["inference_options"] as? JSONObject ?? [:]
        batteryAutomation.state = options["allow_local_on_battery"] as? Bool == true ? .on : .off
        cloudAutomation.state = options["allow_automatic_cloud"] as? Bool == true ? .on : .off
        let telemetry = value["system_resources"] as? JSONObject ?? [:]
        let availableGiB = (telemetry["memory_available_bytes"] as? Double ?? 0) / 1_073_741_824
        let watts = (telemetry["battery_discharge_watts"] as? Double).map { String(format: "%.1f W（电池硬件采样）", $0) } ?? "不可用（接电源时不估算整机功耗）"
        resourceText.stringValue = "可用内存：\(String(format: "%.1f", availableGiB)) GiB\nCPU 负载：\(telemetry["system_cpu_percent"] ?? "未知")%\n电池放电功率：\(watts)\n持续内存紧张、高放电功率或高 CPU 负载会弹窗提醒。"
        for alert in value["resource_alerts"] as? [JSONObject] ?? [] { systemNotifications.resource(alert); resourceWindow.show(alert) }
        let privacy = value["privacy"] as? JSONObject ?? [:]
        let model = runtime["model"] as? JSONObject ?? [:]
        let routing = runtime["model_routing"] as? JSONObject ?? [:]
        let secondary = routing["secondary"] as? JSONObject
        let native = runtime["native_observer"] as? JSONObject ?? [:]
        let nativePending = privacy["native_consent"] as? String == "MANUAL_REQUIRED"
        let observation = nativePending && privacy["status"] as? String != "paused"
            ? "待授权（隐私页开启）"
            : CompanionPresentation.readableState(CompanionPresentation.value(privacy, "status"))
        let loaded = model["loaded"] as? Bool ?? false
        let power = runtime["low_power"] as? JSONObject ?? [:]
        let powerState = power["active"] as? Bool == true ? "低功耗" : "正常模式"
        let source = (runtime["service_connection"] as? JSONObject)?["route_decision"] as? JSONObject ?? [:]
        let modelSource = source["backend_model"] as? String ?? "尚无服务推理"
        let modelState = "\(powerState) · 轻模型\(loaded ? "已加载" : "空闲") · 服务模型：\(modelSource)"
        let metrics = native["metrics"] as? JSONObject ?? [:]
        let reads = metrics["read_count"] as? Int ?? 0
        let recent = metrics["recent_read_ms"] as? [JSONObject] ?? []
        let nativeState = recent.last?["read_status"] as? String ?? (reads == 0 ? "尚无窗口内容（权限：\(CompanionPresentation.value(native, "ax_permission")))" : "PARTIAL/UNKNOWN")
        connectionText = CompanionPresentation.readableState(CompanionPresentation.value(runtime, "localpilot"))
        let readLabel = ["READ_PARTIAL":"部分读取", "UNKNOWN":"读取状态未知", "READ_FAILED":"读取失败", "READ_SUCCESS_NONEMPTY":"已读取", "READ_SUCCESS_EMPTY":"无可读内容"][nativeState] ?? nativeState
        statusLabel.stringValue = "观察：\(observation) · 窗口：\(readLabel)\n\(modelState) · LocalPilot：\(connectionText)"
        let paused = privacy["status"] as? String == "paused" || privacy["paused"] as? Bool == true
        pauseButton.title = paused ? "恢复观察" : "暂停观察"
        dndButton.title = runtime["dnd"] as? Bool == true ? "关闭勿扰" : "开启勿扰"
        privacyOutput.string = scopeText(privacy["scope"] as? JSONObject ?? privacy) + "\n\n观察与内容读取需要单独授权。Companion 只读；操作系统级沙盒尚未实现。"
        let scope = privacy["scope"] as? JSONObject ?? privacy
        // Preserve in-progress user edits while refreshing.
        if exclusionInput.currentEditor() == nil {
            exclusionInput.stringValue = (scope["excluded_apps"] as? [String] ?? []).joined(separator: ", ")
        }
        let memories = value["memories"] as? [JSONObject] ?? []
        let cards = value["context_cards"] as? [JSONObject] ?? []
        memoryOutput.string = "你明确保存的记忆\n" + (memories.isEmpty ? "还没有保存的事实或偏好。你可以在下方明确告诉我。" : memories.map(CompanionPresentation.memoryText).joined(separator: "\n\n"))
        memoryOutput.string += "\n\n────────\n近期窗口观察\n" + (cards.isEmpty ? "正在等待可读取的普通窗口。" : cards.map(CompanionPresentation.contextText).joined(separator: "\n\n────────\n\n"))
        let actionable = (value["notices"] as? [JSONObject] ?? []).filter { $0["status"] as? String == "pending" }.count
        statusItem?.button?.title = actionable > 0 ? "● Companion \(actionable)" : "◌ Companion"
        statusItem?.button?.toolTip = cards.first.map { "最近看到：\(CompanionPresentation.value($0, "app")) · \(CompanionPresentation.value($0, "time"))" } ?? "等待获准窗口"
        let selectedNotice = noticePicker.selectedItem?.representedObject as? String
        noticePicker.removeAllItems()
        for notice in value["notices"] as? [JSONObject] ?? [] {
            guard let id = notice["id"] as? String else { continue }
            noticePicker.addItem(withTitle: String((notice["message"] as? String ?? "建议").prefix(55)))
            noticePicker.lastItem?.representedObject = id
        }
        select(noticePicker, value: selectedNotice); selectNotice()
        presentNewNotices(value, runtime: runtime)
        let health = value["feedback_health"] as? JSONObject ?? [:]
        let blockers = health["blockers"] as? [String] ?? []
        activityLabel.stringValue = cards.first.map { "最近看到 \(CompanionPresentation.value($0, "app")) · \(CompanionPresentation.value($0, "time"))" } ?? "等待获准窗口"
        if let quiet = blockers.first(where: { $0.contains("静音") || $0.contains("静默") || $0.contains("暂停") }) { activityLabel.stringValue += " · " + quiet }
        reminderOutput.string = (value["reminders"] as? [JSONObject] ?? []).map {
            let due = Date(timeIntervalSince1970: $0["due_at"] as? Double ?? 0)
            return "\($0["text"] as? String ?? "事项")\n到期：\(due.formatted()) · \(($0["delivered"] as? Bool == true) ? "已提醒" : "待提醒")"
        }.joined(separator: "\n\n")
        if reminderOutput.string.isEmpty { reminderOutput.string = "还没有明确设置的提醒。" }
        let proactive = value["proactive"] as? JSONObject ?? [:]
        select(levelPicker, value: proactive["level"] as? String)
        select(deliveryPicker, value: proactive["delivery"] as? String)
        let escalation = value["escalation"] as? JSONObject ?? [:]
        let selectedTask = taskPicker.selectedItem?.representedObject as? String
        taskPicker.removeAllItems()
        for (id, row) in (escalation["tasks"] as? [String: JSONObject] ?? [:]).sorted(by: { $0.key < $1.key }) {
            taskPicker.addItem(withTitle: "\(String(id.prefix(14))) · \(CompanionPresentation.taskText(row).components(separatedBy: "\n")[0])")
            taskPicker.lastItem?.representedObject = id
        }
        select(taskPicker, value: selectedTask)
        if let pending = escalation["pending"] as? JSONObject { taskOutput.string = escalationText(pending) }
        else { selectTask() }
    }

    private func select(_ picker: NSPopUpButton, value: String?) {
        guard let value = value else { return }
        if let item = picker.itemArray.first(where: { $0.representedObject as? String == value }) { picker.select(item) }
    }
    private func scopeText(_ scope: JSONObject) -> String {
        func list(_ key: String) -> String { (scope[key] as? [String] ?? []).joined(separator: "\n  ") }
        let enabled = scope["all_apps"] as? Bool == true ? "所有普通应用（仍排除密码库、私密输入与排除项）" : scope["native_enabled"] as? Bool == true ? "已配置" : "未启用"
        let ax = scope["ax_enabled"] as? Bool == true ? "已配置可访问结构读取" : "未启用"
        let windows = scope["content_windows"] as? [String] ?? []
        let windowScope = windows.isEmpty ? "未设置精确标题；以 Host 应用与窗口范围检查为准" : windows.joined(separator: "\n  ")
        let apps = scope["all_apps"] as? Bool == true ? "所有普通应用；密码库与自身界面跳过" : list("allowed_apps")
        let content = scope["all_content"] as? Bool == true ? "所有普通应用的可访问静态文字；私密输入仍剪枝" : list("content_apps")
        return "原生观察：\(enabled) · AX：\(ax)\n文件目录：\n  \(list("files"))\n\n排除目录：\n  \(list("excluded_directories"))\n\n授权应用：\n  \(apps)\n\n允许内容读取：\n  \(content)\n\n允许内容读取的窗口：\n  \(windowScope)\n\n排除应用：\n  \(list("excluded_apps"))\n\n排除窗口：\n  \(list("excluded_windows"))\n\n处理位置：本地\(scope["controlled_target"] is JSONObject ? " · 仅固定的自有受控测试应用" : "")"
    }
    private func escalationText(_ pending: JSONObject) -> String {
        let rows = pending["relevant_memories"] as? [JSONObject] ?? []
        let events = pending["recent_events"] as? [JSONObject] ?? []
        let files = pending["relevant_files"] as? [String] ?? []
        return "准备的任务（尚未提交）：\n\(CompanionPresentation.value(pending, "user_request"))\n\n会携带以下已过滤上下文，请逐项核对：\n\(rows.map(CompanionPresentation.memoryText).joined(separator: "\n\n"))\n\n近期事件：\n\(events.map(CompanionPresentation.memoryText).joined(separator: "\n\n"))\n\n文件引用：\n\(files.joined(separator: "\n"))"
    }
    private func notice() -> JSONObject? {
        let id = noticePicker.selectedItem?.representedObject as? String
        return (snapshot["notices"] as? [JSONObject] ?? []).first { $0["id"] as? String == id }
    }
    @objc func selectNotice() {
        guard let row = notice() else { noticeOutput.string = "暂无主动建议。静默评估不会发送通知。真人帮助价值仍待反馈验证。"; return }
        noticeOutput.string = "\(CompanionPresentation.value(row, "message"))\n\n状态：\(CompanionPresentation.value(row, "status"))"
        if let explain = row["explanation"] as? JSONObject {
            noticeOutput.string += "\n\n证据说明：\(CompanionPresentation.value(explain, "reason", fallback: CompanionPresentation.value(explain, "evidence")))"
        }
    }
    @objc func selectTask() {
        let id = taskPicker.selectedItem?.representedObject as? String ?? ""
        let escalation = snapshot["escalation"] as? JSONObject ?? [:]
        let row = (escalation["tasks"] as? [String: JSONObject] ?? [:])[id]
        taskOutput.string = row.map { "任务 \(id)\n\(CompanionPresentation.taskText($0))" }
            ?? "在任务输入框描述任务，然后点击“准备任务”。准备后核对上下文，再确认提交。"
    }
    @objc func sendChat() {
        let text = chatInput.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !busy else { return }
        chatOutput.string += "\n\n你：\(text)"; chatInput.stringValue = ""
        request(["command": "ask", "text": text]) { [weak self] result in
            guard let self = self else { return }
            let response = result["text"] as? String ?? result["reason"] as? String ?? result["error"] as? String ?? CompanionPresentation.readableState(CompanionPresentation.value(result, "status"))
            self.chatOutput.string += "\nCompanion：\(response)"
            if let memories = result["memories"] as? [JSONObject], !memories.isEmpty {
                self.chatOutput.string += "\n\n引用：\n" + memories.map(CompanionPresentation.memoryText).joined(separator: "\n\n")
            }
            if self.chatOutput.string.count > 24000 { self.chatOutput.string = String(self.chatOutput.string.suffix(24000)) }
            self.chatOutput.scrollToEndOfDocument(nil)
        }
    }
    private func feedback(_ action: String) {
        guard let row = notice(), let id = row["id"] as? String else { return }
        guard ["pending", "ignored"].contains(row["status"] as? String ?? "") else {
            activityLabel.stringValue = "这条提醒已评价或已过期，请选择一条新的提醒。"; return
        }
        request(["command": "notice_action", "id": id, "action": action]) { [weak self] result in
            self?.noticeOutput.string += "\n\n" + (result["text"] as? String ?? "反馈已提交。")
            self?.refresh()
        }
    }
    @objc func acceptNoticeHelp() { feedback("help") }
    @objc func useful() { feedback("useful") }
    @objc func notUseful() { feedback("not_needed") }
    @objc func muteNotice() { feedback("mute") }
    @objc func setProactive() {
        request(["command": "proactive_settings", "level": levelPicker.selectedItem?.representedObject as? String ?? "low",
                 "delivery": deliveryPicker.selectedItem?.representedObject as? String ?? "silent"]) { [weak self] _ in self?.refresh() }
    }
    func showSuggestions(noticeID: String? = nil) {
        if panel?.isVisible != true { togglePanel() }
        tabs.selectTabViewItem(at: 2)
        if pageButtons.indices.contains(2) { selectPage(pageButtons[2]) }
        if let id = noticeID { select(noticePicker, value: id); selectNotice() }
    }
    func presentNewNotices(_ value: JSONObject, runtime: JSONObject) {
        let enabled = (value["proactive"] as? JSONObject)?["delivery"] as? String == "enabled"
        let rows = value["notices"] as? [JSONObject] ?? []
        let candidates = rows.filter { row in
            guard let id = row["id"] as? String, let time = row["timestamp"] as? Double else { return false }
            return row["status"] as? String == "pending" && row["delivery"] as? String == "popup_available"
                && !presentedIDs.contains(id) && Date().timeIntervalSince1970-time < 3600
        }
        if !inferenceWindow.active { statusItem?.button?.toolTip = enabled && !candidates.isEmpty ? "Companion · 有新建议" : "Companion" }
        guard enabled, runtime["dnd"] as? Bool != true, runtime["quiet_now"] as? Bool != true,
              let row = candidates.last, let id = row["id"] as? String else { return }
        let canHelp = ["repeated_error", "project_help", "document_revisions", "requested_help"].contains(row["type"] as? String ?? "")
        let help: (() -> Void)? = canHelp ? { [weak self] in
            self?.request(["command":"notice_action", "id":id, "action":"help"]) { _ in }
        } : nil
        if banner.show(row["message"] as? String ?? "有一条新建议", help:help, open: { [weak self] in self?.showSuggestions(noticeID:id) }) {
            client.saveBannerReceipt(banner.lastPresentation.merging(["notice_id":id,"kind":"proactive"]) { _,new in new })
            presentedIDs.insert(id); client.savePresentedIDs(presentedIDs)
            client.command(["command":"notice_presented", "id":id, "channel":"native_banner"]) { _ in }
        }
    }
    @objc func checkFeedback() {
        request(["command":"feedback_check"]) { [weak self] result in
            guard let self = self else { return }
            let text = result["text"] as? String ?? "未得到服务反馈"
            self.noticeOutput.string = text
            _ = self.banner.show(text, open: { [weak self] in self?.showSuggestions() })
            self.client.saveBannerReceipt(self.banner.lastPresentation.merging(["kind":"manual_feedback_check"]) { _,new in new })
        }
    }
    @objc func saveReminder() {
        let text = reminderInput.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { activityLabel.stringValue = "请填写要提醒的事项。"; return }
        request(["command":"set_reminder", "text":text, "due_at":reminderDate.dateValue.timeIntervalSince1970,
                 "confirmed":true]) { [weak self] result in
            if result["status"] as? String == "ok" { self?.reminderInput.stringValue = "" }
            self?.refresh()
        }
    }
    @objc func togglePause() {
        if busy {
            // Privacy pause must reach Host's immediate admission fence even
            // while an inference is pending. This exception can only pause;
            // resume and all other mutations remain serialized and Host-owned.
            guard !pausePending else { return }
            pausePending = true
            activityLabel.stringValue = "正在请求暂停观察，等待服务确认…"
            client.command(["command": "pause_observation", "paused": true]) { [weak self] result in
                DispatchQueue.main.async {
                    guard let self = self else { return }
                    self.pausePending = false
                    self.activityLabel.stringValue = result["status"] as? String == "paused"
                        ? "观察已暂停。" : "暂停请求尚未确认，请检查服务状态。"
                    self.refresh()
                }
            }
            return
        }
        request(["command": "privacy"]) { [weak self] privacy in
            guard let self = self else { return }
            let paused = privacy["status"] as? String == "paused" || privacy["paused"] as? Bool == true
            self.request(["command": "pause_observation", "paused": !paused]) { _ in self.refresh() }
        }
    }
    @objc func toggleDND() {
        request(["command": "status"]) { [weak self] status in
            guard let self = self else { return }
            self.request(["command": "dnd", "enabled": !(status["dnd"] as? Bool ?? false)]) { _ in self.refresh() }
        }
    }
    @objc func setExclusions() {
        let apps = exclusionInput.stringValue.components(separatedBy: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        request(["command": "set_app_exclusions", "apps": apps]) { [weak self] result in
            self?.privacyOutput.string = "\(result["text"] as? String ?? "排除设置已提交。更改范围后，请重新核对并授权观察。")"
            self?.refresh()
        }
    }
    @objc func authorize() {
        request(["command": "authorize_observation", "confirmed": false]) { [weak self] result in
            guard let self = self, let scope = result["scope"] as? JSONObject else { return }
            self.privacyOutput.string = self.scopeText(scope)
            let alert = NSAlert(); alert.messageText = "授权以上范围的只读观察？"
            alert.informativeText = self.scopeText(scope) + "\n\n敏感输入会被过滤。系统辅助功能权限仍需你手动授予；可随时暂停。"
            alert.addButton(withTitle: "确认授权"); alert.addButton(withTitle: "取消")
            if alert.runModal() == .alertFirstButtonReturn {
                self.request(["command": "authorize_observation", "confirmed": true,
                              "expected_consent_id": result["consent_id"] as? String ?? ""]) { _ in self.refresh() }
            }
        }
    }
    @objc func prepareTask() {
        let text = taskInput.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { taskOutput.string = "请先在任务输入框描述任务。"; return }
        request(["command": "escalate", "text": text]) { [weak self] result in
            self?.taskOutput.string = result["text"] as? String ?? "任务已准备；请核对上下文。"
            self?.refresh()
        }
    }
    @objc func submitTask() {
        request(["command": "escalation_status"]) { [weak self] result in
            guard let self = self, let pending = result["pending"] as? JSONObject,
                  let digest = result["review_digest"] as? String, !digest.isEmpty else {
                self?.taskOutput.string = "没有待核对的任务，请先准备任务。"; return
            }
            self.taskOutput.string = self.escalationText(pending)
            let cloud = self.cloudGrant.state == .on
            let retry = result["submission"] is JSONObject
            let alert = NSAlert(); alert.messageText = retry ? "使用原幂等键恢复这次提交？" : "提交当前核对的任务？"
            alert.informativeText = String(CompanionPresentation.value(pending, "user_request").prefix(600)) + "\n\n请核对面板中的来源与上下文。此确认仅允许提交；任务执行与工具审批仍由 LocalPilot 管理。" + (cloud ? "仅发送本次问题给云端，本地观察、文件和记忆将被省略。" : "未授权云端外传。")
            alert.addButton(withTitle: "确认提交"); alert.addButton(withTitle: "取消")
            if alert.runModal() == .alertFirstButtonReturn {
                self.request(["command": "submit_escalation", "approved": true, "cloud_approved": cloud, "expected_digest": digest, "retry": retry]) { result in
                    self.taskOutput.string = CompanionPresentation.taskText(result)
                    if let reason = result["reason"] as? String { self.taskOutput.string += "\n\(reason)" }
                    self.refresh()
                }
            }
        }
    }
    @objc func checkTask() {
        guard let id = taskPicker.selectedItem?.representedObject as? String else { return }
        request(["command": "task_status", "task_id": id, "cloud_approved": false]) { [weak self] result in
            self?.taskOutput.string = "任务 \(id)\n" + CompanionPresentation.taskText(result)
        }
    }
    @objc func cancelTask() {
        guard let id = taskPicker.selectedItem?.representedObject as? String else { return }
        let alert = NSAlert(); alert.messageText = "请求取消此任务？"
        alert.informativeText = "任务 \(id)。取消请求不保证撤销已经执行的操作；最终状态以 LocalPilot 为准。"
        alert.addButton(withTitle: "请求取消"); alert.addButton(withTitle: "返回")
        if alert.runModal() == .alertFirstButtonReturn {
            request(["command": "task_cancel", "task_id": id, "approved": true, "cloud_approved": false]) { [weak self] result in
                self?.taskOutput.string = CompanionPresentation.taskText(result)
            }
        }
    }
    @objc func checkConnection() {
        request(["command": "localpilot_health", "cloud_approved": false]) { [weak self] result in
            self?.connectionText = CompanionPresentation.readableState(CompanionPresentation.value(result, "status"))
            self?.taskOutput.string = "LocalPilot：\(self?.connectionText ?? "UNKNOWN")\n\(result["reason"] as? String ?? result["text"] as? String ?? "连接测试只代表当前接口可达性。")"
        }
    }
    func showInference(_ result: JSONObject) {
        uiControlTrace("show_inference " + (result["status"] as? String ?? "none"))
        if let control = result["control"] as? JSONObject ?? result["inference_control"] as? JSONObject {
            inferenceWindow.show(control)
            systemNotifications.inference(control)
            let active = inferenceWindow.active
            let local = control["kind"] as? String == "local"
            let waiting = control["phase"] as? String == "prepared" && !(control["required_confirmations"] as? [String] ?? []).isEmpty
            statusItem?.button?.toolTip = active ? (waiting ? "Companion · 等待确认" : local ? "Companion · 本地推理" : "Companion · 云端推理") : "Companion"
            statusItem?.button?.setAccessibilityLabel(statusItem?.button?.toolTip)
            inferenceMenuItem?.title = active ? (waiting ? "推理等待确认…" : "当前推理与结果…") : "最近推理结果…"
            stopMenuItem?.isEnabled = active
            stopMenuItem?.title = local ? "停止并释放本地模型" : "接收本轮后停止云端任务"
            schedulePolling()
        }
    }
    func acknowledgeControl(_ id: String, attempt: Int = 0) {
        client.command(["command":"inference_panel_presented", "ticket_id":id]) { [weak self] result in
            DispatchQueue.main.async {
                guard let self = self, self.inferenceWindow.ticket == id else { return }
                uiControlTrace("ack_status " + (result["status"] as? String ?? "none"))
                self.showInference(result)
                if result["status"] as? String == "ready_to_start" { self.startInference(id, confirmed: false) }
                else if result["status"] as? String == "ui_required" && attempt < 10 {
                    // UI can draw before the launcher has atomically published
                    // its PID/birth record. Recheck ownership; never bypass it.
                    DispatchQueue.main.asyncAfter(deadline: .now()+0.25) { [weak self] in self?.acknowledgeControl(id, attempt: attempt+1) }
                }
            }
        }
    }
    @objc func enableSystemNotifications() {
        systemNotifications.requestPermission { [weak self] text in DispatchQueue.main.async { self?.activityLabel.stringValue = text } }
    }
    @objc func showInferenceControl() { inferenceWindow.toggle() }
    @objc func stopCurrentInference() { if let id = inferenceWindow.ticket { stopInference(id) } }
    func startInference(_ id: String, confirmed: Bool) {
        client.command(["command":"inference_start", "ticket_id":id, "confirmed":confirmed]) { [weak self] result in
            DispatchQueue.main.async {
                self?.showInference(result)
                self?.activityLabel.stringValue = result["text"] as? String ?? "推理状态已更新"
                self?.refresh()
            }
        }
    }
    func stopInference(_ id: String) {
        // Deliberately bypass the serialized UI busy flag.
        client.command(["command":"inference_stop", "ticket_id":id]) { [weak self] result in
            DispatchQueue.main.async { self?.showInference(result); self?.refresh() }
        }
    }
    @objc func setInferenceOptions() {
        request(["command":"inference_options", "allow_local_on_battery":batteryAutomation.state == .on,
                 "allow_automatic_cloud":cloudAutomation.state == .on]) { [weak self] _ in self?.refresh() }
    }
    @objc func quitUI() {
        if inferenceWindow.active, let id = inferenceWindow.ticket {
            client.command(["command":"inference_stop", "ticket_id":id]) { _ in DispatchQueue.main.async { NSApp.terminate(nil) } }
        } else { NSApp.terminate(nil) }
    }
    func applicationWillTerminate(_ notification: Notification) { timer?.invalidate(); client.close() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}
