"""Linux adapters exercise files, real CLI subprocesses and retained observations."""
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

from companion.config import Config, PrivateData, default_data_dir
from companion.runtime import linux_power, systemd
from companion.runtime.power import LowPowerPolicy
from companion.observers.native import filter_native_event, native_options
from companion.observers.linux_helper import application_id, session_events
from companion.observers.linux_meeting_helper import Capture, wav_bytes, capture_command


class LinuxPowerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def supply(self, name, **values):
        folder = self.root / name
        folder.mkdir(exist_ok=True)
        for key, value in values.items():
            (folder / key).write_text(str(value) + '\n')
        return folder

    def test_no_supply_is_unknown_and_mains_online_is_observed(self):
        self.assertIsNone(linux_power.external_power(self.root))
        self.supply('AC', type='Mains', online=0)
        self.assertFalse(linux_power.external_power(self.root))
        self.supply('USB_C', type='USB_C', online=1)
        self.assertTrue(linux_power.external_power(self.root))

    def test_unknown_online_and_peripheral_battery_do_not_invent_ac(self):
        self.supply('mouse', type='Battery', online=1)
        self.supply('phone', type='USB', online=1, scope='Device')
        self.supply('AC', type='Mains', online='unknown')
        self.assertIsNone(linux_power.external_power(self.root))

    def test_battery_watts_use_micro_units_and_add_real_readings(self):
        self.supply('BAT0', type='Battery', status='Discharging', power_now=15_000_000)
        self.supply('BAT1', type='Battery', status='Discharging', voltage_now=12_000_000, current_now=-2_000_000)
        self.assertEqual(linux_power.battery_discharge(self.root), 39.0)

    def test_partial_battery_telemetry_is_unknown(self):
        self.supply('BAT0', type='Battery', status='Discharging', power_now=15_000_000)
        battery = self.supply('BAT1', type='Battery', status='Charging', power_now=2_000_000)
        self.assertIsNone(linux_power.battery_discharge(self.root))
        (battery / 'status').write_text('Discharging\n')
        (battery / 'power_now').write_text('invalid\n')
        self.assertIsNone(linux_power.battery_discharge(self.root))

    def test_actual_powerprofiles_process_is_read_only_and_conservative(self):
        executable = self.root / 'powerprofilesctl'
        mode = self.root / 'mode'
        executable.write_text('#!/bin/sh\n[ "$#" = 1 ] && [ "$1" = get ] || exit 5\n/bin/cat "' + str(mode) + '"\n')
        executable.chmod(0o700)
        with patch.dict(os.environ, {'PATH':str(self.root)}), patch.object(linux_power, 'PLATFORM_PROFILE', self.root / 'absent'):
            for value, expected in [('power-saver', True), ('balanced', False), ('performance', False), ('unknown', None)]:
                mode.write_text(value)
                self.assertIs(linux_power.low_power(), expected)

    def test_platform_profile_fallback_and_system_policy(self):
        profile = self.root / 'platform_profile'
        with patch.dict(os.environ, {'PATH':str(self.root)}), patch.object(linux_power, 'PLATFORM_PROFILE', profile), patch('companion.runtime.power.sys.platform', 'linux'):
            for value, expected in [('low-power', True), ('balanced', False), ('performance', False), ('unrecognized', True)]:
                profile.write_text(value)
                self.assertIs(LowPowerPolicy(Config(low_power_policy='system')).active(), expected)

    def test_xdg_data_home_defaults_without_creating_anything(self):
        with patch.dict(os.environ, {'XDG_DATA_HOME':str(self.root / 'xdg')}), patch('companion.config.sys.platform', 'linux'):
            self.assertEqual(default_data_dir(), str(self.root / 'xdg' / 'LocalPilotCompanion'))
            self.assertFalse((self.root / 'xdg').exists())


class LinuxSystemdTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.private = PrivateData(self.root / 'state')
        self.config = self.root / 'config $A %n.json'
        self.config.write_text('{}')

    def test_unit_is_accepted_by_systemd_parser_with_literal_paths(self):
        executable = shutil.which('systemd-analyze')
        if not executable:
            self.skipTest('systemd-analyze unavailable')
        text = systemd.unit_text(self.config)
        self.assertIn('$$A %%n.json', text)
        self.assertIn('Restart=no', text)
        self.assertNotIn('sudo', text)
        unit = self.root / systemd.UNIT
        unit.write_text(text)
        result = subprocess.run([executable, 'verify', str(unit)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_preview_and_confirmation_do_not_install(self):
        with patch.dict(os.environ, {'XDG_CONFIG_HOME':str(self.root / 'config')}), patch('companion.runtime.systemd.sys.platform', 'linux'):
            preview = systemd.manage('render', self.config, self.private)
            self.assertEqual(preview['status'], 'preview')
            self.assertEqual(Path(preview['path']).read_text(), systemd.unit_text(self.config))
            result = systemd.manage('install', self.config, self.private)
            self.assertEqual(result['status'], 'confirmation_required')
            self.assertFalse((self.root / 'config').exists())

    def manager(self, fail=False):
        executable = self.root / 'systemctl'
        executable.write_text(f'#!{sys.executable}\nimport sys\n'
            f'from pathlib import Path\nwith Path({str(self.root / "calls")!r}).open("a") as f: f.write(repr(sys.argv[1:])+"\\n")\n'
            'assert sys.argv[1] == "--user"\n'
            f'if {fail!r} and "enable" in sys.argv: raise SystemExit(1)\n'
            'if "show" in sys.argv: print("ActiveState=active\\nMainPID=0")\n')
        executable.chmod(0o700)

    def test_install_and_uninstall_bind_exact_owned_file(self):
        self.manager()
        environment = self.root / 'clients.env'
        environment.write_text('LOCALPILOT_COMPANION_TOKEN=not-a-real-token\n')
        environment.chmod(0o600)
        with patch.dict(os.environ, {'PATH':str(self.root), 'XDG_CONFIG_HOME':str(self.root / 'config')}), patch('companion.runtime.systemd.sys.platform', 'linux'):
            installed = systemd.manage('install', self.config, self.private, True, str(environment))
            self.assertEqual(installed['status'], 'installed')
            unit = Path(installed['path'])
            self.assertNotIn('not-a-real-token', unit.read_text())
            self.assertEqual(unit.stat().st_mode & 0o777, 0o600)
            self.assertEqual(systemd.manage('status', self.config, self.private)['status'], 'active')
            old = unit.read_bytes()
            unit.write_bytes(old + b'# user modification\n')
            with self.assertRaisesRegex(ValueError, 'Modified'):
                systemd.manage('uninstall', self.config, self.private, True)
            self.assertTrue(unit.exists())
            unit.write_bytes(old)
            removed = systemd.manage('uninstall', self.config, self.private, True)
            self.assertEqual(removed['status'], 'uninstalled')
            self.assertFalse(unit.exists())
            self.assertTrue(self.private.root.is_dir())

    def test_failed_enable_keeps_owned_recovery_receipt(self):
        self.manager(fail=True)
        with patch.dict(os.environ, {'PATH':str(self.root), 'XDG_CONFIG_HOME':str(self.root / 'config')}), patch('companion.runtime.systemd.sys.platform', 'linux'):
            result = systemd.manage('install', self.config, self.private, True)
            self.assertEqual(result['reason'], 'systemd_start_failed')
            self.assertTrue(Path(result['path']).exists())
            self.assertTrue(self.private.file('systemd-installation.json').exists())
            self.assertEqual(systemd.manage('uninstall', self.config, self.private, True)['status'], 'uninstalled')

    def test_unrelated_unit_and_public_credentials_are_preserved(self):
        self.manager()
        environment = self.root / 'public.env'
        environment.write_text('EXAMPLE=not-a-real-token\n')
        environment.chmod(0o644)
        with patch.dict(os.environ, {'PATH':str(self.root), 'XDG_CONFIG_HOME':str(self.root / 'config')}), patch('companion.runtime.systemd.sys.platform', 'linux'):
            with self.assertRaisesRegex(ValueError, 'private'):
                systemd.manage('install', self.config, self.private, True, str(environment))
            destination = self.root / 'config' / 'systemd' / 'user' / systemd.UNIT
            destination.parent.mkdir(parents=True)
            destination.write_text('existing unrelated service')
            with self.assertRaisesRegex(ValueError, 'Existing'):
                systemd.manage('install', self.config, self.private, True)
            with self.assertRaisesRegex(ValueError, 'Unrecognized'):
                systemd.manage('uninstall', self.config, self.private, True)
            self.assertEqual(destination.read_text(), 'existing unrelated service')


class LinuxObservationTests(unittest.TestCase):
    def raw(self, source='linux.atspi'):
        return {'source':source, 'kind':'ax.snapshot', 'timestamp':datetime.now(timezone.utc).isoformat(),
            'object':{'bundle_id':'linux.synthetic', 'pid':123},
            'evidence':{'window_title':'Owned project', 'read_status':'READ_PARTIAL', 'complete':False,
                'nodes':[{'id':0, 'role':'AXWindow'}, {'id':1, 'parent':0, 'role':'AXStaticText', 'text':'Native Linux receipt 7492'}]}}

    def config(self, **kwargs):
        return Config(native_observation_enabled=True, native_ax_enabled=True,
            native_app_allowlist=('linux.synthetic',), native_content_app_allowlist=('linux.synthetic',), **kwargs)

    def test_linux_source_preserves_provider_identity_and_input_pruning(self):
        raw = self.raw()
        raw['evidence']['nodes'].extend([{'id':2, 'parent':0, 'role':'AXTextField', 'text':'DO_NOT_COLLECT'},
                                       {'id':3, 'parent':2, 'role':'AXStaticText', 'text':'DO_NOT_COLLECT'}])
        result = filter_native_event(raw, native_options(self.config()))
        self.assertEqual(result['source'], 'linux_accessibility')
        self.assertNotIn('DO_NOT_COLLECT', json.dumps(result))
        self.assertFalse(result['evidence']['complete'])

    def test_linux_metadata_scope_does_not_emit_text(self):
        config = self.config()
        config.native_content_app_allowlist = ()
        result = filter_native_event(self.raw(), native_options(config))
        self.assertNotIn('window_title', result['evidence'])
        self.assertNotIn('Native Linux', json.dumps(result))

    def test_linux_app_and_window_exclusions_precede_storage(self):
        self.assertIsNone(filter_native_event(self.raw(), native_options(self.config(native_app_exclusions=('linux.synthetic',)))))
        self.assertIsNone(filter_native_event(self.raw(), native_options(self.config(native_window_exclusions=('Owned project',)))))

    def test_linux_activity_is_retrievable_and_revocation_hides_it(self):
        from companion.runtime.service import Companion
        with tempfile.TemporaryDirectory() as directory:
            app = Companion(self.config(data_dir=str(Path(directory) / 'state'), backend='disabled', localpilot_endpoint='', low_power_policy='off'))
            try:
                app.privacy.authorize(True)
                event = filter_native_event(self.raw(), native_options(app.config))
                app.process_native(event)
                rows = app.observation_context('7492')
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['evidence_type'], 'OBSERVED')
                self.assertIn('7492', rows[0]['summary'])
                backend = type(app.native)
                app.command({'command':'set_app_exclusions', 'apps':['linux.unrelated']})
                self.assertIs(type(app.native), backend)
                app.config.native_content_app_allowlist = ()
                self.assertEqual(app.observation_context('7492'), [])
            finally:
                app.native.stop()
                app.observer.stop()
                app.channel.stop()
                app.model.unload()
                app.store.close()
                app.lock.close()

    def test_logind_unlock_and_idle_are_distinct_events(self):
        locked = {'Active':'yes', 'LockedHint':'yes', 'IdleHint':'yes'}
        active = {'Active':'yes', 'LockedHint':'no', 'IdleHint':'no'}
        events = session_events(locked, active)
        kinds = [kind for kind, _ in events]
        self.assertIn('session.became_active', kinds)
        self.assertIn('session.idle_changed', kinds)
        self.assertNotIn('system.did_wake', kinds)
        self.assertEqual(session_events(active, active), [])

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux /proc identity required')
    def test_own_process_identity_uses_executable_not_command_arguments(self):
        result = application_id(os.getpid())
        self.assertRegex(result, r'^linux\.[A-Za-z0-9_-]+$')
        self.assertNotIn('test_linux_runtime', result)
        self.assertIsNone(application_id(999999999))


@unittest.skipUnless(sys.platform.startswith('linux') and hasattr(os, 'memfd_create'), 'Linux memfd required')
class LinuxMeetingProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_pcm_container_has_exact_sample_count(self):
        data = b'\0\0' * 16000
        with wave.open(io.BytesIO(wav_bytes(data)), 'rb') as audio:
            self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()), (1, 2, 16000))
            self.assertEqual(audio.readframes(audio.getnframes()), data)

    def test_pactl_json_source_schema_distinguishes_microphone_and_sink_monitor(self):
        from companion.observers.linux_meeting import devices
        executable = self.root / 'pactl'
        # PulseAudio 17 pactl.c/json.c encode the owning sink name, or an empty string.
        rows = [{'name':'alsa_input.owned', 'description':'Owned microphone', 'monitor_source':''},
                {'name':'alsa_output.owned.monitor', 'description':'Owned output monitor', 'monitor_source':'alsa_output.owned'}]
        executable.write_text(f'#!{sys.executable}\nimport json,sys\n'
            'assert sys.argv[1].startswith("--server=unix:")\n'
            'assert sys.argv[2:] == ["--format=json", "list", "sources"]\n'
            f'print(json.dumps({rows!r}))\n')
        executable.chmod(0o700)
        with patch.dict(os.environ, {'PATH':str(self.root)}):
            result = devices()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual([row['monitor'] for row in result['sources']], [False, True])
        self.assertEqual([row['name'] for row in result['sources']], [row['name'] for row in rows])
        self.assertFalse(result['recording_started'])

    def test_unknown_pactl_monitor_schema_is_unavailable_not_an_assumed_microphone(self):
        from companion.observers.linux_meeting import devices
        executable = self.root / 'pactl'
        for row in ({'name':'source', 'monitor_of_sink':5}, {'name':'source', 'monitor_source':5}):
            with self.subTest(row=row):
                executable.write_text(f'#!{sys.executable}\nimport json\nprint(json.dumps({[row]!r}))\n')
                executable.chmod(0o700)
                with patch.dict(os.environ, {'PATH':str(self.root)}):
                    result = devices()
                self.assertEqual(result['status'], 'unavailable')
                self.assertEqual(result['reason'], 'invalid_pulse_source_list')
                self.assertEqual(result['sources'], [])

    def test_actual_ffmpeg_pcm_and_memfd_transport_without_audio_files(self):
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            self.skipTest('ffmpeg unavailable')
        pcm = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
            'sine=frequency=440:sample_rate=16000', '-t', '0.25', '-ac', '1', '-f', 's16le', 'pipe:1'],
            capture_output=True, check=True, timeout=10).stdout
        executable = self.root / 'whisper-protocol-fixture'
        executable.write_text(f'#!{sys.executable}\nimport sys, wave\n'
            'path = sys.argv[sys.argv.index("--file")+1]\nassert path.startswith("/proc/self/fd/")\n'
            'with wave.open(path, "rb") as audio: assert audio.getnframes() == 4000\n'
            'assert "--no-gpu" in sys.argv\nprint("Synthetic transport fixture; no ASR quality claim")\n')
        executable.chmod(0o700)
        capture = Capture({'whisper':str(executable), 'model':'synthetic-model-path', 'locale':'zh-CN'})
        before = set(self.root.iterdir())
        self.assertEqual(capture.transcribe(pcm), 'Synthetic transport fixture; no ASR quality claim')
        self.assertEqual(set(self.root.iterdir()), before)
        self.assertEqual(capture.processes, [])

    def test_transcriber_failure_is_not_successful_text(self):
        executable = self.root / 'whisper-failure-fixture'
        executable.write_text('#!/bin/sh\nexit 4\n')
        executable.chmod(0o700)
        capture = Capture({'whisper':str(executable), 'model':'none', 'locale':'en'})
        with self.assertRaisesRegex(RuntimeError, 'whisper_transcription_failed'):
            capture.transcribe(b'\0\0' * 16000)
        self.assertEqual(capture.processes, [])

    def test_stop_before_transcription_never_spawns_a_process(self):
        capture = Capture({'whisper':'/does/not/exist', 'model':'none', 'locale':'en'})
        capture.request_stop()
        self.assertIsNone(capture.transcribe(b'\0\0' * 16000))
        self.assertEqual(capture.processes, [])

    def test_capture_argv_is_fixed_to_selected_local_pulse_source(self):
        command = capture_command('/usr/bin/ffmpeg', 'unix:/run/user/1000/pulse/native', 'alsa_input.example')
        self.assertEqual(command[command.index('-i')+1], 'alsa_input.example')
        self.assertEqual(command[-1], 'pipe:1')
        self.assertIn('s16le', command)
        self.assertNotIn('shell', command)

    def test_real_capture_failure_exits_without_claiming_transcription(self):
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            self.skipTest('ffmpeg unavailable')
        from companion.observers import linux_meeting
        settings = {'ffmpeg':ffmpeg, 'whisper':'/not-started-whisper', 'model':'/not-loaded-model',
            'sources':{'mic':'nonexistent-source'}, 'server':'unix:' + str(self.root / 'absent.sock'),
            'locale':'en', 'session':'synthetic-capture-failure'}
        process = subprocess.Popen([sys.executable, str(linux_meeting.HELPER), '--settings', json.dumps(settings)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            process.wait(timeout=10)
            events = [json.loads(line) for line in process.stdout]
            self.assertEqual(process.returncode, 1)
            self.assertEqual(events[-1]['state'], 'failed')
            self.assertEqual(events[-1]['detail'], 'audio_capture_exited')
            self.assertFalse(any(event['type'] == 'transcript' for event in events))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    def test_stop_terminates_owned_continuous_ffmpeg_before_transcription(self):
        ffmpeg = shutil.which('ffmpeg')
        if not ffmpeg:
            self.skipTest('ffmpeg unavailable')
        import psutil
        from companion.observers import linux_meeting
        adapter = self.root / 'synthetic-audio-device'
        adapter.write_text(f'#!{sys.executable}\nimport os\nos.execv({ffmpeg!r}, '
            f'[{ffmpeg!r}, "-nostdin", "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi", "-i", '
            '"anullsrc=sample_rate=16000:channel_layout=mono", "-f", "s16le", "pipe:1"])\n')
        adapter.chmod(0o700)
        settings = {'ffmpeg':str(adapter), 'whisper':'/not-started-whisper', 'model':'/not-loaded-model',
            'sources':{'mic':'synthetic-source'}, 'server':'unused-synthetic-adapter',
            'locale':'en', 'session':'synthetic-capture-stop'}
        process = subprocess.Popen([sys.executable, str(linux_meeting.HELPER), '--settings', json.dumps(settings)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        children = []
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                children = psutil.Process(process.pid).children()
                if children:
                    break
                time.sleep(.02)
            self.assertTrue(children)
            process.stdin.write(b'stop\n')
            process.stdin.flush()
            process.wait(timeout=6)
            events = [json.loads(line) for line in process.stdout]
            self.assertEqual(process.returncode, 0, process.stderr.read().decode())
            self.assertEqual(events[-1]['state'], 'stopped')
            self.assertFalse(any(event['type'] == 'transcript' for event in events))
            self.assertTrue(all(not child.is_running() for child in children))
            self.assertEqual(set(self.root.iterdir()), {adapter})
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    def test_signal_during_transcription_stops_owned_processes_without_stdin_command(self):
        import psutil
        from companion.observers import linux_meeting
        audio = self.root / 'bounded-pcm-fixture'
        transcriber = self.root / 'blocking-transcriber-fixture'
        started = self.root / 'transcriber-started'
        audio.write_text(f'#!{sys.executable}\nimport sys,time\n'
            'sys.stdout.buffer.write(bytes(480000));sys.stdout.buffer.flush();time.sleep(60)\n')
        transcriber.write_text(f'#!{sys.executable}\nimport os,sys,time,wave\nfrom pathlib import Path\n'
            'with wave.open(sys.argv[sys.argv.index("--file")+1], "rb") as audio: assert audio.getnframes() == 240000\n'
            f'Path({str(started)!r}).write_text(str(os.getpid()))\ntime.sleep(60)\n')
        audio.chmod(0o700)
        transcriber.chmod(0o700)
        settings = {'ffmpeg':str(audio), 'whisper':str(transcriber), 'model':'fixture-not-loaded',
            'sources':{'mic':'owned-fixture'}, 'server':'unused-fixture', 'locale':'en', 'session':'signal-stop'}
        for signum in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=signum):
                started.unlink(missing_ok=True)
                process = subprocess.Popen([sys.executable, str(linux_meeting.HELPER), '--settings', json.dumps(settings)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
                try:
                    deadline = time.monotonic() + 6
                    while not started.exists() and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue(started.exists(), 'Transcriber did not receive the PCM descriptor')
                    children = psutil.Process(process.pid).children()
                    self.assertEqual(len(children), 2)
                    process.send_signal(signum)
                    process.wait(timeout=6)
                    events = [json.loads(line) for line in process.stdout]
                    self.assertEqual(process.returncode, 0, process.stderr.read().decode())
                    self.assertEqual(events[-1]['state'], 'stopped')
                    self.assertFalse(any(event['type'] == 'transcript' for event in events))
                    self.assertTrue(all(not child.is_running() for child in children))
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    for stream in (process.stdin, process.stdout, process.stderr):
                        stream.close()


if __name__ == '__main__':
    unittest.main()
