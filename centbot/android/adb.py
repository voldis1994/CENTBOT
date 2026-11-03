"""ADB helpers."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any


def adb_available(adb_path: str = "adb") -> bool:
    return shutil.which(adb_path) is not None


def adb(cmd: list[str], adb_path: str = "adb", timeout: float = 30.0) -> dict[str, Any]:
    if not adb_available(adb_path):
        return {"ok": False, "error": "adb_not_installed", "hint": "Install Android platform-tools and ensure adb is on PATH."}
    try:
        proc = subprocess.run([adb_path, *cmd], capture_output=True, text=True, timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def devices(adb_path: str = "adb") -> list[str]:
    result = adb(["devices"], adb_path=adb_path)
    if not result.get("ok"):
        return []
    lines = result.get("stdout", "").splitlines()[1:]
    out = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            out.append(parts[0])
    return out
