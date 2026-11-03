"""Automatic new-task detection."""

from __future__ import annotations

from typing import Any

from centbot.core.database import Database
from centbot.core.logger import ActionJournal


class NewTaskWatcher:
    def __init__(self, db: Database, journal: ActionJournal):
        self.db = db
        self.journal = journal

    def detect_new(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        new_ones: list[dict[str, Any]] = []
        for task in candidates:
            existing = self.db.fetchone(
                "SELECT id, status FROM tasks WHERE platform=? AND external_id=?",
                (task["platform"], task["external_id"]),
            )
            if existing is None:
                task["is_new"] = True
                new_ones.append(task)
            else:
                task["is_new"] = False
                task["id"] = existing["id"]
        if new_ones:
            self.journal.record("new_tasks", "ok", count=len(new_ones))
        return new_ones
