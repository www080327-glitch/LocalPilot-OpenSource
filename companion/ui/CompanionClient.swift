import Foundation
import Darwin

typealias JSONObject = [String: Any]

enum CompanionClientError: Error {
    case invalidRuntime
}

/// A credential is loaded from the private Host runtime; no endpoint is accepted from UI input.
final class CompanionClient: NSObject, URLSessionTaskDelegate {
    let runtimeURL: URL
    let port: Int
    let token: String
    private var session: URLSession!

    init(runtimePath: String) throws {
        let url = URL(fileURLWithPath: runtimePath)
        var info = stat()
        guard lstat(url.path, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG,
              info.st_uid == getuid(), info.st_mode & 0o077 == 0,
              info.st_size > 0, info.st_size <= 8192,
              let state = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? JSONObject,
              let runtimePort = state["port"] as? Int, runtimePort > 0, runtimePort <= 65535,
              let runtimeToken = state["token"] as? String, runtimeToken.count >= 32,
              runtimeToken.count <= 128,
              runtimeToken.range(of: "^[A-Za-z0-9_-]+$", options: .regularExpression) != nil else {
            throw CompanionClientError.invalidRuntime
        }
        runtimeURL = url
        port = runtimePort
        token = runtimeToken
        super.init()
        let config = URLSessionConfiguration.ephemeral
        config.connectionProxyDictionary = [:]
        config.urlCache = nil
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.timeoutIntervalForRequest = 125
        config.timeoutIntervalForResource = 130
        session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }

    func runtimeMatches() -> Bool {
        guard let data = try? Data(contentsOf: runtimeURL),
              let current = try? JSONSerialization.jsonObject(with: data) as? JSONObject else { return false }
        return current["token"] as? String == token && current["port"] as? Int == port
    }

    func command(_ body: JSONObject, tokenOverride: String? = nil, completion: @escaping (JSONObject) -> Void) {
        guard JSONSerialization.isValidJSONObject(body),
              let encoded = try? JSONSerialization.data(withJSONObject: body), encoded.count <= 32768 else {
            completion(["status": "error", "text": "请求过长，请缩短后重试。"])
            return
        }
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/command")!)
        request.httpMethod = "POST"
        request.httpBody = encoded
        request.setValue("Bearer \(tokenOverride ?? token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
        session.dataTask(with: request) { data, response, error in
            guard error == nil, let http = response as? HTTPURLResponse else {
                completion(["status": "unavailable", "text": "Companion 服务暂时无法连接。"])
                return
            }
            guard http.statusCode == 200 else {
                completion(["status": http.statusCode == 403 ? "forbidden" : "error",
                            "http_status": http.statusCode, "text": "服务拒绝了请求，请检查授权或重新启动此界面。"])
                return
            }
            guard let content = data, content.count <= 2_097_152,
                  let result = try? JSONSerialization.jsonObject(with: content) as? JSONObject else {
                completion(["status": "error", "text": "服务响应格式不正确。"])
                return
            }
            completion(result)
        }.resume()
    }

    // Credentials never follow redirects, including loopback-to-cloud redirects.
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }

    func close() { session.invalidateAndCancel() }

    func presentedIDs() -> Set<String> {
        let url = runtimeURL.deletingLastPathComponent().appendingPathComponent("ui-presented.json")
        var info = stat()
        guard lstat(url.path, &info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_uid == getuid(),
              info.st_size <= 16384, let data = try? Data(contentsOf: url),
              let ids = try? JSONSerialization.jsonObject(with: data) as? [String] else { return [] }
        return Set(ids.suffix(100).filter { !$0.isEmpty && $0.count <= 128 })
    }
    func savePresentedIDs(_ ids: Set<String>) {
        let directory = runtimeURL.deletingLastPathComponent()
        let temporary = directory.appendingPathComponent(".ui-presented-" + UUID().uuidString)
        let target = directory.appendingPathComponent("ui-presented.json")
        guard let data = try? JSONSerialization.data(withJSONObject: Array(ids.sorted().suffix(100))) else { return }
        let fd = Darwin.open(temporary.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)
        guard fd >= 0 else { return }
        let written = data.withUnsafeBytes { Darwin.write(fd, $0.baseAddress, $0.count) }
        Darwin.close(fd)
        if written == data.count { _ = Darwin.rename(temporary.path, target.path) }
        _ = Darwin.unlink(temporary.path)
    }
    func saveBannerReceipt(_ value: JSONObject) {
        let directory = runtimeURL.deletingLastPathComponent()
        let temporary = directory.appendingPathComponent(".ui-banner-" + UUID().uuidString)
        let target = directory.appendingPathComponent("ui-banner-last.json")
        guard let data = try? JSONSerialization.data(withJSONObject: value) else { return }
        let fd = Darwin.open(temporary.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)
        guard fd >= 0 else { return }
        let written = data.withUnsafeBytes { Darwin.write(fd, $0.baseAddress, $0.count) }
        Darwin.close(fd)
        if written == data.count { _ = Darwin.rename(temporary.path, target.path) }
        _ = Darwin.unlink(temporary.path)
    }
}

enum CompanionPresentation {
    static func value(_ object: JSONObject, _ key: String, fallback: String = "UNKNOWN") -> String {
        guard let value = object[key], !(value is NSNull) else { return fallback }
        if let text = value as? String { return text }
        return String(describing: value)
    }

    static func readableState(_ state: String) -> String {
        return ["running": "运行中", "active": "观察中", "paused": "已暂停", "approval_required": "等待确认",
            "authorized": "已授权", "disabled": "未启用", "unavailable": "不可用", "LOCALPILOT_UNAVAILABLE": "服务暂时不可用", "CONNECTED": "已连接", "AUTH_REJECTED": "身份认证被拒绝",
            "configured_unverified": "已配置，连接未验证", "ok": "正常", "completed": "已完成",
            "failed": "失败", "cancelled": "已取消", "timed_out": "已超时",
            "submitted": "已提交", "incomplete": "未完成", "requires_approval": "等待审批",
            "not_submitted": "未提交", "recovery_required": "需要恢复检查"][state] ?? state
    }

    static func taskText(_ row: JSONObject) -> String {
        let current = row["last_status"] as? JSONObject ?? row["result"] as? JSONObject ?? row
        let state = value(current, "status", fallback: value(row, "phase"))
        let verified = current["goal_verified"] as? Bool == true
        let display = current["unknown_mutation"] as? Bool == true ? "UNKNOWN：副作用待核对" : state == "completed" && !verified ? "运行结束 · 目标尚未验证" : readableState(state)
        var text = "状态：\(display)"
        text += "\n验收：\(value(current, "verification_status", fallback: "not_run")) · 工程：\(value(current, "engineering_status", fallback: "unverified"))"
        if row["connection_error"] != nil { text += "\n服务暂时断线，保留最后权威任务状态。" }
        if let progress = current["progress_text"] as? String, !progress.isEmpty { text += "\n流式进度（尚未验收）：\(progress)" }
        if let execution = current["task_execution"] as? String { text += " · 执行：\(execution)" }
        if let required = current["required_action"] as? JSONObject { text += "\n需要操作：\(value(required, "type"))；请在 LocalPilot 中完成审批。" }
        if let usage = current["cache_usage"] as? JSONObject {
            if let ratio = usage["cache_hit_ratio"] as? Double {
                text += String(format: "\n缓存命中：%.2f%% · 未命中输入：%@ · 输出：%@", ratio*100, value(usage,"cache_miss_tokens"), value(usage,"output_tokens"))
            } else { text += "\n缓存用量：UNKNOWN" }
        }
        if let answer = current["agent_response"] as? String { text += "\n\(answer)" }
        return text
    }

    static func memoryText(_ row: JSONObject) -> String {
        let evidence = row["evidence"] as? JSONObject ?? [:]
        let text = row["text"] as? String ?? row["summary"] as? String ?? evidence["summary"] as? String ?? value(row, "kind")
        let reference = row["source_reference"] as? String ?? ""
        let source = reference.isEmpty ? value(row, "source", fallback: "来源未记录") : reference
        let state = value(row, "evidence_type", fallback: value(row, "epistemic"))
        let epistemic = ["OBSERVED":"实际观察", "USER_CONFIRMED":"你明确告诉我的", "MODEL_INFERRED":"模型推断，未确认", "EXTERNAL_SOURCE":"外部资料", "UNKNOWN":"依据不足，未确认"][state] ?? state
        let read = value(evidence, "read_status", fallback: value(evidence, "coverage", fallback: ""))
        return "\(text)\n来源：\(source)\n证据：\(epistemic)\(read.isEmpty ? "" : " · 读取：\(read)")"
    }

    static func contextText(_ row: JSONObject) -> String {
        let text = row["text"] as? String ?? ""
        let state = value(row, "read_status")
        let read = ["READ_PARTIAL":"部分读取", "READ_FAILED":"读取失败", "UNKNOWN":"读取状态未知", "READ_SUCCESS_NONEMPTY":"已读取", "READ_SUCCESS_EMPTY":"界面没有可读内容"][state] ?? state
        return "\(value(row, "app")) · \(value(row, "title"))\n\(value(row, "time")) · \(read)\n\(text.isEmpty ? "尚未读到静态文字，无法判断正文。" : "可读文字：" + text)\n来源：\(value(row, "source_reference")) · 实际观察；不代表工作事实或任务完成。"
    }

    static func pretty(_ value: Any) -> String {
        guard JSONSerialization.isValidJSONObject(value),
              let data = try? JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys]),
              let text = String(data: data, encoding: .utf8) else { return "UNKNOWN" }
        return text
    }
}
