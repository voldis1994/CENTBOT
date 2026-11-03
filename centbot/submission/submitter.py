"""Automatic allowed-work submission."""

from __future__ import annotations

from typing import Any

from centbot.core.database import Database, utcnow
from centbot.core.logger import ActionJournal


class Submitter:
    def __init__(self, platforms: dict, db: Database, journal: ActionJournal, dry_run: bool = True):
        self.platforms = platforms
        self.db = db
        self.journal = journal
        self.dry_run = dry_run

    def submit(self, task_row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        if self.dry_run:
            self.db.execute(
                "INSERT INTO submissions(task_id, platform, status, submitted_at, response_json) VALUES(?,?,?,?,?)",
                (task_row["id"], task_row["platform"], "dry_run_submitted", utcnow(), str(payload)[:2000]),
            )
            self.journal.record("submit", "dry_run", task_id=task_row["id"])
            return {"ok": True, "mode": "dry_run"}
        conn = self.platforms.get(task_row["platform"])
        if not conn:
            return {"ok": False, "error": "unknown_platform"}
        task_obj = task_row.get("_task")
        result = conn.submit_result(task_obj, payload) if task_obj else {"ok": False, "error": "missing_task_object"}
        status = "submitted" if result.get("ok") else "submit_failed"
        self.db.execute(
            "INSERT INTO submissions(task_id, platform, status, submitted_at, response_json) VALUES(?,?,?,?,?)",
            (task_row["id"], task_row["platform"], status, utcnow(), str(result)[:2000]),
        )
        self.journal.record("submit", status, task_id=task_row["id"], result=result)
        return result
