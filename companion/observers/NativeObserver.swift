// Read-only protocol surface. No AX setters/actions, Apple Events, CG input,
// arbitrary commands, file reads, network clients, app launches or activation.
// Accessibility authorization is broader than this API; no OS sandbox claim.
import AppKit
import ApplicationServices
import Foundation
import Darwin
import CryptoKit

let blockedApps: Set<String> = ["com.apple.keychainaccess", "com.agilebits.onepassword-osx", "com.1password.1password", "com.bitwarden.desktop", "io.localpilot.companion.ui"]
let secretPattern = "password|passwd|passphrase|cookie|keychain|credential|(?:access|refresh|login|auth|bearer)[ _-]*token|api[ _-]*key|authorization\\s*:|bearer\\s+\\S+|sk-[A-Za-z0-9_-]{12,}|-----BEGIN[^\\n]*PRIVATE KEY|密码|口令|密钥|令牌"
let secretRegex = try! NSRegularExpression(pattern: secretPattern, options: [.caseInsensitive])
let sensitiveWindowPattern = secretPattern + "|(?:^|[/_. -])(?:id_rsa|id_ed25519|secrets?|credentials?)(?:$|[/_. -])|\\.(?:env|pem|key|p12|pfx)(?:$|\\s|[—–-])"
let sensitiveWindowRegex = try! NSRegularExpression(pattern: sensitiveWindowPattern, options: [.caseInsensitive])
struct ApplicationReadProfile {
    let id: String
    let deniedRoles: Set<String>
    let deniedSubroles: Set<String> = ["AXSecureTextField", "AXDialog", "AXSystemDialog"]
    static func forBundle(_ bundle: String) -> ApplicationReadProfile {
        let names = ["com.apple.finder": "finder", "com.apple.Safari": "safari", "com.google.Chrome": "chrome",
            "org.chromium.Chromium": "chrome", "com.microsoft.VSCode": "vscode", "com.microsoft.VSCodeInsiders": "vscode",
            "com.apple.Preview": "preview", "com.apple.TextEdit": "textedit"]
        let id = names[bundle] ?? "generic"
        var roles: Set<String> = ["AXSheet", "AXDialog", "AXPopover"]
        if id == "vscode" { roles.formUnion(["AXOutline", "AXTable"]) }
        return ApplicationReadProfile(id: id, deniedRoles: roles)
    }
}
// This decorates attribute reads, while AXReadEngine remains the only walker.
// Rejected role/subrole/window eligibility never reads descendants or values.
final class ProfileReadGuard<Element> {
    let base: AXReadProvider<Element>
    let profile: ApplicationReadProfile
    let content: Bool
    let exactTitles: Set<String>
    var identities: [(Element, String)] = []
    var denied: [Element] = []
    var windowTitles: [(Element, String)] = []
    var prunedCount = 0
    var titleEligibilityFailed = false
    init(base: AXReadProvider<Element>, bundle: String, content: Bool, exactTitles: Set<String>) {
        self.base = base; self.profile = .forBundle(bundle); self.content = content; self.exactTitles = exactTitles
    }
    func qualified(_ title: String) -> Bool {
        title.count <= 300 && !title.unicodeScalars.contains(where: { $0.value < 32 }) &&
        sensitiveWindowRegex.firstMatch(in: title, range: NSRange(title.startIndex..., in: title)) == nil &&
        (exactTitles.isEmpty || exactTitles.contains(title))
    }
    func deny(_ element: Element) -> AXAttributeRead {
        if !denied.contains(where: { base.equal($0, element) }) { denied.append(element); prunedCount += 1 }
        return AXAttributeRead(value: nil, error: -90006, status: .unknown)
    }
    func read(_ element: Element, _ attribute: String) -> AXAttributeRead {
        if denied.contains(where: { base.equal($0, element) }) { return deny(element) }
        let role = identities.first(where: { base.equal($0.0, element) })?.1
        if role == "AXWindow", attribute == "AXSubrole", content || !exactTitles.isEmpty {
            guard windowTitles.count < 8 else { return deny(element) }
            let title = base.read(element, "AXTitle")
            guard title.succeeded, let text = title.value as? String, qualified(text) else {
                titleEligibilityFailed = true; return deny(element)
            }
            windowTitles.append((element, text))
        }
        let result = base.read(element, attribute)
        if attribute == "AXRole", result.succeeded, let role = result.value as? String {
            identities.append((element, role))
            if profile.deniedRoles.contains(role) { return deny(element) }
        }
        if attribute == "AXSubrole", result.succeeded, let subrole = result.value as? String,
           profile.deniedSubroles.contains(subrole), subrole != "AXSecureTextField" { return deny(element) }
        return result
    }
    func provider() -> AXReadProvider<Element> {
        AXReadProvider(read: { self.read($0, $1) }, elements: base.elements, equal: base.equal)
    }
    func titlesStillQualified() -> Bool {
        windowTitles.allSatisfy { element, expected in
            let read = base.read(element, "AXTitle")
            return read.succeeded && read.value as? String == expected && qualified(expected)
        }
    }
}
func safeText(_ text: String?, _ limit: Int = 300) -> String? {
    guard let text = text, secretRegex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) == nil else { return nil }
    guard !text.unicodeScalars.contains(where: { $0.value < 32 && $0 != "\n" && $0 != "\t" }) else { return nil }
    return String(text.prefix(limit))
}
struct Options {
    let allowlist: Set<String>
    let exclusions: Set<String>
    let content: Set<String>
    let windowExclusions: Set<String>
    let contentWindowAllowlist: Set<String>
    let ax: Bool
    let lowPower: Bool
    let allApps: Bool
    let allContent: Bool
    let maxNodes: Int
    let maxDepth: Int
    let parent: pid_t
    init(_ data: [String: Any]) {
        allowlist = Set((data["allowlist"] as? [String] ?? []).prefix(100))
        exclusions = Set((data["exclusions"] as? [String] ?? []).prefix(100))
        content = Set((data["content_allowlist"] as? [String] ?? []).prefix(100)).intersection(allowlist)
        windowExclusions = Set((data["window_exclusions"] as? [String] ?? []).prefix(100))
        contentWindowAllowlist = Set((data["content_window_allowlist"] as? [String] ?? []).prefix(100))
        lowPower = data["low_power"] as? Bool ?? true
        ax = data["ax_enabled"] as? Bool ?? false
        allApps = data["all_apps"] as? Bool ?? false
        allContent = allApps && (data["all_content"] as? Bool ?? false)
        maxNodes = min(512, max(1, data["max_nodes"] as? Int ?? 80))
        maxDepth = min(16, max(1, data["max_depth"] as? Int ?? 5))
        parent = pid_t(data["parent_pid"] as? Int ?? Int(getppid()))
    }
    func allowed(_ bundle: String) -> Bool {
        bundle.range(of: "^[A-Za-z0-9_-]+(?:\\.[A-Za-z0-9_-]+)+$", options: .regularExpression) != nil && (allApps || allowlist.contains(bundle)) && !exclusions.contains(bundle) && !blockedApps.contains(bundle.lowercased()) && safeText(bundle) != nil
    }
    func contentAllowed(_ bundle: String) -> Bool { allowed(bundle) && (allContent || content.contains(bundle)) }
}
func emit(_ source: String, _ kind: String, _ object: [String: Any], _ evidence: [String: Any], content: Bool = false) {
    let value: [String: Any] = ["timestamp": ISO8601DateFormatter().string(from: Date()),
        "source": source, "kind": kind, "object": object, "evidence": evidence,
        "confidence": kind == "ax.snapshot" ? 0.8 : 1.0,
        "sensitivity": content ? "content" : "metadata", "dedupe_key": "python-recomputed"]
    if let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]), data.count < 128 * 1024 {
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data([10]))
    }
}
func permission() -> Bool {
    AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: false] as CFDictionary)
}
func status(_ ax: Bool) {
    emit("macos.observer", "observation.status", ["type": "system"],
         ["ax_permission": ax ? (permission() ? "granted" : "MANUAL_REQUIRED") : "disabled", "lock_state": "UNKNOWN", "coverage": "PARTIAL"])
}
func readInput() -> [String: Any] {
    var data = Data()
    let limit = 128 * 1024
    while data.count <= limit {
        do {
            guard let chunk = try FileHandle.standardInput.read(upToCount: min(8192, limit + 1 - data.count)) else { break }
            if chunk.isEmpty { break }
            data.append(chunk)
        } catch { exit(2) }
    }
    if data.count > limit { exit(2) }
    return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
}

// Fixture provider implements only attribute lookup. The shared engine performs
// the sole traversal for both scripted trees and real AX elements.
final class FixtureElement {
    let data: [String: Any]
    let name: String
    let focused: FixtureElement?
    init(_ data: [String: Any], name: String = "window", focused: FixtureElement? = nil) {
        self.data = data; self.name = data["fixture_id"] as? String ?? name; self.focused = focused
    }
}
func readPolicy(_ options: Options, _ content: Bool, focusedWindowOnly: Bool = true) -> AXReadPolicy {
    .observer(contentAllowed: content, excludedWindowTitles: options.windowExclusions, focusedWindowOnly: focusedWindowOnly)
}
func readLimits(_ options: Options) -> AXReadLimits {
    AXReadLimits(maxNodes: options.maxNodes, maxDepth: options.maxDepth, maxCharacters: 4000, maxSeconds: 0.35)
}
func targetMatches(pid: pid_t, bundle: String, livePID: pid_t?, liveBundle: String?,
                   terminated: Bool, frontPID: pid_t?, frontBundle: String?) -> Bool {
    pid > 0 && !bundle.isEmpty && !terminated && livePID == pid && liveBundle == bundle
        && frontPID == pid && frontBundle == bundle
}
func liveTarget(_ pid: pid_t, _ bundle: String) -> Bool {
    let live = NSRunningApplication(processIdentifier: pid)
    let front = NSWorkspace.shared.frontmostApplication
    return targetMatches(pid: pid, bundle: bundle, livePID: live?.processIdentifier, liveBundle: live?.bundleIdentifier,
        terminated: live?.isTerminated ?? true, frontPID: front?.processIdentifier, frontBundle: front?.bundleIdentifier)
}
struct ControlledTarget {
    let pid: pid_t
    let bundle: String
    let bundleURL: String
    let launchTime: Double
    let owner: pid_t
    let digest: String
    init?(_ data: [String: Any]) {
        guard let pid = data["pid"] as? Int, pid > 0, let owner = data["owner_pid"] as? Int, owner > 0,
              let bundle = data["bundle_id"] as? String, bundle.hasPrefix("org.localpilot.companion.validation."),
              let path = data["bundle_url"] as? String, path.hasPrefix("/"), path.hasSuffix(".app"),
              !path.unicodeScalars.contains(where: { $0.value < 32 }),
              let launch = data["launch_time"] as? Double, launch.isFinite, launch > 0 else { return nil }
        self.pid = pid_t(pid); self.owner = pid_t(owner); self.bundle = bundle; self.bundleURL = path; self.launchTime = launch
        let identity = [String(pid), bundle, path, String(format: "%.6f", locale: Locale(identifier: "en_US_POSIX"), launch), String(owner)].joined(separator: "\n")
        self.digest = SHA256.hash(data: Data(identity.utf8)).map { String(format: "%02x", $0) }.joined()
    }
    func live() -> Bool {
        var birth = proc_bsdinfo()
        guard proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &birth, Int32(MemoryLayout<proc_bsdinfo>.size)) == MemoryLayout<proc_bsdinfo>.size,
              birth.pbi_ppid == owner, birth.pbi_uid == getuid() else { return false }
        let created = Double(birth.pbi_start_tvsec) + Double(birth.pbi_start_tvusec) / 1000000
        guard kill(owner, 0) == 0, let app = NSRunningApplication(processIdentifier: pid), !app.isTerminated,
              app.bundleIdentifier == bundle, app.bundleURL?.path == bundleURL,
              abs(created - launchTime) < 0.00001 else { return false }
        return true
    }
}
// Explicit read-only diagnostic scope, never an owned-target impersonation.
// It binds the ordinary app's actual process lifetime and bundle identity.
struct ApplicationInspectionTarget {
    let pid: pid_t
    let bundle: String
    let launchTime: Double
    init?(_ data: [String: Any]) {
        guard let pid = data["pid"] as? Int, pid > 0,
              let bundle = data["bundle_id"] as? String, !bundle.isEmpty,
              let launch = data["launch_time"] as? Double, launch.isFinite, launch > 0 else { return nil }
        self.pid = pid_t(pid); self.bundle = bundle; self.launchTime = launch
    }
    func live() -> Bool {
        var birth = proc_bsdinfo()
        guard proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &birth, Int32(MemoryLayout<proc_bsdinfo>.size)) == MemoryLayout<proc_bsdinfo>.size,
              birth.pbi_uid == getuid(), let app = NSRunningApplication(processIdentifier: pid),
              !app.isTerminated, app.bundleIdentifier == bundle else { return false }
        let created = Double(birth.pbi_start_tvsec) + Double(birth.pbi_start_tvusec) / 1000000
        return abs(created - launchTime) < 0.00001
    }
}
func observerEvidence(_ result: [String: Any], coverage: String) -> [String: Any] {
    var evidence: [String: Any] = ["coverage": coverage, "lock_state": "UNKNOWN"]
    for key in ["read_status", "complete", "structural_complete", "attributes_complete", "content_truncated", "read_errors", "node_count", "truncated", "read_scope", "window_coverage"] {
        evidence[key] = result[key]
    }
    evidence["shared_core_version"] = result["shared_ax_version"]
    evidence["pruned_count"] = result["privacy_pruned_subtrees"]
    evidence["read_error_count"] = (result["read_errors"] as? [[String: Any]] ?? []).count + (result["omitted_read_errors"] as? Int ?? 0)
    evidence["elapsed_ms"] = (result["read_elapsed_seconds"] as? Double ?? 0) * 1000
    var nodes = [[String: Any]]()
    for node in result["nodes"] as? [[String: Any]] ?? [] {
        var clean: [String: Any] = [:]
        for key in ["id", "parent", "role", "subrole", "children_read_status"] { clean[key] = node[key] }
        if let text = safeText(node["text"] as? String, 500) { clean["text"] = text }
        if node["role"] as? String == "AXWindow", let title = safeText(node["title"] as? String) { evidence["window_title"] = title }
        nodes.append(clean)
    }
    evidence["nodes"] = nodes
    return evidence
}
func fixtureSnapshot(_ tree: [String: Any], title: String?, _ options: Options, _ content: Bool, trace: Bool) -> [String: Any] {
    var root = tree
    if let title { root["title"] = title }
    let application = FixtureElement(["read_failures": tree["application_read_failures"] ?? [:]], name: "application", focused: FixtureElement(root))
    var getters = [[String: Any]]()
    var targetValid = tree["fixture_target_valid"] as? Bool ?? true
    let targetChangeAfter = tree["fixture_target_changes_after_getters"] as? Int
    let provider = AXReadProvider<FixtureElement>(read: { item, attribute in
        if let threshold = targetChangeAfter, getters.count >= threshold { targetValid = false }
        guard targetValid else { return AXAttributeRead(value: nil, error: -90005, status: .unknown) }
        if trace { getters.append(["node": item.name, "attribute": attribute]) }
        if let failures = item.data["read_failures"] as? [String: Int], let code = failures[attribute] {
            return AXAttributeRead(value: nil, error: code)
        }
        if attribute == "AXFocusedWindow" { return AXAttributeRead(value: item.focused.map { [$0] } ?? []) }
        let keys = ["AXRole": "role", "AXSubrole": "subrole", "AXTitle": "title", "AXValue": "value"]
        if let key = keys[attribute] {
            if let value = item.data[key] { return AXAttributeRead(value: value) }
            return AXAttributeRead(value: nil, error: -25205)
        }
        if attribute == "AXChildren" {
            guard let raw = item.data["children"] else { return AXAttributeRead(value: [FixtureElement](), status: .successEmpty) }
            guard let children = raw as? [[String: Any]] else { return AXAttributeRead(value: "malformed") }
            return AXAttributeRead(value: children.enumerated().map { FixtureElement($0.element, name: item.name + "." + String($0.offset)) })
        }
        return AXAttributeRead(value: nil, error: -25205)
    }, elements: { $0 as? [FixtureElement] }, equal: { $0 === $1 })
    let bundle = tree["fixture_bundle"] as? String ?? "org.localpilot.synthetic"
    let profile = ProfileReadGuard(base: provider, bundle: bundle, content: content, exactTitles: options.contentWindowAllowlist)
    let result = AXReadEngine(provider: profile.provider(), policy: readPolicy(options, content), limits: readLimits(options)).snapshot(application: application)
    var evidence = observerEvidence(result, coverage: "MOCK_ONLY")
    evidence["application_profile"] = profile.profile.id; evidence["profile_version"] = 1
    evidence["profile_pruned_count"] = profile.prunedCount
    if !targetValid {
        evidence["nodes"] = [[String: Any]](); evidence["node_count"] = 0
        evidence["read_status"] = "UNKNOWN"; evidence["complete"] = false
        evidence["structural_complete"] = false; evidence["attributes_complete"] = false
        evidence["reason"] = "target_changed_during_read"
        evidence.removeValue(forKey: "window_title")
    }
    if trace { evidence["getter_trace"] = getters }
    return evidence
}
func runFixture(_ data: [String: Any], appKit: Bool = false) {
    let options = Options(data["config"] as? [String: Any] ?? [:])
    var events = data["events"] as? [[String: Any]] ?? []
    if appKit {
        // These controls never enter a displayed NSWindow or become first responder.
        let editor = NSTextView(frame: .zero); editor.string = "SYNTHETIC editor value MUST NOT EMIT"
        let secure = NSSecureTextField(frame: .zero); secure.stringValue = "SYNTHETIC password MUST NOT EMIT"
        let label = NSTextField(labelWithString: "Synthetic project status ready")
        let tree: [String: Any] = ["role": "AXWindow", "children": [
            ["role": "AXStaticText", "value": label.stringValue],
            ["role": "AXTextArea", "value": editor.string],
            ["role": "AXTextField", "subrole": "AXSecureTextField", "value": secure.stringValue]]]
        events = [["bundle_id": "org.localpilot.synthetic", "kind": "ax.snapshot", "tree": tree, "title": "Synthetic fixture"]]
    }
    for event in events.prefix(100) {
        let bundle = event["bundle_id"] as? String ?? ""
        guard options.allowed(bundle) else { continue }
        let kind = event["kind"] as? String ?? "ax.snapshot"
        let content = options.ax && options.contentAllowed(bundle)
        var evidence: [String: Any] = ["coverage": "MOCK_ONLY", "fixture_origin": appKit ? "synthetic_appkit_controls" : "synthetic_json", "lock_state": "UNKNOWN"]
        if options.ax, var tree = event["tree"] as? [String: Any] {
            tree["fixture_bundle"] = bundle
            evidence.merge(fixtureSnapshot(tree, title: event["title"] as? String, options, content, trace: data["trace"] as? Bool ?? false)) { _, new in new }
        }
        emit(kind == "ax.snapshot" ? "macos.ax" : "macos.workspace", kind, ["bundle_id": bundle, "pid": Int(getpid())], evidence, content: content)
    }
}

// Independent state flags prevent a screen-wake notification from clearing a
// session-inactive suspension. None of these flags asserts that a lock occurred.
struct SessionState {
    var screenInactive = false
    var sessionInactive = false
    var sleepInactive = false
    var suspended: Bool { screenInactive || sessionInactive || sleepInactive }
    mutating func update(_ kind: String) {
        switch kind {
        case "system.screens_sleep": screenInactive = true
        case "system.screens_wake": screenInactive = false
        case "session.resigned_active": sessionInactive = true
        case "session.became_active": sessionInactive = false
        case "system.will_sleep": sleepInactive = true
        case "system.did_wake": sleepInactive = false
        default: break
        }
    }
}
func fixtureSession(_ data: [String: Any]) {
    var state = SessionState()
    for kind in (data["events"] as? [String] ?? []).prefix(100) {
        state.update(kind)
        emit("macos.observer", "observation.status", ["type": "system"],
             ["coverage": "MOCK_ONLY", "notification": kind, "reason": state.suspended ? "suspended" : "active", "lock_state": "UNKNOWN"])
    }
}
func watchParent(_ parent: pid_t) -> DispatchSourceProcess {
    if getppid() != parent || kill(parent, 0) != 0 { exit(0) }
    let monitor = DispatchSource.makeProcessSource(identifier: parent, eventMask: .exit, queue: .main)
    monitor.setEventHandler { exit(0) }
    monitor.resume()
    // Close the race where the parent exited immediately before registration.
    if getppid() != parent || kill(parent, 0) != 0 { exit(0) }
    return monitor
}

final class Observer {
    let options: Options
    let controlled: ControlledTarget?
    let inspection: ApplicationInspectionTarget?
    var tokens = [NSObjectProtocol]()
    var axObserver: AXObserver?
    var observedPID: pid_t = 0
    var activeBundle = ""
    var session = SessionState()
    var suspended: Bool { session.suspended }
    var snapshotPending = false
    var parentMonitor: DispatchSourceProcess?
    var unsupported = 0
    var notificationCount = 0
    var coalescedNotifications = 0
    var snapshotCount = 0
    var stableReads = 0
    var lastReadDigest = ""
    var lastReadTime: TimeInterval = 0
    var contextRefreshTimer: Timer?
    var registeredWindows = [AXUIElement]()
    init(_ options: Options, controlled: ControlledTarget? = nil, inspection: ApplicationInspectionTarget? = nil) {
        self.options = options; self.controlled = controlled; self.inspection = inspection
    }
    func targetLive(_ pid: pid_t, _ bundle: String) -> Bool {
        if let target = controlled { return target.pid == pid && target.bundle == bundle && target.live() }
        if let target = inspection { return target.pid == pid && target.bundle == bundle && target.live() }
        return liveTarget(pid, bundle)
    }
    func attachCurrentTarget() {
        observeForeground(controlled.map { NSRunningApplication(processIdentifier: $0.pid) } ?? NSWorkspace.shared.frontmostApplication)
    }
    func detachAX() {
        if let observer = axObserver { CFRunLoopRemoveSource(CFRunLoopGetMain(), AXObserverGetRunLoopSource(observer), .defaultMode) }
        stableReads = 0; lastReadDigest = ""; lastReadTime = 0
        axObserver = nil; observedPID = 0; activeBundle = ""; registeredWindows = []
    }
    func observeForeground(_ app: NSRunningApplication?) {
        detachAX()
        guard !suspended, options.ax, let app = app, let bundle = app.bundleIdentifier,
              options.allowed(bundle), targetLive(app.processIdentifier, bundle), permission() else { return }
        activeBundle = bundle; observedPID = app.processIdentifier
        var observer: AXObserver?
        let callback: AXObserverCallback = { _, _, _, refcon in
            guard let refcon = refcon else { return }
            Unmanaged<Observer>.fromOpaque(refcon).takeUnretainedValue().scheduleSnapshot()
        }
        if AXObserverCreate(observedPID, callback, &observer) == .success, let observer = observer {
            axObserver = observer
            let appElement = AXUIElementCreateApplication(observedPID)
            AXUIElementSetMessagingTimeout(appElement, 0.1)
            unsupported = 0
            for notification in [kAXFocusedWindowChangedNotification, kAXWindowCreatedNotification, kAXTitleChangedNotification] {
                let result = AXObserverAddNotification(observer, appElement, notification as CFString, Unmanaged.passUnretained(self).toOpaque())
                if result != .success && result != .notificationAlreadyRegistered { unsupported += 1 }
            }
            CFRunLoopAddSource(CFRunLoopGetMain(), AXObserverGetRunLoopSource(observer), .defaultMode)
        }
        scheduleSnapshot()
    }
    func scheduleSnapshot() {
        notificationCount += 1
        if snapshotPending { coalescedNotifications += 1 }
        guard !snapshotPending, !suspended else { return }
        snapshotPending = true
        // Coalesce notification bursts; no periodic UI polling.
        DispatchQueue.main.asyncAfter(deadline: .now() + (options.lowPower ? min(15.0, 3.0 * Double(1 + stableReads)) : 0.3)) { [weak self] in
            guard let self = self else { return }
            self.snapshotPending = false
            if !self.suspended { self.snapshot() }
        }
    }
    func snapshot() {
        guard observedPID > 0, options.allowed(activeBundle), permission() else { return }
        let readStarted = ProcessInfo.processInfo.systemUptime
        let pid = observedPID
        let bundle = activeBundle
        guard targetLive(pid, bundle) else { return }
        let app = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app, 0.1)
        let content = options.contentAllowed(bundle)
        let system = AXReadProvider<AXUIElement>.system(messageTimeout: 0.1)
        var selectedWindow: AXUIElement?
        var windowReferences = [[String: Any]]()
        var lifetime = proc_bsdinfo()
        guard proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &lifetime, Int32(MemoryLayout<proc_bsdinfo>.size)) == MemoryLayout<proc_bsdinfo>.size else { return }
        let created = Double(lifetime.pbi_start_tvsec) + Double(lifetime.pbi_start_tvusec) / 1000000
        var traceElements = [AXUIElement]()
        var getterTrace = [[String: Any]]()
        let protected = AXReadProvider<AXUIElement>(read: { element, attribute in
            guard self.targetLive(pid, bundle) else { return AXAttributeRead(value: nil, error: -90005, status: .unknown) }
            var current = proc_bsdinfo()
            guard proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &current, Int32(MemoryLayout<proc_bsdinfo>.size)) == MemoryLayout<proc_bsdinfo>.size,
                  current.pbi_start_tvsec == lifetime.pbi_start_tvsec, current.pbi_start_tvusec == lifetime.pbi_start_tvusec else {
                return AXAttributeRead(value: nil, error: -90005, status: .unknown)
            }
            var elementPID: pid_t = 0
            guard AXUIElementGetPid(element, &elementPID) == .success, elementPID == pid else {
                return AXAttributeRead(value: nil, error: -90005, status: .unknown)
            }
            if self.controlled == nil && self.inspection == nil, let selected = selectedWindow {
                let currentWindow = system.read(app, "AXFocusedWindow")
                guard currentWindow.succeeded, let elements = system.elements(currentWindow.value),
                      elements.count == 1, CFEqual(elements[0], selected) else {
                    return AXAttributeRead(value: nil, error: -90005, status: .unknown)
                }
            }
            let value = system.read(element, attribute)
            if attribute == "AXFocusedWindow", self.controlled == nil && self.inspection == nil,
               value.succeeded, let elements = system.elements(value.value), elements.count == 1 { selectedWindow = elements[0] }
            if self.controlled != nil || self.inspection != nil, getterTrace.count < 800 {
                if !traceElements.contains(where: { CFEqual($0, element) }) { traceElements.append(element) }
                var item: [String: Any] = ["node": traceElements.firstIndex(where: { CFEqual($0, element) }) ?? -1,
                    "attribute": attribute, "status": value.status.rawValue, "error": value.error]
                if attribute == "AXRole", let role = value.value as? String { item["role"] = role }
                getterTrace.append(item)
            }
            return value
        }, elements: system.elements, equal: system.equal)
        let profile = ProfileReadGuard(base: protected, bundle: bundle, content: content, exactTitles: options.contentWindowAllowlist)
        let result = AXReadEngine(provider: profile.provider(),
            policy: readPolicy(options, content, focusedWindowOnly: controlled == nil && inspection == nil), limits: readLimits(options)).snapshot(application: app,
                onNode: { element, row, _, _ in
                    // Subscribe using elements admitted by the single shared
                    // walker; no separate window discovery or traversal.
                    if row["role"] as? String == "AXWindow" {
                        let identity = [String(pid), String(format: "%.6f", created), String(CFHash(element))].joined(separator: ":")
                        windowReferences.append(["node_id": row["id"] ?? 0,
                            "reference": SHA256.hash(data: Data(identity.utf8)).map { String(format: "%02x", $0) }.joined(),
                            "identity_quality": "EPHEMERAL_AX_REFERENCE", "launch_time": created])
                    }
                    if row["role"] as? String == "AXWindow", let observer = self.axObserver,
                       !self.registeredWindows.contains(where: { CFEqual($0, element) }) {
                        for name in [kAXTitleChangedNotification, kAXValueChangedNotification, kAXUIElementDestroyedNotification] {
                            let code = AXObserverAddNotification(observer, element, name as CFString, Unmanaged.passUnretained(self).toOpaque())
                            if code != .success && code != .notificationAlreadyRegistered { self.unsupported += 1 }
                        }
                        self.registeredWindows.append(element)
                    }
                })
        var evidence = observerEvidence(result, coverage: "PARTIAL")
        evidence["application_profile"] = profile.profile.id; evidence["profile_version"] = 1
        evidence["profile_pruned_count"] = profile.prunedCount
        evidence["window_references"] = Array(windowReferences.prefix(8))
        if !targetLive(pid, bundle) || !profile.titlesStillQualified() {
            evidence["nodes"] = [[String: Any]](); evidence["node_count"] = 0
            evidence["read_status"] = "UNKNOWN"; evidence["complete"] = false
            evidence["structural_complete"] = false; evidence["attributes_complete"] = false
            evidence["reason"] = "target_changed_during_read"
            evidence.removeValue(forKey: "window_title")
            evidence["window_references"] = [[String: Any]]()
        }
        if let data = try? JSONSerialization.data(withJSONObject: ["nodes": evidence["nodes"] ?? [], "read_status": evidence["read_status"] ?? "UNKNOWN"], options: .sortedKeys) {
            let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
            stableReads = digest == lastReadDigest ? min(4, stableReads + 1) : 0
            lastReadDigest = digest
        }
        lastReadTime = ProcessInfo.processInfo.systemUptime
        evidence["unsupported_notifications"] = unsupported
        evidence["notification_count"] = notificationCount
        evidence["coalesced_notifications"] = coalescedNotifications
        snapshotCount += 1
        evidence["snapshot_count"] = snapshotCount
        evidence["capture_scope"] = controlled != nil ? "controlled_owned_application" : inspection != nil ? "authorized_application_inspection" : "frontmost_authorized_focused_window"
        if let controlled { evidence["target_descriptor_sha256"] = controlled.digest; evidence["getter_trace"] = getterTrace }
        if inspection != nil { evidence["getter_trace"] = getterTrace }
        evidence["elapsed_ms"] = (ProcessInfo.processInfo.systemUptime - readStarted) * 1000
        emit("macos.ax", "ax.snapshot", ["bundle_id": bundle, "pid": Int(pid)], evidence, content: content)
    }
    func start() {
        let center = NSWorkspace.shared.notificationCenter
        let appEvents: [(Notification.Name, String)] = [(.init(NSWorkspace.didLaunchApplicationNotification.rawValue), "app.launched"),
            (NSWorkspace.didTerminateApplicationNotification, "app.terminated"), (NSWorkspace.didActivateApplicationNotification, "app.activated"),
            (NSWorkspace.didDeactivateApplicationNotification, "app.deactivated"), (NSWorkspace.didHideApplicationNotification, "app.hidden"),
            (NSWorkspace.didUnhideApplicationNotification, "app.unhidden")]
        for (name, kind) in appEvents {
            tokens.append(center.addObserver(forName: name, object: nil, queue: .main) { [weak self] note in
                guard let self = self else { return }
                let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
                if kind == "app.activated", self.controlled == nil { self.observeForeground(app) }
                if kind == "app.deactivated", self.controlled == nil, app?.processIdentifier == self.observedPID { self.detachAX() }
                if kind == "app.terminated", app?.processIdentifier == self.observedPID { self.detachAX() }
                guard !self.suspended, let app = app, let bundle = app.bundleIdentifier, self.options.allowed(bundle) else { return }
                emit("macos.workspace", kind, ["bundle_id": bundle, "pid": Int(app.processIdentifier)], ["notification": name.rawValue, "coverage": "PARTIAL"])
            })
        }
        let systemEvents: [(Notification.Name, String)] = [(NSWorkspace.willSleepNotification, "system.will_sleep"),
            (NSWorkspace.didWakeNotification, "system.did_wake"), (NSWorkspace.screensDidSleepNotification, "system.screens_sleep"),
            (NSWorkspace.screensDidWakeNotification, "system.screens_wake"), (NSWorkspace.sessionDidResignActiveNotification, "session.resigned_active"),
            (NSWorkspace.sessionDidBecomeActiveNotification, "session.became_active"), (NSWorkspace.activeSpaceDidChangeNotification, "workspace.space_changed")]
        for (name, kind) in systemEvents {
            tokens.append(center.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                guard let self = self else { return }
                var evidence: [String: Any] = ["notification": name.rawValue, "coverage": "PARTIAL", "lock_state": "UNKNOWN"]
                self.session.update(kind)
                if self.suspended { self.detachAX() }
                if !self.suspended && ["system.did_wake", "system.screens_wake", "session.became_active"].contains(kind) {
                    self.attachCurrentTarget()
                }
                if self.suspended { evidence["reason"] = "observation_suspended_until_active_session_and_screen" }
                if kind.hasPrefix("session.") { evidence["session_state"] = kind == "session.became_active" ? "active" : "inactive" }
                if kind.hasPrefix("system.screens_") { evidence["screen_state"] = kind == "system.screens_wake" ? "awake" : "asleep" }
                if kind == "system.will_sleep" || kind == "system.did_wake" { evidence["sleep_state"] = kind == "system.did_wake" ? "awake" : "sleep_requested" }
                emit("macos.workspace", kind, ["type": "system"], evidence)
            })
        }
        status(options.ax)
        // Only a foreground allowlisted app is inspected. No window enumeration
        // or UI reads occur when AX is disabled or authorization is absent.
        attachCurrentTarget()
        // A stable window may emit no AX notifications while being read.
        // Three fresh bounded reads over ten minutes can establish an offer
        // without inventing duration from one old snapshot or waking a model.
        if controlled == nil && inspection == nil {
            contextRefreshTimer = Timer.scheduledTimer(withTimeInterval: options.lowPower ? 900 : 300, repeats: true) { [weak self] _ in
                guard let self, !self.suspended, self.observedPID > 0 else { return }
                let refresh: TimeInterval = self.options.lowPower && self.stableReads >= 2 ? 1800 : self.options.lowPower ? 900 : 300
                if ProcessInfo.processInfo.systemUptime - self.lastReadTime >= refresh { self.scheduleSnapshot() }
            }
        }
        // A kernel process-exit source replaces polling the parent once/second.
        parentMonitor = watchParent(options.parent)
        RunLoop.main.run()
    }
}

let mode = CommandLine.arguments.dropFirst().first ?? ""
switch mode {
case "--capabilities":
    let value: [String: Any] = ["protocol": 2, "profile": "observer", "shared_core_version": "1.0.0",
        "operations": ["listen", "controlled-listen", "inspect-application", "applications", "frontmost-identity", "status", "fixture", "fixture-snapshot", "fixture-session", "fixture-target", "fixture-parent-watch", "self-test", "capabilities"],
        "actions": [String](), "scope": "frontmost_authorized_focused_window", "os_sandbox": "NOT_IMPLEMENTED"]
    if let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) {
        FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data([10]))
    }
case "--status": status(true)
case "--frontmost-identity":
    FileHandle.standardOutput.write(Data((String(NSWorkspace.shared.frontmostApplication?.processIdentifier ?? 0) + "\n").utf8))
case "--applications":
    let apps = NSWorkspace.shared.runningApplications.compactMap { app -> [String: Any]? in
        guard let bundle = app.bundleIdentifier, !blockedApps.contains(bundle.lowercased()), safeText(bundle) != nil,
              !bundle.lowercased().contains("openai"), !bundle.lowercased().contains("clash"),
              !bundle.lowercased().contains("codex"), !bundle.lowercased().contains("chatgpt") else { return nil }
        return ["bundle_id": bundle, "pid": Int(app.processIdentifier), "version": app.bundleURL.flatMap { Bundle(url: $0)?.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String } ?? "UNKNOWN"]
    }
    if let data = try? JSONSerialization.data(withJSONObject: apps, options: [.sortedKeys]) { FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data([10])) }
case "--fixture": runFixture(readInput())
case "--fixture-snapshot": runFixture(readInput(), appKit: true)
case "--fixture-session": fixtureSession(readInput())
case "--fixture-target":
    let data = readInput()
    let allowed = targetMatches(pid: pid_t(data["pid"] as? Int ?? 0), bundle: data["bundle"] as? String ?? "",
        livePID: (data["live_pid"] as? Int).map { pid_t($0) }, liveBundle: data["live_bundle"] as? String,
        terminated: data["terminated"] as? Bool ?? true,
        frontPID: (data["front_pid"] as? Int).map { pid_t($0) }, frontBundle: data["front_bundle"] as? String)
    emit("macos.observer", "observation.status", ["type": "system"], ["coverage": "MOCK_ONLY", "target_allowed": allowed])
case "--fixture-parent-watch":
    let monitor = watchParent(Options(readInput()).parent)
    emit("macos.observer", "observation.status", ["type": "system"], ["reason": "parent_watch_ready", "coverage": "MOCK_ONLY"])
    RunLoop.main.run()
    withExtendedLifetime(monitor) {}
case "--self-test":
    // Only the helper's own app role. No real user windows, controls or documents.
    let app = NSApplication.shared
    app.setActivationPolicy(.prohibited)
    if !permission() {
        emit("macos.observer", "observation.status", ["type": "system"], ["ax_permission": "MANUAL_REQUIRED", "coverage": "NOT_RUN", "self_process_only": true, "lock_state": "UNKNOWN"])
    } else {
        // Build our own synthetic window without ordering it on screen. A hidden
        // window may legitimately be absent from AXWindows; report that limit.
        let fixture = NSWindow(contentRect: NSRect(x: -10000, y: -10000, width: 240, height: 120),
                               styleMask: [.titled], backing: .buffered, defer: false)
        fixture.title = "LocalPilot synthetic hidden fixture"
        let label = NSTextField(labelWithString: "Synthetic project ready")
        let editor = NSTextView(frame: .zero); editor.string = "Synthetic editor MUST NOT COLLECT"
        let secure = NSSecureTextField(frame: .zero); secure.stringValue = "Synthetic secure MUST NOT COLLECT"
        fixture.contentView?.addSubview(label)
        fixture.contentView?.addSubview(editor)
        fixture.contentView?.addSubview(secure)
        // A bounded self-query is diagnostic only: a same-thread self request
        // may return cannotComplete. Never display/activate to force success.
        let element = AXUIElementCreateApplication(getpid())
        AXUIElementSetMessagingTimeout(element, 0.1)
        var value: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &value)
        let snapshot = AXReadEngine(provider: AXReadProvider<AXUIElement>.system(messageTimeout: 0.1),
            policy: .observer(contentAllowed: false, focusedWindowOnly: false),
            limits: AXReadLimits(maxNodes: 80, maxDepth: 5, maxSeconds: 0.35)).snapshot(application: element)
        let nodes = snapshot["nodes"] as? [[String: Any]] ?? []
        let fixtureFound = nodes.contains { $0["role"] as? String == "AXWindow" }
        emit("macos.observer", "observation.status", ["type": "system"], ["ax_permission": "granted", "coverage": "PARTIAL", "ax_error": result.rawValue,
            "self_role_status": result == .success ? "TESTED" : "FAILED", "self_ax_role": safeText(value as? String) ?? "UNKNOWN",
            "self_windows_ax_error": snapshot["AXWindows_error"] ?? 0, "self_windows_count": snapshot["AXWindows_count"] ?? 0,
            "self_fixture_found": fixtureFound, "self_fixture_child_count": max(0, nodes.count - 1),
            "self_fixture_tree_status": fixtureFound && nodes.count > 1 ? "TESTED" : "NOT_RUN", "window_displayed": false,
            "read_status": snapshot["read_status"] ?? "UNKNOWN", "complete": snapshot["complete"] ?? false,
            "self_process_only": true, "external_app_tree_status": "NOT_RUN", "lock_state": "UNKNOWN"])
        withExtendedLifetime(fixture) {}
    }
case "--listen": Observer(Options(readInput())).start()
case "--controlled-listen":
    let input = readInput(); let options = Options(input)
    guard let raw = input["controlled_target"] as? [String: Any], let target = ControlledTarget(raw),
          options.allowlist == [target.bundle], options.allowed(target.bundle), target.live(),
          input["target_descriptor_sha256"] as? String == target.digest else { exit(2) }
    Observer(options, controlled: target).start()
case "--inspect-application":
    let input = readInput(); let options = Options(input)
    guard input["explicit_application_read"] as? Bool == true, options.ax,
          let raw = input["inspection_target"] as? [String: Any], let target = ApplicationInspectionTarget(raw),
          options.allowlist == [target.bundle], options.allowed(target.bundle), target.live() else { exit(2) }
    guard permission() else { status(true); exit(0) }
    let inspector = Observer(options, inspection: target)
    inspector.observedPID = target.pid; inspector.activeBundle = target.bundle
    inspector.snapshot()
default: exit(2)
}
