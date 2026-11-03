"""Error repair mechanism."""

from __future__ import annotations

from typing import Any, Callable

from centbot.core.logger import get_logger

log = get_logger("centbot.repair")


class ErrorRepair:
    def __init__(self, max_attempts: int = 2):
        self.max_attempts = max_attempts

    def run_with_repair(self, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        last: dict[str, Any] = {"ok": False, "error": "not_started"}
        for attempt in range(1, self.max_attempts + 1):
            try:
                last = fn()
            except Exception as exc:  # noqa: BLE001
                last = {"ok": False, "error": str(exc), "attempt": attempt}
            if last.get("ok"):
                last["attempts"] = attempt
                return last
            log.warning("Repair attempt %s failed: %s", attempt, last.get("error"))
        last["attempts"] = self.max_attempts
        last["repaired"] = False
        return last
