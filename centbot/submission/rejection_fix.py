"""Rejected work repair process."""

from __future__ import annotations

from typing import Any

from centbot.core.database import Database, utcnow
from centbot.core.logger import ActionJournal


class RejectionRepairProcess:
    def __init__(self, db: Database, journal: ActionJournal):
        self.db = db
        self.journal = journal

    def handle(self, task_id: str, reason: str = "") -> dict[str, Any]:
        self.db.execute(
            "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
            ("needs_repair", utcnow(), task_id),
        )
        self.journal.record("rejection_repair", "queued", task_id=task_id, reason=reason)
        return {"ok": True, "task_id": task_id, "status": "needs_repair"}
