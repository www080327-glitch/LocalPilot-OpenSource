// Stable build: public macOS AX only. LOCAL_NATIVE adds an isolated experimental
// keyboard module. Neither build activates apps, dispatches mouse input, or captures screens.
import AppKit
import ApplicationServices
import CoreGraphics
import IOKit
import CryptoKit

func attr(_ element: AXUIElement, _ name: String) -> Any? {
    var result: CFTypeRef?
    return AXUIElementCopyAttributeValue(element, name as CFString, &result) == .success ? result : nil
}
func scalar(_ value: Any?) -> Any {
    if let v = value as? String { return String(v.prefix(2048)) }
    if let v = value as? NSNumber { return v }
    return NSNull()
}
func actions(_ element: AXUIElement) -> [String] {
    var result: CFArray?
    _ = AXUIElementCopyActionNames(element, &result)
    return result as? [String] ?? []
}
func identity(_ element: AXUIElement) -> [String: Any] {
    let role = attr(element, "AXRole") as? String ?? "UNKNOWN"
    let subrole = attr(element, "AXSubrole") as? String
    let secure = role == "AXSecureTextField" || subrole == "AXSecureTextField"
    let rawTitle = attr(element, "AXTitle")
    let rawDescription = attr(element, "AXDescription")
    let rawValue = secure ? nil : attr(element, "AXValue")
    var settable: DarwinBoolean = false
    _ = AXUIElementIsAttributeSettable(element, "AXValue" as CFString, &settable)
    var selectionLength: Any = NSNull()
    if !secure && ["AXTextArea", "AXTextField", "AXComboBox"].contains(role), let range = attr(element, "AXSelectedTextRange") as CFTypeRef?, CFGetTypeID(range) == AXValueGetTypeID() {
        var selectedRange = CFRange()
        if AXValueGetValue(unsafeBitCast(range, to: AXValue.self), .cfRange, &selectedRange) { selectionLength = selectedRange.length }
    }
    var row: [String: Any] = ["role": role, "subrole": subrole ?? NSNull(), "identifier": scalar(attr(element, "AXIdentifier")),
            "title": scalar(rawTitle), "description": scalar(rawDescription),
            "value": scalar(rawValue),
            "enabled": scalar(attr(element, "AXEnabled")), "actions": actions(element),
            "value_settable": !secure && settable.boolValue, "selection_length": selectionLength,
            "selected": ["AXMenuItem", "AXMenuBarItem", "AXRow", "AXRadioButton", "AXCheckBox"].contains(role) ? scalar(attr(element, "AXSelected")) : NSNull(),
            "expanded": ["AXRow", "AXOutline", "AXDisclosureTriangle"].contains(role) ? scalar(attr(element, "AXExpanded")) : NSNull()]
#if LOCAL_NATIVE
    // Keep the WebKit DOM identity separate; stable AX observations are unchanged.
    if role == "AXTextArea", let domID = attr(element, "AXDOMIdentifier") as? String {
        row["dom_identifier"] = domID
    }
#endif
    for (key, value) in [("title", rawTitle), ("description", rawDescription), ("value", rawValue)] {
        if let text = value as? String {
            if text.count > 2048 { row[key + "_omitted_chars"] = text.count - 2048 }
            // Fingerprint full attributes: same-length edits beyond a clipped
            // preview must still invalidate a stale element.
            row[key + "_sha256"] = SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
        }
    }
#if COMPUTER_USE
    row["bounds"] = cuRect(element) ?? NSNull()
    row["focused"] = scalar(attr(element, "AXFocused"))
    row["protected"] = secure
#endif
    return row
}
func encode(_ object: Any) -> Data { (try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])) ?? Data() }
func fail(_ code: String, _ message: String) -> [String: Any] {
    ["status": "error", "error": code, "message": message]
}

final class Bridge {
#if COMPUTER_USE
    let computer = ComputerUse()
#endif
#if LOCAL_NATIVE
    let nativeInput = LocalNativeInput()
#endif
    var references: [String: AXUIElement] = [:]
    var identities: [String: Data] = [:]
    var owners: [String: Int32] = [:]
    var paths: [String: [Int]] = [:]
    var rootAttributes: [String: String] = [:]
    var epoch = 0
    var allowed: Set<String>
    init(_ allowed: Set<String>) { self.allowed = allowed }

    func environment() -> [String: Any] {
        // AppKit's foreground/process properties update only when its run loop
        // is serviced. Blocking stdin must not freeze interference observations.
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.01))
        let session = CGSessionCopyCurrentDictionary() as? [String: Any] ?? [:]
        let console = session["kCGSSessionOnConsoleKey"] as? Bool ?? false
        let login = session["kCGSessionLoginDoneKey"] as? Bool ?? false
        // This dictionary key is observable, undocumented, and only an advisory signal.
        let locked = session["CGSSessionScreenIsLocked"] as? Bool
        let mouse = CGEvent(source: nil)?.location
        let focusStartPID = NSWorkspace.shared.frontmostApplication?.processIdentifier ?? -1
        var focus: CFTypeRef?
        var focusApp: CFTypeRef?
        let system = AXUIElementCreateSystemWide()
        AXUIElementSetMessagingTimeout(system, 0.25)
        let appError = AXUIElementCopyAttributeValue(system, "AXFocusedApplication" as CFString, &focusApp)
        var focusSource = "system_AXFocusedApplication"
        // Some apps are readable through their actual application element while
        // the system-wide focused-application lookup returns cannotComplete.
        // Read the same AXFocusedUIElement attribute on the observed foreground
        // process; do not infer focus from its window, selection, or contents.
        if appError != .success || focusApp == nil || CFGetTypeID(focusApp!) != AXUIElementGetTypeID() {
            if focusStartPID > 0 {
                focusApp = AXUIElementCreateApplication(focusStartPID)
                focusSource = "frontmost_application_AXFocusedUIElement"
            }
        }
        var focusError = appError
        if let focusApp, CFGetTypeID(focusApp) == AXUIElementGetTypeID() {
            AXUIElementSetMessagingTimeout(unsafeBitCast(focusApp, to: AXUIElement.self), 0.25)
            focusError = AXUIElementCopyAttributeValue(unsafeBitCast(focusApp, to: AXUIElement.self), "AXFocusedUIElement" as CFString, &focus)
        }
        var focusDescription: [String: Any] = [:]
        if let focus, CFGetTypeID(focus) == AXUIElementGetTypeID() {
            let element = unsafeBitCast(focus, to: AXUIElement.self)
            var pid: pid_t = 0
            _ = AXUIElementGetPid(element, &pid)
            // Avoid collecting unrelated user content: only role and identifier.
            focusDescription = ["pid": pid, "role": scalar(attr(element, "AXRole")),
                                "subrole": scalar(attr(element, "AXSubrole")),
                                "identifier": scalar(attr(element, "AXIdentifier"))]
        }
        var idle: Double = 0
        let hid = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("IOHIDSystem"))
        if hid != 0 {
            if let value = IORegistryEntryCreateCFProperty(hid, "HIDIdleTime" as CFString, kCFAllocatorDefault, 0)?.takeRetainedValue() as? NSNumber {
                idle = value.doubleValue / 1_000_000_000
            }
            IOObjectRelease(hid)
        }
        // Refresh after AX messaging, which can wait for another process. A
        // foreground change or a focus belonging to another process is unknown.
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.01))
        let front = NSWorkspace.shared.frontmostApplication
        let rawFrontPID = front?.processIdentifier ?? -1
        let focusConsistent = rawFrontPID > 0 && rawFrontPID == focusStartPID && (focusDescription["pid"] as? pid_t) == rawFrontPID
        if !focusConsistent { focusDescription = [:] }
        let frontCandidates = rawFrontPID > 0 ? [rawFrontPID] : candidates(front?.bundleIdentifier ?? "UNKNOWN", scoped: false)
        let frontPID = frontCandidates.count == 1 ? frontCandidates[0] : -1
        var timebase = mach_timebase_info_data_t()
        mach_timebase_info(&timebase)
        // Sample absolute first: with no accumulated sleep, the opposite order
        // can subtract a later absolute tick from an earlier continuous tick
        // and trap on unsigned underflow. Missing evidence never becomes sleep.
        let absoluteTicks = mach_absolute_time()
        let continuousTicks = mach_continuous_time()
        let sleepTicks = continuousTicks >= absoluteTicks ? continuousTicks - absoluteTicks : 0
        let sleepSeconds = Double(sleepTicks) * Double(timebase.numer) / Double(timebase.denom) / 1_000_000_000
        var power: [String: Any] = [:]
        for (serviceName, field) in [("IOPMrootDomain", "lid_closed"), ("IODisplayWrangler", "display_power_state")] {
            let service = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching(serviceName))
            if service != 0 {
                let key = serviceName == "IOPMrootDomain" ? "AppleClamshellState" : "IOPowerManagement"
                let property = IORegistryEntryCreateCFProperty(service, key as CFString, kCFAllocatorDefault, 0)?.takeRetainedValue()
                power[field] = serviceName == "IOPMrootDomain" ? scalar(property) : scalar((property as? [String: Any])?["CurrentPowerState"])
                IOObjectRelease(service)
            }
        }
        return ["trusted": AXIsProcessTrusted(), "frontmost_pid": frontPID,
                "frontmost_pid_source": rawFrontPID > 0 ? "NSWorkspace" : frontPID > 0 ? "CGWindow_owner_metadata" : "UNKNOWN",
                "frontmost_app": front?.bundleIdentifier ?? "UNKNOWN", "focused_element": focusDescription,
                "focus_observable": focusError == .success && focusConsistent && !focusDescription.isEmpty, "focus_ax_error": focusError.rawValue,
                "focus_application_ax_error": appError.rawValue, "focus_source": focusSource,
                "focus_pid_matches_frontmost": focusConsistent,
                "mouse": mouse.map { [$0.x, $0.y] } ?? [], "input_idle_seconds": idle,
                "locked": locked ?? (!console || !login), "lock_signal": locked == nil ? "console_login_inference" : "CGSession_dictionary",
                "on_console": console, "login_done": login, "session_available": !session.isEmpty,
                "session_id": scalar(session["kCGSSessionAuditIDKey"]), "power": power,
                "sleep_total_seconds": sleepSeconds]
    }
    func candidates(_ id: String, scoped: Bool = true) -> [pid_t] {
        guard !scoped || allowed.contains(id) else { return [] }
        var pids = Set(NSRunningApplication.runningApplications(withBundleIdentifier: id)
            .filter { !$0.isTerminated && $0.processIdentifier > 0 && kill($0.processIdentifier, 0) == 0 }
            .map { $0.processIdentifier })
        // NSRunningApplication can expose pid=-1 for a real app. Resolve only
        // public window-owner metadata whose NSRunningApplication bundle matches.
        let windows = CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
        for window in windows {
            guard let pid = window[kCGWindowOwnerPID as String] as? Int32, pid > 0,
                  let running = NSRunningApplication(processIdentifier: pid), running.bundleIdentifier == id,
                  !running.isTerminated, kill(pid, 0) == 0 else { continue }
            pids.insert(pid)
        }
        return pids.sorted()
    }
    func rootElements(_ app: AXUIElement, _ attribute: String) -> [AXUIElement] {
        let value = attr(app, attribute)
        if let elements = value as? [AXUIElement] { return elements }
        if let element = value as CFTypeRef?, CFGetTypeID(element) == AXUIElementGetTypeID() {
            return [unsafeBitCast(element, to: AXUIElement.self)]
        }
        return []
    }
    func tree(_ id: String, _ maxNodes: Int, _ depth: Int, _ windowTitle: String?, _ includeMenus: Bool) -> [String: Any] {
        epoch += 1
#if COMPUTER_USE
        computer.bindings.removeAll()
        computer.observedWindows.removeAll()
#endif
        references.removeAll(); identities.removeAll(); owners.removeAll(); paths.removeAll(); rootAttributes.removeAll()
        guard allowed.contains(id) else { return fail("app_not_allowed", "Host app allowlist rejects target.") }
        guard AXIsProcessTrusted() else { return fail("accessibility_not_trusted", "Grant Accessibility to the launching host manually; no prompt is automated.") }
        let pids = candidates(id)
        if pids.count > 1 { return fail("ambiguous_app", "Multiple running apps share a bundle ID; no arbitrary process selection.") }
        guard let pid = pids.first else { return fail("app_closed_or_pid_unavailable", "No verified positive PID; no automatic launch or activation.") }
        let root = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(root, 0.75)
        var rows: [[String: Any]] = []
        var seen: [AXUIElement] = []
        var truncated = false
        func visit(_ element: AXUIElement, _ path: [Int], _ level: Int, _ rootAttribute: String) {
            if rows.count >= maxNodes { truncated = true; return }
            if seen.contains(where: { CFEqual($0, element) }) { return }
            seen.append(element)
            let handle = "\(epoch):\(rows.count)"
            var row = identity(element)
            identities[handle] = encode(row)
#if COMPUTER_USE
            let binding = computer.observeBinding(element, pid)
            computer.bindings[handle] = binding
            row["window_binding"] = binding
#endif
            row["handle"] = handle; row["path"] = path
            row["root_attribute"] = rootAttribute
            references[handle] = element; owners[handle] = pid
            paths[handle] = path
            rootAttributes[handle] = rootAttribute
            rows.append(row)
            let children = attr(element, "AXChildren") as? [AXUIElement] ?? []
            if level >= depth { if !children.isEmpty { truncated = true }; return }
            for (i, child) in children.enumerated() { visit(child, path + [i], level + 1, rootAttribute) }
        }
        // Windows are the supported scope; avoid broad menu/content scraping.
        var windowsValue: CFTypeRef?
        let windowError = AXUIElementCopyAttributeValue(root, "AXWindows" as CFString, &windowsValue)
        let windows = windowsValue as? [AXUIElement] ?? []
        var matchedWindows = 0
        for (i, window) in windows.enumerated() {
            if windowTitle == nil || attr(window, "AXTitle") as? String == windowTitle {
                visit(window, [i], 0, "AXWindows"); matchedWindows += 1
            }
        }
        let focused = rootElements(root, "AXFocusedWindow")
        for (i, window) in focused.enumerated() {
            if !windows.contains(where: { CFEqual($0, window) }) && (windowTitle == nil || attr(window, "AXTitle") as? String == windowTitle) {
                visit(window, [i], 0, "AXFocusedWindow"); matchedWindows += 1
            }
        }
        if windowTitle != nil && matchedWindows == 0 {
            var result = fail("window_not_found", "Exact target window is not exposed by AXWindows/AXFocusedWindow; cause UNKNOWN. No guessed replacement or activation.")
            result["app"] = id; result["pid"] = pid
            result["window_title"] = windowTitle ?? NSNull()
            result["AXWindows_count"] = windows.count
            result["AXWindows_error"] = windowError.rawValue
            result["AXFocusedWindow_count"] = focused.count
            result["window_coverage"] = "AXWindows_plus_AXFocusedWindow_not_all_WindowServer_windows"
            return result
        }
        if includeMenus {
            for (i, menu) in rootElements(root, "AXMenuBar").enumerated() { visit(menu, [i], 0, "AXMenuBar") }
        }
        return ["status": "ok", "app": id, "pid": pid, "epoch": epoch,
                "nodes": rows, "window_count": matchedWindows, "AXWindows_count": windows.count,
                "AXFocusedWindow_count": focused.count,
                "AXWindows_error": windowError.rawValue, "focused_window_fallback": matchedWindows > windows.count || rows.contains { $0["root_attribute"] as? String == "AXFocusedWindow" },
                "window_title": windowTitle ?? NSNull(), "include_menu_bar": includeMenus, "truncated": truncated,
                "window_coverage": "AXWindows_plus_AXFocusedWindow_not_all_WindowServer_windows"]
    }
    func execute(_ request: [String: Any]) -> [String: Any] {
        let op = request["op"] as? String ?? ""
#if COMPUTER_USE
        if op.hasPrefix("cu_") { return computer.execute(request, self) }
        if op == "action", let refusal = computer.validate(request, self) { return refusal }
#endif
#if LOCAL_NATIVE
        if op == "native_context" || op == "native_text" || op == "native_process_status" {
            return nativeInput.execute(request, bridge: self)
        }
#endif
        if op == "environment" { return ["status": "ok", "environment": environment()] }
        if op == "inspect_apps" {
            return ["status": "ok", "apps": allowed.sorted().flatMap { id in candidates(id).map { pid in ["app": id, "name": NSRunningApplication(processIdentifier: pid)?.localizedName ?? id, "pid": pid] as [String: Any] } }]
        }
        if op == "inspect_tree", let id = request["app"] as? String {
            return tree(id, min(512, max(1, request["max_nodes"] as? Int ?? 256)), min(20, max(0, request["max_depth"] as? Int ?? 12)), request["window_title"] as? String, request["include_menu_bar"] as? Bool ?? false)
        }
        if op == "action", let handle = request["handle"] as? String, let id = request["app"] as? String {
            guard allowed.contains(id) else { return fail("app_not_allowed", "Target is outside host scope.") }
            let pids = candidates(id)
            if pids.count > 1 { return fail("ambiguous_app", "No action sent to ambiguous app.") }
            guard let pid = pids.first else { return fail("app_closed", "Target closed or PID unavailable.") }
            guard let element = references[handle], owners[handle] == pid else { return fail("stale_element", "Observe and find again.") }
            let root = AXUIElementCreateApplication(pid)
            AXUIElementSetMessagingTimeout(root, 0.75)
            var resolved: AXUIElement? = nil
            for (depth, index) in (paths[handle] ?? []).enumerated() {
                let parent = resolved ?? root
                let children = depth == 0 ? rootElements(root, rootAttributes[handle] ?? "AXWindows") : attr(parent, "AXChildren") as? [AXUIElement] ?? []
                if index >= children.count { return fail("stale_element", "Element path no longer exists.") }
                resolved = children[index]
            }
            guard let resolved, CFEqual(resolved, element) else { return fail("stale_element", "Element was replaced; no action sent.") }
            guard identities[handle] == encode(identity(element)) else { return fail("element_changed", "AX attributes changed; no action sent.") }
            let before = environment()
            guard before["locked"] as? Bool == false, before["session_available"] as? Bool == true else { return fail("locked_or_unknown", "GUI writes pause until manual unlock and resync.") }
            guard request["allow_frontmost"] as? Bool == true || (before["frontmost_pid"] as? Int32 != pid && before["frontmost_app"] as? String != id) else {
                return fail("user_app_active", "Target is the user's foreground app; hand off or explicitly opt in from host.")
            }
            if before["frontmost_pid"] as? Int32 != pid || before["frontmost_app"] as? String != id {
                // A background AX mutation can disturb IME composition without
                // changing the frontmost app. Check at the native dispatch boundary.
                let focus = before["focused_element"] as? [String: Any] ?? [:]
                let role = focus["role"] as? String
                var inputError: String?
                if before["focus_observable"] as? Bool != true || role == nil || role == "" || role == "AXUnknown" {
                    inputError = "background_input_focus_unknown"
                } else if ["AXTextField", "AXTextArea", "AXComboBox", "AXSearchField", "AXSecureTextField"].contains(role!) || focus["subrole"] as? String == "AXSecureTextField" {
                    inputError = "user_text_input_active"
                } else if let idle = before["input_idle_seconds"] as? Double, idle.isFinite && idle >= 0 {
                    if idle < 1 { inputError = "user_input_active" }
                } else {
                    inputError = "user_input_state_unknown"
                }
                if let inputError {
                    return ["status": "error", "error": inputError,
                            "message": "Background write paused to protect human text/IME input; no action sent.",
                            "action_sent": false, "before": before]
                }
            }
            let kind = request["kind"] as? String ?? ""
            let result: AXError
            if kind == "set_value" {
                guard (attr(element, "AXRole") as? String) != "AXSecureTextField", (attr(element, "AXSubrole") as? String) != "AXSecureTextField", let value = request["value"] as? String, value.count <= 2048 else { return fail("invalid_value", "Only bounded non-secure text values are supported.") }
                var settable: DarwinBoolean = false
                _ = AXUIElementIsAttributeSettable(element, "AXValue" as CFString, &settable)
                guard settable.boolValue else { return fail("value_not_settable", "No keyboard fallback.") }
#if COMPUTER_USE
                if let refusal = computer.validate(request, self) { return refusal }
#endif
                result = AXUIElementSetAttributeValue(element, "AXValue" as CFString, value as CFString)
            } else {
                let action = request["action"] as? String ?? ""
                let foregroundMenu = action == "AXShowMenu" || (["AXPress", "AXPick"].contains(action) && ["AXMenuBarItem", "AXMenuItem", "AXMenuButton", "AXPopUpButton"].contains(attr(element, "AXRole") as? String ?? ""))
                if foregroundMenu && before["frontmost_app"] as? String != id {
                    return fail("foreground_action_required", "Background menu actions are blocked; no action sent.")
                }
                guard ["AXPress", "AXConfirm", "AXCancel", "AXIncrement", "AXDecrement", "AXShowMenu", "AXPick", "AXExpand", "AXCollapse", "AXScrollUpByPage", "AXScrollDownByPage", "AXScrollLeftByPage", "AXScrollRightByPage"].contains(action), actions(element).contains(action) else {
                    return fail("unsupported_action", "Use only supported semantic actions; no coordinate fallback.")
                }
#if COMPUTER_USE
                if let refusal = computer.validate(request, self) { return refusal }
#endif
                result = AXUIElementPerformAction(element, action as CFString)
            }
            return ["status": result == .success ? "ok" : "error", "ax_error": result.rawValue,
                    "action_sent": true, "before": before, "after": environment()]
        }
        return fail("invalid_request", "Unknown operation or missing fields.")
    }
}

let bridge = Bridge(Set(CommandLine.arguments.dropFirst()))
#if COMPUTER_USE && !LEGACY_STDIO_LOOP
// AX/WindowServer/AppKit clients may need main-thread callbacks while an AX
// read is pending. Keep the main run loop alive; serialize stdio on one worker.
_ = NSWorkspace.shared
let mainPort=Port();RunLoop.main.add(mainPort,forMode:.default)
Thread.detachNewThread {
    let workerPort=Port();RunLoop.current.add(workerPort,forMode:.default)
    while let line = readLine() {
        autoreleasepool {
            do {
                guard line.utf8.count <= 32768, let request = try JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any] else {
                    print(String(data: encode(fail("invalid_json", "Bounded object required.")), encoding: .utf8)!); return
                }
                print(String(data: encode(bridge.execute(request)), encoding: .utf8)!)
            } catch { print(String(data: encode(fail("invalid_json", String(describing: error))), encoding: .utf8)!) }
            fflush(stdout)
        }
    }
    DispatchQueue.main.async { CFRunLoopStop(CFRunLoopGetMain()) }
}
CFRunLoopRun()
#else
while let line = readLine() {
    autoreleasepool {
        do {
            guard line.utf8.count <= 32768, let request = try JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any] else {
                print(String(data: encode(fail("invalid_json", "Bounded object required.")), encoding: .utf8)!); return
            }
            print(String(data: encode(bridge.execute(request)), encoding: .utf8)!)
        } catch { print(String(data: encode(fail("invalid_json", String(describing: error))), encoding: .utf8)!) }
        fflush(stdout)
    }
}
#endif
