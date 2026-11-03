"""Automatic touch and gesture system."""

from __future__ import annotations

from typing import Any

from centbot.android.adb import adb


class GestureSystem:
    def __init__(self, serial: str | None = None, adb_path: str = "adb"):
        self.serial = serial
        self.adb_path = adb_path

    def _prefix(self) -> list[str]:
        return ["-s", self.serial] if self.serial else []

    def tap(self, x: int, y: int) -> dict[str, Any]:
        return adb([*self._prefix(), "shell", "input", "tap", str(x), str(y)], adb_path=self.adb_path)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> dict[str, Any]:
        return adb(
            [*self._prefix(), "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
            adb_path=self.adb_path,
        )

    def text(self, value: str) -> dict[str, Any]:
        escaped = value.replace(" ", "%s")
        return adb([*self._prefix(), "shell", "input", "text", escaped], adb_path=self.adb_path)

    def keyevent(self, code: int) -> dict[str, Any]:
        return adb([*self._prefix(), "shell", "input", "keyevent", str(code)], adb_path=self.adb_path)
