"""Android emulator setup and multi-instance management."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from centbot.android.adb import devices
from centbot.core.logger import get_logger

log = get_logger("centbot.android.emulator")


def emulator_available(emulator_path: str = "emulator") -> bool:
    return shutil.which(emulator_path) is not None


class EmulatorManager:
    def __init__(self, emulator_path: str = "emulator", adb_path: str = "adb", max_emulators: int = 2, default_avd: str = "CentBot_API_30"):
        self.emulator_path = emulator_path
        self.adb_path = adb_path
        self.max_emulators = max_emulators
        self.default_avd = default_avd
        self._procs: list[subprocess.Popen] = []

    def status(self) -> dict[str, Any]:
        return {
            "emulator_installed": emulator_available(self.emulator_path),
            "running_devices": devices(self.adb_path),
            "managed_procs": len(self._procs),
            "max_emulators": self.max_emulators,
            "default_avd": self.default_avd,
            "setup_hint": "Install Android SDK + create AVD named CentBot_API_30 (or configure android.default_avd).",
        }

    def start(self, avd: str | None = None) -> dict[str, Any]:
        if not emulator_available(self.emulator_path):
            return {"ok": False, "error": "emulator_not_installed", **self.status()}
        if len(devices(self.adb_path)) >= self.max_emulators:
            return {"ok": False, "error": "max_emulators_reached"}
        avd_name = avd or self.default_avd
        proc = subprocess.Popen(
            [self.emulator_path, "-avd", avd_name, "-no-audio", "-no-boot-anim"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._procs.append(proc)
        return {"ok": True, "pid": proc.pid, "avd": avd_name}

    def stop_all(self) -> None:
        for proc in self._procs:
            proc.terminate()
        self._procs.clear()
