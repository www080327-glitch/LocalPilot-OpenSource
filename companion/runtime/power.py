"""Host power policy. Local wall time comes from the operating system."""
from datetime import datetime
import re
import subprocess
import sys
import time


def system_power_source():
    text = subprocess.check_output(['/usr/bin/pmset', '-g', 'batt'], text=True, timeout=2)
    match = re.search(r"^Now drawing from '(AC Power|Battery Power)'\s*$", text, re.MULTILINE)
    return match[1] if match else None


def profile_low_power(settings, source):
    current = None
    values = []
    for line in settings.splitlines():
        header = re.fullmatch(r'(AC Power|Battery Power|UPS Power):', line.strip())
        if line and not line[0].isspace() and line.rstrip().endswith(':'):
            current = header[1] if header else None
        elif current == source:
            value = re.fullmatch(r'\s*lowpowermode\s+([01])\s*', line)
            if value:
                values.append(value[1])
    return len(values) != 1 or values[0] == '1'


def local_model_block_reason(config):
    """Fail closed before worker spawn or HTTP inference; adapters are test-only."""
    import os
    if os.environ.get("LOCALPILOT_DISABLE_LOCAL_MODELS") == "1":
        return "Local model inference disabled by operator"
    if config.allow_local_on_battery:
        return None
    try:
        import psutil
        battery = psutil.sensors_battery()
        if battery is not None and battery.power_plugged is True:
            return None
    except (OSError, AttributeError):
        pass
    return "External power required for local model inference (power unknown or on battery)"


class LowPowerPolicy:
    def __init__(self, config):
        self.config = config
        if config.low_power_policy not in {"always", "until", "off", "system"}:
            raise ValueError("low_power_policy must be always, until or off")
        if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", config.low_power_until):
            raise ValueError("low_power_until requires explicit local HH:MM")

    def active(self, now=None):
        if self.config.low_power_policy=='system':
            if sys.platform!='darwin':return True
            source = None
            try:
                source = system_power_source()
                if source is None:return True
                cached=getattr(self,'_system_cached',(0,None,True))
                if source==cached[1] and time.monotonic()-cached[0]<15:return cached[2]
                value=profile_low_power(subprocess.check_output(['/usr/bin/pmset','-g','custom'],text=True,timeout=2),source)
                if system_power_source()!=source:value=True
            except (OSError,subprocess.SubprocessError):value=True
            self._system_cached=(time.monotonic(),source,value)
            return value
        if self.config.low_power_policy == "always":
            return True
        if self.config.low_power_policy == "off":
            return False
        now = now or datetime.now().astimezone()
        hour, minute = map(int, self.config.low_power_until.split(":"))
        return (now.hour, now.minute) < (hour, minute)

    def snapshot(self):
        now = datetime.now().astimezone()
        return {"active": self.active(now), "policy": self.config.low_power_policy,
                "until_local": self.config.low_power_until, "timezone": str(now.tzinfo),
                "local_time": now.isoformat(), "background_inference": False,
                "small_model_on_demand": self.config.lightweight_on_demand,
                "large_model_auto_load": False}
