"""Linux provider for the existing native observation transport."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

from .native import NativeObserver


HELPER = Path(__file__).with_name('linux_helper.py')


def helper_environment():
    result = {'PATH':os.environ.get('PATH', '/usr/bin:/bin'), 'LANG':'C.UTF-8', 'LC_ALL':'C.UTF-8'}
    for name in ('DISPLAY', 'XAUTHORITY', 'XDG_SESSION_TYPE', 'XDG_SESSION_ID', 'XDG_RUNTIME_DIR',
                 'DBUS_SESSION_BUS_ADDRESS', 'AT_SPI_BUS_ADDRESS', 'HOME', 'GI_TYPELIB_PATH', 'LD_LIBRARY_PATH', 'XDG_DATA_DIRS'):
        if name in os.environ:
            result[name] = os.environ[name]
    return result


def helper_runtime():
    for executable in dict.fromkeys((sys.executable, '/usr/bin/python3')):
        try:
            result = subprocess.run([executable, str(HELPER), '--probe'], capture_output=True,
                                    text=True, timeout=3, env=helper_environment())
            if result.returncode == 0 and json.loads(result.stdout).get('atspi') is True:
                return executable, True
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    return sys.executable, False


def capabilities():
    executable, atspi = helper_runtime()
    x11 = bool(os.environ.get('DISPLAY') and os.environ.get('XDG_SESSION_TYPE') != 'wayland' and shutil.which('xprop'))
    return {'platform':'linux', 'x11_foreground_metadata':x11,
            'atspi_static_text':atspi and bool(os.environ.get('DBUS_SESSION_BUS_ADDRESS')),
            'atspi_installed':atspi, 'session_logind':bool(shutil.which('loginctl')),
            'wayland_global_windows':False, 'scope':'authorized_foreground_registered_apps_only',
            'read_only_actions':True, 'os_read_only_sandbox':False, 'helper_python':executable,
            'native_validation':'runtime_checked_on_explicit_start'}


class LinuxNativeObserver(NativeObserver):
    def __init__(self, config, callback):
        super().__init__(config, callback)
        self.capabilities = None

    def status(self):
        return super().status() | {'platform':'linux', 'capabilities':self.capabilities,
            'coverage':'PARTIAL; AT-SPI registered foreground static text, X11 metadata, logind session hints'}

    def start(self):
        if not self.config.native_observation_enabled or self._paused:
            return super().start()
        if self.process is not None and self.process.poll() is None:
            return self.status()
        if self.options.get('controlled_target'):
            self._state, self._reason = 'unavailable', 'macos_controlled_validation_target_not_supported'
            return self.status()
        self.capabilities = capabilities()
        from .linux_helper import session_state
        if not self.capabilities['x11_foreground_metadata'] and not self.capabilities['atspi_static_text'] and not session_state():
            self._state, self._reason = 'unavailable', 'No accessible graphical session, X11 display or AT-SPI session bus'
            return self.status()
        try:
            self.process = subprocess.Popen([self.capabilities['helper_python'], str(HELPER)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=helper_environment(), close_fds=True)
            self.process.stdin.write((json.dumps(self.options) + '\n').encode())
            self.process.stdin.close()
            self._state, self._reason = 'running', 'read-only Linux helper; 5-second session polling and bounded foreground refresh'
            self.thread = threading.Thread(target=self._read, args=(self.process,), daemon=True)
            self.thread.start()
        except (OSError, ValueError):
            self._state, self._reason = 'error', 'Linux observer helper unavailable'
            self.stop()
        return self.status()
