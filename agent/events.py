"""Frontend-neutral events. Renderers subscribe; runtime code never prints."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class RuntimeEvent:
    sequence: int
    type: str
    data: dict
    turn_id: int
    timestamp: str

    def to_dict(self):
        return asdict(self)


class EventStream:
    def __init__(self, callback=None, max_events=2000):
        self.callback = callback
        self.max_events = max_events
        self.events = []
        self.sequence = 0
        self.observer_errors = []

    def emit(self, event_type, *, turn_id=0, **data):
        self.sequence += 1
        event = RuntimeEvent(self.sequence, event_type, data, turn_id,
                             datetime.now(timezone.utc).isoformat())
        self.events.append(event)
        del self.events[:-self.max_events]
        if self.callback:
            try:
                self.callback(event)
            except Exception as error:
                # A failing GUI/renderer must never replay or interrupt a tool.
                self.observer_errors.append(type(error).__name__)
                del self.observer_errors[:-20]
        return event
