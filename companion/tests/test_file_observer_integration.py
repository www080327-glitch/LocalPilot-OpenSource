"""Exercise Companion's real filesystem observer with a temporary directory."""
import queue
from pathlib import Path
import tempfile
import time
import unittest

from companion.config import Config
from companion.observers.files import FileObserver, ReadScope


class FileObserverIntegrationTests(unittest.TestCase):
    def test_created_and_deleted_document_events(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            events = queue.Queue()
            observer = FileObserver(
                ReadScope(Config(watch_dirs=(str(root),), exclude_dirs=())),
                lambda path, kind: events.put((path, kind)),
            )
            observer.start()
            try:
                document = root / "observed.txt"
                document.write_text("observed", encoding="utf-8")
                self.assert_event(events, document, {"created", "modified"})
                document.unlink()
                self.assert_event(events, document, {"deleted"})
            finally:
                observer.stop()

    def assert_event(self, events, document, kinds):
        deadline = time.monotonic() + 10
        received = []
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                event = events.get(timeout=remaining)
            except queue.Empty:
                break
            received.append(event)
            if event[0] == str(document) and event[1] in kinds:
                return
        self.fail(f"No {kinds} event for document; received {received!r}")
