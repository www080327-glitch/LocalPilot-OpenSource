// Disposable native AppKit test surface; launched in the background, no user data.
import AppKit

final class Fixture: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var field: NSTextField!
    var result: NSTextField!
    var count = 0
    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 60, y: 80, width: 440, height: 230),
                          styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "LocalPilot AX Test"
        window.setAccessibilityIdentifier("lp.fixture.window")
        field = NSTextField(frame: NSRect(x: 20, y: 165, width: 390, height: 28))
        field.stringValue = "initial"
        field.setAccessibilityIdentifier("lp.fixture.input")
        field.setAccessibilityLabel("Test input")
        result = NSTextField(labelWithString: "ready")
        result.frame = NSRect(x: 20, y: 40, width: 390, height: 30)
        result.setAccessibilityIdentifier("lp.fixture.result")
        let button = NSButton(title: "Apply test value", target: self, action: #selector(apply))
        button.frame = NSRect(x: 20, y: 100, width: 190, height: 32)
        button.setAccessibilityIdentifier("lp.fixture.apply")
        let replace = NSButton(title: "Replace field", target: self, action: #selector(replaceField))
        replace.frame = NSRect(x: 230, y: 100, width: 170, height: 32)
        replace.setAccessibilityIdentifier("lp.fixture.replace")
        window.contentView?.addSubview(field)
        window.contentView?.addSubview(result)
        window.contentView?.addSubview(button)
        window.contentView?.addSubview(replace)
        window.orderFrontRegardless() // Visible test window; does not make app active.
    }
    @objc func apply() { count += 1; result.stringValue = "applied:\(field.stringValue):\(count)" }
    @objc func replaceField() {
        let frame = field.frame
        field.removeFromSuperview()
        field = NSTextField(frame: frame)
        field.stringValue = "replaced"
        field.setAccessibilityIdentifier("lp.fixture.input")
        field.setAccessibilityLabel("Test input replacement")
        window.contentView?.addSubview(field)
    }
}
let application = NSApplication.shared
application.setActivationPolicy(.accessory)
let delegate = Fixture()
application.delegate = delegate
application.run()
