"""Task-local opt-in for local inference while macOS is in low-power mode."""
from contextlib import contextmanager
from contextvars import ContextVar

_allowed = ContextVar('localpilot_low_power_task_consent', default=False)


def allowed():
    return _allowed.get() is True


@contextmanager
def task_consent(confirmed):
    token = _allowed.set(confirmed is True)
    try:
        yield
    finally:
        _allowed.reset(token)
