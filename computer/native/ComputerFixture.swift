// One disposable app; no user documents, networking or product installation.
import AppKit
import WebKit

var fixtureEventSink: ((NSEvent) -> Void)?
final class FixtureApplication: NSApplication {
    override func sendEvent(_ event:NSEvent) {
        if event.type == .keyDown || event.type == .keyUp { fixtureEventSink?(event) }
        super.sendEvent(event)
    }
}
final class InstrumentedText: NSTextView {
    var onEvent: ((String) -> Void)?
    override func insertText(_ string: Any, replacementRange: NSRange) {
        super.insertText(string, replacementRange: replacementRange); onEvent?("insertText")
    }
    override func setMarkedText(_ string: Any, selectedRange: NSRange, replacementRange: NSRange) {
        super.setMarkedText(string, selectedRange:selectedRange, replacementRange:replacementRange); onEvent?("markedText")
    }
    override func keyDown(with event: NSEvent) { onEvent?("keyDown"); super.keyDown(with:event) }
    override func mouseDown(with event: NSEvent) { onEvent?(event.clickCount == 2 ? "doubleClick" : "mouseDown"); super.mouseDown(with:event) }
}
final class ComputerFixture: NSObject, NSApplicationDelegate, WKScriptMessageHandler, NSTableViewDataSource, NSTableViewDelegate {
    var protectedWindow:NSWindow?; var coverWindow:NSWindow?
    var lastCommand=""
    var window: NSWindow!; var second: NSWindow!; var field: NSTextField!; var result: NSTextField!
    var text: InstrumentedText!; var web: WKWebView!; var tabs: NSTabView!
    var nativeEvents:[[String:Any]]=[]
    var generation=0; var applied=0; var events:[String:Int]=[:]; var webValue=""; var sheet:NSWindow?
    let directory: URL
    init(_ path:String) { directory=URL(fileURLWithPath:path); super.init() }
    func applicationDidFinishLaunching(_ notification:Notification) {
        buildWindow(); buildSecond(); buildMenu()
        fixtureEventSink={ event in
            self.nativeEvents.append(["type":event.type.rawValue,"key_code":event.keyCode,"flags":event.modifierFlags.rawValue,"window":event.windowNumber,"marker":event.cgEvent?.getIntegerValueField(.eventSourceUserData) ?? 0])
            if self.nativeEvents.count > 500 { self.nativeEvents.removeFirst() }; self.save()
        }
        Timer.scheduledTimer(withTimeInterval:0.1, repeats:true) { _ in self.processFixtureCommand(); self.save() }
        save()
    }
    func field(_ text:String,_ id:String,_ frame:NSRect) -> NSTextField {
        let v=NSTextField(string:text); v.frame=frame; v.setAccessibilityIdentifier(id); return v
    }
    func button(_ title:String,_ id:String,_ x:Double,_ y:Double,_ action:Selector) -> NSButton {
        let b=NSButton(title:title,target:self,action:action); b.frame=NSRect(x:x,y:y,width:145,height:30); b.setAccessibilityIdentifier(id); return b
    }
    func buildWindow() {
        generation += 1
        window=NSWindow(contentRect:NSRect(x:100,y:100,width:760,height:630),styleMask:[.titled,.closable,.resizable,.miniaturizable],backing:.buffered,defer:false)
        window.isReleasedWhenClosed=false; window.title="LocalPilot Computer Fixture"; window.setAccessibilityIdentifier("cu.window")
        let content=window.contentView!
        field=self.field("initial","cu.input",NSRect(x:20,y:570,width:510,height:28)); field.setAccessibilityLabel("Test input")
        result=NSTextField(labelWithString:"ready"); result.frame=NSRect(x:20,y:535,width:710,height:28); result.setAccessibilityIdentifier("cu.result")
        content.addSubview(field); content.addSubview(result)
        for b in [button("Apply","cu.apply",550,570,#selector(apply)),button("Open Sheet","cu.sheet",20,495,#selector(openSheet)),button("Choose File","cu.file",180,495,#selector(chooseFile)),button("Rebuild Window","cu.rebuild",340,495,#selector(rebuild)),button("Move Window","cu.move",500,495,#selector(move))] { content.addSubview(b) }
        tabs=NSTabView(frame:NSRect(x:20,y:20,width:720,height:460)); tabs.setAccessibilityIdentifier("cu.tabs")
        let native=NSTabViewItem(identifier:"native"); native.label="Native Editor"
        let nativeView=NSView(frame:NSRect(x:0,y:0,width:700,height:420))
        let scroll=NSScrollView(frame:NSRect(x:10,y:220,width:670,height:175)); scroll.hasVerticalScroller=true; scroll.setAccessibilityIdentifier("cu.rich.scroll"); scroll.verticalScroller?.setAccessibilityIdentifier("cu.rich.scrollbar")
        text=InstrumentedText(frame:NSRect(x:0,y:0,width:650,height:170)); text.string="native initial"; text.isRichText=true; text.setAccessibilityIdentifier("cu.richtext"); text.setAccessibilityLabel("Rich text test editor")
        text.onEvent={ name in self.events[name,default:0]+=1; if name == "doubleClick" { self.result.stringValue="double clicked" }; self.save() }; scroll.documentView=text; nativeView.addSubview(scroll)
        let listScroll=NSScrollView(frame:NSRect(x:10,y:10,width:670,height:190)); listScroll.hasVerticalScroller=true; listScroll.setAccessibilityIdentifier("cu.list.scroll"); listScroll.verticalScroller?.setAccessibilityIdentifier("cu.list.scrollbar")
        let table=NSTableView(frame:NSRect(x:0,y:0,width:650,height:1000)); table.setAccessibilityIdentifier("cu.list")
        let column=NSTableColumn(identifier:NSUserInterfaceItemIdentifier("items")); column.title="Generated records"; column.width=640; table.addTableColumn(column); table.dataSource=self; table.delegate=self
        listScroll.documentView=table; nativeView.addSubview(listScroll); native.view=nativeView; tabs.addTabViewItem(native)
        let webTab=NSTabViewItem(identifier:"web"); webTab.label="Browser Form"
        let config=WKWebViewConfiguration(); config.userContentController.add(self,name:"fixture")
        web=WKWebView(frame:NSRect(x:0,y:0,width:700,height:420),configuration:config); web.setAccessibilityIdentifier("cu.web")
        web.loadHTMLString("""
        <!doctype html><html lang="zh"><body style="font:20px system-ui;padding:24px"><h2>Generated browser form</h2><label for="entry">中文测试文本</label><br><textarea id="entry" aria-label="Browser text" style="width:540px;height:100px"></textarea><br><button id="submit" onclick="document.getElementById('output').textContent='web:'+document.getElementById('entry').value;window.webkit.messageHandlers.fixture.postMessage(document.getElementById('entry').value)">Apply browser form</button><p id="output" aria-label="Browser result">web ready</p><script>document.getElementById('entry').addEventListener('input',e=>window.webkit.messageHandlers.fixture.postMessage(e.target.value));</script></body></html>
        """,baseURL:nil)
        webTab.view=web; tabs.addTabViewItem(webTab); content.addSubview(tabs)
        if CommandLine.arguments.contains("--background") { window.orderBack(nil) } else { window.orderFrontRegardless() }
    }
    func buildSecond() {
        second=NSWindow(contentRect:NSRect(x:900,y:150,width:340,height:220),styleMask:[.titled,.closable,.resizable],backing:.buffered,defer:false)
        second.isReleasedWhenClosed=false; second.title="LocalPilot Computer Secondary"; second.setAccessibilityIdentifier("cu.secondary")
        let label=NSTextField(labelWithString:"Generated secondary window"); label.frame=NSRect(x:15,y:150,width:300,height:26); second.contentView?.addSubview(label)
        second.contentView?.addSubview(button("Move Main","cu.secondary.move",20,90,#selector(move)))
        if CommandLine.arguments.contains("--background") { second.orderBack(nil) } else { second.orderFrontRegardless() }
    }
    func buildMenu() {
        let bar=NSMenu(); let app=NSMenuItem(); bar.addItem(app)
        let menu=NSMenu(); menu.addItem(withTitle:"Fixture Menu Action",action:#selector(menuAction),keyEquivalent:"m").target=self
        menu.addItem(withTitle:"Quit Fixture",action:#selector(quit),keyEquivalent:"q").target=self
        app.title="Fixture"; app.submenu=menu
        let edit=NSMenuItem(); edit.title="Edit"; let editMenu=NSMenu(title:"Edit")
        editMenu.addItem(withTitle:"Select All",action:#selector(NSText.selectAll(_:)),keyEquivalent:"a")
        edit.submenu=editMenu; bar.addItem(edit); NSApp.mainMenu=bar
    }
    @objc func apply() { applied += 1; result.stringValue="applied:\(field.stringValue):\(applied)"; save() }
    @objc func menuAction() { result.stringValue="menu applied"; save() }
    @objc func openSheet() {
        let s=NSWindow(contentRect:NSRect(x:0,y:0,width:350,height:150),styleMask:[.titled],backing:.buffered,defer:false)
        s.title="Fixture Sheet"; s.setAccessibilityIdentifier("cu.sheet.window")
        s.contentView?.addSubview(field("sheet initial","cu.sheet.input",NSRect(x:20,y:85,width:300,height:28)))
        s.contentView?.addSubview(button("Close Sheet","cu.sheet.close",20,25,#selector(closeSheet)))
        sheet=s; window.beginSheet(s); save()
    }
    @objc func closeSheet() { if let s=sheet { window.endSheet(s); s.orderOut(nil); sheet=nil }; result.stringValue="sheet closed"; save() }
    @objc func chooseFile() {
        let panel=NSOpenPanel(); panel.directoryURL=directory; panel.canChooseDirectories=false; panel.allowsMultipleSelection=false
        panel.beginSheetModal(for:window) { response in
            self.result.stringValue=response == .OK ? "file:"+(panel.url?.lastPathComponent ?? "UNKNOWN") : "file cancelled"; self.save()
        }
    }
    @objc func rebuild() { window.close(); buildWindow(); save() }
    @objc func move() { window.setFrameOrigin(NSPoint(x:window.frame.origin.x+35,y:window.frame.origin.y+20)); result.stringValue="moved"; save() }
    @objc func quit() { NSApp.terminate(nil) }
    func numberOfRows(in tableView:NSTableView) -> Int { 80 }
    func tableView(_ tableView:NSTableView, objectValueFor tableColumn:NSTableColumn?, row:Int) -> Any? { "Generated record \(row)" }
    func tableViewSelectionDidChange(_ notification:Notification) {
        if let table=notification.object as? NSTableView { result.stringValue="selected:\(table.selectedRow)"; save() }
    }
    func userContentController(_ userContentController:WKUserContentController,didReceive message:WKScriptMessage) { webValue=message.body as? String ?? ""; events["webInput",default:0]+=1; save() }
    // Host fault-injection surface in this generated fixture only. It is not
    // registered as a product/model tool and never accepts arbitrary code/path.
    func processFixtureCommand() {
        let path=directory.appendingPathComponent("fixture-command.json")
        guard let data=try? Data(contentsOf:path), let command=(try? JSONSerialization.jsonObject(with:data)) as? [String:String], let id=command["id"], id != lastCommand, let name=command["command"] else { return }
        lastCommand=id; try? FileManager.default.removeItem(at:path)
        switch name {
        case "move":move()
        case "rebuild":rebuild()
        case "show_sheet":openSheet()
        case "close_sheet":closeSheet()
        case "web_tab":tabs.selectTabViewItem(at:1)
        case "native_tab":tabs.selectTabViewItem(at:0)
        case "cover":
            coverWindow=NSWindow(contentRect:window.frame,styleMask:[.titled,.closable],backing:.buffered,defer:false)
            coverWindow?.title="LocalPilot Fixture Cover";coverWindow?.isReleasedWhenClosed=false;coverWindow?.orderFrontRegardless()
        case "uncover":coverWindow?.close();coverWindow=nil
        case "protected":
            let s=NSWindow(contentRect:NSRect(x:150,y:150,width:400,height:200),styleMask:[.titled,.closable],backing:.buffered,defer:false)
            s.title="LocalPilot Computer Protected Fixture";s.isReleasedWhenClosed=false;s.setAccessibilityIdentifier("cu.protected.window")
            let field=NSSecureTextField(frame:NSRect(x:20,y:110,width:350,height:28));field.stringValue="generated-test-secret";field.setAccessibilityIdentifier("cu.protected.input");s.contentView?.addSubview(field)
            s.contentView?.addSubview(button("Protected Test Button","cu.protected.button",20,40,#selector(menuAction)));s.orderFrontRegardless();protectedWindow=s
        case "close_protected":protectedWindow?.close();protectedWindow=nil
        default:break
        }
    }
    func save() {
        guard window != nil else { return }
        let state:[String:Any]=["last_command":lastCommand,"protected_visible":protectedWindow != nil,"generation":generation,"window_id":window.windowNumber,"input":field.stringValue,"result":result.stringValue,"richtext":text.string,"marked_text":text.hasMarkedText(),"web":webValue,"events":events,"native_events":nativeEvents,"active":NSApp.isActive,"sheet":sheet != nil]
        if let data=try? JSONSerialization.data(withJSONObject:state,options:[.sortedKeys]) { try? data.write(to:directory.appendingPathComponent("fixture-state.json"),options:.atomic) }
    }
}
let app=FixtureApplication.shared; app.setActivationPolicy(.regular)
let directory=CommandLine.arguments.count>1 ? CommandLine.arguments[1] : NSTemporaryDirectory()+"localpilot-computer-fixture"
try FileManager.default.createDirectory(atPath:directory,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700])
let delegate=ComputerFixture(directory); app.delegate=delegate; app.run()
