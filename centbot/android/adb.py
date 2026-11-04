"""ADB helpers — device discovery, detailed listing, boot wait."""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any


def adb_available(adb_path: str = "adb") -> bool:
    return shutil.which(adb_path) is not None or _path_exists(adb_path)


def _path_exists(path: str) -> bool:
    try:
        from pathlib import Path

        return Path(path).is_file()
    except OSError:
        return False


def resolve_adb(adb_path: str = "adb") -> str:
    return shutil.which(adb_path) or adb_path


def adb(cmd: list[str], adb_path: str = "adb", timeout: float = 30.0) -> dict[str, Any]:
    exe = resolve_adb(adb_path)
    if not adb_available(exe):
        return {
            "ok": False,
            "error": "adb_not_installed",
            "hint": "Install Android platform-tools and ensure adb is on PATH (INSTALL_ANDROID.bat).",
        }
    try:
        proc = subprocess.run([exe, *cmd], capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def devices(adb_path: str = "adb") -> list[str]:
    """Return serials in state 'device' (ready)."""
    result = adb(["devices"], adb_path=adb_path)
    if not result.get("ok"):
        return []
    lines = result.get("stdout", "").splitlines()[1:]
    out: list[str] = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            out.append(parts[0])
    return out


def devices_detailed(adb_path: str = "adb") -> list[dict[str, Any]]:
    """Parse ``adb devices -l`` into structured rows."""
    result = adb(["devices", "-l"], adb_path=adb_path)
    if not result.get("ok"):
        return []
    rows: list[dict[str, Any]] = []
    for line in (result.get("stdout") or "").splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        meta: dict[str, str] = {}
        for token in parts[2:]:
            if ":" in token:
                k, v = token.split(":", 1)
                meta[k] = v
        rows.append(
            {
                "serial": serial,
                "state": state,
                "product": meta.get("product"),
                "model": meta.get("model"),
                "device": meta.get("device"),
                "transport_id": meta.get("transport_id"),
                "ready": state == "device",
                "is_emulator": str(serial).startswith("emulator-"),
            }
        )
    return rows


def emulator_avd_name(adb_path: str, serial: str) -> str | None:
    """Ask emulator console for its AVD name."""
    result = adb(["-s", serial, "emu", "avd", "name"], adb_path=adb_path, timeout=10)
    if not result.get("ok"):
        return None
    for line in (result.get("stdout") or "").splitlines():
        name = line.strip()
        if name and name.upper() != "OK":
            return name
    return None


def wait_boot_completed(
    adb_path: str = "adb",
    serial: str | None = None,
    timeout_s: float = 180.0,
    poll_s: float = 2.0,
) -> dict[str, Any]:
    """Block until ``sys.boot_completed`` is 1 for the given serial (or default device)."""
    exe = resolve_adb(adb_path)
    base = [exe]
    if serial:
        base += ["-s", serial]
    deadline = time.time() + timeout_s
    last_err: str | None = None
    while time.time() < deadline:
        try:
            out = subprocess.check_output(
                base + ["shell", "getprop", "sys.boot_completed"],
                text=True,
                timeout=10,
                stderr=subprocess.DEVNULL,
            )
            if out.strip() == "1":
                return {"ok": True, "serial": serial, "boot_completed": True}
        except (OSError, subprocess.SubprocessError) as exc:
            last_err = str(exc)
        time.sleep(poll_s)
    return {"ok": False, "error": "boot_timeout", "serial": serial, "detail": last_err}


def ensure_server(adb_path: str = "adb") -> dict[str, Any]:
    """Restart ADB server so devices reconnect after Windows sleep/crash."""
    kill = adb(["kill-server"], adb_path=adb_path, timeout=15)
    start = adb(["start-server"], adb_path=adb_path, timeout=30)
    return {"ok": bool(start.get("ok")), "kill": kill, "start": start, "devices": devices_detailed(adb_path)}
