import subprocess
import platform

def get_os(): #获取操作系统

    if platform.system() == "Darwin":
        os = "macOS"

    else:
        os = "Unknown"

    return os

def get_arch(): #获取cpu架构

    if platform.machine() == "arm64":
        arch = "arm64"

    else:
        arch = "Unknown"

    return arch

def get_system_output(): #获取系统数据
    system_output = subprocess.run(
        ["/usr/sbin/system_profiler", "SPHardwareDataType"],
        capture_output=True,
        text=True
    )

    return system_output.stdout


text = get_system_output()


def get_chip(): #获取芯片型号

    for line in text.splitlines():

        if "Chip:" in line:
            result_1 = line.strip()

            chip = result_1.split(":")[1].strip()

            break

        else:
            chip = "Unknown"

    return chip

def get_memory():
    memory = None

    for line in text.splitlines():

        if "Memory:" in line:
            result_1 = line.strip()
            result_2 = result_1.split(":")[1]
            memory = int(result_2.split("G")[0].strip())
            break

    return memory

def get_computer():

    for line in text.splitlines():
        if "Model Name:" in line:
            result_1 = line.strip()

            computer = result_1.split(":")[1].strip()

            break

        else:
            computer = "Unknown"

    return computer

def get_hardware():

    os_name = get_os()
    arch = get_arch()
    chip = get_chip()
    status = "supported" if os_name == "macOS" and arch == "arm64" else "deferred"
    reason = None
    if os_name == "macOS" and arch != "arm64":
        reason = "Intel Mac support is deferred; this release targets Apple Silicon + MLX."
    elif os_name != "macOS":
        reason = "Only macOS + Apple Silicon is in the current supported scope."

    hardware = {
        "os": os_name,
        "arch": arch,
        "chip": chip,
        "memory": get_memory(),
        "computer": get_computer(),
        "platform_status": status,
        "platform_reason": reason,
    }

    return hardware
