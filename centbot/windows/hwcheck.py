"""Hardware / OS capability checks for CENTBOT Windows setup."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from typing import Any

import psutil


MIN_RAM_GB_FOUR_EMULATORS = 12.0
MIN_DISK_GB = 25.0
MIN_CPU_CORES = 4


def windows_version() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "is_windows": platform.system().lower() == "windows",
    }


def cpu_info() -> dict[str, Any]:
    return {
        "physical_cores": psutil.cpu_count(logical=False) or 0,
        "logical_cores": psutil.cpu_count(logical=True) or 0,
        "ok_for_four_emulators": (psutil.cpu_count(logical=False) or 0) >= MIN_CPU_CORES,
    }


def ram_info() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    total_gb = vm.total / (1024**3)
    return {
        "total_gb": round(total_gb, 2),
        "available_gb": round(vm.available / (1024**3), 2),
        "ok_for_four_emulators": total_gb >= MIN_RAM_GB_FOUR_EMULATORS,
        "recommended_emulators": recommended_emulator_count(total_gb, psutil.cpu_count(logical=False) or 0),
    }


def disk_info(path: str | None = None) -> dict[str, Any]:
    target = path or os.getcwd()
    usage = shutil.disk_usage(target)
    free_gb = usage.free / (1024**3)
    return {
        "path": target,
        "free_gb": round(free_gb, 2),
        "total_gb": round(usage.total / (1024**3), 2),
        "ok": free_gb >= MIN_DISK_GB,
    }


def recommended_emulator_count(ram_gb: float, physical_cores: int) -> int:
    if ram_gb < 6 or physical_cores < 2:
        return 0
    if ram_gb < 8 or physical_cores < 3:
        return 1
    if ram_gb < 12 or physical_cores < 4:
        return 2
    if ram_gb < 16:
        return 3
    return 4


def virtualization_supported() -> dict[str, Any]:
    """Best-effort HV / VT-x / AMD-V detection (Windows-focused)."""
    info: dict[str, Any] = {"ok": False, "method": None, "detail": None}
    if platform.system().lower() != "windows":
        # Linux KVM presence is informative only — not Windows install proof
        info["ok"] = os.path.exists("/dev/kvm")
        info["method"] = "linux_kvm"
        info["detail"] = "Non-Windows host; Windows Hyper-V/VT-x not applicable"
        return info
    # systeminfo Hyper-V Requirements
    try:
        out = subprocess.check_output(["systeminfo"], text=True, timeout=60, errors="ignore")
        lower = out.lower()
        if "a hypervisor has been detected" in lower or "virtualization enabled in firmware: yes" in lower:
            info["ok"] = True
            info["method"] = "systeminfo"
            info["detail"] = "Virtualization reported available"
            return info
        if "virtualization enabled in firmware: no" in lower:
            info["ok"] = False
            info["method"] = "systeminfo"
            info["detail"] = "Virtualization disabled in firmware"
            return info
    except (OSError, subprocess.SubprocessError) as exc:
        info["detail"] = f"systeminfo_failed:{exc}"
    # Fallback: assume unknown
    info["detail"] = info.get("detail") or "Could not confirm virtualization; enable VT-x/AMD-V and Hyper-V/WHPX"
    return info


def full_hw_report(path: str | None = None) -> dict[str, Any]:
    win = windows_version()
    cpu = cpu_info()
    ram = ram_info()
    disk = disk_info(path)
    virt = virtualization_supported()
    blockers: list[str] = []
    if not win["is_windows"]:
        blockers.append("not_windows_host")
    if not disk["ok"]:
        blockers.append("insufficient_disk")
    if not virt["ok"] and win["is_windows"]:
        blockers.append("virtualization_unavailable")
    if not ram["ok_for_four_emulators"]:
        blockers.append("ram_below_12gb_for_four_emulators")
    if not cpu["ok_for_four_emulators"]:
        blockers.append("cpu_below_4_cores_for_four_emulators")
    return {
        "windows": win,
        "cpu": cpu,
        "ram": ram,
        "disk": disk,
        "virtualization": virt,
        "recommended_emulators": ram["recommended_emulators"],
        "blockers": blockers,
        "can_attempt_setup": True,  # components can still install; emulator count may be reduced
    }
