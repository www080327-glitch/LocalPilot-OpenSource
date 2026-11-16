"""Local PulseAudio/PipeWire-Pulse capture and explicit whisper.cpp transcription."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


HELPER = Path(__file__).with_name('linux_meeting_helper.py')


def capabilities(config):
    whisper = Path(config.meeting_whisper_command) if config.meeting_whisper_command else None
    model = Path(config.meeting_whisper_model) if config.meeting_whisper_model else None
    runtime = os.environ.get('XDG_RUNTIME_DIR', '/run/user/' + str(os.getuid()))
    pulse = Path(runtime) / 'pulse' / 'native'
    return {'platform':'linux', 'backend':'ffmpeg_pulse_whisper_cpp',
            'ffmpeg_available':bool(shutil.which('ffmpeg')), 'pulse_socket_available':pulse.is_socket(),
            'whisper_available':bool(whisper and whisper.is_file() and os.access(whisper, os.X_OK)),
            'model_available':bool(model and model.is_file()), 'model_hash_configured':bool(config.meeting_whisper_model_sha256),
            'microphone_configured':bool(config.meeting_microphone_source),
            'system_source_configured':bool(config.meeting_system_source),
            'runtime_checked_on_explicit_start':True, 'raw_audio_saved':False, 'cloud_fallback':False}


def devices():
    executable = shutil.which('pactl')
    if not executable:
        return {'status':'unavailable', 'reason':'pactl_not_found', 'sources':[]}
    try:
        result = subprocess.run([executable, '--server=' + _pulse_server(), '--format=json', 'list', 'sources'],
            capture_output=True, text=True, timeout=5, env=helper_environment())
    except (OSError, subprocess.SubprocessError):
        return {'status':'unavailable', 'reason':'pulse_server_unavailable', 'sources':[]}
    if result.returncode:
        return {'status':'unavailable', 'reason':'pulse_server_unavailable', 'sources':[]}
    try:
        rows = json.loads(result.stdout)
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get('name'), str)
                or 'monitor_source' not in row or row['monitor_source'] is not None
                and not isinstance(row['monitor_source'], str) for row in rows):
            raise ValueError('Invalid PulseAudio source list')
    except ValueError:
        return {'status':'unavailable', 'reason':'invalid_pulse_source_list', 'sources':[]}
    # pactl JSON names the owning sink monitor_source and writes an empty string for microphones.
    return {'status':'ok', 'sources':[{'name':row['name'], 'description':row.get('description', ''),
        'monitor':bool(row['monitor_source'])} for row in rows],
        'recording_started':False}


def launch(config, capture, locale, session_id):
    state = capabilities(config)
    required = ['ffmpeg_available', 'pulse_socket_available', 'whisper_available', 'model_available', 'model_hash_configured']
    if capture in {'microphone', 'both'}:
        required.append('microphone_configured')
    if capture in {'system', 'both'}:
        required.append('system_source_configured')
    missing = [key for key in required if not state[key]]
    if missing:
        raise RuntimeError('linux_meeting_requires:' + ','.join(missing))
    model = Path(config.meeting_whisper_model)
    if _digest(model) != config.meeting_whisper_model_sha256:
        raise ValueError('linux_meeting_model_hash_mismatch')
    sources = devices()
    if sources['status'] != 'ok':
        raise RuntimeError(sources['reason'])
    known = {row['name']:row for row in sources['sources']}
    selected = {}
    for source, name, monitor in [('mic', config.meeting_microphone_source, False), ('system', config.meeting_system_source, True)]:
        if source == 'mic' and capture == 'system' or source == 'system' and capture == 'microphone':
            continue
        if name not in known or known[name]['monitor'] is not monitor:
            raise ValueError('linux_meeting_audio_source_mismatch:' + source)
        selected[source] = name
    ffmpeg = shutil.which('ffmpeg')
    settings = {'ffmpeg':ffmpeg, 'whisper':config.meeting_whisper_command, 'model':str(model),
                'sources':selected, 'server':_pulse_server(), 'locale':locale, 'session':session_id}
    command = [sys.executable, str(HELPER), '--settings', json.dumps(settings)]
    identity = {'backend':'ffmpeg_pulse_whisper_cpp', 'model_sha256':config.meeting_whisper_model_sha256,
                'whisper_sha256':_digest(Path(config.meeting_whisper_command)), 'ffmpeg_sha256':_digest(Path(ffmpeg)),
                'capture_devices':selected, 'audio_buffer':'bounded_memory_only', 'chunk_seconds':15}
    return command, helper_environment(), identity


def helper_environment():
    result = {'PATH':os.environ.get('PATH', '/usr/bin:/bin'), 'LANG':'C.UTF-8', 'LC_ALL':'C.UTF-8'}
    for name in ('HOME', 'XDG_RUNTIME_DIR', 'LD_LIBRARY_PATH'):
        if name in os.environ:
            result[name] = os.environ[name]
    return result


def _pulse_server():
    return 'unix:' + str(Path(os.environ.get('XDG_RUNTIME_DIR', '/run/user/' + str(os.getuid()))) / 'pulse' / 'native')


def _digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()
