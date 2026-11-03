"""Submitted work status checks against live platforms."""

from __future__ import annotations

from typing import Any

from centbot.core.database import Database, utcnow


class SubmissionStatusChecker:
    def __init__(self, platforms: dict, db: Database):
        self.platforms = platforms
        self.db = db

    def poll_pending(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            "SELECT s.*, t.external_id AS task_external_id FROM submissions s "
            "LEFT JOIN tasks t ON t.id = s.task_id "
            "WHERE s.status IN ('submitted', 'dry_run_submitted', 'pending') "
            "ORDER BY s.id DESC LIMIT 50"
        )
        updates = []
        for row in rows:
            if row["status"] == "dry_run_submitted":
                status = "local_only"
            else:
                conn = self.platforms.get(row["platform"])
                if not conn:
                    continue
                external = row.get("task_external_id") or str(row["id"])
                status = conn.check_submission_status(str(external)).get("status", "unknown")
            self.db.execute(
                "UPDATE submissions SET status=?, checked_at=? WHERE id=?",
                (status, utcnow(), row["id"]),
            )
            updates.append({**row, "status": status})
        return updates
