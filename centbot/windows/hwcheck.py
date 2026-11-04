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
    available_gb = vm.available / (1024**3)
    return {
        "total_gb": round(total_gb, 2),
        "available_gb": round(available_gb, 2),
        "ok_for_four_emulators": total_gb >= MIN_RAM_GB_FOUR_EMULATORS and available_gb >= 10.0,
        "recommended_emulators": recommended_emulator_count(
            total_gb,
            psutil.cpu_count(logical=False) or 0,
            available_gb=available_gb,
        ),
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


def recommended_emulator_count(
    ram_gb: float,
    physical_cores: int,
    *,
    available_gb: float | None = None,
) -> int:
    """How many AVDs to run. Prefer free RAM when provided — total RAM alone over-promises."""
    if ram_gb < 6 or physical_cores < 2:
        return 0
    if ram_gb < 8 or physical_cores < 3:
        by_total = 1
    elif ram_gb < 12 or physical_cores < 4:
        by_total = 2
    elif ram_gb < 16:
        by_total = 3
    else:
        by_total = 4
    if available_gb is None:
        return by_total
    # ~2.2 GB free per emulator after Windows/Chrome overhead
    if available_gb < 2.0:
        by_free = 0
    elif available_gb < 4.5:
        by_free = 1
    elif available_gb < 7.0:
        by_free = 2
    elif available_gb < 10.0:
        by_free = 3
    else:
        by_free = 4
    return min(by_total, by_free)


def virtualization_supported() -> dict[str, Any]:
    """Best-effort HV / VT-x / AMD-V detection (Windows-focused)."""
    info: dict[str, Any] = {"ok": False, "method": None, "detail": None, "hyper_v": None, "whpx": None}
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
        elif "virtualization enabled in firmware: no" in lower:
            info["ok"] = False
            info["method"] = "systeminfo"
            info["detail"] = "Virtualization disabled in firmware — enable VT-x/AMD-V in BIOS"
            return info
    except (OSError, subprocess.SubprocessError) as exc:
        info["detail"] = f"systeminfo_failed:{exc}"

    # Windows features: Hyper-V + Windows Hypervisor Platform (needed by Android Emulator WHPX)
    features = windows_hypervisor_features()
    info["hyper_v"] = features.get("hyper_v")
    info["whpx"] = features.get("whpx")
    if features.get("whpx") or features.get("hyper_v"):
        info["ok"] = True
        info["method"] = info.get("method") or "windows_features"
        info["detail"] = features.get("detail") or "Hypervisor feature present"
    if not info.get("detail"):
        info["detail"] = "Could not confirm virtualization; enable VT-x/AMD-V and Hyper-V/WHPX"
    return info


def windows_hypervisor_features() -> dict[str, Any]:
    """Detect Hyper-V and Windows Hypervisor Platform optional features."""
    out: dict[str, Any] = {"hyper_v": None, "whpx": None, "detail": None}
    if platform.system().lower() != "windows":
        return out
    ps = (
        "$names=@('Microsoft-Hyper-V-All','HypervisorPlatform','Microsoft-Windows-Subsystem-Linux');"
        "Get-WindowsOptionalFeature -Online -ErrorAction SilentlyContinue |"
        "Where-Object { $_.FeatureName -match 'Hyper-V|HypervisorPlatform' } |"
        "Select-Object FeatureName,State | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        raw = (proc.stdout or "").strip()
        if not raw:
            out["detail"] = "feature_query_empty"
            return out
        import json

        data = json.loads(raw)
        rows = data if isinstance(data, list) else [data]
        for row in rows:
            name = str(row.get("FeatureName") or "")
            state = str(row.get("State") or "").lower()
            enabled = state in {"enabled", "enablepending"}
            if "HypervisorPlatform" in name:
                out["whpx"] = enabled
            if "Hyper-V" in name:
                out["hyper_v"] = enabled or out.get("hyper_v")
        out["detail"] = f"hyper_v={out['hyper_v']} whpx={out['whpx']}"
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        out["detail"] = f"feature_query_failed:{exc}"
    return out


def java_jdk_status() -> dict[str, Any]:
    """Locate a JDK usable by Android cmdline-tools (sdkmanager needs Java 17+)."""
    java = shutil.which("java")
    javac = shutil.which("javac")
    version = None
    if java:
        try:
            proc = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=15, check=False)
            blob = (proc.stderr or proc.stdout or "").strip().splitlines()
            version = blob[0] if blob else None
        except (OSError, subprocess.SubprocessError):
            version = None
    java_home = os.environ.get("JAVA_HOME", "").strip() or None
    ok = bool(java)
    return {
        "ok": ok,
        "java": java,
        "javac": javac,
        "JAVA_HOME": java_home,
        "version": version,
        "hint": None if ok else "Install Temurin JDK 17+ (winget install EclipseAdoptium.Temurin.17.JDK)",
    }


def full_hw_report(path: str | None = None) -> dict[str, Any]:
    win = windows_version()
    cpu = cpu_info()
    ram = ram_info()
    disk = disk_info(path)
    virt = virtualization_supported()
    jdk = java_jdk_status()
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
    if not jdk["ok"] and win["is_windows"]:
        blockers.append("jdk_missing")
    rec = recommended_emulator_count(
        ram["total_gb"],
        cpu["physical_cores"],
        available_gb=ram.get("available_gb"),
    )
    # Disk can also force a lower count
    if disk["free_gb"] < 40 and rec > 2:
        rec = min(rec, 2)
    if disk["free_gb"] < 30 and rec > 1:
        rec = min(rec, 1)
    if rec == 0 and float(ram.get("available_gb") or 0) < 2.0:
        blockers.append("ram_available_too_low_close_apps")
    return {
        "windows": win,
        "cpu": cpu,
        "ram": ram,
        "disk": disk,
        "virtualization": virt,
        "jdk": jdk,
        "recommended_emulators": rec,
        "blockers": blockers,
        "can_attempt_setup": True,  # components can still install; emulator count may be reduced
    }
