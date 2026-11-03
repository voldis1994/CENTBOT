"""Android screen control."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from centbot.android.adb import adb


class AndroidScreen:
    def __init__(self, serial: str | None = None, adb_path: str = "adb"):
        self.serial = serial
        self.adb_path = adb_path

    def _prefix(self) -> list[str]:
        return ["-s", self.serial] if self.serial else []

    def size(self) -> dict[str, Any]:
        result = adb([*self._prefix(), "shell", "wm", "size"], adb_path=self.adb_path)
        return result

    def screenshot(self, dest: Path) -> dict[str, Any]:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        remote = "/sdcard/centbot_screen.png"
        grab = adb([*self._prefix(), "shell", "screencap", "-p", remote], adb_path=self.adb_path)
        if not grab.get("ok"):
            return grab
        pull = adb([*self._prefix(), "pull", remote, str(dest)], adb_path=self.adb_path)
        return {"ok": pull.get("ok", False), "path": str(dest), "details": pull}
