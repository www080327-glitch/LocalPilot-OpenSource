"""Read Linux power telemetry without changing host settings."""
from pathlib import Path
import shutil
import subprocess


POWER_SUPPLY = Path('/sys/class/power_supply')
PLATFORM_PROFILE = Path('/sys/firmware/acpi/platform_profile')


def external_power(root=None):
    supplies = Path(root) if root is not None else POWER_SUPPLY
    observed = []
    try:
        entries = list(supplies.iterdir())
    except OSError:
        return None
    for supply in entries:
        try:
            scope = supply / 'scope'
            if scope.exists() and scope.read_text().strip() == 'Device':
                continue
            kind = (supply / 'type').read_text().strip()
            if kind not in {'Mains', 'USB', 'USB_C', 'USB_PD', 'USB_PD_DRP', 'Wireless'}:
                continue
            online = (supply / 'online').read_text().strip()
            if online in {'0', '1'}:
                observed.append(online == '1')
        except OSError:
            continue
    return any(observed) if observed else None


def low_power():
    executable = shutil.which('powerprofilesctl')
    if executable:
        try:
            result = subprocess.run([executable, 'get'], capture_output=True, text=True, timeout=2)
            mode = result.stdout.strip() if result.returncode == 0 else ''
            if mode in {'power-saver', 'balanced', 'performance'}:
                return mode == 'power-saver'
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        mode = PLATFORM_PROFILE.read_text().strip()
    except OSError:
        return None
    if mode in {'low-power', 'quiet', 'cool'}:
        return True
    if mode in {'balanced', 'balanced-performance', 'performance'}:
        return False
    return None


def battery_discharge(root=None):
    supplies = Path(root) if root is not None else POWER_SUPPLY
    readings = []
    try:
        for supply in supplies.iterdir():
            if (supply / 'type').read_text().strip() != 'Battery':
                continue
            present = supply / 'present'
            if present.exists() and present.read_text().strip() == '0':
                continue
            if (supply / 'status').read_text().strip() != 'Discharging':
                return None
            power = supply / 'power_now'
            if power.exists():
                watts = int(power.read_text().strip()) / 1_000_000
            else:
                voltage = int((supply / 'voltage_now').read_text().strip())
                current = int((supply / 'current_now').read_text().strip())
                watts = abs(voltage * current) / 1_000_000_000_000
            if watts < 0:
                return None
            readings.append(watts)
    except (OSError, ValueError):
        return None
    return sum(readings) if readings else None
