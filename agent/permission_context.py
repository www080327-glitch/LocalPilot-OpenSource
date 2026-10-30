"""Per-dispatch host permission context; never set from model tool arguments."""
from contextvars import ContextVar
from contextlib import contextmanager
_full = ContextVar('localpilot_full_file_access', default=False)

def full_access():
    return _full.get() is True

@contextmanager
def dispatch_access(enabled):
    token = _full.set(enabled is True)
    try:
        yield
    finally:
        _full.reset(token)
