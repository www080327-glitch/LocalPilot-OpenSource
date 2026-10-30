import os
from pathlib import Path
from companion.config import SENSITIVE

EXTENSIONS = {".txt", ".md", ".docx", ".pptx", ".xlsx", ".pdf"}


class ReadScope:
    def __init__(self, config):
        self.config = config
        self.roots = [Path(p) for p in config.watch_dirs]
        self.excludes = [Path(p) for p in config.exclude_dirs]

    def within(self, filename):
        p = Path(os.path.abspath(filename))
        root = next((root for root in self.roots if root == p or root in p.parents), None)
        return (root is not None and
                not any(part in SENSITIVE or part.startswith(".") or part.startswith("~$") for part in p.relative_to(root).parts) and
                not any(e == p or e in p.parents for e in self.excludes) and
                not any(x.is_symlink() for x in (p, *p.parents)))

    def allowed(self, filename):
        from companion.observers.events import PRIVATE_FILE
        p = Path(os.path.abspath(filename))
        return p.suffix.lower() in EXTENSIONS and self.within(p) and not PRIVATE_FILE.search(str(p))

    def read(self, filename):
        """Descriptor traversal refuses symlinks and opens the source O_RDONLY only."""
        p = Path(os.path.abspath(filename))
        if not self.allowed(p):
            raise PermissionError("Outside read scope")
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in p.parts[1:-1]:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
            source_fd = os.open(p.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        finally:
            os.close(fd)
        with os.fdopen(source_fd, "rb") as source:
            import stat
            st = os.fstat(source.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_size > self.config.max_file_bytes:
                raise ValueError("Not a regular bounded document")
            content = source.read(self.config.max_file_bytes + 1)
            after = os.fstat(source.fileno())
            if len(content) > self.config.max_file_bytes or (st.st_mtime_ns, st.st_size) != (after.st_mtime_ns, after.st_size):
                raise ValueError("Document changed while reading; retry on next event")
            return content, st

    def scan(self):
        count = 0
        for root in self.roots:
            for parent, dirs, files in os.walk(root, followlinks=False):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SENSITIVE and not (Path(parent)/d).is_symlink() and not any(e == Path(parent)/d or e in (Path(parent)/d).parents for e in self.excludes)]
                for name in files:
                    count += 1
                    if count > self.config.max_scan_files:
                        raise ValueError("Startup scan budget exceeded; choose smaller directories")
                    p = Path(parent) / name
                    if self.allowed(p):
                        yield str(p)


class FileObserver:
    def __init__(self, scope, callback):
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):
                if event.event_type not in {"created", "modified", "deleted", "moved"}:
                    return
                if event.is_directory:
                    # A directory move/delete may invalidate many indexed sources.
                    if event.event_type in {"created", "moved", "deleted"}:
                        callback("", "rescan")
                    return
                if scope.allowed(event.src_path):
                    callback(event.src_path, "deleted" if event.event_type == "moved" else event.event_type)
                destination = getattr(event, "dest_path", "")
                if destination and scope.allowed(destination):
                    callback(destination, "created")

        self.observer = Observer()
        for root in scope.roots:
            self.observer.schedule(Handler(), str(root), recursive=True)

    def start(self):
        self.observer.start()

    def stop(self):
        self.observer.stop()
        if self.observer.ident is not None:
            self.observer.join(timeout=5)
