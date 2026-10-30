import AppKit
import Foundation
import Darwin

func uiControlTrace(_ text: String) {
    if ProcessInfo.processInfo.environment["COMPANION_UI_DIAGNOSTICS"] == "1" { fputs(text + "\n", stderr) }
}

func selfTest(client: CompanionClient, ownedMutations: Bool) -> Int32 {
    let started = Date()
    var commands: [JSONObject] = [["command": "ui_snapshot"], ["command": "status"],
        ["command": "privacy"], ["command": "recent_memories", "limit": 12],
        ["command": "observations"], ["command": "notices"], ["command": "escalation_status"],
        ["command": "proactive_settings"]]
    if ownedMutations {
        let marker = client.runtimeURL.deletingLastPathComponent().appendingPathComponent(".ui-validation-owned")
        // The harness alone creates this token-bound marker in its disposable
        // data directory. A normal service cannot be mutated by --self-test.
        guard let content = try? String(contentsOf: marker, encoding: .utf8), content == client.token else { return 3 }
        commands += [["command": "pause_observation", "paused": true],
                     ["command": "dnd", "enabled": true],
                     ["command": "ask", "text": "你好，这是合成 UI 连接测试。"],
                     ["command": "set_app_exclusions", "apps": ["org.localpilot.synthetic.ui-excluded"]],
                     ["command": "proactive_settings", "level": "low", "delivery": "silent"],
                     ["command": "escalate", "text": "请准备一个仅本地的合成测试任务"],
                     ["command": "submit_escalation", "approved": false, "cloud_approved": false],
                     ["command": "ui_snapshot"]]
    }
    var checks: [JSONObject] = []
    var passed = true
    for body in commands {
        let semaphore = DispatchSemaphore(value: 0)
        var response: JSONObject = [:]
        let begin = Date()
        client.command(body) { result in response = result; semaphore.signal() }
        guard semaphore.wait(timeout: .now() + 130) == .success else { return 4 }
        let status = CompanionPresentation.value(response, "status")
        let name = body["command"] as? String ?? ""
        let success = !["error", "forbidden", "UNKNOWN"].contains(status)
            && (name != "ui_snapshot" || response["runtime"] is JSONObject)
        passed = passed && success
        checks.append(["command": name, "status": status, "pass": success,
                       "elapsed_ms": Date().timeIntervalSince(begin) * 1000])
    }
    let semaphore = DispatchSemaphore(value: 0)
    var denied: JSONObject = [:]
    client.command(["command": "status"], tokenOverride: "invalid-ui-validation-token") { result in denied = result; semaphore.signal() }
    guard semaphore.wait(timeout: .now() + 5) == .success else { return 4 }
    let rejected = denied["http_status"] as? Int == 403 && denied["status"] as? String == "forbidden"
    passed = passed && rejected
    checks.append(["command": "invalid_bearer", "pass": rejected, "http_status": denied["http_status"] ?? 0])
    let summary: JSONObject = ["status": passed ? "PASS" : "FAIL", "mode": "hidden_authenticated_native_client",
        "visible_window": false, "menu_bar_item_created": false, "owned_mutations": ownedMutations,
        "manual_clicks": "NOT_RUN", "elapsed_seconds": Date().timeIntervalSince(started), "checks": checks]
    print(CompanionPresentation.pretty(summary))
    client.close()
    return passed ? 0 : 1
}

let arguments = CommandLine.arguments
do {
    if arguments.count >= 3 && arguments[1] == "--self-test" {
        let client = try CompanionClient(runtimePath: arguments[2])
        exit(selfTest(client: client, ownedMutations: arguments.contains("--owned-mutations")))
    } else if arguments.count == 3 && arguments[1] == "--action-self-test" {
        let client = try CompanionClient(runtimePath: arguments[2])
        let marker = client.runtimeURL.deletingLastPathComponent().appendingPathComponent(".ui-validation-owned")
        guard let content = try? String(contentsOf: marker, encoding: .utf8), content == client.token else { exit(3) }
        let app = NSApplication.shared; app.setActivationPolicy(.accessory)
        let controller = MenuBarController(client: client); controller.buildPanel()
        func settle() -> Bool {
            let deadline = Date().addingTimeInterval(8)
            repeat {
                RunLoop.current.run(until: Date().addingTimeInterval(0.05))
                if !controller.busy { return true }
            } while Date() < deadline
            return false
        }
        var checks: JSONObject = [:]
        controller.refresh(); checks["snapshot"] = settle() && !controller.snapshot.isEmpty
        controller.chatInput.stringValue = "合成 UI 聊天测试"; controller.sendChat()
        checks["chat_action_real_host_reply"] = settle() && controller.chatOutput.string.contains("Companion：")
        controller.togglePause(); checks["pause_action"] = settle() && (controller.snapshot["privacy"] as? JSONObject)?["status"] as? String == "paused"
        controller.busy = true; controller.togglePause()
        let busyPauseIssued = controller.pausePending
        let pauseDeadline = Date().addingTimeInterval(8)
        while controller.pausePending && Date() < pauseDeadline { RunLoop.current.run(until: Date().addingTimeInterval(0.05)) }
        controller.busy = false
        checks["busy_pause_reaches_host"] = busyPauseIssued && !controller.pausePending
        controller.refresh(); _ = settle()
        controller.toggleDND(); checks["dnd_action"] = settle() && (controller.snapshot["runtime"] as? JSONObject)?["dnd"] as? Bool == true
        controller.exclusionInput.stringValue = "org.localpilot.synthetic.ui-action"; controller.setExclusions()
        checks["exclusion_action"] = settle() && controller.exclusionInput.stringValue.contains("org.localpilot.synthetic.ui-action")
        controller.levelPicker.selectItem(at: 0); controller.deliveryPicker.selectItem(at: 0); controller.setProactive()
        checks["proactive_action"] = settle() && (controller.snapshot["proactive"] as? JSONObject)?["level"] as? String == "off"
        if controller.noticePicker.numberOfItems > 0 {
            controller.useful(); checks["feedback_action"] = settle() && ((controller.snapshot["proactive"] as? JSONObject)?["feedback"] as? JSONObject)?["useful"] as? Int == 1
        }
        controller.taskInput.stringValue = "准备合成本地任务，不执行工具"; controller.prepareTask()
        checks["task_prepare_action"] = settle() && (controller.snapshot["escalation"] as? JSONObject)?["pending"] is JSONObject
        controller.checkConnection(); checks["connection_action"] = settle() && controller.taskOutput.string.contains("LocalPilot")
        checks["hidden_window"] = controller.panel?.isVisible == false && controller.statusItem == nil
        let pass = checks.values.allSatisfy { $0 as? Bool == true }
        print(CompanionPresentation.pretty(["status": pass ? "PASS" : "FAIL", "mode": "hidden_real_UI_action_selectors",
            "checks": checks, "visible_window": false, "menu_bar_item_created": false,
            "modal_confirmation_clicks": "MANUAL_REQUIRED", "real_model_answer_quality": "NOT_RUN"]));
        client.close(); exit(pass ? 0 : 1)
    } else if arguments.count == 4 && arguments[1] == "--idle-self-test" {
        guard let seconds = Double(arguments[3]), seconds.isFinite, seconds > 0, seconds <= 60 else { exit(2) }
        let client = try CompanionClient(runtimePath: arguments[2])
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let controller = MenuBarController(client: client)
        controller.buildPanel()
        controller.refresh()
        let deadline = Date().addingTimeInterval(seconds)
        while Date() < deadline { RunLoop.current.run(until: min(deadline, Date().addingTimeInterval(0.1))) }
        let pass = controller.panel?.isVisible == false && controller.statusItem == nil && !controller.snapshot.isEmpty
        print(CompanionPresentation.pretty(["status": pass ? "PASS" : "FAIL", "mode": "hidden_native_panel_idle",
            "visible_window": false, "menu_bar_item_created": false, "duration_seconds": seconds,
            "snapshot_requests": controller.pollCount, "visible_UI_cost": "MANUAL_REQUIRED"]));
        client.close(); exit(pass ? 0 : 1)
    } else if arguments.count >= 4 && arguments[1] == "--layout-self-test" {
        let client = try CompanionClient(runtimePath: arguments[2])
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let controller = MenuBarController(client: client)
        controller.buildPanel()
        let synthetic: JSONObject = ["status": "ok", "runtime": ["model": ["loaded": false], "localpilot": "unavailable", "native_observer": ["status": "PARTIAL"]],
            "privacy": ["status": "paused", "scope": ["files": ["合成文档目录"], "allowed_apps": ["org.localpilot.synthetic"], "excluded_apps": [], "content_apps": []]],
            "memories": [["text": "合成明确偏好：先核对来源", "source_reference": "user:synthetic", "evidence_type": "USER_CONFIRMED"]],
            "observations": [["kind": "ax.snapshot", "source_reference": "synthetic:window", "epistemic": "observed", "evidence": ["summary": "公开测试窗口", "read_status": "PARTIAL"]]],
            "notices": [], "proactive": ["level": "low", "delivery": "silent"], "escalation": ["tasks": [:]]]
        controller.applySnapshot(synthetic)
        controller.panel?.appearance = NSAppearance(named: .aqua)
        controller.panel?.contentView?.layoutSubtreeIfNeeded()
        RunLoop.current.run(until: Date().addingTimeInterval(0.3))
        guard let view = controller.panel?.contentView, controller.panel?.isVisible == false,
              controller.statusItem == nil, let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { exit(5) }
        view.cacheDisplay(in: view.bounds, to: bitmap)
        guard let png = bitmap.representation(using: .png, properties: [:]) else { exit(5) }
        try png.write(to: URL(fileURLWithPath: arguments[3]), options: .atomic)
        print(CompanionPresentation.pretty(["status": "PASS", "mode": "hidden_layout_construction",
            "visible_window": false, "menu_bar_item_created": false, "tabs": controller.tabs.tabViewItems.count,
            "width": view.bounds.width, "height": view.bounds.height, "interactive_clicks": "MANUAL_REQUIRED"]))
        client.close(); exit(0)
    } else {
        guard arguments.count == 2 || (arguments.count == 3 && arguments[2] == "--show") else { exit(2) }
        let client = try CompanionClient(runtimePath: arguments[1])
        let app = NSApplication.shared
        let controller = MenuBarController(client: client)
        controller.showOnLaunch = arguments.count == 3
        app.setActivationPolicy(.accessory)
        app.delegate = controller
        // NSApplication does not own its delegate. Retain the controller for
        // the entire event loop, including optimized standalone launches.
        withExtendedLifetime(controller) {
            uiControlTrace("app_run")
            app.run()
        }
    }
} catch {
    // No private paths, bearer tokens, or captured text are printed on failure.
    fputs("Companion UI: private runtime unavailable.\n", stderr)
    exit(2)
}
