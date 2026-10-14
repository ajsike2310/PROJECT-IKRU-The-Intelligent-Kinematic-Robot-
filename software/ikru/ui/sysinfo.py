"""Laptop spec lookup with no extra dependencies (registry / ctypes / nvidia-smi). Never raises."""
import ctypes
import os
import platform
import subprocess


def _reg(path, name):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            return str(winreg.QueryValueEx(k, name)[0]).strip()
    except Exception:
        return ""


def _ram_gb():
    try:
        class MS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong),
                        ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
        m = MS()
        m.l = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.total / 2**30
    except Exception:
        return 0.0


def _gpu():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            text=True, timeout=4, stderr=subprocess.DEVNULL).strip().splitlines()[0]
        name, mem = [p.strip() for p in out.split(",")]
        return f"{name.replace('NVIDIA GeForce ', '')} ({mem})"
    except Exception:
        return ""


def collect():
    bios = r"HARDWARE\DESCRIPTION\System\BIOS"
    vendor = _reg(bios, "SystemManufacturer")
    model = _reg(bios, "SystemProductName")
    cpu = _reg(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString") or platform.processor()
    cpu = " ".join(cpu.replace("(R)", "").replace("(TM)", "").split())
    ram = _ram_gb()
    return {
        "machine": " ".join(x for x in (vendor, model) if x) or platform.node(),
        "cpu": f"{cpu} ({os.cpu_count()} threads)" if cpu else "",
        "ram": f"{ram:.0f} GB RAM" if ram else "",
        "gpu": _gpu(),
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
    }
