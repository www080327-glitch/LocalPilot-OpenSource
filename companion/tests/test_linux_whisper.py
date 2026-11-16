"""Explicit real ASR qualification; ordinary regression never downloads a model."""
import hashlib
import os
from pathlib import Path
import sys
import threading
import time
import unittest
import wave

from companion.observers.linux_meeting_helper import Capture


@unittest.skipUnless(sys.platform.startswith('linux') and os.environ.get('LOCALPILOT_TEST_WHISPER_CLI'),
                     'Explicit identified whisper.cpp/model/public sample required')
class RealWhisperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = Path(os.environ['LOCALPILOT_TEST_WHISPER_CLI'])
        cls.model = Path(os.environ['LOCALPILOT_TEST_WHISPER_MODEL'])
        sample = Path(os.environ['LOCALPILOT_TEST_WHISPER_WAV'])
        expected = os.environ['LOCALPILOT_TEST_WHISPER_SHA256']
        if hashlib.sha256(cls.model.read_bytes()).hexdigest() != expected:
            raise ValueError('Explicit ASR model hash mismatch')
        if hashlib.sha256(sample.read_bytes()).hexdigest() != '59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e':
            raise ValueError('Expected the pinned upstream whisper.cpp JFK sample')
        with wave.open(str(sample), 'rb') as stream:
            if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 16000):
                raise ValueError('Unexpected upstream WAV format')
            cls.pcm = stream.readframes(stream.getnframes())

    def capture(self):
        return Capture({'whisper':str(self.binary), 'model':str(self.model), 'locale':'en-US'})

    def test_real_cpu_transcription_from_memory_descriptor(self):
        capture = self.capture()
        text = capture.transcribe(self.pcm)
        self.assertIn('ask not', text.lower())
        self.assertIn('your country', text.lower())
        self.assertEqual(capture.processes, [])

    def test_real_whisper_process_is_stopped_without_late_text(self):
        import psutil
        capture = self.capture()
        result = {}
        def transcribe():
            try:
                result['text'] = capture.transcribe(self.pcm * 4)
            except Exception as error:
                result['error'] = repr(error)
        thread = threading.Thread(target=transcribe)
        thread.start()
        process = None
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            with capture.lock:
                process = capture.processes[0] if capture.processes else None
            if process and process.poll() is None:
                cpu = psutil.Process(process.pid).cpu_times()
                if cpu.user + cpu.system > .05:
                    break
            time.sleep(.02)
        try:
            self.assertIsNotNone(process)
            started = time.monotonic()
            capture.request_stop()
            thread.join(timeout=6)
            self.assertFalse(thread.is_alive())
            self.assertLess(time.monotonic() - started, 6)
            self.assertIsNotNone(process.poll())
            self.assertEqual(result, {'text':None})
        finally:
            capture.request_stop()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
