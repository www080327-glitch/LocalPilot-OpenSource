import AppKit
import UserNotifications

/// Optional system delivery. Permission is requested only by a user button.
/// Dismissal has no control semantics; only the explicit Stop action cancels.
final class SystemNotifications: NSObject, UNUserNotificationCenterDelegate {
    var onStop: ((String) -> Void)?
    var onOpen: (() -> Void)?
    private let center = UNUserNotificationCenter.current()
    private var seen = Set<String>()

    override init() {
        super.init(); center.delegate = self
        let stop = UNNotificationAction(identifier: "STOP_INFERENCE", title: "停止本次推理", options: [.destructive])
        let open = UNNotificationAction(identifier: "OPEN_INFERENCE", title: "查看与确认", options: [.foreground])
        let category = UNNotificationCategory(identifier: "INFERENCE", actions: [stop, open], intentIdentifiers: [], options: [])
        center.setNotificationCategories([category])
    }
    func requestPermission(_ done: @escaping (String) -> Void) {
        center.requestAuthorization(options: [.alert]) { granted, error in
            if !granted { done("系统通知未允许；使用菜单栏原生卡片。"); return }
            if Bundle.main.object(forInfoDictionaryKey: "CompanionTimeSensitiveNotifications") as? Bool != true {
                done("系统通知已允许。本地试用版使用普通提醒；专注模式穿透尚未验证。"); return
            }
            self.center.getNotificationSettings { settings in
                let allowed: Bool
                if #available(macOS 12.0, *) { allowed = settings.timeSensitiveSetting == .enabled } else { allowed = false }
                done(allowed ? "系统通知与时效性提醒已允许；专注模式仍由系统决定。" : "系统通知已允许；要穿透专注模式，请在系统中允许时效性通知。")
            }
        }
    }
    func post(id: String, title: String, body: String, ticket: String? = nil, urgent: Bool = false) {
        guard !seen.contains(id) else { return }; seen.insert(id)
        center.getNotificationSettings { [weak self] settings in
            guard settings.authorizationStatus == .authorized else { return }
            let content = UNMutableNotificationContent(); content.title = title; content.body = body
            content.threadIdentifier = "companion-resources"
            if #available(macOS 12.0, *) {
                let entitled = Bundle.main.object(forInfoDictionaryKey: "CompanionTimeSensitiveNotifications") as? Bool == true
                content.interruptionLevel = urgent ? (entitled ? .timeSensitive : .active) : .passive
                content.relevanceScore = urgent ? 0.9 : 0.2
            }
            if let ticket = ticket { content.categoryIdentifier = "INFERENCE"; content.userInfo = ["ticket":ticket] }
            // Never put questions, observations, memory, credentials or model
            // replies into lock-screen notification previews.
            self?.center.add(UNNotificationRequest(identifier: id, content: content, trigger: nil))
        }
    }
    func inference(_ value: JSONObject) {
        guard let id = value["id"] as? String, value["phase"] as? String == "prepared" else { return }
        let local = value["kind"] as? String == "local"
        let agent = value["mode"] as? String == "execution"
        let requires = !(value["required_confirmations"] as? [String] ?? []).isEmpty
        post(id: "inference-"+id, title: requires ? (agent ? "需要帮助吗？确认后启动标准 Agent" : local ? "需要确认：本次本地模型的资源使用" : "需要确认：本次云端调用可能产生费用") : "Companion 开始推理",
             body: agent ? "需要你的明确同意才启动标准 Agent 协助；工具操作仍需单独审批。" : local ? "本地模型按需运行，结束后释放。可从菜单栏或此通知停止。" : "云端仅接收本次问题。停止后会尽量收完已发出的本轮回复。", ticket: id, urgent: requires)
    }
    func resource(_ value: JSONObject) {
        post(id: "resource-\(value["kind"] ?? "")-\(value["at"] ?? "")", title: "Companion · 系统资源提醒",
             body: value["message"] as? String ?? "资源状态需要留意。", urgent: ["memory","battery_discharge"].contains(value["kind"] as? String ?? ""))
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list])
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        DispatchQueue.main.async {
            if response.actionIdentifier == "STOP_INFERENCE", let ticket = response.notification.request.content.userInfo["ticket"] as? String {
                self.onStop?(ticket)
            } else if ["OPEN_INFERENCE", UNNotificationDefaultActionIdentifier].contains(response.actionIdentifier) { self.onOpen?() }
            completionHandler()
        }
    }
}
