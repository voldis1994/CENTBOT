"""Emergency stop controls."""

from __future__ import annotations

from pathlib import Path

from centbot.core.logger import ActionJournal, get_logger

log = get_logger("centbot.emergency")


class EmergencyStop:
    def __init__(self, flag_path: Path, journal: ActionJournal | None = None):
        self.flag_path = Path(flag_path)
        self.journal = journal
        self._triggered = False

    def is_active(self) -> bool:
        return self._triggered or self.flag_path.exists()

    def trigger(self, reason: str = "manual") -> None:
        self._triggered = True
        self.flag_path.parent.mkdir(parents=True, exist_ok=True)
        self.flag_path.write_text(reason, encoding="utf-8")
        log.critical("EMERGENCY STOP: %s", reason)
        if self.journal:
            self.journal.record("emergency_stop", "triggered", reason=reason)

    def clear(self) -> None:
        self._triggered = False
        if self.flag_path.exists():
            self.flag_path.unlink()
        if self.journal:
            self.journal.record("emergency_stop", "cleared")
