"""Owned GTK window on an isolated Xvfb display and D-Bus session."""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def gtk_window():
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('GdkX11', '3.0')
    from gi.repository import Gtk, Gdk, GLib
    window = Gtk.Window(title='LocalPilot owned Linux fixture')
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.pack_start(Gtk.Label(label='Owned Linux receipt 7492'), True, True, 5)
    entry = Gtk.Entry()
    entry.set_text('INPUT_CONTENT_MUST_NOT_BE_OBSERVED')
    box.pack_start(entry, True, True, 5)
    password = Gtk.Entry()
    password.set_visibility(False)
    password.set_text('PASSWORD_CONTENT_MUST_NOT_BE_OBSERVED')
    box.pack_start(password, True, True, 5)
    window.add(box)
    window.set_default_size(480, 240)
    window.show_all()
    window.present()

    def focus():
        window.get_window().focus(Gdk.CURRENT_TIME)
        import ctypes
        lib = ctypes.CDLL('libX11.so.6')
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.XInternAtom.restype = ctypes.c_ulong
        lib.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                                       ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int]
        lib.XFlush.argtypes = [ctypes.c_void_p]
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        display = lib.XOpenDisplay(None)
        root = lib.XDefaultRootWindow(display)
        atom = lib.XInternAtom(display, b'_NET_ACTIVE_WINDOW', False)
        value = ctypes.c_ulong(window.get_window().get_xid())
        lib.XChangeProperty(display, root, atom, 33, 32, 0, ctypes.cast(ctypes.byref(value), ctypes.POINTER(ctypes.c_ubyte)), 1)
        lib.XFlush(display)
        lib.XCloseDisplay(display)
        print(json.dumps({'ready':True, 'pid':os.getpid()}), flush=True)
        return False

    GLib.timeout_add(400, focus)
    Gtk.main()


def check():
    from companion.config import Config
    from companion.observers.linux import LinuxNativeObserver
    from companion.observers.linux_helper import application_id
    temporary = tempfile.TemporaryDirectory()
    processes = []
    observer = None
    display_read, display_write = os.pipe()
    try:
        server = subprocess.Popen([shutil.which('Xvfb'), '-displayfd', str(display_write), '-screen', '0',
            '800x600x24', '-nolisten', 'tcp'], pass_fds=(display_write,), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        processes.append(server)
        os.close(display_write)
        display_write = None
        if not select.select([display_read], [], [], 8)[0]:
            raise RuntimeError('Owned Xvfb did not create a display')
        display = os.read(display_read, 100).decode().strip()
        if not display.isdecimal():
            raise RuntimeError('Owned Xvfb returned invalid display')
        os.environ.update(DISPLAY=':' + display, XDG_SESSION_TYPE='x11', NO_AT_BRIDGE='0')
        subprocess.run(['gdbus', 'call', '--session', '--dest', 'org.a11y.Bus', '--object-path', '/org/a11y/bus',
            '--method', 'org.freedesktop.DBus.Properties.Set', 'org.a11y.Status', 'IsEnabled', '<true>'],
            check=True, capture_output=True, timeout=5)
        child = subprocess.Popen(['/usr/bin/python3', str(Path(__file__).resolve()), '--gtk'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        processes.append(child)
        if not select.select([child.stdout], [], [], 8)[0]:
            raise RuntimeError('Owned GTK fixture did not become ready')
        ready = json.loads(child.stdout.readline())
        app = application_id(ready['pid'])
        events = []
        config = Config(data_dir=str(Path(temporary.name) / 'state'), native_observation_enabled=True,
            native_ax_enabled=True, native_app_allowlist=(app,), native_content_app_allowlist=(app,),
            native_content_window_allowlist=('LocalPilot owned Linux fixture',), low_power_policy='off',
            native_ax_max_nodes=30, native_ax_max_depth=5)
        observer = LinuxNativeObserver(config, events.append)
        started = observer.start()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not any('Owned Linux receipt 7492' in json.dumps(event) for event in events):
            time.sleep(.1)
        observer.pause()
        rendered = json.dumps(events, ensure_ascii=False)
        assert 'Owned Linux receipt 7492' in rendered, rendered + '\n' + json.dumps(started)
        assert 'INPUT_CONTENT_MUST_NOT_BE_OBSERVED' not in rendered, rendered
        assert 'PASSWORD_CONTENT_MUST_NOT_BE_OBSERVED' not in rendered, rendered
        assert any(event['source'] == 'linux_accessibility' for event in events), rendered
        assert observer.process is None
        print(json.dumps({'status':'PASS', 'scope':'owned GTK + isolated Xvfb/D-Bus; no user apps',
            'readable_static_text':True, 'editable_and_password_excluded':True,
            'helper_stopped_on_pause':True, 'events':events, 'capabilities':started['capabilities']}, ensure_ascii=False))
    finally:
        if observer:
            observer.stop()
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            for stream in (process.stdout, process.stderr):
                if stream:
                    stream.close()
        os.close(display_read)
        if display_write is not None:
            os.close(display_write)
        temporary.cleanup()


if __name__ == '__main__':
    gtk_window() if sys.argv[1:] == ['--gtk'] else check()
