import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux native fixture required')
class LinuxNativeProcessTests(unittest.TestCase):
    def test_owned_gtk_readonly_observation_and_pause(self):
        if not all(shutil.which(name) for name in ('Xvfb', 'dbus-run-session', 'gdbus')):
            self.skipTest('Isolated Linux Xvfb/D-Bus tools unavailable')
        probe = subprocess.run(['/usr/bin/python3', '-c',
            'import gi; gi.require_version("Atspi", "2.0"); gi.require_version("Gtk", "3.0")'],
            capture_output=True, text=True, timeout=5)
        if probe.returncode:
            self.skipTest('Distro Python GI Atspi/Gtk bindings unavailable')
        bus = subprocess.run([shutil.which('dbus-run-session'), '--', '/bin/true'],
                             capture_output=True, text=True, timeout=5)
        if bus.returncode and 'Failed to open socket: Operation not permitted' in bus.stderr:
            self.skipTest('Environment blocks the isolated D-Bus Unix socket; native GTK test NOT_RUN')
        self.assertEqual(bus.returncode, 0, bus.stderr)
        result = subprocess.run([shutil.which('dbus-run-session'), '--', sys.executable,
            str(Path(__file__).with_name('linux_native_fixture.py'))], capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(report['status'], 'PASS')
        self.assertTrue(report['editable_and_password_excluded'])


if __name__ == '__main__':
    unittest.main()
