"""Read-only Linux observation process; stdout is the bounded native protocol."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from companion.observers.native import app_scope_allowed as allowed, content_scope_allowed as content_allowed
from companion.observers.app_profiles import window_qualified


def atspi_module():
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
        return Atspi
    except (ImportError, ValueError):
        return None


def application_id(pid):
    try:
        process = Path('/proc') / str(pid)
        if process.stat().st_uid != os.getuid():
            return None
        name = Path(os.readlink(process / 'exe')).name
    except OSError:
        return None
    return 'linux.' + re.sub(r'[^A-Za-z0-9_-]', '_', name)[:100]


def session_state():
    executable = shutil.which('loginctl')
    if not executable:
        return {}
    try:
        result = subprocess.run([executable, 'show-session', 'auto',
            '--property=Active,LockedHint,IdleHint,Type,Remote', '--no-pager'],
            capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode:
        return {}
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if values.get('Type') not in {'x11', 'wayland'} or values.get('Remote') != 'no':
        return {}
    return {key:values[key] for key in ('Active', 'LockedHint', 'IdleHint') if values.get(key) in {'yes', 'no'}}


def x11_window():
    if not os.environ.get('DISPLAY') or os.environ.get('XDG_SESSION_TYPE') == 'wayland':
        return None
    executable = shutil.which('xprop')
    if not executable:
        return None
    try:
        result = subprocess.run([executable, '-len', '64', '-root', '_NET_ACTIVE_WINDOW'],
            capture_output=True, text=True, timeout=2)
        match = re.search(r'window id # (0x[0-9a-fA-F]+)', result.stdout)
        if result.returncode or not match or int(match[1], 16) == 0:
            return None
        identifier = match[1]
        result = subprocess.run([executable, '-len', '64', '-id', identifier, '_NET_WM_PID'],
            capture_output=True, text=True, timeout=2)
        match = re.search(r'_NET_WM_PID\(CARDINAL\) = ([0-9]+)', result.stdout)
        if result.returncode or not match:
            return None
        pid = int(match[1])
        app = application_id(pid)
        return {'pid':pid, 'bundle_id':app, 'window_id':identifier} if app else None
    except (OSError, subprocess.SubprocessError):
        return None


def x11_title(window_id):
    try:
        result = subprocess.run([shutil.which('xprop'), '-len', '1200', '-id', window_id,
            '-f', '_NET_WM_NAME', '8u', '_NET_WM_NAME'], capture_output=True, text=True, timeout=2)
        match = re.search(r'_NET_WM_NAME\(UTF8_STRING\) = (".*")', result.stdout)
        return json.loads(match[1])[:300] if result.returncode == 0 and match else None
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return None


def qualified_title(title, options):
    if title in options['window_exclusions']:
        return False
    return window_qualified(title, options.get('content_window_allowlist', []))


def atspi_snapshot(atspi, options, foreground=None):
    if atspi is None:
        return None
    deadline = time.monotonic() + 2
    try:
        desktop = atspi.get_desktop(0)
        for index in range(min(desktop.get_child_count(), 100)):
            if time.monotonic() >= deadline:
                return None
            application = desktop.get_child_at_index(index)
            pid = application.get_process_id()
            app = application_id(pid)
            if not allowed(app, options) or foreground and pid != foreground['pid']:
                continue
            for child_index in range(min(application.get_child_count(), 8)):
                if time.monotonic() >= deadline:
                    return None
                window = application.get_child_at_index(child_index)
                states = window.get_state_set()
                if not states.contains(atspi.StateType.ACTIVE) or not states.contains(atspi.StateType.SHOWING):
                    continue
                if not content_allowed(app, options):
                    if options['window_exclusions'] and window.get_name()[:300] in options['window_exclusions']:
                        continue
                    return {'pid':pid, 'bundle_id':app}, None
                title = window.get_name()[:300]
                if not qualified_title(title, options):
                    continue
                proof = read_atspi_tree(window, atspi, options)
                proof.update(window_title=title, coverage='PARTIAL', read_scope='foreground_atspi_static_text',
                             capture_scope='foreground_application', ax_permission='available')
                return {'pid':pid, 'bundle_id':app}, proof
    except Exception:
        return None  # Toolkit failures do not broaden acquisition to another app/window.
    return None


def read_atspi_tree(window, atspi, options):
    denied = {getattr(atspi.Role, name) for name in ('ENTRY', 'PASSWORD_TEXT', 'COMBO_BOX', 'SPIN_BUTTON')}
    static = {getattr(atspi.Role, name) for name in ('LABEL', 'STATIC', 'TEXT', 'PARAGRAPH', 'HEADING')}
    nodes, queue = [], [(window, None, 0)]
    errors = pruned = 0
    chars = 4000
    deadline = time.monotonic() + 2
    while queue and len(nodes) < options['max_nodes'] and time.monotonic() < deadline:
        item, parent, depth = queue.pop(0)
        try:
            role = item.get_role()
            if role in denied:
                pruned += 1
                continue
            states = item.get_state_set()
            if states.contains(atspi.StateType.EDITABLE) or not states.contains(atspi.StateType.SHOWING):
                pruned += 1
                continue
            node = {'id':len(nodes), 'role':'AXWindow' if parent is None else 'AXStaticText' if role in static else 'AXGroup'}
            if parent is not None:
                node['parent'] = parent
            if role in static and chars:
                text_interface = item.get_text_iface()
                # PyGObject's Accessible.get_text shadows the Text interface method.
                text = atspi.Text.get_text(text_interface, 0, min(500, chars, text_interface.get_character_count())) if text_interface else item.get_name()[:min(500, chars)]
                if text:
                    node['text'] = text
                    chars -= len(text)
            count = item.get_child_count()
            node['children_read_status'] = 'READ_SUCCESS_NONEMPTY' if count else 'READ_SUCCESS_EMPTY'
            nodes.append(node)
            if depth < options['max_depth']:
                available = max(0, options['max_nodes'] - len(nodes) - len(queue))
                pruned += max(0, count - available)
                for index in range(min(count, available)):
                    if time.monotonic() >= deadline:
                        pruned += count - index
                        break
                    queue.append((item.get_child_at_index(index), node['id'], depth+1))
            elif count:
                pruned += count
        except Exception:
            errors += 1
    partial = bool(errors or pruned or queue or not chars)
    return {'nodes':nodes, 'node_count':len(nodes), 'read_error_count':errors, 'pruned_count':pruned,
            'read_status':'READ_PARTIAL' if partial else 'READ_SUCCESS_NONEMPTY' if nodes else 'READ_SUCCESS_EMPTY',
            'complete':False, 'structural_complete':not partial, 'attributes_complete':not errors,
            'truncated':bool(queue), 'content_truncated':not chars}


def emit(kind, obj, evidence, source='linux.session'):
    value = {'source':source, 'kind':kind, 'object':obj, 'evidence':evidence,
             'timestamp':datetime.now(timezone.utc).isoformat()}
    print(json.dumps(value, ensure_ascii=False), flush=True)


def session_events(previous, current):
    if not current or current == previous:
        return []
    proof = {'session_state':'active' if current.get('Active') == 'yes' else 'inactive' if current.get('Active') == 'no' else 'UNKNOWN',
             'lock_state':'locked' if current.get('LockedHint') == 'yes' else 'unlocked' if current.get('LockedHint') == 'no' else 'UNKNOWN',
             'idle_state':'idle' if current.get('IdleHint') == 'yes' else 'active' if current.get('IdleHint') == 'no' else 'UNKNOWN',
             'reason':'logind_current_graphical_session'}
    events = [('observation.status', proof)]
    before = previous.get('Active') == 'yes' and previous.get('LockedHint') == 'no'
    after = current.get('Active') == 'yes' and current.get('LockedHint') == 'no'
    if before != after:
        events.append(('session.became_active' if after else 'session.resigned_active', proof))
    if previous and previous.get('IdleHint') != current.get('IdleHint'):
        events.append(('session.idle_changed', proof))
    return events


def run(options):
    atspi = atspi_module() if os.environ.get('DBUS_SESSION_BUS_ADDRESS') else None
    if atspi:
        atspi.set_timeout(500, 1000)
    last_session, last_foreground, last_snapshot = {}, None, None
    last_read = 0
    suspend_clock = getattr(time, 'CLOCK_BOOTTIME', None)
    suspend_offset = time.clock_gettime(suspend_clock) - time.monotonic() if suspend_clock is not None else None
    emit('observation.status', {}, {'ax_permission':'available' if atspi else 'unavailable',
         'coverage':'PARTIAL', 'reason':'linux_read_only_x11_logind_atspi'})
    while os.getppid() == options['parent_pid']:
        current = session_state()
        for kind, proof in session_events(last_session, current):
            emit(kind, {}, proof)
        last_session = current
        if suspend_offset is not None:
            now_offset = time.clock_gettime(suspend_clock) - time.monotonic()
            if now_offset - suspend_offset > 2:
                emit('system.did_wake', {}, {'sleep_state':'awake', 'reason':'linux_boottime_suspend_elapsed'})
            suspend_offset = now_offset
        if current.get('LockedHint') != 'yes' and current.get('Active') != 'no':
            foreground = x11_window()
            if foreground and allowed(foreground['bundle_id'], options) and foreground != last_foreground:
                proof = {'coverage':'X11_FOREGROUND_METADATA', 'read_scope':'foreground_application'}
                if content_allowed(foreground['bundle_id'], options) or options['window_exclusions']:
                    title = x11_title(foreground['window_id'])
                    if title in options['window_exclusions'] or title is None and options['window_exclusions']:
                        foreground = None
                    elif content_allowed(foreground['bundle_id'], options) and qualified_title(title, options):
                        proof['window_title'] = title
                if foreground:
                    emit('app.activated', foreground, proof, 'linux.desktop')
            changed = foreground != last_foreground
            if changed or time.monotonic() - last_read >= (120 if options['low_power'] else 30):
                snapshot = atspi_snapshot(atspi, options, foreground)
                if snapshot is not None and snapshot != last_snapshot:
                    obj, proof = snapshot
                    if not foreground:
                        emit('app.activated', obj, {'coverage':'AT_SPI_REGISTERED_FOREGROUND'}, 'linux.desktop')
                    if proof is not None:
                        emit('ax.snapshot', obj, proof, 'linux.atspi')
                last_snapshot = snapshot
                last_read = time.monotonic()
            last_foreground = foreground
        time.sleep(5)


if __name__ == '__main__':
    if sys.argv[1:] == ['--probe']:
        print(json.dumps({'atspi':atspi_module() is not None}))
    else:
        raw = sys.stdin.buffer.readline(32769)
        if len(raw) > 32768 or not raw.endswith(b'\n'):
            raise SystemExit('Invalid Linux observer options')
        run(json.loads(raw))
