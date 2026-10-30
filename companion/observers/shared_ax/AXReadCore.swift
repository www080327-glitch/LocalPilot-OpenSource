// LocalPilot shared AX read core 1.0.0. No UI mutation or process execution API.
import Foundation

enum AXReadStatus: String {
    case successEmpty = "READ_SUCCESS_EMPTY"
    case successNonempty = "READ_SUCCESS_NONEMPTY"
    case failed = "READ_FAILED"
    case partial = "READ_PARTIAL"
    case unknown = "UNKNOWN"
}

struct AXAttributeRead {
    let value: Any?
    let error: Int
    let status: AXReadStatus
    var succeeded: Bool { error == 0 && [.successEmpty, .successNonempty].contains(status) }
    init(value: Any?, error: Int = 0, status: AXReadStatus? = nil) {
        self.value = value; self.error = error
        let empty = (value as? String)?.isEmpty == true || (value as? [Any])?.isEmpty == true
        self.status = status ?? (error == 0 ? (value == nil ? .unknown : empty ? .successEmpty : .successNonempty) : .failed)
    }
}

struct AXReadProvider<Element> {
    let read: (Element, String) -> AXAttributeRead
    // nil means malformed, while [] means an explicitly successful empty list.
    let elements: (Any?) -> [Element]?
    let equal: (Element, Element) -> Bool
    init(read: @escaping (Element, String) -> AXAttributeRead,
         elements: @escaping (Any?) -> [Element]?, equal: @escaping (Element, Element) -> Bool) {
        self.read = read; self.elements = elements; self.equal = equal
    }
}

struct AXReadLimits {
    let maxNodes: Int
    let maxDepth: Int
    let maxCharacters: Int
    let maxSeconds: Double
    init(maxNodes: Int = 256, maxDepth: Int = 12, maxCharacters: Int = 4000, maxSeconds: Double = 8) {
        self.maxNodes = min(512, max(1, maxNodes)); self.maxDepth = min(20, max(0, maxDepth))
        self.maxCharacters = min(16384, max(0, maxCharacters)); self.maxSeconds = min(30, max(0.001, maxSeconds))
    }
}

struct AXReadPolicy {
    let observer: Bool
    let contentAllowed: Bool
    let excludedWindowTitles: Set<String>
    let focusedWindowOnly: Bool
    static let executor = AXReadPolicy(observer: false, contentAllowed: false, excludedWindowTitles: [], focusedWindowOnly: false)
    static func observer(contentAllowed: Bool = false, excludedWindowTitles: Set<String> = [], focusedWindowOnly: Bool = true) -> AXReadPolicy {
        AXReadPolicy(observer: true, contentAllowed: contentAllowed, excludedWindowTitles: excludedWindowTitles, focusedWindowOnly: focusedWindowOnly)
    }
    static let inputRoles: Set<String> = ["AXTextField", "AXTextArea", "AXComboBox", "AXSearchField", "AXSecureTextField"]
    static func isPrivateInput(role: String, subrole: String?) -> Bool {
        inputRoles.contains(role) || subrole == "AXSecureTextField"
    }
}

final class AXReadNodeContext<Element> {
    let element: Element
    let path: [Int]
    let rootAttribute: String
    private let provider: AXReadProvider<Element>
    private let deadline: Double
    private(set) var reads: [String: AXAttributeRead] = [:]
    init(element: Element, path: [Int], rootAttribute: String, provider: AXReadProvider<Element>, deadline: Double) {
        self.element = element; self.path = path; self.rootAttribute = rootAttribute
        self.provider = provider; self.deadline = deadline
    }
    func read(_ attribute: String) -> AXAttributeRead {
        if let cached = reads[attribute] { return cached }
        let result = ProcessInfo.processInfo.systemUptime < deadline ? provider.read(element, attribute)
            : AXAttributeRead(value: nil, error: -90002, status: .unknown)
        reads[attribute] = result
        return result
    }
    func value(_ attribute: String) -> Any? { let result = read(attribute); return result.succeeded ? result.value : nil }
}

final class AXReadEngine<Element> {
    let provider: AXReadProvider<Element>
    let policy: AXReadPolicy
    let limits: AXReadLimits
    init(provider: AXReadProvider<Element>, policy: AXReadPolicy, limits: AXReadLimits = AXReadLimits()) {
        self.provider = provider; self.policy = policy; self.limits = limits
    }
    func snapshot(application: Element, windowTitle: String? = nil, includeMenus: Bool = false,
                  executorRow: ((Element, AXReadNodeContext<Element>) -> [String: Any])? = nil,
                  onNode: ((Element, [String: Any], [Int], String) -> Void)? = nil) -> [String: Any] {
        let start = ProcessInfo.processInfo.systemUptime
        let deadline = start + limits.maxSeconds
        var rows: [[String: Any]] = []
        var errors: [[String: Any]] = []
        var seen: [Element] = []
        var structuralFailure = false
        var unknownFailure = false
        var truncated = false
        var contentTruncated = false
        var omittedErrors = 0
        var privacyPruned = 0
        var matchedWindows = 0
        var remainingCharacters = limits.maxCharacters
        func issue(_ result: AXAttributeRead, _ attribute: String, _ path: [Int], _ scope: String, structural: Bool) {
            if structural || policy.observer { structuralFailure = true; unknownFailure = unknownFailure || result.status == .unknown }
            let code = result.error
            let reason = code == -90001 ? "malformed_attribute" : code == -90002 ? "time_budget_exhausted" : code == -90003 ? "missing_or_unknown_role" : code == -90004 ? "malformed_subrole" : code == -90005 ? "target_scope_changed" : "AX_attribute_read_failed"
            if errors.count < 128 {
                errors.append(["attribute": attribute, "path": path, "scope": scope,
                    "status": result.status.rawValue, "error": code, "reason": reason,
                    "structural": structural, "retry_allowed": [-25204, -25202, -90002].contains(code),
                    "retry_class": [-25204, -25202, -90002].contains(code) ? "fresh_read_allowed_no_action_replay" : "permission_provider_or_scope_review"])
            } else { omittedErrors += 1 }
        }
        func malformed(_ attribute: String, _ path: [Int], _ scope: String, code: Int = -90001) {
            issue(AXAttributeRead(value: nil, error: code, status: .unknown), attribute, path, scope, structural: true)
        }
        func roots(_ attribute: String, optional: Bool = false) -> (elements: [Element], error: Int) {
            let result = ProcessInfo.processInfo.systemUptime < deadline ? provider.read(application, attribute)
                : AXAttributeRead(value: nil, error: -90002, status: .unknown)
            if !result.succeeded {
                if !(optional && [-25205, -25212].contains(result.error)) { issue(result, attribute, [], "application", structural: true) }
                return ([], result.error)
            }
            if attribute == "AXWindows" && !(result.value is [Any]) { malformed(attribute, [], "application"); return ([], -90001) }
            guard let elements = provider.elements(result.value) else { malformed(attribute, [], "application"); return ([], -90001) }
            return (elements, 0)
        }
        func admit(_ context: AXReadNodeContext<Element>) -> Bool {
            let roleRead = context.read("AXRole")
            guard roleRead.succeeded, let role = roleRead.value as? String, !["", "UNKNOWN", "AXUnknown"].contains(role) else {
                if !roleRead.succeeded { issue(roleRead, "AXRole", context.path, context.rootAttribute, structural: true) }
                else { malformed("AXRole", context.path, context.rootAttribute, code: -90003) }
                return !policy.observer
            }
            if role.range(of: "^AX[A-Za-z]{1,60}$", options: .regularExpression) == nil {
                malformed("AXRole", context.path, context.rootAttribute, code: -90003); return !policy.observer
            }
            // The role-only secure case must stop before even reading subrole.
            if policy.observer && AXReadPolicy.inputRoles.contains(role) { privacyPruned += 1; return false }
            if policy.observer {
                let subroleRead = context.read("AXSubrole")
                if !subroleRead.succeeded && ![-25205, -25212].contains(subroleRead.error) {
                    issue(subroleRead, "AXSubrole", context.path, context.rootAttribute, structural: true); return false
                }
                if subroleRead.error == 0, let raw = subroleRead.value, !(raw is String) {
                    malformed("AXSubrole", context.path, context.rootAttribute, code: -90004); return false
                }
                if subroleRead.error == 0 && subroleRead.value == nil {
                    malformed("AXSubrole", context.path, context.rootAttribute, code: -90004); return false
                }
                if let subrole = subroleRead.value as? String, !subrole.isEmpty,
                   (subrole == "AXUnknown" || subrole.range(of: "^AX[A-Za-z]{1,60}$", options: .regularExpression) == nil) {
                    malformed("AXSubrole", context.path, context.rootAttribute, code: -90004); return false
                }
                if subroleRead.value as? String == "AXSecureTextField" { privacyPruned += 1; return false }
            }
            return true
        }
        func visit(_ context: AXReadNodeContext<Element>, _ level: Int, _ parent: Int?) {
            guard ProcessInfo.processInfo.systemUptime < deadline else { truncated = true; issue(AXAttributeRead(value: nil, error: -90002, status: .unknown), "AXChildren", context.path, context.rootAttribute, structural: true); return }
            guard rows.count < limits.maxNodes else { truncated = true; return }
            if seen.contains(where: { provider.equal($0, context.element) }) { return }
            seen.append(context.element)
            guard admit(context) else { return }
            if policy.observer, context.value("AXRole") as? String == "AXWindow", !policy.excludedWindowTitles.isEmpty {
                let titleRead = context.read("AXTitle")
                guard titleRead.succeeded, let title = titleRead.value as? String else {
                    if !titleRead.succeeded { issue(titleRead, "AXTitle", context.path, context.rootAttribute, structural: true) }
                    else { malformed("AXTitle", context.path, context.rootAttribute) }
                    return
                }
                if policy.excludedWindowTitles.contains(title) { privacyPruned += 1; return }
            }
            let index = rows.count
            var row: [String: Any]
            if policy.observer {
                row = ["id": index, "role": context.value("AXRole") as? String ?? "UNKNOWN"]
                if let parent { row["parent"] = parent }
                if let subrole = context.value("AXSubrole") as? String, !subrole.isEmpty { row["subrole"] = String(subrole.prefix(256)) }
                if policy.contentAllowed, row["role"] as? String == "AXStaticText", remainingCharacters > 0 {
                    let read = context.read("AXValue")
                    if let text = read.value as? String, read.succeeded {
                        let clipped = String(text.prefix(min(500, remainingCharacters)))
                        row["text"] = clipped; remainingCharacters -= clipped.count
                        if text.count > clipped.count { row["text_omitted_chars"] = text.count - clipped.count; contentTruncated = true }
                    } else if !read.succeeded { issue(read, "AXValue", context.path, context.rootAttribute, structural: false) }
                    else { malformed("AXValue", context.path, context.rootAttribute) }
                }
                if policy.contentAllowed, row["role"] as? String == "AXStaticText", remainingCharacters == 0,
                   context.reads["AXValue"] == nil { contentTruncated = true }
                if policy.contentAllowed, row["role"] as? String == "AXWindow" {
                    let read = context.read("AXTitle")
                    if let title = read.value as? String, read.succeeded {
                        row["title"] = String(title.prefix(500))
                        if title.count > 500 { row["title_omitted_chars"] = title.count - 500; contentTruncated = true }
                    }
                    else if !read.succeeded { issue(read, "AXTitle", context.path, context.rootAttribute, structural: false) }
                    else { malformed("AXTitle", context.path, context.rootAttribute) }
                }
            } else { row = executorRow?(context.element, context) ?? ["role": context.value("AXRole") as? String ?? "UNKNOWN"] }
            row["path"] = context.path; row["root_attribute"] = context.rootAttribute
            var attributeReads: [String: String] = [:]
            for (attribute, result) in context.reads.sorted(by: { $0.key < $1.key }) {
                attributeReads[attribute] = result.status.rawValue
                if !policy.observer && !result.succeeded { issue(result, attribute, context.path, context.rootAttribute, structural: attribute == "AXRole") }
            }
            row["attribute_reads"] = attributeReads
            onNode?(context.element, row, context.path, context.rootAttribute)
            rows.append(row)
            let childrenRead = context.read("AXChildren")
            guard childrenRead.succeeded else { issue(childrenRead, "AXChildren", context.path, context.rootAttribute, structural: true); return }
            guard childrenRead.value is [Any] else { malformed("AXChildren", context.path, context.rootAttribute); return }
            guard let children = provider.elements(childrenRead.value) else { malformed("AXChildren", context.path, context.rootAttribute); return }
            rows[index]["children_read_status"] = children.isEmpty ? AXReadStatus.successEmpty.rawValue : AXReadStatus.successNonempty.rawValue
            if level >= limits.maxDepth { if !children.isEmpty { truncated = true }; return }
            for (childIndex, child) in children.enumerated() {
                if rows.count >= limits.maxNodes || ProcessInfo.processInfo.systemUptime >= deadline { truncated = true; break }
                visit(AXReadNodeContext(element: child, path: context.path + [childIndex], rootAttribute: context.rootAttribute, provider: provider, deadline: deadline), level + 1, policy.observer ? index : nil)
            }
        }
        let windowsRead = policy.focusedWindowOnly ? (elements: [Element](), error: 0) : roots("AXWindows")
        let focusedRead = roots("AXFocusedWindow", optional: !policy.focusedWindowOnly)
        var focusedFallback = false
        func processWindow(_ window: Element, _ index: Int, _ attribute: String) {
            let context = AXReadNodeContext(element: window, path: [index], rootAttribute: attribute, provider: provider, deadline: deadline)
            guard admit(context) else { return }
            if windowTitle != nil || !policy.excludedWindowTitles.isEmpty {
                let read = context.read("AXTitle")
                guard read.succeeded, let title = read.value as? String else {
                    if !read.succeeded { issue(read, "AXTitle", [index], attribute, structural: true) }
                    else { malformed("AXTitle", [index], attribute) }
                    return
                }
                if policy.excludedWindowTitles.contains(title) { privacyPruned += 1; return }
                if let windowTitle, title != windowTitle { return }
            }
            matchedWindows += 1
            if attribute == "AXFocusedWindow" { focusedFallback = true }
            visit(context, 0, nil)
        }
        for (index, window) in windowsRead.elements.enumerated() { processWindow(window, index, "AXWindows") }
        for (index, window) in focusedRead.elements.enumerated() where !windowsRead.elements.contains(where: { provider.equal($0, window) }) { processWindow(window, index, "AXFocusedWindow") }
        if includeMenus && !policy.observer {
            for (index, menu) in roots("AXMenuBar").elements.enumerated() {
                visit(AXReadNodeContext(element: menu, path: [index], rootAttribute: "AXMenuBar", provider: provider, deadline: deadline), 0, nil)
            }
        }
        let structuralComplete = !structuralFailure && !truncated
        let complete = structuralComplete && errors.isEmpty && omittedErrors == 0 && !contentTruncated
        let readStatus: AXReadStatus = complete ? (rows.isEmpty ? .successEmpty : .successNonempty)
            : !rows.isEmpty ? .partial : unknownFailure || truncated ? .unknown : .failed
        var result: [String: Any] = ["status": "ok", "nodes": rows, "node_count": rows.count,
            "read_status": readStatus.rawValue, "complete": complete, "structural_complete": structuralComplete,
            "attributes_complete": errors.isEmpty && omittedErrors == 0, "read_errors": errors,
            "content_truncated": contentTruncated,
            "omitted_read_errors": omittedErrors, "privacy_pruned_subtrees": privacyPruned,
            "read_scope": policy.observer ? (policy.focusedWindowOnly ? "authorized_focused_window_filtered_private_inputs" : "authorized_windows_filtered_private_inputs") : "AXWindows_plus_AXFocusedWindow",
            "shared_ax_version": "1.0.0", "window_count": matchedWindows, "AXWindows_count": windowsRead.elements.count,
            "AXFocusedWindow_count": focusedRead.elements.count, "AXWindows_error": windowsRead.error,
            "focused_window_fallback": focusedFallback, "window_title": windowTitle ?? NSNull(),
            "include_menu_bar": includeMenus && !policy.observer, "truncated": truncated,
            "window_coverage": "AXWindows_plus_AXFocusedWindow_not_all_WindowServer_windows"]
        // Executor content fingerprints must not change only because of timing.
        if policy.observer { result["read_elapsed_seconds"] = ProcessInfo.processInfo.systemUptime - start }
        if windowTitle != nil && matchedWindows == 0 {
            result["status"] = "error"; result["error"] = complete ? "window_not_found" : "window_read_incomplete"
            result["message"] = complete ? "Exact target window is absent from the complete supported AX scope." : "Window selection is incomplete; target absence UNKNOWN."
        }
        return result
    }
}
