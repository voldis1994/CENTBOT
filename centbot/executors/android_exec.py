"""Android automation executor wired to ADB/emulator modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from centbot.android.adb import devices, wait_boot_completed
from centbot.android.app_testing import AppTestingModule
from centbot.android.emulator import EmulatorManager
from centbot.core.logger import get_logger
from centbot.executors.base import ExecutionResult, Executor

log = get_logger("centbot.android_exec")


class AndroidExecutor(Executor):
    category = "android"

    def __init__(self, adb_path: str = "adb", emulator_path: str = "emulator", enabled: bool = True):
        self.adb_path = adb_path
        self.emulator_path = emulator_path
        self.enabled = enabled

    def execute(self, task: dict[str, Any], workdir: Path) -> ExecutionResult:
        if not self.enabled:
            return ExecutionResult(ok=False, category=self.category, error="android_disabled")
        workdir.mkdir(parents=True, exist_ok=True)
        evidence = workdir / "android"
        evidence.mkdir(parents=True, exist_ok=True)

        serial = task.get("android_serial") or task.get("serial")
        avd = task.get("android_avd") or task.get("avd")
        mgr = EmulatorManager(
            self.emulator_path,
            self.adb_path,
            enabled=True,
            default_avd=str(avd or "CENTBOT_ANDROID_01"),
        )
        status = mgr.status()
        if not status.get("emulator_installed") and not status.get("running_devices"):
            log.error("android_runtime_unavailable task=%s status=%s", task.get("id"), status)
            return ExecutionResult(
                ok=False,
                category=self.category,
                error="android_runtime_unavailable",
                output=status,
            )

        if not serial:
            # Prefer mapped AVD serial, else first ready emulator
            serial = (status.get("serial_by_avd") or {}).get(avd) if avd else None
            if not serial:
                ready = devices(self.adb_path)
                serial = ready[0] if ready else None
        if not serial:
            started = mgr.start(str(avd) if avd else None, wait_boot=True, boot_timeout_s=120)
            serial = started.get("serial")
            if not serial:
                log.error("android_no_device task=%s start=%s", task.get("id"), started)
                return ExecutionResult(
                    ok=False,
                    category=self.category,
                    error="android_no_device",
                    output={"status": status, "start": started},
                )
        boot = wait_boot_completed(self.adb_path, serial=str(serial), timeout_s=60)
        if not boot.get("ok"):
            log.error("android_boot_incomplete serial=%s", serial)
            return ExecutionResult(
                ok=False,
                category=self.category,
                error="android_boot_incomplete",
                output={"boot": boot, "serial": serial},
            )

        tester = AppTestingModule(serial=str(serial), adb_path=self.adb_path)
        apk = workdir / "app.apk"
        install_result = None
        if apk.exists():
            install_result = tester.install_apk(str(apk))
            if not install_result.get("ok"):
                log.error("apk_install_failed serial=%s result=%s", serial, install_result)
                return ExecutionResult(
                    ok=False,
                    category=self.category,
                    error="apk_install_failed",
                    output=install_result,
                    evidence_dir=str(evidence),
                )
        smoke = tester.smoke_test(evidence)
        artifacts = [str(p) for p in evidence.glob("*") if p.is_file()]
        report = evidence / "android_result.json"
        import json

        report.write_text(
            json.dumps(
                {
                    "serial": serial,
                    "avd": avd,
                    "smoke": smoke,
                    "install": install_result,
                    "task_id": task.get("id"),
                    "title": task.get("title"),
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        artifacts.append(str(report))
        ok = bool(smoke.get("ok"))
        if not ok:
            log.error("android_smoke_failed serial=%s smoke=%s", serial, smoke)
        return ExecutionResult(
            ok=ok,
            category=self.category,
            output={"serial": serial, "avd": avd, "status": status, "smoke": smoke},
            artifacts=artifacts,
            error=None if ok else "android_smoke_failed",
            evidence_dir=str(evidence),
        )
