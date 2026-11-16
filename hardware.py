"""Identify the host and MLX recommendation scope without importing inference runtimes."""
import platform
from pathlib import Path
import subprocess


def get_hardware():
    os_name = get_os()
    arch = get_arch()
    text = None if os_name == 'Linux' else get_system_output()
    supported = os_name == 'macOS' and arch == 'arm64'
    reason = None
    if os_name == 'macOS' and arch == 'x86_64':
        reason = ('The bundled MLX recommendation requires Apple Silicon. Intel Macs can use '
                  'a configured local OpenAI-compatible endpoint or a cloud route; native Intel APP qualification is pending.')
    elif not supported:
        reason = ('The bundled MLX recommendation targets macOS + Apple Silicon. '
                  'Core can use a configured local OpenAI-compatible endpoint or a cloud route; '
                  'this does not qualify native desktop features or provider acceleration.')
    return {'os': os_name, 'arch': arch, 'chip': get_chip(text),
            'memory': get_memory(text), 'computer': get_computer(text),
            'platform_status': 'supported' if supported else 'deferred',
            'platform_reason': reason, 'mps_availability': 'NOT_PROBED'}


def get_os():
    name = platform.system()
    return 'macOS' if name == 'Darwin' else name or 'Unknown'


def external_power():
    """Observe AC power; a missing battery alone does not establish a power source."""
    import psutil
    try:
        battery = psutil.sensors_battery()
    except (OSError, NotImplementedError):
        battery = None
    if battery is not None and type(battery.power_plugged) is bool:
        return battery.power_plugged
    if platform.system() == 'Linux':
        return _linux_external_power(Path('/sys/class/power_supply'))
    if platform.system() != 'Darwin':
        return None
    try:
        result = subprocess.run(['/usr/bin/pmset', '-g', 'batt'],
                                capture_output=True, text=True, timeout=3, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = result.stdout.splitlines()
    if not lines:
        return None
    if lines[0].strip() == "Now drawing from 'AC Power'":
        return True
    if lines[0].strip() == "Now drawing from 'Battery Power'":
        return False
    return None


def _linux_external_power(root):
    states = []
    try:
        supplies = list(root.iterdir())
    except OSError:
        return None
    for supply in supplies:
        try:
            kind = (supply / 'type').read_text().strip()
            if kind not in {'Mains', 'USB', 'USB_C', 'USB_PD', 'USB_PD_DRP', 'Wireless'}:
                continue
            scope = supply / 'scope'
            if scope.exists() and scope.read_text().strip() == 'Device':
                continue
            online = (supply / 'online').read_text().strip()
            if online in {'0', '1'}:
                states.append(online == '1')
        except OSError:
            continue
    return any(states) if states else None


def get_arch():
    machine = platform.machine().lower()
    return {'aarch64': 'arm64', 'amd64': 'x86_64'}.get(machine, machine or 'Unknown')


def get_system_output():
    if platform.system() != 'Darwin':
        return ''
    try:
        return subprocess.run(['/usr/sbin/system_profiler', 'SPHardwareDataType'],
                              capture_output=True, text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def profile_values(text):
    return {key.strip(): value.strip() for line in text.splitlines()
            if ':' in line for key, value in [line.split(':', 1)]}


def get_chip(text=None):
    if text is None and platform.system() == 'Linux':
        try:
            values = profile_values(Path('/proc/cpuinfo').read_text())
            return values.get('model name') or values.get('Hardware') or platform.processor() or 'Unknown'
        except OSError:
            return platform.processor() or 'Unknown'
    values = profile_values(get_system_output() if text is None else text)
    return values.get('Chip') or values.get('Processor Name') or 'Unknown'


def get_memory(text=None):
    if text is None and platform.system() == 'Linux':
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    value = profile_values(get_system_output() if text is None else text).get('Memory', '')
    parts = value.split()
    if len(parts) != 2 or parts[1] not in {'GB', 'TB'}:
        return None
    try:
        return float(parts[0]) * (1024 if parts[1] == 'TB' else 1)
    except ValueError:
        return None


def get_computer(text=None):
    if text is None and platform.system() == 'Linux':
        try:
            return Path('/sys/devices/virtual/dmi/id/product_name').read_text().strip() or 'Linux host'
        except OSError:
            return 'Linux host'
    return profile_values(get_system_output() if text is None else text).get('Model Name', 'Unknown')
