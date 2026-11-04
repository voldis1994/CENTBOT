"""Create and manage CENTBOT_ANDROID_01..04 AVDs."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from centbot.windows.hwcheck import full_hw_report, recommended_emulator_count
from centbot.windows.install_state import SetupProgress

AVD_NAMES = [
    "CENTBOT_ANDROID_01",
    "CENTBOT_ANDROID_02",
    "CENTBOT_ANDROID_03",
    "CENTBOT_ANDROID_04",
]

DEFAULT_PACKAGE = "system-images;android-30;google_apis;x86_64"
DEFAULT_DEVICE = "pixel_4"
# Fallback device profiles if pixel_4 is unavailable on the host SDK
DEVICE_FALLBACKS = ("pixel_4", "pixel_3a", "pixel", "pixel_5")

Runner = Callable[[list[str], dict[str, Any] | None], dict[str, Any]]


def _run(cmd: list[str], opts: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = opts or {}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=opts.get("timeout", 300), check=False)
        return {"ok": proc.returncode == 0, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:], "cmd": cmd}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc), "cmd": cmd}


def list_avds(emulator_path: str = "emulator") -> list[str]:
    exe = shutil.which(emulator_path) or emulator_path
    try:
        out = subprocess.check_output([exe, "-list-avds"], text=True, timeout=30, stderr=subprocess.DEVNULL)
        return [ln.strip() for ln in out.splitlines() if ln.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def ensure_avds(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Alias used by android_sdk / INSTALL_ANDROID.bat."""
    return ensure_centbot_avds(*args, **kwargs)


def ensure_centbot_avds(
    *,
    count: int | None = None,
    progress: SetupProgress | None = None,
    runner: Runner | None = None,
    sdkmanager: str = "sdkmanager",
    avdmanager: str = "avdmanager",
    package: str = DEFAULT_PACKAGE,
    device: str = DEFAULT_DEVICE,
) -> dict[str, Any]:
    """Create up to four AVDs; reduce count if RAM/CPU insufficient."""
    run = runner or _run
    hw = full_hw_report()
    rec = count if count is not None else hw.get("recommended_emulators", 4)
    rec = max(0, min(4, int(rec)))
    names = AVD_NAMES[:rec]
    existing = set(list_avds())
    created: list[str] = []
    skipped: list[str] = []
    errors: list[dict[str, Any]] = []

    if rec < 4:
        errors.append(
            {
                "warning": "reduced_emulator_count",
                "requested": 4,
                "using": rec,
                "reason": hw.get("blockers") or ["resource_limit"],
                "ram_gb": (hw.get("ram") or {}).get("total_gb"),
                "cpu_cores": (hw.get("cpu") or {}).get("physical_cores"),
            }
        )

    if not shutil.which(avdmanager) and not Path(avdmanager).exists():
        detail = "avdmanager_not_found"
        if progress:
            progress.mark("android_avds", ok=False, detail=detail)
        return {
            "ok": False,
            "error": detail,
            "recommended": rec,
            "names_planned": names,
            "hint": "Install Android SDK cmdline-tools so avdmanager is on PATH",
            "windows": sys.platform.startswith("win"),
        }

    # Ensure system image (idempotent — sdkmanager skips installed packages)
    run([sdkmanager, "--install", package], {"timeout": 1800})

    device_profile = device
    for name in names:
        if name in existing:
            skipped.append(name)
            # Still refresh non-destructive tweaks on existing AVDs
            _write_avd_config_tweaks(name, hw=hw)
            continue
        # Never pass --force for existing names (already skipped). Create new only.
        result = _create_avd(avdmanager, name, package, device_profile)
        if not result.get("ok"):
            # Retry with alternate Pixel device profiles
            for alt in DEVICE_FALLBACKS:
                if alt == device_profile:
                    continue
                result = _create_avd(avdmanager, name, package, alt)
                if result.get("ok"):
                    device_profile = alt
                    break
        if result.get("ok"):
            created.append(name)
            _write_avd_config_tweaks(name, hw=hw)
        else:
            errors.append({"avd": name, "result": result})

    final_existing = set(list_avds())
    present = [n for n in AVD_NAMES if n in final_existing]
    ok = len(present) >= max(1, rec) if rec else True
    if progress:
        progress.mark(
            "android_avds",
            ok=ok or (rec == 0),
            detail=f"present={present};created={created};skipped={skipped};errors={len(errors)}",
        )
    return {
        "ok": ok or rec == 0,
        "recommended": rec,
        "created": created,
        "skipped_existing": skipped,
        "present": present,
        "missing": [n for n in names if n not in final_existing],
        "errors": errors,
        "virtualization": hw.get("virtualization"),
    }


def _create_avd(avdmanager: str, name: str, package: str, device: str) -> dict[str, Any]:
    """Create one AVD without overwriting an existing definition."""
    cmd = [avdmanager, "create", "avd", "-n", name, "-k", package, "-d", device]
    try:
        proc = subprocess.run(
            cmd,
            input="no\n",
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": (proc.stdout or "")[-1000:],
            "stderr": (proc.stderr or "")[-1000:],
            "device": device,
            "cmd": cmd,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc), "device": device, "cmd": cmd}


def _write_avd_config_tweaks(avd_name: str, hw: dict[str, Any] | None = None) -> None:
    """Optimize RAM/CPU/graphics/disk for multi-instance when config.ini is found."""
    home = Path.home()
    candidates = [
        home / ".android" / "avd" / f"{avd_name}.avd" / "config.ini",
        home / "AppData" / "Local" / "Android" / "Sdk" / ".android" / "avd" / f"{avd_name}.avd" / "config.ini",
    ]
    ram_gb = float(((hw or {}).get("ram") or {}).get("total_gb") or 16)
    # Scale per-AVD RAM: keep host usable when running multiple instances
    if ram_gb < 8:
        ram_mb = "1536"
    elif ram_gb < 12:
        ram_mb = "2048"
    elif ram_gb < 16:
        ram_mb = "2048"
    else:
        ram_mb = "3072"
    cores = int(((hw or {}).get("cpu") or {}).get("physical_cores") or 4)
    per_avd_cores = "2" if cores >= 6 else "1"
    tweaks = {
        "hw.ramSize": ram_mb,
        "hw.cpu.ncore": per_avd_cores,
        "hw.gpu.enabled": "yes",
        "hw.gpu.mode": "auto",
        "disk.dataPartition.size": "2G",
        "hw.keyboard": "yes",
        "skin.name": "pixel_4",
        "hw.device.name": "pixel_4",
    }
    for path in candidates:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            lines = text.splitlines()
            keys = {ln.split("=", 1)[0]: i for i, ln in enumerate(lines) if "=" in ln}
            for k, v in tweaks.items():
                entry = f"{k}={v}"
                if k in keys:
                    lines[keys[k]] = entry
                else:
                    lines.append(entry)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            continue


def wait_for_boot(adb_path: str = "adb", serial: str | None = None, timeout_s: float = 180.0) -> dict[str, Any]:
    """Delegate to shared ADB boot waiter (sys.boot_completed=1)."""
    from centbot.android.adb import wait_boot_completed

    return wait_boot_completed(adb_path=adb_path, serial=serial, timeout_s=timeout_s)


def plan_emulator_count() -> dict[str, Any]:
    hw = full_hw_report()
    ram = hw.get("ram") or {}
    rec = recommended_emulator_count(
        float(ram.get("total_gb") or 0),
        int((hw.get("cpu") or {}).get("physical_cores") or 0),
        available_gb=float(ram.get("available_gb") or 0),
    )
    if rec <= 0:
        msg = (
            f"Brīvā RAM ~{ram.get('available_gb')} GB — aizver Chrome/citas programmas, "
            "tad STOP+START (emulatoriem vajag ≥2 GB brīvus)."
        )
    elif rec >= 4:
        msg = None
    else:
        msg = (
            f"Resources allow {rec} emulator(s), not 4 "
            f"(total {ram.get('total_gb')} GB / free {ram.get('available_gb')} GB). "
            "CENTBOT will use the reduced count."
        )
    return {
        "recommended": rec,
        "names": AVD_NAMES[:rec] if rec > 0 else [],
        "hw": hw,
        "message": msg,
        "reason": msg,
    }
