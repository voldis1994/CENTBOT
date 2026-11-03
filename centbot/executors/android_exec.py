"""Android automation executor wired to ADB/emulator modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from centbot.android.app_testing import AppTestingModule
from centbot.android.emulator import EmulatorManager
from centbot.executors.base import ExecutionResult, Executor


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
        mgr = EmulatorManager(self.emulator_path, self.adb_path)
        status = mgr.status()
        if not status.get("emulator_installed") and not status.get("running_devices"):
            return ExecutionResult(
                ok=False,
                category=self.category,
                error="android_runtime_unavailable",
                output=status,
            )
        tester = AppTestingModule(adb_path=self.adb_path)
        apk = workdir / "app.apk"
        if apk.exists():
            install = tester.install_apk(str(apk))
            if not install.get("ok"):
                return ExecutionResult(ok=False, category=self.category, error="apk_install_failed", output=install)
        smoke = tester.smoke_test(evidence)
        return ExecutionResult(
            ok=bool(smoke.get("ok")),
            category=self.category,
            output={"status": status, "smoke": smoke},
            artifacts=[str(p) for p in evidence.glob("*")],
            error=None if smoke.get("ok") else "android_smoke_failed",
            evidence_dir=str(evidence),
        )
