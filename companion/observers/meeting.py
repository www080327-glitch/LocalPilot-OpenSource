"""Explicit, visible on-device transcription; no automatic recording or restart."""
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import plistlib
from queue import Empty, Full, Queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

from companion.config import PrivateData
from .events import redact_text
from .native import helper_environment

SOURCE = Path(__file__).with_name("MeetingTranscriber.swift")
ACTIVE = {"starting", "recording", "stopping"}
STATES = ACTIVE | {"stopped", "unavailable", "denied", "failed"}


def build_meeting_helper(app):
    if sys.platform != "darwin":
        raise RuntimeError("Meeting transcription requires macOS")
    app = Path(os.path.abspath(app))
    parent = PrivateData(app.parent)
    app = parent.file(app.name)
    contents = app / "Contents"
    macos = contents / "MacOS"
    # Ownership markers inside Contents or MacOS make codesign reject the app bundle.
    for directory in (app, contents, macos):
        if directory.is_symlink():
            raise ValueError("Meeting helper bundle path must not be a symlink")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    binary = macos / "MeetingTranscriber"
    manifest = parent.file("meeting-helper-build.json")
    info_path = contents / "Info.plist"
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    bundle_id = "io.localpilot.companion.meeting." + hashlib.sha256(str(parent.root).encode()).hexdigest()[:12]
    info = {"CFBundleName":"LocalPilot Meeting Transcription", "CFBundleIdentifier":bundle_id,
            "CFBundleVersion":"1", "CFBundlePackageType":"APPL", "CFBundleExecutable":"MeetingTranscriber",
            "LSUIElement":True, "LSMinimumSystemVersion":"11.0",
            "NSSpeechRecognitionUsageDescription":"在你明确开始会议转写后，仅在本机识别所选音频并保存文字，不使用云端转写。",
            "NSScreenCaptureUsageDescription":"在你明确选择系统音轨转写后，读取系统声音供本机语音识别；不保存屏幕图像或音频，停止后结束采集。",
            "NSMicrophoneUsageDescription":"在你明确选择麦克风转写后，获取麦克风语音；点击停止立即结束采集。"}
    info_bytes = plistlib.dumps(info)
    expected = {"source_sha256":source_hash, "info_sha256":hashlib.sha256(info_bytes).hexdigest(), "protocol":1}
    if binary.is_symlink() or info_path.is_symlink():
        raise ValueError("Meeting helper bundle files must not be symlinks")
    if binary.is_file() and manifest.is_file():
        prior = json.loads(manifest.read_text())
        if (all(prior.get(key) == value for key, value in expected.items())
                and info_path.is_file() and hashlib.sha256(info_path.read_bytes()).hexdigest() == expected["info_sha256"]
                and prior.get("binary_sha256") == hashlib.sha256(binary.read_bytes()).hexdigest()):
            return str(binary)
    info_path.write_bytes(info_bytes)
    subprocess.run(["/usr/bin/xcrun", "swiftc", "-target", platform.machine()+"-apple-macos11.0", str(SOURCE), "-o", str(binary)],
        check=True, timeout=120, env=helper_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    binary.chmod(0o700)
    for attribute in ("com.apple.FinderInfo", "com.apple.ResourceFork"):
        subprocess.run(["/usr/bin/xattr", "-rd", attribute, str(app)], check=False,
            timeout=30, env=helper_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", str(app)],
        check=True, timeout=30, env=helper_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(app)],
        check=True, timeout=30, env=helper_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    parent.write("meeting-helper-build.json", json.dumps(expected | {"binary_sha256":hashlib.sha256(binary.read_bytes()).hexdigest()}) + "\n")
    return str(binary)


def meeting_launch(config, capture, locale, session_id, private):
    if sys.platform.startswith('linux'):
        from .linux_meeting import launch
        return launch(config, capture, locale, session_id)
    binary = build_meeting_helper(private.root / 'MeetingTranscriber.app')
    return [binary, '--locale', locale, '--session', session_id, '--capture', capture], helper_environment(), {}


class MeetingCapture:
    def __init__(self, service):
        self.service = service
        self.process = self.reader = None
        self.events = Queue(maxsize=128)
        self.overflow = threading.Event()
        self.stop_requested = threading.Event()
        self.discard = False
        self.failure = None
        self.seen = set()
        self.output = None
        self.state = service.store.get("meeting_capture", {"state":"idle", "segments":0, "sources":{}})
        if self.state["state"] in ACTIVE:
            self.state.update(state="interrupted", detail="runtime_restarted_capture_not_resumed")
            self._save()

    def status(self):
        active = self.state["state"] in ACTIVE or (self.process is not None and self.process.poll() is None)
        result = {"status":"active" if active else "ok", "meeting":dict(self.state),
                "supported_host":sys.platform == "darwin" or sys.platform.startswith('linux'), "capture_availability":"checked_on_explicit_start",
                "coverage":"仅自动转写所选麦克风/系统音轨，可能误识别、重复或遗漏；说话者与事实未经验证，不保存音视频。"}
        if sys.platform.startswith('linux'):
            from .linux_meeting import capabilities
            result['capabilities'] = capabilities(self.service.config)
        return result

    def start(self, capture, locale="zh-CN", label=None):
        if capture not in {"microphone", "system", "both"} or not isinstance(locale, str) or not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}", locale):
            raise ValueError("Choose microphone, system or both and a language locale")
        label = label or "本地会议转写"
        if not isinstance(label, str) or not label.strip() or len(label) > 120 or redact_text(label) != label:
            raise ValueError("Use a bounded nonsensitive meeting label")
        self.drain()
        if self.state["state"] in ACTIVE:
            return self.status() | {"reason":"meeting_already_active"}
        if self.process is not None:
            self.stop()
        if self.service.privacy.paused():
            return {"status":"unavailable", "reason":"observation_paused", "meeting":dict(self.state)}
        session_id = str(uuid.uuid4())
        try:
            command, environment, identity = meeting_launch(self.service.config, capture, locale, session_id, self.service.private)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            detail = str(error)[:300] if sys.platform.startswith('linux') else 'macos_required' if sys.platform != 'darwin' else 'helper_build_failed'
            self.state = {"state":"unavailable", "detail":detail,
                          "capture":capture, "locale":locale, "label":label, "error_type":type(error).__name__, "segments":0, "sources":{}}
            self._save()
            return self.status() | {"status":"unavailable"}
        self.output = PrivateData(PrivateData(self.service.private.root / "meetings").root / ("meeting-"+session_id))
        registered = self.service.sources.connect("meeting", str(self.output.root), label, False)
        self.state = {"session_id":session_id, "state":"starting", "capture":capture, "locale":locale,
                      "label":label, "started_at":time.time(), "source_id":registered["source"]["id"],
                      "segments":0, "sources":{name:{"state":"starting"} for name in
                          (["mic", "system"] if capture == "both" else ["mic"] if capture == "microphone" else ["system"])},
                      "raw_audio_saved":False, "cloud_fallback":False}
        self.state.update(identity)
        self.discard = False
        self.failure = None
        self.seen.clear()
        self.stop_requested.clear()
        self.overflow.clear()
        self._save()
        try:
            self.process = subprocess.Popen(command,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment, start_new_session=True)
        except OSError as error:
            self.state.update(state="failed", detail="helper_launch_failed", error_type=type(error).__name__)
            self._save()
            return self.status() | {"status":"error"}
        self.reader = threading.Thread(target=self._read, args=(self.process, session_id), daemon=True)
        self.reader.start()
        return self.status()

    def request_stop(self):
        self.stop_requested.set()
        process = self.process
        if process and process.stdin:
            try:
                process.stdin.write(b"stop\n")
                process.stdin.flush()
            except (OSError, ValueError):
                pass
            try:
                process.stdin.close()
            except OSError:
                pass

    def stop(self, discard=False):
        self.discard |= discard
        self.request_stop()
        process = self.process
        if process is not None:
            if self.state["state"] in ACTIVE:
                self.state.update(state="stopping")
            self._save()
            try:
                process.wait(timeout=13)
            except subprocess.TimeoutExpired:
                self.failure = "helper_stop_required_termination"
                if self.state.get('backend') == 'ffmpeg_pulse_whisper_cpp':
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    if self.state.get('backend') == 'ffmpeg_pulse_whisper_cpp':
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait(timeout=3)
            if self.reader:
                self.reader.join(timeout=2)
            self.drain()
            if self.state["state"] in ACTIVE:
                self.state.update(state="stopped", ended_at=time.time())
            if process.stdin and not process.stdin.closed:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            if process.stdout:
                process.stdout.close()
            self.process = self.reader = None
            self._save()
        return self.status() | {"status":"stopped" if self.state["state"] in {"idle", "stopped"} else self.status()["status"]}

    def clear(self):
        self.stop(discard=True)
        root = self.service.private.root / "meetings"
        if root.exists():
            PrivateData(root)
            shutil.rmtree(root)
        self.state = {"state":"idle", "segments":0, "sources":{}}
        self.output = None
        self.seen.clear()
        self.failure = None
        self.overflow.clear()

    def drain(self):
        changed = False
        while True:
            try:
                session_id, event = self.events.get_nowait()
            except Empty:
                break
            if session_id != self.state.get("session_id"):
                continue
            changed = True
            if event["type"] == "transcript":
                try:
                    self._transcript(event)
                except (OSError, ValueError):
                    self.discard = True
                    self.failure = "transcript_storage_unavailable"
                    self.state.update(state="failed", detail="transcript_storage_unavailable")
                    self.request_stop()
            elif event["type"] == "status":
                fields = {key:event[key] for key in ("state", "detail", "at")}
                if event["source"] == "all":
                    self.state.update(state=event["state"], detail=event["detail"])
                    if event['state'] not in ACTIVE:
                        self.state['ended_at'] = event['at']
                    for source in self.state["sources"]:
                        self.state["sources"][source] = fields
                else:
                    self.state["sources"][event["source"]] = fields
            else:
                self.state["exit_code"] = event["returncode"]
                if self.state["state"] in ACTIVE:
                    self.state.update(state="failed", detail="helper_exited_without_terminal_status", ended_at=time.time())
                elif self.state['state'] == 'stopped' and event['returncode'] != 0:
                    self.state.update(state='failed', detail='helper_exit_nonzero')
        if self.overflow.is_set():
            changed |= self.state.get("detail") != "transcript_queue_overflow"
            self.failure = "transcript_queue_overflow"
        if self.failure:
            state = "stopping" if self.process is not None and self.process.poll() is None else "failed"
            changed |= (self.state.get("state"), self.state.get("detail")) != (state, self.failure)
            self.state.update(state=state, detail=self.failure)
        if changed and self.state.get("session_id"):
            self._save()

    def _transcript(self, event):
        if self.discard or self.service.privacy.paused() or event["segment"] in self.seen:
            return
        source = self.service.sources.get(self.state["source_id"])
        if not source["enabled"]:
            self.discard = True
            self.request_stop()
            return
        # Immutable segment files keep earlier observation IDs current while a
        # long meeting continues, and avoid reimporting its entire history.
        filename = self.output.write(f"segment-{len(self.seen)+1:06d}-{event['source']}.jsonl",
                                     json.dumps(event, ensure_ascii=False) + "\n")
        self.seen.add(event["segment"])
        self.state.update(segments=len(self.seen), last_transcript_at=event["ended_at"])
        self.state["last_sync"] = self.service.sources.sync(source["id"], selected_file=filename)
        if self.state['last_sync']['status'] != 'ok':
            raise ValueError('Final transcript could not be indexed')

    def _read(self, process, session_id):
        try:
            for line in iter(lambda:process.stdout.readline(32769), b""):
                try:
                    event = parse_message(line)
                except (ValueError, TypeError, json.JSONDecodeError):
                    event = {"type":"status", "state":"failed", "detail":"invalid_helper_protocol", "source":"all", "at":time.time()}
                    self.discard = True
                    self.failure = "invalid_helper_protocol"
                    self.request_stop()
                self._enqueue(session_id, event)
        finally:
            self._enqueue(session_id, {"type":"process_exit", "returncode":process.wait()})

    def _enqueue(self, session_id, event):
        try:
            self.events.put_nowait((session_id, event))
        except Full:
            self.overflow.set()
            self.request_stop()
        try:
            self.service.queue.put_nowait(("meeting", None, None))
        except Full:
            pass

    def _save(self):
        self.service.store.set("meeting_capture", self.state)


def parse_message(line):
    if len(line) > 32768 or not line.endswith(b"\n"):
        raise ValueError("Meeting helper line budget exceeded")
    value = json.loads(line)
    if not isinstance(value, dict) or value.get("type") not in {"status", "transcript"}:
        raise ValueError("Unknown meeting helper event")
    source = value.get("source")
    if source not in {"mic", "system", "all"}:
        raise ValueError("Unknown meeting audio source")
    if value["type"] == "status":
        if value.get("state") not in STATES or not isinstance(value.get("detail", ""), str) or len(value.get("detail", "")) > 300:
            raise ValueError("Invalid meeting state")
        timestamps = (value.get("at"),)
        result = {"type":"status", "state":value["state"], "detail":redact_text(value.get("detail", "")), "source":source, "at":value.get("at")}
    else:
        if (source == "all" or value.get("final") is not True or not isinstance(value.get("text"), str)
                or not value["text"].strip() or len(value["text"]) > 4000
                or not isinstance(value.get("segment"), str) or not 1 <= len(value["segment"]) <= 100):
            raise ValueError("Only bounded final transcripts may be persisted")
        timestamps = (value.get("started_at"), value.get("ended_at"))
        result = {key:value[key] for key in ("type", "final", "source", "segment")}
        result.update(started_at=timestamps[0], ended_at=timestamps[-1])
        result["text"] = redact_text(value["text"])
    if any(type(at) not in (int, float) or not math.isfinite(at) or not 0 <= at <= time.time()+60 for at in timestamps) or timestamps[-1] < timestamps[0]:
        raise ValueError("Invalid transcription timestamps")
    return result
