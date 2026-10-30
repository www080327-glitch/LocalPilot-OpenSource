"""Device backend contract. Inference backends and the permission gateway are unrelated."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class ComputerBackend(Protocol):
    allowed_apps: frozenset
    name: str
    native_keyboard: bool
    capabilities: dict

    def environment(self): ...
    def inspect_apps(self): ...
    def inspect_tree(self, app, **bounds): ...
    def action(self, app, handle, kind, **args): ...
    def qualify_action(self, name, app, node): ...
    def request_stop(self): ...
    def quiesce(self): ...
    def finish_resume(self): ...
    def close(self): ...


class AXBackend:
    """Compatibility wrapper for the existing adapter, including scripted adapters."""
    name = "macos_ax"
    native_keyboard = False
    capabilities = {
        "semantic_ax": "existing", "background_keyboard": "unsupported",
        "ime_isolation": "UNKNOWN", "modifier_isolation": "unsupported",
        "NSTextView": "AX_only", "WKWebView": "AX_only", "AppKit_sheet": "AX_only",
        "ViewBridge": "UNKNOWN", "Electron": "UNKNOWN", "menu": "foreground_only",
        "background_mouse": "unsupported",
    }

    def __init__(self, adapter):
        self.transport = adapter
        self.allowed_apps = adapter.allowed_apps

    def environment(self):
        return self.transport.environment()

    def inspect_apps(self):
        return self.transport.inspect_apps()

    def inspect_tree(self, app, **bounds):
        return self.transport.inspect_tree(app, **bounds)

    def action(self, app, handle, kind, **args):
        return self.transport.action(app, handle, kind, **args)

    def qualify_action(self, name, app, node):
        if name == "type_text":
            return {"status": "error", "error": "capability_rejected", "action_sent": False,
                    "capability": "background_keyboard", "fallback": "human"}
        return {"status": "ok", "concurrent_input": False}

    def request_stop(self):
        pass

    def quiesce(self):
        return {"status": "ok", "cleanup": "not_required", "quiescent": True}

    def finish_resume(self):
        pass

    def close(self):
        self.transport.close()
