"""Owned audio helper. PCM stays in bounded RAM and is discarded on stop."""
import argparse
import io
import json
import os
from queue import Empty, Full, Queue
import signal
import subprocess
import sys
import threading
import time
import uuid
import wave


CHUNK_SECONDS = 15
SAMPLE_RATE = 16000
CHUNK_BYTES = CHUNK_SECONDS * SAMPLE_RATE * 2


def capture_command(ffmpeg, server, source):
    return [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-f', 'pulse', '-server', server,
            '-name', 'LocalPilot Companion', '-stream_name', 'Explicit meeting transcription', '-i', source,
            '-ac', '1', '-ar', str(SAMPLE_RATE), '-f', 's16le', 'pipe:1']


def wav_bytes(pcm):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(pcm)
    return stream.getvalue()


class Capture:
    def __init__(self, settings):
        self.settings = settings
        self.stopped = threading.Event()
        self.pending = Queue(maxsize=4)
        self.processes = []
        self.lock = threading.Lock()
        self.output_lock = threading.Lock()
        self.failure = None

    def emit(self, value):
        with self.output_lock:
            print(json.dumps(value, ensure_ascii=False), flush=True)

    def status(self, state, detail, source='all'):
        self.emit({'type':'status', 'state':state, 'detail':detail, 'source':source, 'at':time.time()})

    def spawn(self, command, **options):
        with self.lock:
            if self.stopped.is_set():
                return None
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, **options)
            self.processes.append(process)
            return process

    def request_stop(self, *_):
        self.stopped.set()
        with self.lock:
            for process in self.processes:
                if process.poll() is None:
                    process.terminate()

    def read_stop(self):
        for line in sys.stdin:
            if line.strip() == 'stop':
                break
        self.request_stop()

    def watch_stop(self):
        self.stopped.wait()
        self.request_stop()

    def read_audio(self, source, device):
        try:
            process = self.spawn(capture_command(self.settings['ffmpeg'], self.settings['server'], device))
        except OSError:
            self.failure = 'audio_capture_launch_failed'
            self.request_stop()
            return
        if process is None:
            return
        self.status('starting', 'waiting_for_local_audio', source)
        first_chunk = True
        try:
            while not self.stopped.is_set():
                began = time.time()
                data = process.stdout.read(CHUNK_BYTES)
                if not data:
                    if not self.stopped.is_set():
                        self.failure = 'audio_capture_exited'
                        self.request_stop()
                    break
                if len(data) != CHUNK_BYTES:
                    if not self.stopped.is_set():
                        self.failure = 'audio_capture_incomplete_chunk'
                        self.request_stop()
                    break
                if first_chunk:
                    self.status('recording', 'local_audio_received', source)
                    self.status('recording', 'local_audio_received')
                    first_chunk = False
                try:
                    self.pending.put_nowait((source, began, time.time(), data))
                except Full:
                    self.failure = 'transcription_backlog_audio_discarded'
                    self.request_stop()
        except OSError:
            if not self.stopped.is_set():
                self.failure = 'audio_capture_read_failed'
                self.request_stop()
        finally:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            process.stdout.close()
            with self.lock:
                self.processes.remove(process)

    def transcribe(self, pcm):
        descriptor = os.memfd_create('localpilot-meeting-pcm', os.MFD_CLOEXEC)
        try:
            data = wav_bytes(pcm)
            with os.fdopen(os.dup(descriptor), 'wb') as stream:
                stream.write(data)
            os.lseek(descriptor, 0, os.SEEK_SET)
            command = [self.settings['whisper'], '--model', self.settings['model'],
                '--file', '/proc/self/fd/' + str(descriptor), '--language', self.settings['locale'].split('-')[0],
                '--threads', '2', '--no-gpu', '--no-timestamps', '--no-prints']
            process = self.spawn(command, pass_fds=(descriptor,))
            if process is None:
                return None
            try:
                try:
                    output, _ = process.communicate(timeout=120)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    raise RuntimeError('transcription_timeout') from None
            finally:
                with self.lock:
                    self.processes.remove(process)
            if self.stopped.is_set():
                return None
            if process.returncode:
                raise RuntimeError('whisper_transcription_failed')
            text = output.decode('utf-8').strip()
            if len(text) > 4000:
                raise RuntimeError('transcription_text_budget_exceeded')
            return text
        finally:
            os.close(descriptor)

    def run(self):
        signal.signal(signal.SIGTERM, lambda *_: self.stopped.set())
        signal.signal(signal.SIGINT, lambda *_: self.stopped.set())
        # Wake blocking audio/ASR subprocesses without taking their lock in a signal handler.
        threading.Thread(target=self.watch_stop, daemon=True).start()
        listener = threading.Thread(target=self.read_stop, daemon=True)
        listener.start()
        threads = [threading.Thread(target=self.read_audio, args=(source, device), daemon=True)
                   for source, device in self.settings['sources'].items()]
        for thread in threads:
            thread.start()
        self.status('starting', 'waiting_for_local_audio')
        try:
            while not self.stopped.is_set():
                try:
                    source, began, ended, data = self.pending.get(timeout=.2)
                except Empty:
                    continue
                text = self.transcribe(data)
                if text and not self.stopped.is_set():
                    self.emit({'type':'transcript', 'final':True, 'source':source, 'text':text,
                        'segment':self.settings['session'] + '-' + uuid.uuid4().hex, 'started_at':began, 'ended_at':ended})
        except (OSError, ValueError, RuntimeError) as error:
            self.failure = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        finally:
            self.request_stop()
            for thread in threads:
                thread.join(timeout=3)
            for process in self.processes:
                if process.poll() is None:
                    process.kill()
                process.wait()
                if process.stdout and not process.stdout.closed:
                    process.stdout.close()
            self.status('failed' if self.failure else 'stopped', self.failure or 'stopped_partial_audio_buffer_discarded')
        return 1 if self.failure else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--settings', required=True)
    args = parser.parse_args()
    raise SystemExit(Capture(json.loads(args.settings)).run())
