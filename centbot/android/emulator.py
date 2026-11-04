"""Android emulator setup and multi-instance management (up to 4 CENTBOT AVDs)."""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any

from centbot.android.adb import (
    devices,
    devices_detailed,
    emulator_avd_name,
    ensure_server,
    wait_boot_completed,
)
from centbot.core.logger import get_logger

log = get_logger("centbot.android.emulator")

DEFAULT_AVDS = [
    "CENTBOT_ANDROID_01",
    "CENTBOT_ANDROID_02",
    "CENTBOT_ANDROID_03",
    "CENTBOT_ANDROID_04",
]


def emulator_available(emulator_path: str = "emulator") -> bool:
    from pathlib import Path

    if shutil.which(emulator_path):
        return True
    try:
        return Path(emulator_path).is_file()
    except OSError:
        return False


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
        self._errors: dict[str, str] = {}
        self._serial_by_avd: dict[str, str] = {}
        self._active_tasks: dict[str, str] = {}

    def _centbot_avd_set(self) -> set[str]:
        return set(self.avds) | set(DEFAULT_AVDS)

    def _refresh_serial_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for row in devices_detailed(self.adb_path):
            if not row.get("ready") or not row.get("is_emulator"):
                continue
            serial = str(row["serial"])
            avd = emulator_avd_name(self.adb_path, serial)
            if avd and avd in self._centbot_avd_set():
                mapping[avd] = serial
        self._serial_by_avd = mapping
        return mapping

    def status(self) -> dict[str, Any]:
        installed = emulator_available(self.emulator_path)
        detailed = devices_detailed(self.adb_path) if (self.enabled or installed) else []
        mapping = self._refresh_serial_map() if (self.enabled or installed) else {}
        running_ready = [d["serial"] for d in detailed if d.get("ready")]
        n_running = len([a for a in self.avds if a in mapping])
        slots = []
        for i, name in enumerate(self.avds):
            serial = mapping.get(name)
            alive = bool(self._procs.get(name) and self._procs[name].poll() is None) or bool(serial)
            slots.append(
                {
                    "name": name,
                    "avd": name,
                    "index": i + 1,
                    "worker": f"android_{i + 1}",
                    "serial": serial,
                    "adb_id": serial,
                    "connection": "connected" if serial else ("starting" if alive else "offline"),
                    "managed": name in self._procs,
                    "alive": alive,
                    "active_task": self._active_tasks.get(name),
                    "error": self._errors.get(name),
                }
            )
        return {
            "enabled": self.enabled,
            "ok": bool(self.enabled),
            "available": bool(self.enabled and installed),
            "active": n_running,
            "running": n_running,
            "emulator_installed": installed,
            "running_devices": running_ready,
            "devices_detailed": detailed,
            "serial_by_avd": dict(mapping),
            "managed_procs": len(self._procs),
            "managed_avds": list(self._procs.keys()),
            "max_emulators": self.max_emulators,
            "default_avd": self.default_avd,
            "avds": self.avds,
            "slots": slots,
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

    def set_active_task(self, avd: str, task_id: str | None) -> None:
        if task_id:
            self._active_tasks[avd] = task_id
        else:
            self._active_tasks.pop(avd, None)

    def start(self, avd: str | None = None, *, wait_boot: bool = True, boot_timeout_s: float = 180.0) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "android_disabled", **self.status()}
        if not emulator_available(self.emulator_path):
            return {"ok": False, "error": "emulator_not_installed", **self.status()}
        if self.max_emulators <= 0:
            return {"ok": False, "error": "max_emulators_zero"}
        avd_name = avd or self.default_avd
        mapping = self._refresh_serial_map()
        if avd_name in mapping:
            serial = mapping[avd_name]
            boot = wait_boot_completed(self.adb_path, serial=serial, timeout_s=min(30.0, boot_timeout_s)) if wait_boot else {"ok": True}
            self._errors.pop(avd_name, None)
            return {"ok": True, "skipped": True, "avd": avd_name, "serial": serial, "boot": boot}
        if avd_name in self._procs and self._procs[avd_name].poll() is None:
            return {"ok": True, "skipped": True, "avd": avd_name, "pid": self._procs[avd_name].pid}
        # Cap concurrent CENTBOT devices
        if len(mapping) >= self.max_emulators:
            return {"ok": False, "error": "max_emulators_reached", "avd": avd_name}
        try:
            proc = subprocess.Popen(
                [
                    self.emulator_path,
                    "-avd",
                    avd_name,
                    "-no-audio",
                    "-no-boot-anim",
                    "-gpu",
                    "auto",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._procs[avd_name] = proc
            self._errors.pop(avd_name, None)
        except OSError as exc:
            self._errors[avd_name] = str(exc)
            return {"ok": False, "error": str(exc), "avd": avd_name}

        boot: dict[str, Any] = {"ok": True, "skipped": not wait_boot}
        serial: str | None = None
        if wait_boot:
            deadline = time.time() + boot_timeout_s
            while time.time() < deadline:
                mapping = self._refresh_serial_map()
                serial = mapping.get(avd_name)
                if serial:
                    boot = wait_boot_completed(self.adb_path, serial=serial, timeout_s=max(5.0, deadline - time.time()))
                    break
                if proc.poll() is not None:
                    self._errors[avd_name] = "emulator_exited_early"
                    return {"ok": False, "error": "emulator_exited_early", "avd": avd_name, "pid": proc.pid}
                time.sleep(2)
            else:
                boot = {"ok": False, "error": "serial_timeout", "avd": avd_name}
        return {
            "ok": bool(boot.get("ok")),
            "pid": proc.pid,
            "avd": avd_name,
            "serial": serial,
            "boot": boot,
        }

    def start_fleet(self, *, wait_boot: bool = True, boot_timeout_s: float = 120.0) -> dict[str, Any]:
        results = []
        for name in self.avds[: self.max_emulators]:
            results.append(self.start(name, wait_boot=wait_boot, boot_timeout_s=boot_timeout_s))
            time.sleep(1)
        return {"ok": any(r.get("ok") for r in results), "results": results, **self.status()}

    def stop(self, avd: str) -> dict[str, Any]:
        """Stop a single CENTBOT-managed AVD only."""
        if avd not in self._centbot_avd_set():
            return {"ok": False, "error": "not_centbot_avd", "avd": avd}
        mapping = self._refresh_serial_map()
        serial = mapping.get(avd)
        killed = []
        if serial:
            subprocess.run(
                [self.adb_path, "-s", serial, "emu", "kill"],
                capture_output=True,
                timeout=20,
                check=False,
            )
            killed.append(serial)
        proc = self._procs.pop(avd, None)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
            killed.append(f"pid:{proc.pid}")
        self._active_tasks.pop(avd, None)
        self._errors.pop(avd, None)
        return {"ok": True, "avd": avd, "killed": killed}

    def stop_all(self) -> None:
        """Stop ONLY CENTBOT_ANDROID_* emulators — never foreign AVDs."""
        allowed = self._centbot_avd_set()
        for name in list(self._procs.keys()):
            self.stop(name)
        try:
            for row in devices_detailed(self.adb_path):
                serial = str(row.get("serial") or "")
                if not serial.startswith("emulator-"):
                    continue
                avd = emulator_avd_name(self.adb_path, serial)
                if avd and avd in allowed:
                    subprocess.run(
                        [self.adb_path, "-s", serial, "emu", "kill"],
                        capture_output=True,
                        timeout=15,
                        check=False,
                    )
        except Exception as exc:  # noqa: BLE001
            log.warning("stop_all partial failure: %s", exc)

    def recover_fleet(self, *, restart_adb: bool = True) -> dict[str, Any]:
        """Reconnect ADB and restart missing CENTBOT AVDs after crash / reboot."""
        adb_report = ensure_server(self.adb_path) if restart_adb else {"ok": True, "skipped": True}
        if not self.enabled:
            return {"ok": False, "error": "android_disabled", "adb": adb_report}
        mapping = self._refresh_serial_map()
        restarted: list[dict[str, Any]] = []
        for name in self.avds[: self.max_emulators]:
            if name in mapping:
                # Ensure boot completed
                boot = wait_boot_completed(self.adb_path, serial=mapping[name], timeout_s=30)
                if not boot.get("ok"):
                    restarted.append(self.start(name, wait_boot=True, boot_timeout_s=90))
                else:
                    restarted.append({"ok": True, "avd": name, "serial": mapping[name], "skipped": True})
            else:
                restarted.append(self.start(name, wait_boot=True, boot_timeout_s=120))
        return {"ok": any(r.get("ok") for r in restarted), "adb": adb_report, "results": restarted, **self.status()}

    def bind_workers(self) -> list[dict[str, Any]]:
        """Ordered binding: CENTBOT_ANDROID_0N → android_N."""
        mapping = self._refresh_serial_map()
        out = []
        for i, name in enumerate(self.avds[:4], start=1):
            out.append(
                {
                    "worker": f"android_{i}",
                    "avd": name,
                    "serial": mapping.get(name),
                    "connected": name in mapping,
                }
            )
        return out
