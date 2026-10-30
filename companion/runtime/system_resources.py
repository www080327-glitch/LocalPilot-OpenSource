"""Deterministic local telemetry. CPU load is never converted into watts."""
import plistlib
import subprocess
import time


def _signed_current(value):
    if type(value) not in (int,float):return None
    if value>=2**63:value-=2**64
    elif 2**31<=value<2**32:value-=2**32
    return value


def snapshot():
    import psutil
    memory=psutil.virtual_memory();battery=psutil.sensors_battery()
    on_ac=battery.power_plugged if battery is not None else None
    watts=None
    if on_ac is False:
        try:
            raw=subprocess.check_output(["/usr/sbin/ioreg","-rn","AppleSmartBattery","-a"],timeout=2)
            battery_data=plistlib.loads(raw)[0]
            voltage=battery_data.get("Voltage")
            current=_signed_current(battery_data.get("InstantAmperage",battery_data.get("Amperage")))
            if type(voltage) in (int,float) and current is not None and 0<voltage<30000 and abs(current)<30000:
                watts=abs(voltage*current)/1000000
        except (OSError,ValueError,IndexError,TypeError,subprocess.TimeoutExpired):pass
    return {"at":time.time(),"on_ac_power":on_ac,"battery_percent":battery.percent if battery else None,
        "memory_available_bytes":memory.available,"memory_total_bytes":memory.total,
        "memory_used_percent":memory.percent,"swap_used_bytes":psutil.swap_memory().used,
        "system_cpu_percent":psutil.cpu_percent(interval=None),"battery_discharge_watts":watts,
        "energy_source":"battery_voltage_current" if watts is not None else "UNAVAILABLE",
        "energy_scope":"battery electrical discharge only; AC system power unavailable",
        "gpu_utilization":None}


class ResourceMonitor:
    def __init__(self, config, sampler=snapshot):
        self.config=config;self.sampler=sampler;self.latest={}
        self.last_sample=0;self.since={};self.last_alert={}

    def poll(self, force=False, now=None):
        now=time.time() if now is None else now
        if not force and now-self.last_sample<self.config.resource_sample_seconds:return []
        self.last_sample=now;self.latest=self.sampler()
        memory_low=self.latest["memory_available_bytes"]<self.config.resource_memory_alert_bytes
        watts=self.latest.get("battery_discharge_watts")
        high_energy=watts is not None and watts>=self.config.resource_discharge_alert_watts
        high_cpu=self.latest.get("system_cpu_percent",0)>=self.config.resource_cpu_alert_percent
        alerts=[]
        for kind,active in (("memory",memory_low),("battery_discharge",high_energy),("cpu_load",high_cpu)):
            if not active:self.since.pop(kind,None);continue
            self.since.setdefault(kind,now)
            if now-self.since[kind]<self.config.resource_alert_sustain_seconds:continue
            if now-self.last_alert.get(kind,-1e12)<self.config.resource_alert_cooldown_seconds:continue
            self.last_alert[kind]=now
            message=(f"系统可用内存偏低：{self.latest['memory_available_bytes']/1024**3:.1f} GiB。" if kind=="memory" else
                f"电池持续放电功率较高：{watts:.1f} W（电池硬件采样）。" if kind=="battery_discharge" else
                f"系统 CPU 持续高负载：{self.latest['system_cpu_percent']:.0f}%。这不是瓦数测量。")
            alerts.append({"kind":kind,"at":now,"message":message,"source":"host_resource_telemetry"})
        return alerts
