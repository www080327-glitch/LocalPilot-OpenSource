// Read-only macOS provider. No actions, attribute setters or input dispatch.
import Foundation
import ApplicationServices

extension AXReadProvider where Element == AXUIElement {
    static func system(messageTimeout: Float = 0.75) -> AXReadProvider<AXUIElement> {
        AXReadProvider<AXUIElement>(read: { element, attribute in
            AXUIElementSetMessagingTimeout(element, messageTimeout)
            var value: CFTypeRef?
            let error = AXUIElementCopyAttributeValue(element, attribute as CFString, &value)
            return AXAttributeRead(value: value, error: Int(error.rawValue))
        }, elements: { value in
            if let elements = value as? [AXUIElement] { return elements }
            if let value = value as CFTypeRef?, CFGetTypeID(value) == AXUIElementGetTypeID() {
                return [unsafeBitCast(value, to: AXUIElement.self)]
            }
            return nil
        }, equal: { CFEqual($0, $1) })
    }
}
