// First-party, default-off Computer Use helper. Public APIs only.
import AppKit
import ApplicationServices
import CoreGraphics
import ScreenCaptureKit
import CryptoKit
import Carbon
import Darwin

func cuRect(_ element: AXUIElement) -> [Double]? {
    guard let p = attr(element, "AXPosition") as CFTypeRef?, CFGetTypeID(p) == AXValueGetTypeID(),
          let s = attr(element, "AXSize") as CFTypeRef?, CFGetTypeID(s) == AXValueGetTypeID() else { return nil }
    var point = CGPoint.zero; var size = CGSize.zero
    guard AXValueGetValue(unsafeBitCast(p, to: AXValue.self), .cgPoint, &point),
          AXValueGetValue(unsafeBitCast(s, to: AXValue.self), .cgSize, &size),
          [point.x, point.y, size.width, size.height].allSatisfy({ $0.isFinite }), size.width > 0, size.height > 0 else { return nil }
    return [point.x, point.y, size.width, size.height]
}
func cuBirth(_ pid: pid_t) -> String? {
    var info = proc_bsdinfo(); let n = MemoryLayout<proc_bsdinfo>.size
    guard proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, Int32(n)) == n else { return nil }
    return "\(info.pbi_start_tvsec).\(info.pbi_start_tvusec)"
}
func cuWindows() -> [[String: Any]] {
    CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
}
func cuWindow(_ element: AXUIElement, _ pid: pid_t) -> AXUIElement? {
    let role = attr(element, "AXRole") as? String ?? ""
    if role == "AXWindow" { return element }
    if let v = attr(element, "AXWindow") as CFTypeRef?, CFGetTypeID(v) == AXUIElementGetTypeID() { return unsafeBitCast(v, to: AXUIElement.self) }
    // App menus have no AXWindow. Bind them only to the actual foreground
    // application's currently focused AX window, never an arbitrary window.
    if ["AXMenu", "AXMenuBar", "AXMenuBarItem", "AXMenuItem"].contains(role), NSWorkspace.shared.frontmostApplication?.processIdentifier == pid,
       let v = attr(AXUIElementCreateApplication(pid), "AXFocusedWindow") as CFTypeRef?, CFGetTypeID(v) == AXUIElementGetTypeID() { return unsafeBitCast(v, to: AXUIElement.self) }
    return nil
}
func cuBinding(_ element: AXUIElement, _ pid: pid_t) -> [String: Any] {
    guard let window = cuWindow(element, pid) else { return ["status": "UNKNOWN", "reason": "no_AXWindow"] }
    guard let rect = cuRect(window), let birth = cuBirth(pid) else { return ["status": "UNKNOWN", "reason": "window_identity_missing"] }
    let matches = cuWindows().filter { row in
        guard row[kCGWindowOwnerPID as String] as? Int32 == pid,
              row[kCGWindowLayer as String] as? Int == 0,
              let raw = row[kCGWindowBounds as String] as? [String: Any],
              let bounds = CGRect(dictionaryRepresentation: raw as CFDictionary) else { return false }
        return bounds == CGRect(x: rect[0], y: rect[1], width: rect[2], height: rect[3])
    }
    guard matches.count == 1, let wid = matches[0][kCGWindowNumber as String] as? UInt32 else {
        return ["status": "UNKNOWN", "reason": "AX_CG_window_mapping_ambiguous", "matches": matches.count]
    }
    return ["status": "ok", "pid": pid, "process_birth": birth, "window_id": wid,
            "window_title": attr(window, "AXTitle") as? String ?? "", "bounds": rect,
            "window_identity": identity(window)]
}

final class ComputerUse {
    var bindings: [String: [String: Any]] = [:]
    var observedWindows: [(AXUIElement, [String: Any])] = []
    func observeBinding(_ element: AXUIElement, _ pid: pid_t) -> [String: Any] {
        guard let window = cuWindow(element, pid) else { return ["status":"UNKNOWN", "reason":"no_AXWindow"] }
        if let cached = observedWindows.first(where: { CFEqual($0.0,window) }) { return cached.1 }
        let binding = cuBinding(window,pid)
        observedWindows.append((window,binding))
        return binding
    }
    func refuse(_ reason: String) -> [String: Any] {
        ["status": "error", "error": reason, "action_sent": false, "replay_allowed": false, "fallback": "human"]
    }
    func validate(_ r: [String: Any], _ b: Bridge, checkControlState: Bool = true) -> [String: Any]? {
        guard AXIsProcessTrusted(), let app = r["app"] as? String, b.allowed.contains(app),
              !["com.apple.systempreferences", "com.apple.SecurityAgent", "com.apple.loginwindow", "com.apple.UserNotificationCenter", "com.apple.keychainaccess"].contains(app),
              let handle = r["handle"] as? String, let element = b.references[handle],
              let pid = b.owners[handle], b.candidates(app) == [pid],
              let expected = r["binding"] as? [String: Any], expected["status"] as? String == "ok",
              encode(expected) == encode(bindings[handle] ?? [:]), encode(expected) == encode(cuBinding(element, pid)) else {
            return refuse("target_window_or_process_changed")
        }
        let root = AXUIElementCreateApplication(pid); AXUIElementSetMessagingTimeout(root, 0.5)
        var resolved: AXUIElement?
        for (depth, i) in (b.paths[handle] ?? []).enumerated() {
            let parent = resolved ?? root
            let children = depth == 0 ? b.rootElements(root, b.rootAttributes[handle] ?? "AXWindows") : attr(parent, "AXChildren") as? [AXUIElement] ?? []
            guard i >= 0, i < children.count else { return refuse("stale_element_path") }
            resolved = children[i]
        }
        guard let resolved, CFEqual(resolved, element), !checkControlState || b.identities[handle] == encode(identity(element)) else { return refuse("stale_element_identity") }
        let role = attr(element, "AXRole") as? String ?? ""
        guard role != "AXSecureTextField", attr(element, "AXSubrole") as? String != "AXSecureTextField",
              role != "AXSystemDialog", safeWindow(element) else { return refuse("protected_control_or_window") }
        let operation=r["op"] as? String ?? ""
        if operation != "cu_validate" && operation != "cu_capture" && attr(element,"AXEnabled") as? Bool == false { return refuse("disabled_control") }
        guard let authorization = r["authorization_path"] as? String, authorization.hasPrefix("/"), !FileManager.default.fileExists(atPath:authorization) else { return refuse("authorization_revoked_or_unbound") }
        guard let stop = r["stop_path"] as? String, stop.hasPrefix("/"), !FileManager.default.fileExists(atPath: stop) else { return refuse("stopped_or_missing_control_fence") }
        return nil
    }
    func safeWindow(_ element: AXUIElement) -> Bool {
        var pid: pid_t = 0
        guard AXUIElementGetPid(element, &pid) == .success, let window = cuWindow(element, pid) else { return false }
        var count = 0
        func scan(_ node: AXUIElement, _ depth: Int) -> Bool {
            count += 1
            guard count <= 1024, depth <= 24 else { return false }
            let role = attr(node, "AXRole") as? String ?? ""
            if ["AXSecureTextField", "AXSystemDialog"].contains(role) || ["AXSecureTextField", "AXSystemDialog"].contains(attr(node, "AXSubrole") as? String ?? "") { return false }
            var value: CFTypeRef?
            let result = AXUIElementCopyAttributeValue(node, "AXChildren" as CFString, &value)
            guard result == .success || result == .noValue || result == .attributeUnsupported else { return false }
            let children = value as? [AXUIElement] ?? []
            return children.allSatisfy { scan($0, depth + 1) }
        }
        return scan(window, 0)
    }
    func foreground(_ r: [String: Any], _ b: Bridge, _ pid: pid_t) -> Bool {
        let env = b.environment()
        return env["frontmost_pid"] as? pid_t == pid && env["locked"] as? Bool == false && env["session_available"] as? Bool == true && !IsSecureEventInputEnabled()
    }
    func topWindow(_ point: CGPoint, _ wid: UInt32) -> Bool {
        let rows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
        for row in rows {
            guard (row[kCGWindowAlpha as String] as? Double ?? 0) > 0,
                  let raw = row[kCGWindowBounds as String] as? [String: Any],
                  let rect = CGRect(dictionaryRepresentation: raw as CFDictionary), rect.contains(point) else { continue }
            return row[kCGWindowNumber as String] as? UInt32 == wid
        }
        return false
    }
    func execute(_ r: [String: Any], _ b: Bridge) -> [String: Any] {
        let op = r["op"] as? String ?? ""
        if op == "cu_status" { return ["status": "ok", "trusted": AXIsProcessTrusted(), "screen_capture": CGPreflightScreenCaptureAccess(), "secure_input": IsSecureEventInputEnabled(), "adapter_revision": 2] }
        if op == "cu_windows" {
            guard let app = r["app"] as? String, b.allowed.contains(app), AXIsProcessTrusted(),
                  let titles = r["titles"] as? [String], b.candidates(app).count == 1 else { return refuse("window_scope_unavailable") }
            let pid = b.candidates(app)[0]; let root = AXUIElementCreateApplication(pid)
            AXUIElementSetMessagingTimeout(root,0.5)
            var rawWindows:CFTypeRef?
            let readError=AXUIElementCopyAttributeValue(root,"AXWindows" as CFString,&rawWindows)
            guard readError == .success, let windows=rawWindows as? [AXUIElement] else { return ["status":"error","error":"window_list_unobservable","ax_error":readError.rawValue,"action_sent":false] }
            let focused = NSWorkspace.shared.frontmostApplication?.processIdentifier == pid ? b.rootElements(root,"AXFocusedWindow").first : nil
            return ["status":"ok", "windows": windows.filter { titles.contains(attr($0,"AXTitle") as? String ?? "") }.map { window in
                var row=cuBinding(window,pid); row["frontmost"] = NSWorkspace.shared.frontmostApplication?.processIdentifier == pid && focused.map{CFEqual($0,window)} == true
                return row
            }]
        }
        if let refusal = validate(r, b) { return refusal }
        let handle = r["handle"] as! String; let element = b.references[handle]!; let pid = b.owners[handle]!
        let binding = bindings[handle]!; let before = b.environment()
        guard before["locked"] as? Bool == false, before["session_available"] as? Bool == true else { return refuse("locked_or_unknown") }
        if op == "cu_validate" { return ["status": "ok", "binding": binding, "before": before] }
        if op == "cu_capture" { return capture(r, b, element, binding) }
        guard r["foreground_authorized"] as? Bool == true, safeWindow(element) else { return refuse("foreground_or_sensitive_scope_rejected") }
        if op == "cu_focus" {
            guard let running = NSRunningApplication(processIdentifier: pid),
                  let value = attr(element, "AXWindow") as CFTypeRef? ?? (attr(element, "AXRole") as? String == "AXWindow" ? element : nil),
                  CFGetTypeID(value) == AXUIElementGetTypeID() else { return refuse("window_unavailable") }
            let window = unsafeBitCast(value, to: AXUIElement.self)
            _ = AXUIElementPerformAction(window, "AXRaise" as CFString)
            let posted = running.activate(options: [])
            RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))
            let focused = attr(AXUIElementCreateApplication(pid), "AXFocusedWindow") as CFTypeRef?
            let matches = focused.map { CFGetTypeID($0) == AXUIElementGetTypeID() && CFEqual($0, window) } ?? false
            return ["status": posted && foreground(r, b, pid) && matches ? "ok" : "error", "action_sent": true, "window_focused": matches, "before": before, "after": b.environment(), "input_cleanup": "no_owned_inputs"]
        }
        guard foreground(r, b, pid) else { return refuse("foreground_control_lost") }
        if op == "cu_select" {
            var settable: DarwinBoolean = false
            _ = AXUIElementIsAttributeSettable(element, "AXSelected" as CFString, &settable)
            guard settable.boolValue, attr(element,"AXEnabled") as? Bool != false else { return refuse("selection_not_settable") }
            let result = AXUIElementSetAttributeValue(element, "AXSelected" as CFString, kCFBooleanTrue)
            return ["status":result == .success ? "ok":"error", "ax_error":result.rawValue, "action_sent":true, "input_cleanup":"no_owned_inputs"]
        }
        guard let source = CGEventSource(stateID: .privateState) else { return refuse("event_source_unavailable") }
        var posted = 0
        if op == "cu_text" || op == "cu_shortcut" {
            let root = AXUIElementCreateApplication(pid)
            guard let focused = attr(root, "AXFocusedUIElement") as CFTypeRef?, CFGetTypeID(focused) == AXUIElementGetTypeID(), CFEqual(focused, element) else { return refuse("target_not_keyboard_responder") }
            let keys: [String: CGKeyCode] = ["return":36, "tab":48, "escape":53, "up":126, "down":125, "left":123, "right":124, "a":0, "s":1, "w":13, "t":17]
            let code: CGKeyCode; var flags: CGEventFlags = []
            if op == "cu_text" {
                guard ["AXTextArea", "AXTextField", "AXComboBox"].contains(attr(element, "AXRole") as? String ?? ""), let text = r["text"] as? String, (1...64).contains(text.utf16.count) else { return refuse("invalid_unicode_text") }
                code = 0
            } else {
                guard let name = r["key"] as? String, let key = keys[name], let modifiers = r["modifiers"] as? [String], Set(modifiers).isSubset(of: ["command", "shift", "option", "control"]) else { return refuse("unsupported_shortcut") }
                code = key
                for m in modifiers { flags.insert(["command":CGEventFlags.maskCommand, "shift":.maskShift, "option":.maskAlternate, "control":.maskControl][m]!) }
            }
            guard let down = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: true), let up = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: false) else { return refuse("event_creation_failed") }
            down.flags = flags; up.flags = flags
            down.setIntegerValueField(.eventSourceUserData,value:0x4c504355); up.setIntegerValueField(.eventSourceUserData,value:0x4c504355)
            if op == "cu_text", let text = r["text"] as? String { let units = Array(text.utf16); down.keyboardSetUnicodeString(stringLength: units.count, unicodeString: units); up.keyboardSetUnicodeString(stringLength: units.count, unicodeString: units) }
            if let refusal = validate(r, b) { return refusal }; guard foreground(r, b, pid) else { return refuse("foreground_control_lost") }
            down.postToPid(pid); posted += 1
            // Always release only our own event, including cancellation after down.
            up.postToPid(pid); posted += 1
        } else if op == "cu_click" || op == "cu_double_click" {
            guard let point = r["point"] as? [Double], point.count == 2, point.allSatisfy({$0.isFinite}),
                  let bounds = binding["bounds"] as? [Double], let wid = binding["window_id"] as? UInt32,
                  CGRect(x:bounds[0], y:bounds[1], width:bounds[2], height:bounds[3]).contains(CGPoint(x:point[0], y:point[1])) else { return refuse("point_outside_window") }
            let p = CGPoint(x:point[0], y:point[1])
            guard topWindow(p, wid), let control = cuRect(element), CGRect(x:control[0], y:control[1], width:control[2], height:control[3]).contains(p), attr(element, "AXEnabled") as? Bool == true else { return refuse("occluded_or_inoperable_target") }
            var hit: AXUIElement?
            let hitStatus = AXUIElementCopyElementAtPosition(AXUIElementCreateSystemWide(), Float(p.x), Float(p.y), &hit)
            guard hitStatus == .success, let hit, CFEqual(hit, element) else { return refuse("visual_hit_test_mismatch") }
            for n in 1...(op == "cu_double_click" ? 2 : 1) {
                if let refusal = validate(r, b, checkControlState:n == 1) { if posted == 0 { return refusal }; break }
                guard foreground(r, b, pid), topWindow(p, wid) else { break }
                guard let down = CGEvent(mouseEventSource:source, mouseType:.leftMouseDown, mouseCursorPosition:p, mouseButton:.left), let up = CGEvent(mouseEventSource:source, mouseType:.leftMouseUp, mouseCursorPosition:p, mouseButton:.left) else { break }
                down.flags = []; up.flags = []; down.setIntegerValueField(.mouseEventClickState, value:Int64(n)); up.setIntegerValueField(.mouseEventClickState, value:Int64(n))
                down.post(tap:.cghidEventTap); up.post(tap:.cghidEventTap); posted += 2
            }
        } else { return refuse("unsupported_computer_operation") }
        let expectedEvents = op == "cu_double_click" ? 4 : 2
        return ["status": posted == expectedEvents ? "ok" : "error", "action_sent": posted > 0, "posted_events":posted, "before":before, "after":b.environment(), "input_cleanup":"owned_pairs_POSTED_not_delivery_proof"]
    }
    func capture(_ r: [String: Any], _ b: Bridge, _ element: AXUIElement, _ binding: [String: Any]) -> [String: Any] {
        guard CGPreflightScreenCaptureAccess() else { return refuse("screen_capture_permission_missing") }
        guard safeWindow(element), let wid = binding["window_id"] as? UInt32, let path = r["output"] as? String, path.hasPrefix("/"), !FileManager.default.fileExists(atPath:path) else { return refuse("sensitive_or_invalid_capture_target") }
        guard #available(macOS 14.0, *) else { return refuse("ScreenCaptureKit_requires_macos14") }
        var content: SCShareableContent?; var failure: Error?; var done = false
        SCShareableContent.getExcludingDesktopWindows(true, onScreenWindowsOnly: true) { value, error in content=value; failure=error; done=true }
        let deadline = Date(timeIntervalSinceNow:4)
        while !done && Date() < deadline { RunLoop.current.run(until:Date(timeIntervalSinceNow:0.01)) }
        guard done, failure == nil, let window = content?.windows.first(where: {$0.windowID == wid}), window.owningApplication?.processID == binding["pid"] as? pid_t else { return refuse("capture_window_unavailable") }
        let filter = SCContentFilter(desktopIndependentWindow:window)
        let config = SCStreamConfiguration(); config.showsCursor=false; config.ignoreShadowsSingleWindow=true
        config.width=Int(window.frame.width * 2); config.height=Int(window.frame.height * 2)
        guard config.width > 0, config.height > 0, config.width <= 8192, config.height <= 8192 else { return refuse("capture_size_limit") }
        var result: CGImage?; done=false
        SCScreenshotManager.captureImage(contentFilter:filter, configuration:config) { img, error in result=img; failure=error; done=true }
        while !done && Date() < deadline { RunLoop.current.run(until:Date(timeIntervalSinceNow:0.01)) }
        guard done, failure == nil, var image=result else { return refuse("capture_failed_or_timed_out") }
        if let refusal = validate(r, b) { return refusal }
        var crop = [0.0,0.0,Double(image.width),Double(image.height)]
        if let region=r["crop"] as? [Double] {
            guard region.count == 4, region.allSatisfy({$0.isFinite}), region[0]>=0, region[1]>=0, region[2]>0, region[3]>0, region[0]+region[2]<=Double(image.width), region[1]+region[3]<=Double(image.height), let cropped=image.cropping(to:CGRect(x:region[0], y:region[1], width:region[2], height:region[3])) else { return refuse("crop_outside_image") }
            crop=region; image=cropped
        }
        guard let data=NSBitmapImageRep(cgImage:image).representation(using:.png,properties:[:]) else { return refuse("png_encoding_failed") }
        do { try data.write(to:URL(fileURLWithPath:path), options:.withoutOverwriting); try FileManager.default.setAttributes([.posixPermissions:0o600], ofItemAtPath:path) }
        catch { return refuse("capture_output_failed") }
        return ["status":"ok", "path":path, "sha256":SHA256.hash(data:data).map{String(format:"%02x",$0)}.joined(), "width":image.width, "height":image.height, "crop_pixels":crop, "window_binding":binding, "logical_frame":[window.frame.minX,window.frame.minY,window.frame.width,window.frame.height], "full_image_size":[config.width,config.height], "method":"ScreenCaptureKit_window_only", "cloud_sent":false]
    }
}
