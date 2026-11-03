"""Resumable SETUP progress — skip completed components on re-run."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from centbot.runtime_paths import install_root

    ROOT = install_root()
except Exception:  # noqa: BLE001
    ROOT = Path(__file__).resolve().parents[2]

DEFAULT_STATE_PATH = ROOT / "data" / "setup" / "progress.json"

COMPONENTS = [
    "hw_check",
    "python_venv",
    "git",
    "pip_requirements",
    "playwright_browsers",
    "wsl2",
    "docker_desktop",
    "android_sdk",
    "android_emulator",
    "android_avds",
    "ollama",
    "wizard",
    "verify",
]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class SetupProgress:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else DEFAULT_STATE_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "components": {}, "updated_at": None, "completed": False}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "components": {}, "updated_at": None, "completed": False}

    def save(self) -> None:
        self._data["updated_at"] = _utcnow()
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def mark(self, component: str, *, ok: bool, detail: str | None = None, skipped: bool = False) -> None:
        self._data.setdefault("components", {})[component] = {
            "ok": ok,
            "skipped": skipped,
            "detail": detail,
            "at": _utcnow(),
        }
        if ok and all(
            (self._data["components"].get(c) or {}).get("ok")
            for c in COMPONENTS
            if c != "ollama"  # optional
        ):
            # ollama optional — mark complete when required set done
            required = [c for c in COMPONENTS if c != "ollama"]
            if all((self._data["components"].get(c) or {}).get("ok") for c in required):
                self._data["completed"] = True
        self.save()

    def status(self, component: str) -> dict[str, Any] | None:
        return (self._data.get("components") or {}).get(component)

    def is_done(self, component: str) -> bool:
        st = self.status(component)
        return bool(st and st.get("ok"))

    def is_setup_complete(self) -> bool:
        """Core ready: verify core checks passed. Docker/Android gaps are optional."""
        if not bool(self._data.get("completed")):
            return False
        verify = self.status("verify") or {}
        return bool(verify.get("ok"))

    def missing_required(self) -> list[str]:
        # Core path only — android_sdk/avds are optional for live PC engine start
        required = [
            "hw_check",
            "python_venv",
            "git",
            "pip_requirements",
            "playwright_browsers",
            "wizard",
            "verify",
        ]
        return [c for c in required if not self.is_done(c)]

    def missing_optional(self) -> list[str]:
        optional = ["docker_desktop", "android_sdk", "android_avds"]
        return [c for c in optional if not self.is_done(c)]

    def report(self) -> dict[str, Any]:
        data = dict(self._data)
        data["missing_required"] = self.missing_required()
        data["missing_optional"] = self.missing_optional()
        data["setup_complete"] = self.is_setup_complete()
        data["android_ready"] = bool(self._data.get("android_ready"))
        data["docker_ready"] = bool(self._data.get("docker_ready"))
        return data
