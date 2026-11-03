"""Automated Android app testing module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from centbot.android.adb import adb
from centbot.android.gestures import GestureSystem
from centbot.android.screen import AndroidScreen
from centbot.android.screenshot_analysis import analyze_screenshot


class AppTestingModule:
    def __init__(self, serial: str | None = None, adb_path: str = "adb"):
        self.serial = serial
        self.adb_path = adb_path
        self.screen = AndroidScreen(serial, adb_path)
        self.gestures = GestureSystem(serial, adb_path)

    def install_apk(self, apk_path: str) -> dict[str, Any]:
        prefix = ["-s", self.serial] if self.serial else []
        return adb([*prefix, "install", "-r", apk_path], adb_path=self.adb_path)

    def launch(self, package: str, activity: str | None = None) -> dict[str, Any]:
        prefix = ["-s", self.serial] if self.serial else []
        component = f"{package}/{activity}" if activity else package
        return adb([*prefix, "shell", "am", "start", "-n" if activity else "-a", component if activity else "android.intent.action.MAIN"], adb_path=self.adb_path)

    def smoke_test(self, evidence_dir: Path) -> dict[str, Any]:
        evidence_dir = Path(evidence_dir)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        shot = evidence_dir / "android_smoke.png"
        grab = self.screen.screenshot(shot)
        analysis = analyze_screenshot(shot) if grab.get("ok") else {"ok": False}
        return {"ok": bool(grab.get("ok") and analysis.get("ok")), "screenshot": grab, "analysis": analysis}
