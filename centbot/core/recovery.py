"""Automatic system recovery."""

from __future__ import annotations

import time
import traceback
from typing import Callable

from centbot.core.logger import ActionJournal, get_logger

log = get_logger("centbot.recovery")


class RecoveryManager:
    def __init__(self, journal: ActionJournal, max_restarts: int = 5, backoff: float = 10.0):
        self.journal = journal
        self.max_restarts = max_restarts
        self.backoff = backoff
        self.failures = 0

    def reset(self) -> None:
        self.failures = 0

    def run_protected(self, name: str, fn: Callable[[], None]) -> bool:
        try:
            fn()
            self.failures = 0
            return True
        except Exception as exc:  # noqa: BLE001
            self.failures += 1
            tb = traceback.format_exc()
            log.exception("Protected run failed: %s", name)
            self.journal.record("recovery", "error", name=name, error=str(exc), traceback=tb, failures=self.failures)
            if self.failures >= self.max_restarts:
                self.journal.record("recovery", "halt", name=name, reason="max_restarts")
                return False
            time.sleep(min(self.backoff * self.failures, 120))
            return True

    def should_halt(self) -> bool:
        return self.failures >= self.max_restarts
