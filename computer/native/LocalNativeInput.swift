// Experimental public-API keyboard transport. Derived mechanisms from the accepted
// keyboard PoC: private source + explicit flags + PID Unicode down/up. No focus SPI,
// activation notifications, mouse coordinates, target mutation, or helper broadcast.
import AppKit
import ApplicationServices
import Carbon
import CryptoKit
import Darwin

func nativeBirth(_ pid: pid_t) -> String? {
    var info = proc_bsdinfo()
    let size = MemoryLayout<proc_bsdinfo>.size
    guard proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, Int32(size)) == size else { return nil }
    return "\(info.pbi_start_tvsec).\(info.pbi_start_tvusec)"
}

final class LocalNativeInput {
    struct Target {
        let element: AXUIElement
        let window: AXUIElement
        let pid: pid_t
        let state: [String: Any]
    }
    var sources: [pid_t: (String, CGEventSource)] = [:]
    // This backend owns only Unicode key 0 with empty explicit modifier flags.
    // Buttons/modifiers remain empty because no corresponding action is exposed.
    var ownedKeys: [pid_t: Set<CGKeyCode>] = [:]
    let controller: [String: Any] = ["instance": UUID().uuidString,
        "pid": getpid(), "process_birth": nativeBirth(getpid()) ?? "UNKNOWN"]
    var consumedRequests: Set<String> = []
    var resolutionFailure = "native_target_identity_or_responder_unknown"
    var resolutionDetail: [String: Any] = [:]

    func resolve(_ r: [String: Any], _ b: Bridge) -> Target? {
        resolutionFailure = "native_process_identity_unavailable"
        resolutionDetail = [:]
        guard let app = r["app"] as? String, b.allowed.contains(app),
              let policy = r["policy"] as? [String: String], policy["app"] == app,
              ["NSTextView", "WKWebView", "AppKit_sheet"].contains(policy["kind"] ?? ""),
              let handle = r["handle"] as? String, let element = b.references[handle],
              let pid = b.owners[handle], b.candidates(app) == [pid],
              let running = NSRunningApplication(processIdentifier: pid), !running.isTerminated,
              let birth = nativeBirth(pid) else { return nil }
        resolutionFailure = "native_executable_qualification_mismatch"
        guard running.bundleURL?.standardizedFileURL.path == policy["bundle_path"],
              let executable = running.executableURL, let data = try? Data(contentsOf: executable),
              SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined() == policy["executable_sha256"] else { return nil }
        resolutionFailure = "native_control_role_unqualified"
        guard ["AXTextArea", "AXTextField"].contains(attr(element, "AXRole") as? String ?? ""),
              attr(element, "AXSubrole") as? String != "AXSecureTextField" else { return nil }
        let domTextarea = policy["kind"] == "WKWebView" && policy["dom_identifier"] != nil
        resolutionFailure = "native_control_identifier_mismatch"
        if domTextarea {
            guard policy["identifier"] == nil, attr(element, "AXRole") as? String == "AXTextArea",
                  attr(element, "AXDOMIdentifier") as? String == policy["dom_identifier"] else { return nil }
        } else {
            guard policy["dom_identifier"] == nil,
                  attr(element, "AXIdentifier") as? String == policy["identifier"] else { return nil }
        }
        let root = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(root, 0.75)
        var current: AXUIElement?
        var pathWindow: AXUIElement?
        var inWebArea = false
        resolutionFailure = "native_ax_path_changed"
        for (depth, index) in (b.paths[handle] ?? []).enumerated() {
            let parent = current ?? root
            let children = depth == 0 ? b.rootElements(root, b.rootAttributes[handle] ?? "AXWindows") : attr(parent, "AXChildren") as? [AXUIElement] ?? []
            guard index >= 0, index < children.count else { return nil }
            current = children[index]
            if attr(current!, "AXRole") as? String == "AXWebArea" { inWebArea = true }
            // AXSheet may be a child of its owning AXWindow. AXWindow on the
            // leaf refers to that owner, not necessarily the sheet AX element.
            if attr(current!, "AXRole") as? String == "AXWindow" { pathWindow = current }
        }
        guard let current, CFEqual(current, element) else { return nil }
        resolutionFailure = "native_responder_unverified"
        var focused: CFTypeRef?
        let focusStatus = AXUIElementCopyAttributeValue(root, "AXFocusedUIElement" as CFString, &focused)
        resolutionDetail = ["focus_ax_error": focusStatus.rawValue,
                            "focused_element_matches": focused.map { CFGetTypeID($0) == AXUIElementGetTypeID() && CFEqual($0, element) } ?? false]
        let responderSource: String
        if focusStatus == .success, let focused {
            guard CFGetTypeID(focused) == AXUIElementGetTypeID(), CFEqual(focused, element) else { return nil }
            responderSource = "AXFocusedUIElement"
        } else {
            // WK's remote AX textarea has a local focus bit while the host app's
            // AXFocusedUIElement is unavailable. Require the exact observed leaf
            // under its WebArea; never infer focus from DOM id or host responder.
            guard focusStatus == .noValue, domTextarea, inWebArea, attr(element, "AXFocused") as? Bool == true else { return nil }
            responderSource = "WK_AXFocused_under_WebArea"
        }
        resolutionFailure = "native_window_identity_unavailable"
        guard let windowValue = attr(element, "AXWindow") as CFTypeRef?,
              CFGetTypeID(windowValue) == AXUIElementGetTypeID() else { return nil }
        let window = unsafeBitCast(windowValue, to: AXUIElement.self)
        resolutionFailure = "native_control_window_binding_mismatch"
        guard let pathWindow, CFEqual(pathWindow, window) else { return nil }
        // AppKit can export AXFocusedUIElement after makeMainWindow while PID
        // keyboard events still have windowNumber=0. A first responder or local
        // focus bit alone does not establish the keyboard routing window. Read
        // only: the host must never make another app key/main or activate it.
        var responderProof: [String: Any] = ["source": responderSource,
            "focus_ax_error": focusStatus.rawValue, "path_window_matches": true]
        if policy["kind"] == "NSTextView" {
            var focusedWindow: CFTypeRef?
            let windowFocusStatus = AXUIElementCopyAttributeValue(root, "AXFocusedWindow" as CFString, &focusedWindow)
            let matches = focusedWindow.map { CFGetTypeID($0) == AXUIElementGetTypeID() && CFEqual($0, window) } ?? false
            resolutionDetail["focused_window_ax_error"] = windowFocusStatus.rawValue
            resolutionDetail["focused_window_matches"] = matches
            resolutionFailure = "native_keyboard_window_unverified"
            guard windowFocusStatus == .success, matches else { return nil }
            responderProof["focused_window_ax_error"] = windowFocusStatus.rawValue
            responderProof["focused_window_matches"] = true
        }
        resolutionFailure = "native_window_identity_unavailable"
        guard attr(window, "AXTitle") as? String == policy["window_title"],
              let posValue = attr(window, "AXPosition") as CFTypeRef?, CFGetTypeID(posValue) == AXValueGetTypeID(),
              let sizeValue = attr(window, "AXSize") as CFTypeRef?, CFGetTypeID(sizeValue) == AXValueGetTypeID() else { return nil }
        var point = CGPoint.zero; var size = CGSize.zero
        guard AXValueGetValue(unsafeBitCast(posValue, to: AXValue.self), .cgPoint, &point),
              AXValueGetValue(unsafeBitCast(sizeValue, to: AXValue.self), .cgSize, &size) else { return nil }
        // Match AX window geometry to public WindowServer ownership. Ambiguity is UNKNOWN.
        let windows = CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
        let matches = windows.filter { row in
            guard row[kCGWindowOwnerPID as String] as? Int32 == pid,
                  let raw = row[kCGWindowBounds as String] as? [String: Any],
                  let rect = CGRect(dictionaryRepresentation: raw as CFDictionary) else { return false }
            return rect == CGRect(origin: point, size: size)
        }
        resolutionFailure = "native_window_geometry_ambiguous"
        guard matches.count == 1, let wid = matches[0][kCGWindowNumber as String] as? UInt32 else { return nil }
        return Target(element: element, window: window, pid: pid, state: [
            "app": app, "pid": pid, "process_birth": birth, "window_id": wid, "controller": controller,
            "geometry": [point.x, point.y, size.width, size.height], "epoch": b.epoch,
            "control_fingerprint": String(data: encode(identity(element)), encoding: .utf8) ?? "",
            "window_fingerprint": String(data: encode(identity(window)), encoding: .utf8) ?? "",
            "responder_proof": responderProof, "ax_path": b.paths[handle] ?? [],
            "root_attribute": b.rootAttributes[handle] ?? "AXWindows",
            "kind": policy["kind"]!, "handle": handle])
    }

    func execute(_ r: [String: Any], bridge b: Bridge) -> [String: Any] {
        if r["op"] as? String == "native_process_status" {
            guard let app = r["app"] as? String, b.allowed.contains(app),
                  let raw = r["pid"] as? Int, raw > 0, raw <= Int(Int32.max),
                  let expected = r["process_birth"] as? String, !expected.isEmpty, expected != "UNKNOWN" else {
                return ["status": "error", "reason": "process_identity_unavailable"]
            }
            let pid = pid_t(raw)
            if let current = nativeBirth(pid) {
                return ["status": "ok", "pid": raw, "process_birth": expected,
                        "current_birth": current, "old_generation_exited": current != expected,
                        "evidence": "proc_pidinfo_birth"]
            }
            errno = 0
            let result = Darwin.kill(pid, 0)
            guard result == -1, errno == ESRCH else {
                return ["status": "error", "reason": "process_exit_unknown"]
            }
            return ["status": "ok", "pid": raw, "process_birth": expected,
                    "old_generation_exited": true, "evidence": "kill_zero_ESRCH"]
        }
        guard r["op"] as? String == "native_text" else { return executeInput(r, bridge: b) }
        let requestID = r["request_id"] as? String ?? ""
        let expected = r["target"] as? [String: Any] ?? [:]
        guard encode(expected["controller"] ?? [:]) == encode(controller),
              requestID.count == 32, requestID.allSatisfy({ "0123456789abcdef".contains($0) }),
              !consumedRequests.contains(requestID), consumedRequests.count < 4096 else {
            // No proof for a duplicate: it may name an earlier posted request.
            return ["status": "error", "error": "capability_rejected", "reason": "native_controller_or_request_fenced",
                    "action_sent": false, "input_cleanup": ["status": "error", "cleanup": "UNKNOWN"]]
        }
        consumedRequests.insert(requestID) // Terminal even on rejection. Never retry.
        var result = executeInput(r, bridge: b)
        if result["action_sent"] as? Bool == false,
           let cleanup = result["input_cleanup"] as? [String: Any], cleanup["status"] as? String == "ok",
           ownedKeys.values.allSatisfy({ $0.isEmpty }),
           let path = r["receipt_path"] as? String, let pid = expected["pid"] as? Int32,
           let fence = r["fence"] as? String, !fence.isEmpty,
           let lease = r["lease"] as? String, let owner = r["owner"] as? String {
            let url = URL(fileURLWithPath: path)
            var info = stat()
            // The recovery directory is host-owned, never a model workspace.
            let directory = url.deletingLastPathComponent().path
            let privateDirectory = lstat(directory, &info) == 0 &&
                info.st_mode & S_IFMT == S_IFDIR && info.st_uid == getuid() && info.st_mode & 0o077 == 0
            let proof: [String: Any] = ["version": 1, "kind": "NO_DISPATCH", "terminal": true,
                "posted_events": 0, "request_id": requestID, "fence": fence, "lease": lease, "owner": owner,
                "target_identity": expected, "controller": controller,
                "input_cleanup": ["status": "ok", "cleanup": "no_owned_inputs", "keys": [], "buttons": [], "modifiers": []]]
            if privateDirectory && url.lastPathComponent == "\(pid).\(requestID).no-dispatch.json" {
                let fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)
                if fd >= 0 {
                    let data = encode(proof)
                    let written = data.withUnsafeBytes { Darwin.write(fd, $0.baseAddress, data.count) }
                    let durableFile = written == data.count && fsync(fd) == 0
                    close(fd)
                    let directoryFD = open(directory, O_RDONLY)
                    let durableDirectory = directoryFD >= 0 && fsync(directoryFD) == 0
                    if directoryFD >= 0 { close(directoryFD) }
                    result["no_dispatch_receipt"] = durableFile && durableDirectory ? "durable" : "UNKNOWN"
                } else { result["no_dispatch_receipt"] = "UNKNOWN" }
            }
        }
        return result
    }

    func executeInput(_ r: [String: Any], bridge b: Bridge) -> [String: Any] {
        resolutionDetail = [:]
        func rejected(_ reason: String) -> [String: Any] {
            ["status": "error", "error": "capability_rejected", "reason": reason,
             "qualification_detail": resolutionDetail,
             "action_sent": false, "input_cleanup": ["status": "ok", "cleanup": "no_owned_inputs"]]
        }
        guard AXIsProcessTrusted() else { return rejected("accessibility_not_trusted") }
        guard let target = resolve(r, b) else { return rejected(resolutionFailure) }
        if r["op"] as? String == "native_context" {
            guard b.identities[r["handle"] as? String ?? ""] == encode(identity(target.element)) else { return rejected("native_observation_fingerprint_changed") }
            // Retired processes must not accumulate private event sources. Never
            // discard an outstanding owned-key cleanup obligation.
            for (pid, entry) in sources where nativeBirth(pid) != entry.0 && ownedKeys[pid, default: []].isEmpty {
                sources.removeValue(forKey: pid)
                ownedKeys.removeValue(forKey: pid)
            }
            return ["status": "ok", "target": target.state,
                    "recovery_readiness": ["event_access": CGPreflightPostEventAccess(),
                                           "secure_event_input": IsSecureEventInputEnabled()],
                    "resource_counts": ["event_sources": sources.count, "owned_key_targets": ownedKeys.count]]
        }
        guard ownedKeys[target.pid, default: []].isEmpty else {
            return ["status": "error", "error": "input_cleanup_unknown", "action_sent": false,
                    "input_cleanup": ["status": "error", "cleanup": "UNKNOWN",
                                      "keys": Array(ownedKeys[target.pid, default: []]), "buttons": [], "modifiers": []]]
        }
        guard let expected = r["target"] as? [String: Any], encode(expected) == encode(target.state),
              let text = r["text"] as? String, !text.isEmpty, text.utf16.count <= 64,
              let stop = r["stop_path"] as? String, stop.hasPrefix("/"),
              let lease = r["lease"] as? String, !lease.isEmpty,
              let owner = r["owner"] as? String, !owner.isEmpty,
              let requestID = r["request_id"] as? String, !requestID.isEmpty,
              let remaining = r["lease_remaining"] as? Double, remaining.isFinite, remaining > 0, remaining <= 120 else { return rejected("native_expected_identity_or_request_mismatch") }
        let deadline = ProcessInfo.processInfo.systemUptime + remaining
        let before = b.environment()
        func processValid() -> Bool {
            nativeBirth(target.pid) == target.state["process_birth"] as? String &&
            NSRunningApplication(processIdentifier: target.pid)?.bundleIdentifier == target.state["app"] as? String
        }
        func safe() -> Bool {
            let env = b.environment()
            // A live orphaned controller must still hold the exact durable
            // dispatch authorization, even if its Python owner has exited.
            guard let path = r["receipt_path"] as? String,
                  let data = try? Data(contentsOf: URL(fileURLWithPath: path).deletingLastPathComponent()
                    .appendingPathComponent("\(target.pid).lock.state")),
                  let intent = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
                  intent["status"] as? String == "uncertain",
                  intent["request_id"] as? String == requestID,
                  intent["owner"] as? String == owner, intent["lease"] as? String == lease,
                  intent["fence"] as? String == r["fence"] as? String,
                  encode(intent["controller"] ?? [:]) == encode(controller),
                  encode(intent["target_identity"] ?? [:]) == encode(expected) else { return false }
            guard !FileManager.default.fileExists(atPath: stop), ProcessInfo.processInfo.systemUptime < deadline,
                  processValid(), !IsSecureEventInputEnabled(), AXIsProcessTrusted(), CGPreflightPostEventAccess(),
                  env["locked"] as? Bool == false, env["session_available"] as? Bool == true,
                  (env["frontmost_pid"] as? Int32 ?? -1) > 0,
                  env["frontmost_app"] as? String != "UNKNOWN",
                  encode(["id": env["session_id"] ?? NSNull()]) == encode(["id": before["session_id"] ?? NSNull()]),
                  env["frontmost_pid"] as? Int32 != target.pid,
                  env["frontmost_app"] as? String != target.state["app"] as? String,
                  let fresh = resolve(r, b), CFEqual(fresh.element, target.element), CFEqual(fresh.window, target.window) else { return false }
            // Text changes caused by this dispatch are allowed; window/process/generation must remain exact.
            var a = fresh.state; var c = target.state
            a.removeValue(forKey: "control_fingerprint"); c.removeValue(forKey: "control_fingerprint")
            return encode(a) == encode(c)
        }
        guard safe() else { return rejected("native_dispatch_safety_boundary_rejected") }
        let birth = target.state["process_birth"] as! String
        if sources[target.pid]?.0 != birth {
            guard let source = CGEventSource(stateID: .privateState) else { return rejected("native_event_source_unavailable") }
            sources[target.pid] = (birth, source)
        }
        let source = sources[target.pid]!.1
        let units = Array(text.utf16)
        guard let down = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: true),
              let up = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: false) else { return rejected("native_event_unavailable") }
        for event in [down, up] {
            event.flags = []  // Never merge HID/session physical modifiers.
            event.keyboardSetUnicodeString(stringLength: units.count, unicodeString: units)
            event.setIntegerValueField(.eventSourceUserData, value: 0x4c504e42)
        }
        // Admission stops before down. Once owned, up is cleanup even on takeover/frontmost change.
        guard safe() else { return rejected("native_dispatch_safety_boundary_rejected") }
        ownedKeys[target.pid, default: []].insert(0)
        down.postToPid(target.pid)
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.025))
        let continued = safe()
        // Release only to the same process/window/control. No release to a reused PID.
        let releaseTarget = processValid() ? resolve(r, b) : nil
        let canRelease = releaseTarget.map { fresh in
            CFEqual(fresh.element, target.element) && CFEqual(fresh.window, target.window) &&
            fresh.state["window_id"] as? UInt32 == target.state["window_id"] as? UInt32
        } ?? false
        if canRelease {
            up.postToPid(target.pid)
            ownedKeys[target.pid, default: []].remove(0)
            if ownedKeys[target.pid, default: []].isEmpty { ownedKeys.removeValue(forKey: target.pid) }
        }
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.04))
        return ["status": continued && canRelease ? "ok" : "error",
            "error": continued && canRelease ? NSNull() : "native_dispatch_interrupted",
            "action_sent": true, "dispatch_stage": "POSTED", "posted_events": canRelease ? 2 : 1,
            "request_id": requestID, "target_tap": "NOT_RUN", "before": before, "after": b.environment(),
            "input_cleanup": ["status": canRelease ? "ok" : "error",
                              "cleanup": canRelease ? "owned_key_up_POSTED" : "UNKNOWN",
                              "keys": Array(ownedKeys[target.pid, default: []]), "buttons": [], "modifiers": []]]
    }
}
