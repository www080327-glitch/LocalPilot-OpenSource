import AppKit
import Foundation

final class Popup: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    let output = NSTextView()
    let input = NSTextField()
    let title = NSTextField(labelWithString: "Companion V0.4 · 本地只读")
    var token = ""
    var port = 0
    var noticeID: String?
    var timer: Timer?
    var busy = false
    var runtimePath = ""

    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            runtimePath = CommandLine.arguments[1]
            let data = try Data(contentsOf: URL(fileURLWithPath: runtimePath))
            let state = try JSONSerialization.jsonObject(with: data) as! [String:Any]
            token = state["token"] as! String
            port = state["port"] as! Int
            let record: [String:Any] = ["pid":ProcessInfo.processInfo.processIdentifier, "token":token]
            let recordPath = URL(fileURLWithPath:runtimePath).deletingLastPathComponent().appendingPathComponent("popup.json")
            try JSONSerialization.data(withJSONObject:record).write(to:recordPath,options:.atomic)
        } catch { NSApp.terminate(nil); return }
        window = NSWindow(contentRect: NSRect(x:0,y:0,width:590,height:520), styleMask:[.titled,.closable,.miniaturizable], backing:.buffered, defer:false)
        window.title = "Companion V0.4"
        window.isReleasedWhenClosed = false
        window.center()
        let view = window.contentView!
        title.frame = NSRect(x:16,y:480,width:558,height:24)
        view.addSubview(title)
        let scroll = NSScrollView(frame:NSRect(x:16,y:260,width:558,height:210))
        scroll.hasVerticalScroller = true
        output.isEditable = false
        output.font = NSFont.systemFont(ofSize:14)
        scroll.documentView = output
        view.addSubview(scroll)
        input.frame = NSRect(x:16,y:224,width:558,height:26)
        input.placeholderString = "简单回复，或描述需要的帮助"
        input.target = self
        input.action = #selector(reply)
        view.addSubview(input)
        let buttons: [(String, Selector)] = [("不需要",#selector(notNeeded)),("有用",#selector(useful)),("别再提醒这种",#selector(mute)),("以后多提醒这种",#selector(more)),("回复",#selector(reply)),("帮我",#selector(help)),("勿扰",#selector(dnd)),("退出",#selector(quit)),("观察状态",#selector(state)),("记忆查询",#selector(memory)),("隐私设置",#selector(privacy)),("暂停/恢复观察",#selector(pause)),("授权观察",#selector(authorize)),("LocalPilot连接",#selector(connection)),("升级状态",#selector(taskState)),("提交任务",#selector(submit))]
        for (i,item) in buttons.enumerated() {
            let b = NSButton(title:item.0,target:self,action:item.1)
            b.frame = NSRect(x:16+(i%4)*140,y:16+(i/4)*36,width:138,height:28)
            view.addSubview(b)
        }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps:true)
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval:30,repeats:true) { [weak self] _ in self?.refresh() }
    }

    func command(_ body:[String:Any], done:@escaping ([String:Any])->Void) {
        var request = URLRequest(url:URL(string:"http://127.0.0.1:\(port)/command")!)
        request.httpMethod = "POST"
        request.timeoutInterval = 125
        request.setValue("Bearer \(token)",forHTTPHeaderField:"Authorization")
        request.setValue("application/json",forHTTPHeaderField:"Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject:body)
        URLSession.shared.dataTask(with:request) { data,response,error in
            let result = data.flatMap { try? JSONSerialization.jsonObject(with:$0) as? [String:Any] } ?? ["status":"unavailable", "text":"Companion 服务已停止或无法连接。"]
            DispatchQueue.main.async { done(result) }
        }.resume()
    }

    func refresh() {
        if !FileManager.default.fileExists(atPath:runtimePath) { NSApp.terminate(nil); return }
        if busy { return }
        command(["command":"status"]) { state in
            let privacy = state["privacy"] as? [String:Any] ?? [:]
            let observation = privacy["status"] as? String ?? "未知"
            let model = state["model"] as? [String:Any] ?? [:]
            self.title.stringValue = "Companion V0.4 · 观察 \(observation) · 模型\((model["loaded"] as? Bool ?? false) ? "已加载" : "空闲")"
        }
        command(["command":"notices"]) { result in
            if let rows = result["notices"] as? [[String:Any]], let row = rows.first(where: { $0["status"] as? String == "pending" }), let id = row["id"] as? String, id != self.noticeID {
                self.noticeID = id
                self.output.string = row["message"] as? String ?? ""
            }
        }
    }

    func send(_ action:String) {
        if busy { return }
        let text = input.stringValue
        var body:[String:Any] = ["command":"ask", "text":text.isEmpty ? "我最近主要在忙什么？" : text]
        if let id = noticeID { body = ["command":"notice_action", "id":id, "action":action, "text":text] }
        else if ["ignore", "not_needed", "useful", "mute", "more"].contains(action) { output.string = "当前没有待处理提醒。"; return }
        else if action == "help" { body = ["command":"escalate", "text":text.isEmpty ? "请帮我处理当前问题" : text] }
        busy = true
        title.stringValue = "Companion · 正在本地处理"
        command(body) { result in
            self.busy = false
            self.noticeID = nil
            self.title.stringValue = "Companion V0.4 · 本地只读"
            self.output.string = result["text"] as? String ?? (action == "ignore" ? "已忽略。" : "暂时无法处理，请稍后再试。")
            if let records = result["memories"] as? [[String:Any]] {
                for r in records { self.output.string += "\n来源：\(r["source_reference"] ?? "") [\(r["epistemic"] ?? "")]" }
            }
            self.input.stringValue = ""
        }
    }
    @objc func ignore() { send("ignore") }
    @objc func notNeeded() { send("not_needed") }
    @objc func more() { send("more") }
    @objc func useful() { send("useful") }
    @objc func mute() { send("mute") }
    @objc func reply() { send("reply") }
    @objc func help() { send("help") }
    func show(_ body:[String:Any]) {
        command(body) { result in
            let data = try? JSONSerialization.data(withJSONObject:result,options:[.prettyPrinted,.sortedKeys])
            self.output.string = data.flatMap { String(data:$0,encoding:.utf8) } ?? "暂时无法显示。"
        }
    }
    @objc func state() { show(["command":"status"]) }
    @objc func memory() { show(["command":"retrieve", "text":input.stringValue.isEmpty ? "当前任务" : input.stringValue]) }
    @objc func privacy() { show(["command":"privacy"]) }
    @objc func connection() { show(["command":"localpilot_health"]) }
    @objc func taskState() { show(["command":"escalation_status"]) }
    @objc func pause() {
        command(["command":"privacy"]) { state in
            self.show(["command":"pause_observation", "paused":state["status"] as? String != "paused"])
        }
    }
    @objc func authorize() {
        command(["command":"authorize_observation", "confirmed":false]) { state in
            let data = try? JSONSerialization.data(withJSONObject:state["scope"] ?? [:],options:[.prettyPrinted,.sortedKeys])
            let scope = data.flatMap { String(data:$0,encoding:.utf8) } ?? ""
            self.output.string = scope
            let alert = NSAlert()
            alert.messageText = "授权所显示范围的只读观察？"
            alert.informativeText = scope + "\nAX 系统权限仍需你手动授予。可随时暂停。"
            alert.addButton(withTitle:"授权")
            alert.addButton(withTitle:"取消")
            if alert.runModal() == .alertFirstButtonReturn { self.show(["command":"authorize_observation", "confirmed":true]) }
        }
    }
    @objc func submit() {
        command(["command":"escalation_status"]) { state in
            guard let pending = state["pending"] as? [String:Any] else { self.output.string = "请先描述任务并点击帮我，查看准备的升级请求。"; return }
            let data = try? JSONSerialization.data(withJSONObject:pending,options:[.prettyPrinted,.sortedKeys])
            let preview = data.flatMap { String(data:$0,encoding:.utf8) } ?? ""
            self.output.string = preview
            let alert = NSAlert()
            alert.messageText = "提交已显示的任务与来源上下文？"
            alert.informativeText = String((pending["user_request"] as? String ?? "").prefix(600)) + "\n执行由 LocalPilot 管理，工具审批仍在 LocalPilot 完成。云端传输需单独通过命令行授权。"
            alert.addButton(withTitle:"提交")
            alert.addButton(withTitle:"取消")
            if alert.runModal() == .alertFirstButtonReturn { self.show(["command":"submit_escalation", "approved":true, "expected_digest":state["review_digest"] ?? ""]) }
        }
    }
    @objc func dnd() {
        command(["command":"status"]) { state in
            let enabled = !(state["dnd"] as? Bool ?? false)
            self.command(["command":"dnd", "enabled":enabled]) { _ in self.output.string = enabled ? "勿扰已开启。" : "勿扰已关闭。" }
        }
    }
    @objc func quit() {
        command(["command":"shutdown"]) { _ in NSApp.terminate(nil) }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication) -> Bool { return true }
}

let app = NSApplication.shared
let delegate = Popup()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
