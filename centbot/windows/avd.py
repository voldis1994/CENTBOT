"""Create and manage CENTBOT_ANDROID_01..04 AVDs."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
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

    # Ensure system image
    run([sdkmanager, "--install", package], {"timeout": 1800})

    for name in names:
        if name in existing:
            skipped.append(name)
            continue
        # echo no | avdmanager create avd -n NAME -k PACKAGE -d DEVICE --force
        cmd = [avdmanager, "create", "avd", "-n", name, "-k", package, "-d", device, "--force"]
        # Non-interactive: feed "no" for custom hardware profile prompt when present
        try:
            proc = subprocess.run(
                cmd,
                input="no\n",
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            result = {"ok": proc.returncode == 0, "stdout": proc.stdout[-1000:], "stderr": proc.stderr[-1000:]}
        except (OSError, subprocess.SubprocessError) as exc:
            result = {"ok": False, "error": str(exc)}
        if result.get("ok"):
            created.append(name)
            _write_avd_config_tweaks(name)
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


def _write_avd_config_tweaks(avd_name: str) -> None:
    """Optimize RAM/graphics for multi-instance when config.ini is found."""
    home = Path.home()
    candidates = [
        home / ".android" / "avd" / f"{avd_name}.avd" / "config.ini",
        home / "AppData" / "Local" / "Android" / "Sdk" / ".android" / "avd" / f"{avd_name}.avd" / "config.ini",
    ]
    tweaks = {
        "hw.ramSize": "2048",
        "hw.gpu.enabled": "yes",
        "hw.gpu.mode": "auto",
        "disk.dataPartition.size": "2G",
        "hw.keyboard": "yes",
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
    adb = shutil.which(adb_path) or adb_path
    base = [adb]
    if serial:
        base += ["-s", serial]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            out = subprocess.check_output(base + ["shell", "getprop", "sys.boot_completed"], text=True, timeout=10, stderr=subprocess.DEVNULL)
            if out.strip() == "1":
                return {"ok": True, "serial": serial}
        except (OSError, subprocess.SubprocessError):
            pass
        time.sleep(2)
    return {"ok": False, "error": "boot_timeout", "serial": serial}


def plan_emulator_count() -> dict[str, Any]:
    hw = full_hw_report()
    rec = recommended_emulator_count((hw.get("ram") or {}).get("total_gb") or 0, (hw.get("cpu") or {}).get("physical_cores") or 0)
    return {
        "recommended": rec,
        "names": AVD_NAMES[:rec],
        "hw": hw,
        "message": None
        if rec >= 4
        else f"Resources allow {rec} emulator(s), not 4. CENTBOT will use {rec} and keep roles collapsed.",
    }
