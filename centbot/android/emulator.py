"""Android emulator setup and multi-instance management (up to 4 CENTBOT AVDs)."""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any

from centbot.android.adb import devices
from centbot.core.logger import get_logger

log = get_logger("centbot.android.emulator")

DEFAULT_AVDS = [
    "CENTBOT_ANDROID_01",
    "CENTBOT_ANDROID_02",
    "CENTBOT_ANDROID_03",
    "CENTBOT_ANDROID_04",
]


def emulator_available(emulator_path: str = "emulator") -> bool:
    return shutil.which(emulator_path) is not None


class EmulatorManager:
    def __init__(
        self,
        emulator_path: str = "emulator",
        adb_path: str = "adb",
        max_emulators: int = 4,
        default_avd: str = "CENTBOT_ANDROID_01",
        avds: list[str] | None = None,
        enabled: bool = False,
    ):
        self.emulator_path = emulator_path
        self.adb_path = adb_path
        self.enabled = bool(enabled)
        self.max_emulators = max(0, min(4, int(max_emulators or 0)))
        self.default_avd = default_avd
        self.avds = list(avds or DEFAULT_AVDS)[: max(self.max_emulators, 0)]
        self._procs: dict[str, subprocess.Popen] = {}

    def status(self) -> dict[str, Any]:
        installed = emulator_available(self.emulator_path)
        running = devices(self.adb_path) if self.enabled or installed else []
        n_running = len(running)
        return {
            "enabled": self.enabled,
            "ok": bool(self.enabled),
            # Panel-friendly aliases (UI used to look for these and always showed OFF)
            "available": bool(self.enabled and installed),
            "active": n_running,
            "running": n_running,
            "emulator_installed": installed,
            "running_devices": running,
            "managed_procs": len(self._procs),
            "managed_avds": list(self._procs.keys()),
            "max_emulators": self.max_emulators,
            "default_avd": self.default_avd,
            "avds": self.avds,
            "slots": [
                {
                    "name": name,
                    "index": i + 1,
                    "managed": name in self._procs,
                    "alive": bool(self._procs.get(name) and self._procs[name].poll() is None),
                }
                for i, name in enumerate(self.avds)
            ],
            "label": (
                "OFF"
                if not self.enabled
                else (
                    f"OK · {n_running}"
                    if n_running
                    else ("ON · nav AVD" if installed else "ON · nav SDK")
                )
            ),
            "setup_hint": "Run INSTALL_ANDROID.bat (Google cmdline-tools + CENTBOT_ANDROID AVDs), then STOP/START. Set android.enabled: true.",
        }

    def start(self, avd: str | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "android_disabled", **self.status()}
        if not emulator_available(self.emulator_path):
            return {"ok": False, "error": "emulator_not_installed", **self.status()}
        if self.max_emulators <= 0:
            return {"ok": False, "error": "max_emulators_zero"}
        if len(devices(self.adb_path)) >= self.max_emulators:
            return {"ok": False, "error": "max_emulators_reached"}
        avd_name = avd or self.default_avd
        if avd_name in self._procs and self._procs[avd_name].poll() is None:
            return {"ok": True, "skipped": True, "avd": avd_name, "pid": self._procs[avd_name].pid}
        proc = subprocess.Popen(
            [self.emulator_path, "-avd", avd_name, "-no-audio", "-no-boot-anim", "-gpu", "auto"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._procs[avd_name] = proc
        return {"ok": True, "pid": proc.pid, "avd": avd_name}

    def start_fleet(self) -> dict[str, Any]:
        results = []
        for name in self.avds[: self.max_emulators]:
            results.append(self.start(name))
            time.sleep(1)
        return {"ok": any(r.get("ok") for r in results), "results": results, **self.status()}

    def stop_all(self) -> None:
        for name, proc in list(self._procs.items()):
            try:
                proc.terminate()
            except OSError:
                pass
        self._procs.clear()
        # Also ask emulator consoles to die via adb
        try:
            for serial in devices(self.adb_path):
                if str(serial).startswith("emulator-"):
                    subprocess.run(
                        [self.adb_path, "-s", serial, "emu", "kill"],
                        capture_output=True,
                        timeout=15,
                        check=False,
                    )
        except Exception:  # noqa: BLE001
            pass
